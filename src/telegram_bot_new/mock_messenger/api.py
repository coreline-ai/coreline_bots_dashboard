from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from telegram_bot_new.mock_messenger.schemas import MockSendRequest, RateLimitRuleRequest
from telegram_bot_new.mock_messenger.store import MockMessengerStore

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    store: MockMessengerStore,
    allow_get_updates_with_webhook: bool = False,
) -> FastAPI:
    app = FastAPI(title="Mock Telegram Messenger", version="0.1.0")

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/_mock/ui", status_code=307)

    @app.get("/_mock/ui")
    async def ui_index() -> FileResponse:
        return FileResponse(_web_file("index.html"))

    @app.get("/_mock/ui/app.js")
    async def ui_app_js() -> FileResponse:
        return FileResponse(_web_file("app.js"), media_type="application/javascript")

    @app.get("/_mock/ui/styles.css")
    async def ui_styles_css() -> FileResponse:
        return FileResponse(_web_file("styles.css"), media_type="text/css")

    @app.get("/_mock/threads")
    async def get_threads(token: str | None = None) -> dict[str, Any]:
        return {"ok": True, "result": store.list_threads(token=token)}

    @app.post("/_mock/send")
    async def mock_send(request: MockSendRequest) -> dict[str, Any]:
        queued = store.enqueue_user_message(
            token=request.token,
            chat_id=request.chat_id,
            user_id=request.user_id,
            text=request.text,
        )

        webhook_error: str | None = None
        delivered_via_webhook = False
        if queued["delivery_mode"] == "webhook" and isinstance(queued["webhook_url"], str):
            delivered_via_webhook, webhook_error = await _post_webhook_update(
                url=queued["webhook_url"],
                secret_token=queued["webhook_secret"],
                payload=queued["payload"],
            )
            if delivered_via_webhook:
                store.mark_update_delivered(token=request.token, update_id=queued["update_id"])

        return {
            "ok": True,
            "result": {
                "update_id": queued["update_id"],
                "delivery_mode": queued["delivery_mode"],
                "delivered_via_webhook": delivered_via_webhook,
                "webhook_error": webhook_error,
            },
        }

    @app.get("/_mock/messages")
    async def get_messages(token: str, chat_id: int | None = None, limit: int = 200) -> dict[str, Any]:
        messages = store.get_messages(token=token, chat_id=chat_id, limit=max(1, min(limit, 1000)))
        for message in messages:
            document = message.get("document")
            if isinstance(document, dict):
                document["url"] = f"/_mock/document/{document['id']}?token={token}"
        return {
            "ok": True,
            "result": {
                "messages": messages,
                "updates": store.get_recent_updates(token=token, chat_id=chat_id, limit=max(1, min(limit, 1000))),
            },
        }

    @app.get("/_mock/document/{document_id}")
    async def get_document(document_id: int, token: str) -> FileResponse:
        document = store.get_document_file(token=token, document_id=document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        path = Path(document["path"])
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="document file missing")
        return FileResponse(
            str(path),
            media_type=document["media_type"],
            filename=document["filename"],
            content_disposition_type="inline",
        )

    @app.get("/_mock/state")
    async def get_state(token: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "result": {
                "allow_get_updates_with_webhook": allow_get_updates_with_webhook,
                "state": store.get_state(token=token),
            },
        }

    @app.post("/_mock/rate_limit")
    async def set_rate_limit(rule: RateLimitRuleRequest) -> dict[str, Any]:
        store.set_rate_limit_rule(
            token=rule.token,
            method=rule.method,
            count=rule.count,
            retry_after=rule.retry_after,
        )
        return {"ok": True, "result": True}

    @app.post("/bot{token}/getUpdates")
    async def bot_get_updates(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="getUpdates")) is not None:
            return response

        offset = payload.get("offset")
        limit = payload.get("limit", 100)
        if not isinstance(offset, int):
            offset = None
        if not isinstance(limit, int):
            limit = 100

        updates = store.fetch_updates(
            token=token,
            offset=offset,
            limit=max(1, min(limit, 100)),
            allow_get_updates_with_webhook=allow_get_updates_with_webhook,
        )
        return {"ok": True, "result": updates}

    @app.post("/bot{token}/setWebhook")
    async def bot_set_webhook(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="setWebhook")) is not None:
            return response

        url = payload.get("url")
        if not isinstance(url, str) or not url.strip():
            return _telegram_error(status_code=400, description="Bad Request: url is required")

        secret_token = payload.get("secret_token")
        if secret_token is not None and not isinstance(secret_token, str):
            return _telegram_error(status_code=400, description="Bad Request: secret_token must be string")

        drop_pending_updates = bool(payload.get("drop_pending_updates", False))
        store.set_webhook(
            token=token,
            url=url.strip(),
            secret_token=secret_token,
            drop_pending_updates=drop_pending_updates,
        )
        return {"ok": True, "result": True}

    @app.post("/bot{token}/deleteWebhook")
    async def bot_delete_webhook(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="deleteWebhook")) is not None:
            return response

        drop_pending_updates = bool(payload.get("drop_pending_updates", False))
        store.delete_webhook(token=token, drop_pending_updates=drop_pending_updates)
        return {"ok": True, "result": True}

    @app.post("/bot{token}/sendMessage")
    async def bot_send_message(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="sendMessage")) is not None:
            return response

        chat_id = _parse_chat_id(payload.get("chat_id"))
        text = payload.get("text")
        if chat_id is None:
            return _telegram_error(status_code=400, description="Bad Request: chat_id is required")
        if not isinstance(text, str):
            return _telegram_error(status_code=400, description="Bad Request: text is required")

        result = store.store_bot_message(token=token, chat_id=chat_id, text=text)
        return {"ok": True, "result": result}

    @app.post("/bot{token}/editMessageText")
    async def bot_edit_message_text(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="editMessageText")) is not None:
            return response

        chat_id = _parse_chat_id(payload.get("chat_id"))
        message_id = payload.get("message_id")
        text = payload.get("text")
        if chat_id is None:
            return _telegram_error(status_code=400, description="Bad Request: chat_id is required")
        if not isinstance(message_id, int):
            return _telegram_error(status_code=400, description="Bad Request: message_id is required")
        if not isinstance(text, str):
            return _telegram_error(status_code=400, description="Bad Request: text is required")

        updated = store.edit_bot_message(token=token, chat_id=chat_id, message_id=message_id, text=text)
        if updated is None:
            return _telegram_error(status_code=400, description="Bad Request: message to edit not found")
        return {"ok": True, "result": updated}

    @app.post("/bot{token}/answerCallbackQuery")
    async def bot_answer_callback_query(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="answerCallbackQuery")) is not None:
            return response

        callback_query_id = payload.get("callback_query_id")
        text = payload.get("text")
        if not isinstance(callback_query_id, str) or not callback_query_id:
            return _telegram_error(status_code=400, description="Bad Request: callback_query_id is required")
        if text is not None and not isinstance(text, str):
            return _telegram_error(status_code=400, description="Bad Request: text must be string")

        store.record_callback_answer(token=token, callback_query_id=callback_query_id, text=text)
        return {"ok": True, "result": True}

    @app.post("/bot{token}/sendDocument")
    async def bot_send_document(
        token: str,
        chat_id: str = Form(...),
        caption: str | None = Form(default=None),
        document: UploadFile = File(...),
    ) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="sendDocument")) is not None:
            return response

        parsed_chat_id = _parse_chat_id(chat_id)
        if parsed_chat_id is None:
            return _telegram_error(status_code=400, description="Bad Request: chat_id is required")

        filename = document.filename or "document.bin"
        content = await document.read()
        result = store.store_document(
            token=token,
            chat_id=parsed_chat_id,
            filename=filename,
            content=content,
            caption=caption,
        )
        return {"ok": True, "result": result}

    @app.post("/bot{token}/sendPhoto")
    async def bot_send_photo(
        token: str,
        chat_id: str = Form(...),
        caption: str | None = Form(default=None),
        photo: UploadFile = File(...),
    ) -> Any:
        if (response := _try_rate_limit(store=store, token=token, method="sendPhoto")) is not None:
            return response

        parsed_chat_id = _parse_chat_id(chat_id)
        if parsed_chat_id is None:
            return _telegram_error(status_code=400, description="Bad Request: chat_id is required")

        filename = photo.filename or "photo.bin"
        content = await photo.read()
        result = store.store_document(
            token=token,
            chat_id=parsed_chat_id,
            filename=filename,
            content=content,
            caption=caption,
        )
        return {"ok": True, "result": result}

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


def _try_rate_limit(*, store: MockMessengerStore, token: str, method: str) -> JSONResponse | None:
    retry_after = store.consume_rate_limit(token=token, method=method)
    if retry_after is None:
        return None
    return JSONResponse(
        status_code=429,
        content={
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry later",
            "parameters": {"retry_after": retry_after},
        },
    )


def _telegram_error(*, status_code: int, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "description": description},
    )


def _parse_chat_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value and value.lstrip("-").isdigit():
            return int(value)
    return None


def _web_file(name: str) -> str:
    path = (Path(__file__).resolve().parent / "web" / name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="ui file not found")
    return str(path)


async def _post_webhook_update(
    *,
    url: str,
    secret_token: str | None,
    payload: dict[str, Any],
) -> tuple[bool, str | None]:
    headers: dict[str, str] = {}
    if secret_token:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret_token
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)
        if 200 <= response.status_code < 300:
            return True, None
        return False, f"HTTP {response.status_code}: {response.text[:300]}"
    except Exception as error:
        LOGGER.warning("webhook post failed url=%s error=%s", url, error)
        return False, str(error)
