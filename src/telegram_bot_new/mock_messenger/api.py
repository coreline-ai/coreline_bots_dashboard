from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional, Union

import httpx
import yaml
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from telegram_bot_new.mock_messenger.bot_catalog import (
    build_bot_catalog,
    classify_last_error_tag,
    compact_threads,
    create_dynamic_embedded_bot,
    delete_bot_from_catalog,
    extract_runtime_metrics,
    fetch_embedded_audit_logs,
    fetch_embedded_runtime,
    infer_session_view_from_messages,
)
from telegram_bot_new.mock_messenger.debate import (
    ActiveDebateExistsError,
    DebateNotFoundError,
    DebateOrchestrator,
)
from telegram_bot_new.mock_messenger.schemas import (
    BotCatalogAddRequest,
    BotCatalogDeleteRequest,
    ControlTowerRecoverRequest,
    DebateStartRequest,
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
    app.state.debate_orchestrator = debate_orchestrator

    @app.on_event("shutdown")
    async def _shutdown_event() -> None:
        await debate_orchestrator.shutdown()

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

    @app.get("/_mock/ui/favicon.svg")
    async def ui_favicon() -> FileResponse:
        return FileResponse(_web_file("favicon.svg"), media_type="image/svg+xml")

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

    @app.post("/_mock/debate/start")
    async def start_debate(request: DebateStartRequest) -> dict[str, Any]:
        if len(request.profiles) < 2:
            raise HTTPException(status_code=400, detail="profiles must include at least two participants")

        catalog_rows = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        by_bot_id = {str(row.get("bot_id") or ""): row for row in catalog_rows}

        participants: list[dict[str, Any]] = []
        for profile in request.profiles:
            row = by_bot_id.get(profile.bot_id)
            if row is None:
                raise HTTPException(status_code=400, detail=f"unknown bot_id: {profile.bot_id}")
            expected_token = str(row.get("token") or "")
            if expected_token != profile.token:
                raise HTTPException(status_code=400, detail=f"token mismatch for bot_id: {profile.bot_id}")
            participants.append(
                {
                    "profile_id": profile.profile_id,
                    "label": profile.label,
                    "bot_id": profile.bot_id,
                    "token": profile.token,
                    "chat_id": int(profile.chat_id),
                    "user_id": int(profile.user_id),
                    "adapter": str(row.get("default_adapter") or ""),
                }
            )
        scope_parts = sorted(
            f"{str(item.get('bot_id') or '')}:{int(item.get('chat_id') or 0)}"
            for item in participants
        )
        scope_key = "|".join(scope_parts)

        try:
            result = await debate_orchestrator.start_debate(
                request=request,
                participants=participants,
                scope_key=scope_key,
            )
        except ActiveDebateExistsError as error:
            raise HTTPException(status_code=409, detail=f"active debate already exists: {error}") from error
        return {"ok": True, "result": result}

    @app.get("/_mock/debate/active")
    async def get_active_debate(scope_key: Optional[str] = None) -> dict[str, Any]:
        normalized_scope = scope_key.strip() if isinstance(scope_key, str) and scope_key.strip() else None
        return {"ok": True, "result": debate_orchestrator.get_active_debate_snapshot(scope_key=normalized_scope)}

    @app.get("/_mock/debate/{debate_id}")
    async def get_debate(debate_id: str) -> dict[str, Any]:
        snapshot = debate_orchestrator.get_debate_snapshot(debate_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"unknown debate_id: {debate_id}")
        return {"ok": True, "result": snapshot}

    @app.post("/_mock/debate/{debate_id}/stop")
    async def stop_debate(debate_id: str) -> dict[str, Any]:
        try:
            result = await debate_orchestrator.stop_debate(debate_id)
        except DebateNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"unknown debate_id: {error}") from error
        return {"ok": True, "result": result}

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
        return {"ok": True, "result": {"bots": bots}}

    def _infer_runtime_profile() -> dict[str, Any]:
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        effective_bots = len(catalog)
        source_bots = effective_bots
        source_config: str | None = None

        config_path = Path(bots_config_path).expanduser().resolve()
        default_source = Path.cwd() / "config" / "bots.multibot.yaml"
        if config_path.name == "bots.effective.yaml" and default_source.exists():
            source_config = str(default_source.resolve())
        elif config_path.exists():
            source_config = str(config_path)

        if source_config:
            try:
                raw = yaml.safe_load(Path(source_config).read_text(encoding="utf-8")) or {}
                if isinstance(raw, dict) and isinstance(raw.get("bots"), list):
                    source_bots = len(raw["bots"])
            except Exception:
                source_bots = effective_bots

        max_bots_env = (os.getenv("MAX_BOTS") or "").strip()
        max_bots = int(max_bots_env) if max_bots_env.isdigit() else (effective_bots if source_bots > effective_bots else None)
        return {
            "effective_bots": effective_bots,
            "source_bots": source_bots,
            "max_bots": max_bots,
            "is_capped": bool(source_bots > effective_bots),
            "bots_config_path": str(config_path),
            "source_config_path": source_config,
        }

    @app.get("/_mock/runtime_profile")
    async def get_runtime_profile() -> dict[str, Any]:
        return {"ok": True, "result": _infer_runtime_profile()}

    def _compute_slo_snapshot(logs: list[dict[str, Any]]) -> dict[str, Any]:
        run_turns = [row for row in logs if str(row.get("action") or "") == "run.turn"]
        turn_total = len(run_turns)
        turn_success = sum(1 for row in run_turns if str(row.get("result") or "") == "success")
        turn_fail = max(0, turn_total - turn_success)
        turn_success_rate = round((turn_success / turn_total) * 100, 1) if turn_total > 0 else None
        recoveries = sum(
            1
            for row in logs
            if str(row.get("action") or "") in {"run.stop", "session.new"}
        )
        return {
            "turn_total_recent": turn_total,
            "turn_success_recent": turn_success,
            "turn_fail_recent": turn_fail,
            "turn_success_rate_recent": turn_success_rate,
            "recoveries_recent": recoveries,
        }

    def _compute_tower_state(
        *,
        health: dict[str, Any],
        metrics: dict[str, Any],
        session: dict[str, Any],
        last_error_tag: str,
        slo: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bot_ok = bool(((health or {}).get("bot") or {}).get("ok"))
        run_status = str((session or {}).get("run_status") or "idle").lower()
        in_flight = (metrics or {}).get("in_flight_runs")
        error_tag = str(last_error_tag or "unknown").lower()
        turn_total_recent = int((slo or {}).get("turn_total_recent") or 0)
        turn_success_rate_recent = (slo or {}).get("turn_success_rate_recent")

        state = "healthy"
        reason = "steady"
        action = "none"
        if not bot_ok:
            state = "failing"
            reason = "runtime_down"
            action = "restart_session"
        elif run_status == "error":
            state = "failing"
            reason = "run_error"
            action = "stop_run"
        elif error_tag not in {"", "unknown"}:
            state = "degraded"
            reason = f"error_tag:{error_tag}"
            action = "stop_run"
        elif isinstance(in_flight, int) and in_flight > 0:
            state = "degraded"
            reason = f"in_flight:{in_flight}"
            action = "observe"
        elif isinstance(turn_success_rate_recent, (int, float)) and turn_total_recent >= 3:
            if turn_success_rate_recent < 60:
                state = "failing"
                reason = f"slo:turn_success_rate={turn_success_rate_recent}%"
                action = "restart_session"
            elif turn_success_rate_recent < 85:
                state = "degraded"
                reason = f"slo:turn_success_rate={turn_success_rate_recent}%"
                action = "observe"

        return {
            "state": state,
            "reason": reason,
            "recommended_action": action,
            "run_status": run_status,
            "bot_ok": bot_ok,
            "in_flight_runs": int(in_flight) if isinstance(in_flight, int) else None,
            "turn_total_recent": turn_total_recent,
            "turn_success_rate_recent": turn_success_rate_recent,
        }

    def _latest_chat_id_for_token(token: str) -> int:
        threads = store.list_threads(token=token)
        if not threads:
            return 1001
        top = max(threads, key=lambda row: int(row.get("last_updated_at") or 0))
        candidate = top.get("chat_id")
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.strip().lstrip("-").isdigit():
            return int(candidate.strip())
        return 1001

    async def _collect_bot_diagnostics(*, selected: dict[str, Any], token: str, chat_id: Optional[int], limit: int) -> dict[str, Any]:
        messages = store.get_messages(token=token, chat_id=chat_id, limit=limit)
        threads = store.list_threads(token=token)
        health, metrics_payload = await fetch_embedded_runtime(selected.get("embedded_url"))
        metrics = extract_runtime_metrics(metrics_payload)
        session_view = infer_session_view_from_messages(messages)
        return {
            "health": health,
            "metrics": metrics,
            "session": session_view,
            "threads_top10": compact_threads(threads, selected_chat_id=chat_id),
            "last_error_tag": classify_last_error_tag(messages),
        }

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
        default_provider = str((selected or {}).get("default_adapter") or "gemini")
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

    @app.get("/_mock/audit_logs")
    async def get_audit_logs(
        bot_id: str,
        chat_id: Optional[int] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        selected = next((row for row in catalog if row.get("bot_id") == bot_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown bot_id: {bot_id}")

        logs, embedded_error = await fetch_embedded_audit_logs(
            selected.get("embedded_url"),
            chat_id=chat_id,
            limit=max(1, min(int(limit), 500)),
        )
        return {
            "ok": True,
            "result": {
                "logs": logs,
                "embedded_error": embedded_error,
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

        created_id = str(created.get("bot_id") or "").strip()
        created_row = next((row for row in bots if str(row.get("bot_id")) == created_id), None)
        return {
            "ok": True,
            "result": {
                "bot": created_row or created,
                "total_bots": len(bots),
            },
        }

    @app.post("/_mock/bot_catalog/delete")
    async def delete_bot_catalog_entry(request: BotCatalogDeleteRequest) -> dict[str, Any]:
        async with catalog_mutation_lock:
            removed = delete_bot_from_catalog(bots_config_path=bots_config_path, bot_id=request.bot_id)
            if not removed:
                raise HTTPException(status_code=404, detail=f"unknown bot_id: {request.bot_id}")
            bots = build_bot_catalog(
                bots_config_path=bots_config_path,
                embedded_host=embedded_host,
                embedded_base_port=embedded_base_port,
            )
        return {
            "ok": True,
            "result": {
                "deleted_bot_id": request.bot_id,
                "total_bots": len(bots),
            },
        }

    @app.get("/_mock/bot_diagnostics")
    async def get_bot_diagnostics(
        bot_id: str,
        token: str,
        chat_id: Optional[int] = None,
        limit: int = 120,
    ) -> dict[str, Any]:
        resolved_limit = max(1, min(int(limit), 300))
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        selected = next((row for row in catalog if row.get("bot_id") == bot_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown bot_id: {bot_id}")
        expected_token = str(selected.get("token") or "").strip()
        if expected_token != token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {bot_id}")

        diagnostics = await _collect_bot_diagnostics(
            selected=selected,
            token=token,
            chat_id=chat_id,
            limit=resolved_limit,
        )

        return {
            "ok": True,
            "result": {
                **diagnostics,
            },
        }

    @app.get("/_mock/control_tower")
    async def get_control_tower(chat_id: Optional[int] = None, limit: int = 80) -> dict[str, Any]:
        resolved_limit = max(20, min(int(limit), 300))
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        rows: list[dict[str, Any]] = []
        for bot in catalog:
            token = str(bot.get("token") or "")
            effective_chat_id = int(chat_id) if chat_id is not None else _latest_chat_id_for_token(token)
            diagnostics = await _collect_bot_diagnostics(
                selected=bot,
                token=token,
                chat_id=effective_chat_id,
                limit=resolved_limit,
            )
            logs, _embedded_error = await fetch_embedded_audit_logs(
                bot.get("embedded_url"),
                chat_id=effective_chat_id,
                limit=min(120, resolved_limit),
            )
            slo = _compute_slo_snapshot(logs)
            state = _compute_tower_state(
                health=diagnostics.get("health") or {},
                metrics=diagnostics.get("metrics") or {},
                session=diagnostics.get("session") or {},
                last_error_tag=str(diagnostics.get("last_error_tag") or "unknown"),
                slo=slo,
            )
            rows.append(
                {
                    "bot_id": str(bot.get("bot_id") or ""),
                    "name": str(bot.get("name") or ""),
                    "mode": str(bot.get("mode") or ""),
                    "token": token,
                    "chat_id": effective_chat_id,
                    "embedded_error": _embedded_error,
                    **state,
                }
            )
        summary = {
            "healthy": sum(1 for row in rows if row.get("state") == "healthy"),
            "degraded": sum(1 for row in rows if row.get("state") == "degraded"),
            "failing": sum(1 for row in rows if row.get("state") == "failing"),
            "total": len(rows),
        }
        return {"ok": True, "result": {"summary": summary, "rows": rows}}

    @app.post("/_mock/control_tower/recover")
    async def control_tower_recover(request: ControlTowerRecoverRequest) -> dict[str, Any]:
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        selected = next((row for row in catalog if str(row.get("bot_id")) == request.bot_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown bot_id: {request.bot_id}")
        expected_token = str(selected.get("token") or "").strip()
        selected_token = str(request.token or expected_token).strip()
        if selected_token != expected_token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {request.bot_id}")

        target_chat_id = int(request.chat_id) if isinstance(request.chat_id, int) else _latest_chat_id_for_token(selected_token)
        target_user_id = int(request.user_id)
        command_results: list[dict[str, Any]] = []

        async def _send_recover_command(text: str) -> None:
            outcome = await _enqueue_and_dispatch_user_message(
                selected_token,
                target_chat_id,
                target_user_id,
                text,
            )
            command_results.append({"text": text, "result": outcome})

        if request.strategy == "restart_session":
            await _send_recover_command("/stop")
            await asyncio.sleep(0.2)
            await _send_recover_command("/new")
        else:
            await _send_recover_command("/stop")

        diagnostics = await _collect_bot_diagnostics(
            selected=selected,
            token=selected_token,
            chat_id=target_chat_id,
            limit=120,
        )
        logs, _embedded_error = await fetch_embedded_audit_logs(
            selected.get("embedded_url"),
            chat_id=target_chat_id,
            limit=120,
        )
        slo = _compute_slo_snapshot(logs)
        state = _compute_tower_state(
            health=diagnostics.get("health") or {},
            metrics=diagnostics.get("metrics") or {},
            session=diagnostics.get("session") or {},
            last_error_tag=str(diagnostics.get("last_error_tag") or "unknown"),
            slo=slo,
        )
        return {
            "ok": True,
            "result": {
                "bot_id": request.bot_id,
                "chat_id": target_chat_id,
                "strategy": request.strategy,
                "commands": command_results,
                "slo": slo,
                "embedded_error": _embedded_error,
                **state,
            },
        }

    @app.get("/_mock/forensics/bundle")
    async def get_forensics_bundle(
        bot_id: str,
        token: Optional[str] = None,
        chat_id: Optional[int] = None,
        limit: int = 120,
    ) -> dict[str, Any]:
        resolved_limit = max(20, min(int(limit), 500))
        catalog = build_bot_catalog(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        selected = next((row for row in catalog if row.get("bot_id") == bot_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown bot_id: {bot_id}")
        expected_token = str(selected.get("token") or "").strip()
        selected_token = str(token or expected_token).strip()
        if selected_token != expected_token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {bot_id}")
        target_chat_id = int(chat_id) if chat_id is not None else _latest_chat_id_for_token(selected_token)

        diagnostics = await _collect_bot_diagnostics(
            selected=selected,
            token=selected_token,
            chat_id=target_chat_id,
            limit=resolved_limit,
        )
        logs, embedded_error = await fetch_embedded_audit_logs(
            selected.get("embedded_url"),
            chat_id=target_chat_id,
            limit=resolved_limit,
        )
        slo = _compute_slo_snapshot(logs)
        state = _compute_tower_state(
            health=diagnostics.get("health") or {},
            metrics=diagnostics.get("metrics") or {},
            session=diagnostics.get("session") or {},
            last_error_tag=str(diagnostics.get("last_error_tag") or "unknown"),
            slo=slo,
        )
        return {
            "ok": True,
            "result": {
                "bot_id": bot_id,
                "token": selected_token,
                "chat_id": target_chat_id,
                "runtime_profile": _infer_runtime_profile(),
                "state": state,
                "slo": slo,
                "diagnostics": diagnostics,
                "audit_logs": logs,
                "embedded_error": embedded_error,
                "messages": store.get_messages(token=selected_token, chat_id=target_chat_id, limit=resolved_limit),
                "updates": store.get_recent_updates(token=selected_token, chat_id=target_chat_id, limit=resolved_limit),
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
        caption: Optional[str] = Form(default=None),
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
        caption: Optional[str] = Form(default=None),
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
