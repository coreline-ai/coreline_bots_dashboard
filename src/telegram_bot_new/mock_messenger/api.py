from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from telegram_bot_new.mock_messenger.bot_catalog import (
    build_bot_catalog,
    cleanup_deleted_bot_state_files,
    create_dynamic_embedded_bot,
    delete_bot_from_catalog,
    set_bot_default_role,
)
from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator
from telegram_bot_new.mock_messenger.debate import DebateOrchestrator
from telegram_bot_new.mock_messenger.routes import (
    register_diagnostics_routes,
    register_mock_telegram_routes,
    register_orchestration_routes,
    register_ui_routes,
)
from telegram_bot_new.mock_messenger.runtime_profile import explain_unknown_bot_id, infer_runtime_profile
from telegram_bot_new.mock_messenger.schemas import (
    BotCatalogAddRequest,
    BotCatalogDeleteRequest,
    BotCatalogRoleUpdateRequest,
    MockClearMessagesRequest,
    MockSendRequest,
    RateLimitRuleRequest,
)
from telegram_bot_new.mock_messenger.store import MockMessengerStore
from telegram_bot_new.routing_policy import suggest_route
from telegram_bot_new.skill_library import list_installed_skills

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    store: MockMessengerStore,
    allow_get_updates_with_webhook: bool = False,
    bots_config_path: Union[str, Path] = "config/bots.yaml",
    embedded_host: str = "127.0.0.1",
    embedded_base_port: int = 8600,
) -> FastAPI:
    app = FastAPI(title="Mock Telegram Messenger", version="0.1.0")
    catalog_mutation_lock = asyncio.Lock()

    async def _enqueue_and_dispatch_user_message(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        queued = store.enqueue_user_message(
            token=token,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
        )

        webhook_error: Optional[str] = None
        delivered_via_webhook = False
        if queued["delivery_mode"] == "webhook" and isinstance(queued["webhook_url"], str):
            delivered_via_webhook, webhook_error = await _post_webhook_update(
                url=queued["webhook_url"],
                secret_token=queued["webhook_secret"],
                payload=queued["payload"],
            )
            if delivered_via_webhook:
                store.mark_update_delivered(token=token, update_id=queued["update_id"])
        return {
            "update_id": queued["update_id"],
            "delivery_mode": queued["delivery_mode"],
            "delivered_via_webhook": delivered_via_webhook,
            "webhook_error": webhook_error,
        }

    debate_orchestrator = DebateOrchestrator(
        store=store,
        send_user_message=_enqueue_and_dispatch_user_message,
    )
    cowork_orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=_enqueue_and_dispatch_user_message,
        artifact_root=Path.cwd() / "result",
    )
    app.state.debate_orchestrator = debate_orchestrator
    app.state.cowork_orchestrator = cowork_orchestrator

    @app.on_event("shutdown")
    async def _shutdown_event() -> None:
        await debate_orchestrator.shutdown()
        await cowork_orchestrator.shutdown()
    register_ui_routes(app, web_file=_web_file)

    @app.get("/_mock/threads")
    async def get_threads(token: Optional[str] = None) -> dict[str, Any]:
        return {"ok": True, "result": store.list_threads(token=token)}

    @app.post("/_mock/send")
    async def mock_send(request: MockSendRequest) -> dict[str, Any]:
        result = await _enqueue_and_dispatch_user_message(
            request.token,
            int(request.chat_id),
            int(request.user_id),
            request.text,
        )

        return {
            "ok": True,
            "result": result,
        }
    register_orchestration_routes(
        app,
        debate_orchestrator=debate_orchestrator,
        cowork_orchestrator=cowork_orchestrator,
        bots_config_path=bots_config_path,
        embedded_host=embedded_host,
        embedded_base_port=embedded_base_port,
    )

    @app.get("/_mock/messages")
    async def get_messages(token: str, chat_id: Optional[int] = None, limit: int = 200) -> dict[str, Any]:
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

    @app.post("/_mock/messages/clear")
    async def clear_messages(request: MockClearMessagesRequest) -> dict[str, Any]:
        result = store.clear_messages(token=request.token, chat_id=request.chat_id)
        return {"ok": True, "result": result}

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
    async def get_state(token: Optional[str] = None) -> dict[str, Any]:
        return {
            "ok": True,
            "result": {
                "allow_get_updates_with_webhook": allow_get_updates_with_webhook,
                "state": store.get_state(token=token),
            },
        }

    @app.get("/_mock/bot_catalog")
    async def get_bot_catalog() -> dict[str, Any]:
        bots = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        return {"ok": True, "result": {"bots": bots, "runtime_profile": _infer_runtime_profile()}}

    def _infer_runtime_profile() -> dict[str, Any]:
        return infer_runtime_profile(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )

    def _unknown_bot_detail(bot_id: str) -> str:
        return explain_unknown_bot_id(
            bot_id=str(bot_id or "").strip(),
            runtime_profile=_infer_runtime_profile(),
        )

    @app.get("/_mock/runtime_profile")
    async def get_runtime_profile() -> dict[str, Any]:
        return {"ok": True, "result": _infer_runtime_profile()}

    @app.get("/_mock/projects")
    async def get_projects() -> dict[str, Any]:
        projects = _discover_projects(base_dir=Path.cwd())
        return {"ok": True, "result": {"projects": projects}}

    @app.get("/_mock/skills")
    async def get_skills() -> dict[str, Any]:
        skills = [
            {
                "skill_id": item.skill_id,
                "name": item.name,
                "description": item.description,
                "path": str(item.path),
            }
            for item in list_installed_skills()
        ]
        return {"ok": True, "result": {"skills": skills}}

    @app.get("/_mock/routing/suggest")
    async def suggest_routing(text: str, bot_id: Optional[str] = None) -> dict[str, Any]:
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        selected = next((row for row in catalog if row.get("bot_id") == bot_id), None) if bot_id else None
        default_provider = str((selected or {}).get("default_adapter") or "codex")
        default_models = (selected or {}).get("default_models")
        normalized_models = default_models if isinstance(default_models, dict) else {}
        decision = suggest_route(
            prompt=text,
            session_provider=default_provider,
            session_model=None,
            default_models=normalized_models,
        )
        return {
            "ok": True,
            "result": {
                "enabled": decision.enabled,
                "task_type": decision.task_type,
                "provider": decision.provider,
                "model": decision.model,
                "reason": decision.reason,
                "stripped_prompt": decision.stripped_prompt,
            },
        }

    @app.post("/_mock/bot_catalog/add")
    async def add_bot_catalog_entry(request: BotCatalogAddRequest = Body(default_factory=BotCatalogAddRequest)) -> dict[str, Any]:
        async with catalog_mutation_lock:
            try:
                created = create_dynamic_embedded_bot(
                    bots_config_path=bots_config_path,
                    adapter=request.adapter,
                    bot_id=request.bot_id,
                    token=request.token,
                    name=request.name,
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            bots = build_bot_catalog(
                bots_config_path=bots_config_path,
                embedded_host=embedded_host,
                embedded_base_port=embedded_base_port,
            )
            stability = await _stabilize_embedded_runtime_if_needed(
                bots=bots,
                bots_config_path=bots_config_path,
            )

        created_id = str(created.get("bot_id") or "").strip()
        created_row = next((row for row in bots if str(row.get("bot_id")) == created_id), None)
        return {
            "ok": True,
            "result": {
                "bot": created_row or created,
                "total_bots": len(bots),
                "stability": stability,
            },
        }

    @app.post("/_mock/bot_catalog/delete")
    async def delete_bot_catalog_entry(request: BotCatalogDeleteRequest) -> dict[str, Any]:
        async with catalog_mutation_lock:
            before_bots = build_bot_catalog(
                bots_config_path=bots_config_path,
                embedded_host=embedded_host,
                embedded_base_port=embedded_base_port,
            )
            deleted_row = next((row for row in before_bots if str(row.get("bot_id") or "") == request.bot_id), None)
            removed_entry = delete_bot_from_catalog(bots_config_path=bots_config_path, bot_id=request.bot_id)
            if removed_entry is None:
                raise HTTPException(status_code=404, detail=_unknown_bot_detail(request.bot_id))
            stop_wait = await _wait_embedded_process_stopped_if_needed(
                embedded_url=str((deleted_row or {}).get("embedded_url") or "").strip(),
                bots_config_path=bots_config_path,
            )
            cleanup_deleted_bot_state_files(
                bots_config_path=bots_config_path,
                bot_id=request.bot_id,
                bot_entry=removed_entry,
            )
            cleanup_result: dict[str, int] | None = None
            token = str((deleted_row or {}).get("token") or "").strip()
            if token:
                cleanup_result = store.clear_messages(token=token)
            bots = build_bot_catalog(
                bots_config_path=bots_config_path,
                embedded_host=embedded_host,
                embedded_base_port=embedded_base_port,
            )
            stability = await _stabilize_embedded_runtime_if_needed(
                bots=bots,
                bots_config_path=bots_config_path,
            )
        return {
            "ok": True,
            "result": {
                "deleted_bot_id": request.bot_id,
                "total_bots": len(bots),
                "cleanup": cleanup_result,
                "stop_wait": stop_wait,
                "stability": stability,
            },
        }

    @app.post("/_mock/bot_catalog/role")
    async def update_bot_catalog_role(request: BotCatalogRoleUpdateRequest) -> dict[str, Any]:
        async with catalog_mutation_lock:
            updated = set_bot_default_role(
                bots_config_path=bots_config_path,
                bot_id=request.bot_id,
                role=request.role,
            )
            if not updated:
                raise HTTPException(status_code=404, detail=_unknown_bot_detail(request.bot_id))
            bots = build_bot_catalog(
                bots_config_path=bots_config_path,
                embedded_host=embedded_host,
                embedded_base_port=embedded_base_port,
            )
        selected = next((row for row in bots if str(row.get("bot_id") or "") == request.bot_id), None)
        return {
            "ok": True,
            "result": {
                "bot": selected,
                "total_bots": len(bots),
            },
        }

    register_diagnostics_routes(
        app,
        store=store,
        bots_config_path=bots_config_path,
        embedded_host=embedded_host,
        embedded_base_port=embedded_base_port,
        infer_runtime_profile=_infer_runtime_profile,
        enqueue_and_dispatch_user_message=_enqueue_and_dispatch_user_message,
    )

    @app.post("/_mock/rate_limit")
    async def set_rate_limit(rule: RateLimitRuleRequest) -> dict[str, Any]:
        store.set_rate_limit_rule(
            token=rule.token,
            method=rule.method,
            count=rule.count,
            retry_after=rule.retry_after,
        )
        return {"ok": True, "result": True}

    register_mock_telegram_routes(
        app,
        store=store,
        allow_get_updates_with_webhook=allow_get_updates_with_webhook,
        try_rate_limit=_try_rate_limit,
        telegram_error=_telegram_error,
        parse_chat_id=_parse_chat_id,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


def _try_rate_limit(*, store: MockMessengerStore, token: str, method: str) -> Optional[JSONResponse]:
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


def _parse_chat_id(value: Any) -> Optional[int]:
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


def _discover_projects(*, base_dir: Path) -> list[dict[str, str]]:
    markers = {
        ".git",
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "README.md",
    }
    resolved_base = base_dir.expanduser().resolve()
    candidates: list[Path] = [resolved_base]
    try:
        for child in sorted(resolved_base.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            has_marker = any((child / marker).exists() for marker in markers)
            if has_marker:
                candidates.append(child.resolve())
    except Exception:
        pass

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)

    projects: list[dict[str, str]] = []
    for path in deduped:
        projects.append(
            {
                "name": path.name if path != resolved_base else f"{path.name} (workspace)",
                "path": str(path),
            }
        )
    return projects


async def _post_webhook_update(
    *,
    url: str,
    secret_token: Optional[str],
    payload: dict[str, Any],
) -> tuple[bool, Optional[str]]:
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


def _should_wait_for_runtime_stability(*, bots_config_path: Union[str, Path]) -> bool:
    # Only gate for the local multi-bot runtime to avoid slowing down tests and
    # generic single-process mock usage.
    try:
        resolved = Path(bots_config_path).expanduser().resolve()
    except Exception:
        return False
    marker = str(Path(".runlogs/local-multibot").as_posix())
    return marker in resolved.as_posix()


async def _stabilize_embedded_runtime_if_needed(
    *,
    bots: list[dict[str, Any]],
    bots_config_path: Union[str, Path],
) -> dict[str, Any]:
    if not _should_wait_for_runtime_stability(bots_config_path=bots_config_path):
        return {"enabled": False}

    urls: list[str] = []
    for row in bots:
        embedded_url = str((row or {}).get("embedded_url") or "").strip()
        mode = str((row or {}).get("mode") or "").strip()
        if mode != "embedded" or not embedded_url:
            continue
        urls.append(embedded_url.rstrip("/") + "/healthz")

    if not urls:
        return {"enabled": True, "ready": True, "ready_count": 0, "total": 0, "pending_urls": []}

    deadline = time.monotonic() + 8.0
    pending = set(urls)
    timeout = httpx.Timeout(connect=0.35, read=0.6, write=0.6, pool=0.6)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while pending and time.monotonic() < deadline:
            current_urls = sorted(pending)
            checks = [client.get(url) for url in current_urls]
            results = await asyncio.gather(*checks, return_exceptions=True)
            for url, result in zip(current_urls, results):
                if isinstance(result, Exception):
                    continue
                if 200 <= result.status_code < 300:
                    pending.discard(url)
            if pending:
                await asyncio.sleep(0.2)

    ready = len(pending) == 0
    if not ready:
        LOGGER.warning("runtime stability wait timed out pending=%s", sorted(pending))
    return {
        "enabled": True,
        "ready": ready,
        "ready_count": len(urls) - len(pending),
        "total": len(urls),
        "pending_urls": sorted(pending),
    }


async def _wait_embedded_process_stopped_if_needed(
    *,
    embedded_url: str,
    bots_config_path: Union[str, Path],
) -> dict[str, Any]:
    if not _should_wait_for_runtime_stability(bots_config_path=bots_config_path):
        return {"enabled": False}
    url = str(embedded_url or "").strip()
    if not url:
        return {"enabled": True, "stopped": True, "checked_url": None}

    healthz = url.rstrip("/") + "/healthz"
    deadline = time.monotonic() + 8.0
    timeout = httpx.Timeout(connect=0.25, read=0.5, write=0.5, pool=0.5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(healthz)
                if response.status_code >= 500:
                    return {"enabled": True, "stopped": True, "checked_url": healthz}
            except Exception:
                return {"enabled": True, "stopped": True, "checked_url": healthz}
            await asyncio.sleep(0.2)
    LOGGER.warning("embedded stop wait timed out url=%s", healthz)
    return {"enabled": True, "stopped": False, "checked_url": healthz}
