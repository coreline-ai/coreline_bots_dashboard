from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx


class TelegramApiError(RuntimeError):
    pass


@dataclass(slots=True)
class TelegramRateLimitError(TelegramApiError):
    retry_after: int


RateLimitObserver = Callable[[str, int], Awaitable[None]]


class TelegramClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.telegram.org",
        *,
        on_rate_limit: RateLimitObserver | None = None,
    ) -> None:
        self._token = token
        self._base = f"{base_url.rstrip('/')}/bot{token}"
        self._on_rate_limit = on_rate_limit

    async def get_me(self) -> dict[str, Any]:
        return await self._request_json("getMe", {})

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> int:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            payload["disable_web_page_preview"] = disable_web_page_preview
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self._request_json("sendMessage", payload)
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramApiError("sendMessage missing message_id")
        return message_id

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            payload["disable_web_page_preview"] = disable_web_page_preview
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._request_json(
            "editMessageText",
            payload,
        )

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await self._request_json("answerCallbackQuery", payload)

    async def send_document(self, chat_id: int, file_path: str, caption: str | None = None) -> None:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise TelegramApiError(f"file not found: {file_path}")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        data: dict[str, str] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption

        async with httpx.AsyncClient(timeout=30) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    self._method_url("sendDocument"),
                    data=data,
                    files={"document": (path.name, fh, media_type)},
                )
        try:
            self._parse_response("sendDocument", resp)
        except TelegramRateLimitError as error:
            await self._notify_rate_limit("sendDocument", error.retry_after)
            raise

    async def send_photo(self, chat_id: int, file_path: str, caption: str | None = None) -> None:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise TelegramApiError(f"file not found: {file_path}")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        data: dict[str, str] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption

        async with httpx.AsyncClient(timeout=30) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    self._method_url("sendPhoto"),
                    data=data,
                    files={"photo": (path.name, fh, media_type)},
                )
        try:
            self._parse_response("sendPhoto", resp)
        except TelegramRateLimitError as error:
            await self._notify_rate_limit("sendPhoto", error.retry_after)
            raise

    async def register_webhook(self, *, public_url: str, secret_token: str) -> None:
        await self.delete_webhook(drop_pending_updates=False)
        await self._request_result(
            "setWebhook",
            {
                "url": public_url,
                "secret_token": secret_token,
                "drop_pending_updates": False,
            },
        )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        await self._request_result("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout_sec: int = 25,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_sec,
            "limit": limit,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        result = await self._request_result("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramApiError("Telegram API getUpdates returned non-list result")
        return [item for item in result if isinstance(item, dict)]

    def _method_url(self, method: str) -> str:
        return f"{self._base}/{method}"

    async def _request_result(self, method: str, payload: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._method_url(method), json=payload)
        try:
            return self._parse_response(method, resp)
        except TelegramRateLimitError as error:
            await self._notify_rate_limit(method, error.retry_after)
            raise

    async def _request_json(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request_result(method, payload)
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        raise TelegramApiError(f"Telegram API {method} expected object result")

    def _parse_response(self, method: str, resp: httpx.Response) -> Any:
        try:
            body = resp.json()
        except json.JSONDecodeError as error:
            raise TelegramApiError(f"Telegram API {method} invalid JSON response: {resp.text[:500]}") from error

        if resp.status_code == 429:
            retry_after = 1
            params = body.get("parameters") if isinstance(body, dict) else None
            if isinstance(params, dict) and isinstance(params.get("retry_after"), int):
                retry_after = max(1, int(params["retry_after"]))
            raise TelegramRateLimitError(retry_after=retry_after)

        if resp.status_code >= 400 or body.get("ok") is not True:
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramApiError(f"Telegram API {method} failed: {description or f'HTTP {resp.status_code}'}")

        return body.get("result")

    async def _notify_rate_limit(self, method: str, retry_after: int) -> None:
        if self._on_rate_limit is None:
            return
        try:
            await self._on_rate_limit(method, retry_after)
        except Exception:
            # Metric callbacks must not affect Telegram API behavior.
            return
