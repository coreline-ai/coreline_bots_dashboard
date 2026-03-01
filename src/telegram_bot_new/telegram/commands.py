from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import shutil
import time
from typing import Any, Protocol

from telegram_bot_new.db.repository import ActiveRunExistsError, Repository
from telegram_bot_new.model_presets import (
    SUPPORTED_CLI_PROVIDERS,
    get_available_models,
    is_allowed_model,
    resolve_provider_default_model,
    resolve_selected_model,
)
from telegram_bot_new.services.action_token_service import ActionTokenPayload, ActionTokenService
from telegram_bot_new.services.button_prompt_service import ButtonPromptService
from telegram_bot_new.services.run_service import RunService
from telegram_bot_new.services.session_service import SessionService
from telegram_bot_new.services.youtube_search_service import YoutubeSearchResult
from telegram_bot_new.telegram.api import parse_incoming_update
from telegram_bot_new.telegram.client import TelegramClient


INLINE_ACTIONS = ("summary", "regen", "next", "stop")
SUPPORTED_PROVIDERS = SUPPORTED_CLI_PROVIDERS
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BotIdentity:
    bot_id: str
    bot_name: str
    adapter: str
    owner_user_id: int | None
    default_models: dict[str, str | None] = field(default_factory=dict)


class YoutubeSearchProvider(Protocol):
    async def search_first_video(self, query: str) -> YoutubeSearchResult | None: ...


