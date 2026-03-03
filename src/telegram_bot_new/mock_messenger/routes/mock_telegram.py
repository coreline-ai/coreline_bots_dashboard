from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from telegram_bot_new.mock_messenger.store import MockMessengerStore


def register_mock_telegram_routes(
    app: FastAPI,
    *,
    store: MockMessengerStore,
    allow_get_updates_with_webhook: bool,
    try_rate_limit: Callable[..., Optional[JSONResponse]],
    telegram_error: Callable[..., JSONResponse],
    parse_chat_id: Callable[[Any], Optional[int]],
) -> None:
    @app.post("/bot{token}/getUpdates")
    async def bot_get_updates(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="getUpdates")) is not None:
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
        if (response := try_rate_limit(store=store, token=token, method="setWebhook")) is not None:
            return response

        url = payload.get("url")
        if not isinstance(url, str) or not url.strip():
            return telegram_error(status_code=400, description="Bad Request: url is required")

        secret_token = payload.get("secret_token")
        if secret_token is not None and not isinstance(secret_token, str):
            return telegram_error(status_code=400, description="Bad Request: secret_token must be string")

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
        if (response := try_rate_limit(store=store, token=token, method="deleteWebhook")) is not None:
            return response

        drop_pending_updates = bool(payload.get("drop_pending_updates", False))
        store.delete_webhook(token=token, drop_pending_updates=drop_pending_updates)
        return {"ok": True, "result": True}

    @app.post("/bot{token}/sendMessage")
    async def bot_send_message(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="sendMessage")) is not None:
            return response

        chat_id = parse_chat_id(payload.get("chat_id"))
        text = payload.get("text")
        if chat_id is None:
            return telegram_error(status_code=400, description="Bad Request: chat_id is required")
        if not isinstance(text, str):
            return telegram_error(status_code=400, description="Bad Request: text is required")

        result = store.store_bot_message(token=token, chat_id=chat_id, text=text)
        return {"ok": True, "result": result}

    @app.post("/bot{token}/editMessageText")
    async def bot_edit_message_text(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="editMessageText")) is not None:
            return response

        chat_id = parse_chat_id(payload.get("chat_id"))
        message_id = payload.get("message_id")
        text = payload.get("text")
        if chat_id is None:
            return telegram_error(status_code=400, description="Bad Request: chat_id is required")
        if not isinstance(message_id, int):
            return telegram_error(status_code=400, description="Bad Request: message_id is required")
        if not isinstance(text, str):
            return telegram_error(status_code=400, description="Bad Request: text is required")

        updated = store.edit_bot_message(token=token, chat_id=chat_id, message_id=message_id, text=text)
        if updated is None:
            return telegram_error(status_code=400, description="Bad Request: message to edit not found")
        return {"ok": True, "result": updated}

    @app.post("/bot{token}/answerCallbackQuery")
    async def bot_answer_callback_query(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="answerCallbackQuery")) is not None:
            return response

        callback_query_id = payload.get("callback_query_id")
        text = payload.get("text")
        if not isinstance(callback_query_id, str) or not callback_query_id:
            return telegram_error(status_code=400, description="Bad Request: callback_query_id is required")
        if text is not None and not isinstance(text, str):
            return telegram_error(status_code=400, description="Bad Request: text must be string")

        store.record_callback_answer(token=token, callback_query_id=callback_query_id, text=text)
        return {"ok": True, "result": True}

    @app.post("/bot{token}/sendDocument")
    async def bot_send_document(
        token: str,
        chat_id: str = Form(...),
        caption: Optional[str] = Form(default=None),
        document: UploadFile = File(...),
    ) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="sendDocument")) is not None:
            return response

        parsed_chat_id = parse_chat_id(chat_id)
        if parsed_chat_id is None:
            return telegram_error(status_code=400, description="Bad Request: chat_id is required")

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
        caption: Optional[str] = Form(default=None),
        photo: UploadFile = File(...),
    ) -> Any:
        if (response := try_rate_limit(store=store, token=token, method="sendPhoto")) is not None:
            return response

        parsed_chat_id = parse_chat_id(chat_id)
        if parsed_chat_id is None:
            return telegram_error(status_code=400, description="Bad Request: chat_id is required")

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