class TelegramCommandHandler:
    def __init__(
        self,
        *,
        bot: BotIdentity,
        client: TelegramClient,
        session_service: SessionService,
        run_service: RunService,
        repository: Repository | None = None,
        youtube_search: YoutubeSearchProvider | None = None,
        action_token_service: ActionTokenService | None = None,
        button_prompt_service: ButtonPromptService | None = None,
    ) -> None:
        self._bot = bot
        self._client = client
        self._session_service = session_service
        self._run_service = run_service
        self._repository = repository
        self._youtube_search = youtube_search
        self._action_token_service = action_token_service
        self._button_prompt_service = button_prompt_service

    async def handle_update_payload(self, payload: dict, now_ms: int) -> None:
        parsed = parse_incoming_update(payload)
        if parsed is None:
            return

        if self._bot.owner_user_id is not None and parsed.user_id != self._bot.owner_user_id:
            if parsed.callback_query_id:
                await self._safe_answer_callback(parsed.callback_query_id, "Access denied", now_ms=now_ms)
            else:
                await self._client.send_message(parsed.chat_id, "Access denied: owner only.")
            return

        if parsed.callback_query_id:
            if not parsed.callback_data:
                await self._safe_answer_callback(parsed.callback_query_id, "Unsupported action")
                return
            try:
                await self._handle_callback(parsed.chat_id, parsed.callback_query_id, parsed.callback_data, now_ms)
            except Exception:
                LOGGER.exception(
                    "callback handling failed bot=%s chat_id=%s update_id=%s",
                    self._bot.bot_id,
                    parsed.chat_id,
                    parsed.update_id,
                )
                await self._safe_answer_callback(parsed.callback_query_id, "Action failed")
                raise
            return

        text = (parsed.text or "").strip()
        if not text:
            return

        youtube_intent, youtube_query = self._parse_youtube_search_request(text)
        if youtube_intent and self._youtube_search is not None:
            if not youtube_query:
                await self._client.send_message(parsed.chat_id, "YouTube 검색어를 함께 입력해 주세요. 예: 파이썬 asyncio 유튜브 찾아줘")
                return
            await self._handle_youtube_search(chat_id=parsed.chat_id, query=youtube_query)
            return

        if text.startswith("/"):
            await self._handle_command(chat_id=parsed.chat_id, text=text, now_ms=now_ms)
            return

        adapter_name = await self._resolve_chat_adapter(chat_id=str(parsed.chat_id))
        adapter_model = self._provider_default_or_preset_model(adapter_name)
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(parsed.chat_id),
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            now=now_ms,
        )
        try:
            turn_id = await self._run_service.enqueue_turn(
                session_id=session.session_id,
                bot_id=self._bot.bot_id,
                chat_id=str(parsed.chat_id),
                user_text=text,
                now=now_ms,
            )
        except ActiveRunExistsError:
            await self._client.send_message(parsed.chat_id, "A run is already active in this chat. Use /stop first.")
            return

        await self._client.send_message(
            parsed.chat_id,
            f"Queued turn: {turn_id}\nsession={session.session_id}\nagent={adapter_name}",
            reply_markup=await self._build_turn_action_keyboard(
                chat_id=parsed.chat_id,
                session_id=session.session_id,
                origin_turn_id=turn_id,
                now_ms=now_ms,
            ),
        )

    async def _handle_callback(self, chat_id: int, callback_query_id: str, callback_data: str, now_ms: int) -> None:
        if callback_data == "stop_run":
            stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
            await self._answer_callback(callback_query_id, "Stopping..." if stopped else "No active run", now_ms=now_ms)
            return

        if not callback_data.startswith("act:") or self._action_token_service is None:
            await self._answer_callback(callback_query_id, "Unsupported action", now_ms=now_ms)
            return

        token = callback_data.split(":", 1)[1].strip()
        if not token:
            await self._answer_callback(callback_query_id, "Invalid action token", now_ms=now_ms)
            return

        payload = await self._action_token_service.consume(
            token=token,
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            now=now_ms,
        )
        if payload is None:
            await self._answer_callback(callback_query_id, "Action expired or already used", now_ms=now_ms)
            return

        if payload.run_source == "direct_cancel" or payload.action_type == "stop":
            stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
            await self._answer_callback(callback_query_id, "Stopping..." if stopped else "No active run", now_ms=now_ms)
            return

        if payload.action_type not in ("summary", "regen", "next"):
            await self._answer_callback(callback_query_id, "Unknown action", now_ms=now_ms)
            return

        prompt_text = await self._build_prompt_from_action(payload=payload)
        if not prompt_text:
            await self._answer_callback(callback_query_id, "Cannot build prompt for action", now_ms=now_ms)
            return

        active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
        if active:
            await self._run_service.enqueue_deferred_button_action(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                session_id=payload.session_id,
                action_type=payload.action_type,
                prompt_text=prompt_text,
                origin_turn_id=payload.origin_turn_id,
                now=now_ms,
                max_queue=10,
            )
            await self._answer_callback(callback_query_id, "Queued after current run", now_ms=now_ms)
            await self._client.send_message(chat_id, f"[button] queued {payload.action_type} action.")
            return

        try:
            turn_id = await self._run_service.enqueue_button_turn(
                session_id=payload.session_id,
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                prompt_text=prompt_text,
                now=now_ms,
            )
        except ActiveRunExistsError:
            await self._run_service.enqueue_deferred_button_action(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                session_id=payload.session_id,
                action_type=payload.action_type,
                prompt_text=prompt_text,
                origin_turn_id=payload.origin_turn_id,
                now=now_ms,
                max_queue=10,
            )
            await self._answer_callback(callback_query_id, "Queued after current run", now_ms=now_ms)
            await self._client.send_message(chat_id, f"[button] queued {payload.action_type} action.")
            return

        await self._answer_callback(callback_query_id, "Started", now_ms=now_ms)
        await self._client.send_message(
            chat_id,
            f"[button] queued {payload.action_type}: {turn_id}",
            reply_markup=await self._build_turn_action_keyboard(
                chat_id=chat_id,
                session_id=payload.session_id,
                origin_turn_id=turn_id,
                now_ms=now_ms,
            ),
        )

    async def _answer_callback(self, callback_query_id: str, text: str | None = None, *, now_ms: int | None = None) -> None:
        await self._client.answer_callback_query(callback_query_id, text)
        await self._increment_metric("callback_ack_success", now_ms=now_ms)

    async def _safe_answer_callback(
        self,
        callback_query_id: str,
        text: str | None = None,
        *,
        now_ms: int | None = None,
    ) -> None:
        try:
            await self._answer_callback(callback_query_id, text, now_ms=now_ms)
        except Exception:
            await self._increment_metric("callback_ack_failed", now_ms=now_ms)
            LOGGER.exception("failed to answer callback query bot=%s callback_query_id=%s", self._bot.bot_id, callback_query_id)

    async def _increment_metric(self, metric_key: str, *, now_ms: int | None = None) -> None:
        if self._repository is None:
            return
        try:
            await self._repository.increment_runtime_metric(
                bot_id=self._bot.bot_id,
                metric_key=metric_key,
                now=now_ms if now_ms is not None else int(time.time() * 1000),
            )
        except Exception:
            LOGGER.exception("failed to increment metric bot=%s metric=%s", self._bot.bot_id, metric_key)

    async def _handle_command(self, *, chat_id: int, text: str, now_ms: int) -> None:
        command, *parts = text.split(maxsplit=1)
        arg = parts[0].strip() if parts else ""

        if command == "/start":
            await self._client.send_message(chat_id, self._welcome_text())
            return

        if command == "/help":
            await self._client.send_message(chat_id, self._help_text())
            return

        if command in ("/youtube", "/yt"):
            if self._youtube_search is None:
                await self._client.send_message(chat_id, "YouTube search is not enabled.")
                return
            if not arg:
                await self._client.send_message(chat_id, "Usage: /youtube <query>")
                return
            await self._handle_youtube_search(chat_id=chat_id, query=arg)
            return

        if command == "/new":
            adapter_name = await self._resolve_chat_adapter(chat_id=str(chat_id))
            adapter_model = self._provider_default_or_preset_model(adapter_name)
            session = await self._session_service.create_new(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                adapter_name=adapter_name,
                adapter_model=adapter_model,
                now=now_ms,
            )
            await self._client.send_message(chat_id, f"New session created: {session.session_id} (adapter={adapter_name})")
            return

        if command == "/status":
            status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
            if status is None:
                await self._client.send_message(chat_id, "No session yet. Send a message to start.")
                return
            model = resolve_selected_model(
                provider=status.adapter_name,
                session_model=getattr(status, "adapter_model", None),
                default_models=self._bot.default_models,
            )
            await self._client.send_message(
                chat_id,
                "\n".join(
                    [
                        f"bot={self._bot.bot_id}",
                        f"adapter={status.adapter_name}",
                        f"model={model or 'default'}",
                        f"session={status.session_id}",
                        f"thread={status.adapter_thread_id or 'none'}",
                        f"summary={status.summary_preview or 'none'}",
                    ]
                ),
            )
            return

        if command == "/reset":
            existing = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
            adapter_name = existing.adapter_name if existing is not None else self._bot.adapter
            adapter_model = self._provider_default_or_preset_model(adapter_name)
            if existing:
                await self._session_service.reset(session_id=existing.session_id, now=now_ms)
            new_s = await self._session_service.create_new(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                adapter_name=adapter_name,
                adapter_model=adapter_model,
                now=now_ms,
            )
            await self._client.send_message(chat_id, f"Session reset. New session={new_s.session_id} (adapter={adapter_name})")
            return

        if command == "/summary":
            summary = await self._session_service.get_summary(bot_id=self._bot.bot_id, chat_id=str(chat_id))
            if not summary.strip():
                await self._client.send_message(chat_id, "No summary yet.")
            else:
                await self._client.send_message(chat_id, f"Summary:\n{summary[:3500]}")
            return

        if command == "/mode":
            await self._handle_mode_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
            return

        if command == "/model":
            await self._handle_model_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
            return

        if command == "/providers":
            await self._handle_providers_command(chat_id=chat_id)
            return

        if command == "/stop":
            stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
            await self._client.send_message(chat_id, "Stop requested." if stopped else "No active run.")
            return

        if command == "/echo":
            await self._client.send_message(chat_id, arg or "(empty)")
            return

        await self._client.send_message(chat_id, f"Unknown command: {command}\n\n{self._help_text()}")

    async def _resolve_chat_adapter(self, *, chat_id: str) -> str:
        status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=chat_id)
        if status is not None and status.adapter_name:
            return status.adapter_name
        return self._bot.adapter

    def _provider_default_model(self, provider: str) -> str | None:
        return self._bot.default_models.get(provider)

    def _provider_default_or_preset_model(self, provider: str) -> str | None:
        return resolve_provider_default_model(provider, self._provider_default_model(provider))

    def _provider_models_text(self, provider: str) -> str:
        candidates = get_available_models(provider)
        if not candidates:
            return "none"
        return ", ".join(candidates)

    async def _handle_mode_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
        current_adapter = status.adapter_name if status is not None else self._bot.adapter
        current_model = resolve_selected_model(
            provider=current_adapter,
            session_model=getattr(status, "adapter_model", None),
            default_models=self._bot.default_models,
        ) or "default"

        if not arg:
            await self._client.send_message(
                chat_id,
                "\n".join(
                    [
                        f"mode=cli adapter={current_adapter} model={current_model}",
                        "usage: /mode <codex|gemini|claude>",
                        f"providers={', '.join(SUPPORTED_PROVIDERS)}",
                    ]
                ),
            )
            return

        next_adapter = arg.lower().strip()
        if next_adapter not in SUPPORTED_PROVIDERS:
            await self._client.send_message(
                chat_id,
                f"Unsupported provider: {arg}. Use one of: {', '.join(SUPPORTED_PROVIDERS)}",
            )
            return

        if next_adapter == current_adapter:
            await self._client.send_message(chat_id, f"mode unchanged: adapter={current_adapter}")
            return

        active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
        if active:
            await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /mode.")
            return

        if status is None:
            session = await self._session_service.get_or_create(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                adapter_name=next_adapter,
                adapter_model=self._provider_default_or_preset_model(next_adapter),
                now=now_ms,
            )
            await self._session_service.switch_adapter(
                session_id=session.session_id,
                adapter_name=next_adapter,
                adapter_model=self._provider_default_or_preset_model(next_adapter),
                now=now_ms,
            )
            session_id = session.session_id
        else:
            await self._session_service.switch_adapter(
                session_id=status.session_id,
                adapter_name=next_adapter,
                adapter_model=self._provider_default_or_preset_model(next_adapter),
                now=now_ms,
            )
            session_id = status.session_id

        await self._increment_metric(f"provider_switch_total.{next_adapter}", now_ms=now_ms)
        LOGGER.info(
            "provider switched bot=%s chat_id=%s from=%s to=%s",
            self._bot.bot_id,
            chat_id,
            current_adapter,
            next_adapter,
        )
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"mode switched: {current_adapter} -> {next_adapter}",
                    f"model={self._provider_default_or_preset_model(next_adapter) or 'default'}",
                    f"session={session_id}",
                    "context continuity: rolling summary retained, provider thread reset.",
                ]
            ),
        )

    async def _handle_model_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
        current_adapter = status.adapter_name if status is not None else self._bot.adapter
        current_model = resolve_selected_model(
            provider=current_adapter,
            session_model=getattr(status, "adapter_model", None),
            default_models=self._bot.default_models,
        ) or "default"
        allowed_models = get_available_models(current_adapter)

        if not arg:
            await self._client.send_message(
                chat_id,
                "\n".join(
                    [
                        f"adapter={current_adapter}",
                        f"model={current_model}",
                        f"available_models={self._provider_models_text(current_adapter)}",
                        "usage: /model <model-name>",
                    ]
                ),
            )
            return

        next_model = arg.strip()
        if not next_model:
            await self._client.send_message(chat_id, "Model name is required. usage: /model <model-name>")
            return

        if not allowed_models:
            await self._client.send_message(chat_id, f"No selectable model for provider={current_adapter}")
            return

        if not is_allowed_model(current_adapter, next_model):
            await self._client.send_message(
                chat_id,
                f"Unsupported model for {current_adapter}: {next_model}\nallowed={self._provider_models_text(current_adapter)}",
            )
            return

        active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
        if active:
            await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /model.")
            return

        if status is None:
            session = await self._session_service.get_or_create(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                adapter_name=current_adapter,
                adapter_model=next_model,
                now=now_ms,
            )
            session_id = session.session_id
        else:
            session_id = status.session_id

        await self._session_service.set_model(
            session_id=session_id,
            adapter_model=next_model,
            now=now_ms,
        )
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"model updated: {current_model} -> {next_model}",
                    f"adapter={current_adapter}",
                    f"model={next_model}",
                    f"session={session_id}",
                ]
            ),
        )

    async def _handle_providers_command(self, *, chat_id: int) -> None:
        lines = ["Available CLI providers:"]
        for provider in SUPPORTED_PROVIDERS:
            installed = "yes" if shutil.which(provider) else "no"
            model = self._provider_default_model(provider) or "default"
            lines.append(f"- {provider}: installed={installed}, model={model}")
        await self._client.send_message(chat_id, "\n".join(lines))

    async def _build_prompt_from_action(self, *, payload: ActionTokenPayload) -> str | None:
        if self._repository is None or self._button_prompt_service is None:
            return None
        session = await self._repository.get_session_view(session_id=payload.session_id)
        if session is None:
            return None
        origin_turn = await self._repository.get_turn(turn_id=payload.origin_turn_id)
        if origin_turn is None:
            return None
        latest = await self._repository.get_latest_completed_turn_for_session(session_id=payload.session_id)
        if payload.action_type == "summary":
            return self._button_prompt_service.build_summary_prompt(
                session=session,
                origin_turn=origin_turn,
                latest_turn=latest,
            )
        if payload.action_type == "regen":
            return self._button_prompt_service.build_regen_prompt(
                session=session,
                origin_turn=origin_turn,
            )
        if payload.action_type == "next":
            latest_assistant = (latest.assistant_text or "") if latest is not None else ""
            return self._button_prompt_service.build_next_prompt(
                session=session,
                origin_turn=origin_turn,
                latest_assistant_text=latest_assistant,
            )
        return None

    async def _build_turn_action_keyboard(
        self,
        *,
        chat_id: int,
        session_id: str,
        origin_turn_id: str,
        now_ms: int,
    ) -> dict[str, Any] | None:
        if self._action_token_service is None:
            return None
        token_map: dict[str, str] = {}
        for action in INLINE_ACTIONS:
            run_source = "direct_cancel" if action == "stop" else "codex_cli"
            token = await self._action_token_service.issue(
                bot_id=self._bot.bot_id,
                chat_id=str(chat_id),
                action_type=action,
                run_source=run_source,
                session_id=session_id,
                origin_turn_id=origin_turn_id,
                now=now_ms,
            )
            token_map[action] = token

        return {
            "inline_keyboard": [
                [
                    {"text": "요약", "callback_data": f"act:{token_map['summary']}"},
                    {"text": "다시생성", "callback_data": f"act:{token_map['regen']}"},
                ],
                [
                    {"text": "다음추천", "callback_data": f"act:{token_map['next']}"},
                    {"text": "중단", "callback_data": f"act:{token_map['stop']}"},
                ],
            ]
        }

    def _welcome_text(self) -> str:
        return (
            f"{self._bot.bot_name} ready.\n"
            "Send a message to run CLI.\n"
            "Use /help for commands."
        )

    def _help_text(self) -> str:
        return (
            "/start /help /new /status /reset /summary /mode /model /providers /stop /youtube\n"
            "Plain text message => enqueue CLI turn"
        )

    async def _handle_youtube_search(self, *, chat_id: int, query: str) -> None:
        if self._youtube_search is None:
            return
        normalized_query = " ".join(query.split())
        if not normalized_query:
            await self._client.send_message(chat_id, "YouTube 검색어를 입력해 주세요.")
            return

        try:
            result = await self._youtube_search.search_first_video(normalized_query)
        except Exception:
            await self._client.send_message(chat_id, "YouTube 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
            return
        if result is None:
            await self._client.send_message(chat_id, f"YouTube 검색 결과를 찾지 못했습니다: {normalized_query}")
            return

        # Keep watch URL only so Telegram renders native preview card.
        await self._client.send_message(chat_id, result.url)

    def _parse_youtube_search_request(self, text: str) -> tuple[bool, str | None]:
        lowered = text.lower()
        youtube_variants = (
            "youtube",
            "\uc720\ud29c\ube0c",
            "\uc720\ud22c\ube0c",
            "\uc720\ud2b8\ube0c",
            "\uc720\ud2b8\ubdf0",
        )
        has_youtube = any(variant in lowered for variant in youtube_variants)
        if not has_youtube:
            return (False, None)

        search_hints = (
            "search",
            "find",
            "recommend",
            "show",
            "\ucc3e\uc544",
            "\uac80\uc0c9",
            "\ucd94\ucc9c",
            "\ubcf4\uc5ec",
        )
        if not any(hint in lowered for hint in search_hints):
            return (False, None)

        cleaned = text
        for pattern in (
            r"(?i)\byoutube\b",
            "\uc720\ud29c\ube0c",
            "\uc720\ud22c\ube0c",
            "\uc720\ud2b8\ube0c",
            "\uc720\ud2b8\ubdf0",
            "\ub3d9\uc601\uc0c1",
            "\uc601\uc0c1",
            "\ucc3e\uc544\uc918",
            "\ucc3e\uc544 \uc918",
            "\ucc3e\uc544",
            "\uac80\uc0c9\ud574\uc918",
            "\uac80\uc0c9\ud574 \uc918",
            "\uac80\uc0c9",
            "\ucd94\ucc9c\ud574\uc918",
            "\ucd94\ucc9c\ud574 \uc918",
            "\ucd94\ucc9c",
            "\ubcf4\uc5ec\uc918",
            "\ubcf4\uc5ec \uc918",
            "\ubcf4\uc5ec",
            "\ubbf8\ub9ac\ubcf4\uae30",
            "\ubbf8\ub9ac \ubcf4\uae30",
            "\ud615\uc2dd\uc73c\ub85c",
            "\ud615\uc2dd",
            "\uc774\ub7f0",
            "\uac19\uc740",
            "please",
            "for me",
        ):
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?\n\t")
        return (True, cleaned or None)
