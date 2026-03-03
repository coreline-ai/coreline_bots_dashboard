from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from fastapi import FastAPI, HTTPException

from telegram_bot_new.mock_messenger.bot_catalog import (
    build_bot_catalog,
    classify_last_error_tag,
    compact_threads,
    extract_runtime_metrics,
    fetch_embedded_audit_logs,
    fetch_embedded_runtime,
    infer_session_view_from_messages,
)
from telegram_bot_new.mock_messenger.runtime_profile import explain_unknown_bot_id
from telegram_bot_new.mock_messenger.schemas import ControlTowerRecoverRequest
from telegram_bot_new.mock_messenger.store import MockMessengerStore


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


def _latest_chat_id_for_token(store: MockMessengerStore, token: str) -> int:
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


async def _collect_bot_diagnostics(
    *,
    store: MockMessengerStore,
    selected: dict[str, Any],
    token: str,
    chat_id: Optional[int],
    limit: int,
) -> dict[str, Any]:
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


def register_diagnostics_routes(
    app: FastAPI,
    *,
    store: MockMessengerStore,
    bots_config_path: Union[str, Path],
    embedded_host: str,
    embedded_base_port: int,
    infer_runtime_profile: Callable[[], dict[str, Any]],
    enqueue_and_dispatch_user_message: Callable[[str, int, int, str], Awaitable[dict[str, Any]]],
) -> None:
    def _unknown_bot_detail(bot_id: str) -> str:
        return explain_unknown_bot_id(
            bot_id=str(bot_id or "").strip(),
            runtime_profile=infer_runtime_profile(),
        )

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
            raise HTTPException(status_code=404, detail=_unknown_bot_detail(bot_id))

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
            raise HTTPException(status_code=404, detail=_unknown_bot_detail(bot_id))
        expected_token = str(selected.get("token") or "").strip()
        if expected_token != token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {bot_id}")

        diagnostics = await _collect_bot_diagnostics(
            store=store,
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
            effective_chat_id = int(chat_id) if chat_id is not None else _latest_chat_id_for_token(store, token)
            diagnostics = await _collect_bot_diagnostics(
                store=store,
                selected=bot,
                token=token,
                chat_id=effective_chat_id,
                limit=resolved_limit,
            )
            logs, embedded_error = await fetch_embedded_audit_logs(
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
                    "embedded_error": embedded_error,
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
            raise HTTPException(status_code=404, detail=_unknown_bot_detail(request.bot_id))
        expected_token = str(selected.get("token") or "").strip()
        selected_token = str(request.token or expected_token).strip()
        if selected_token != expected_token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {request.bot_id}")

        target_chat_id = int(request.chat_id) if isinstance(request.chat_id, int) else _latest_chat_id_for_token(store, selected_token)
        target_user_id = int(request.user_id)
        command_results: list[dict[str, Any]] = []

        async def _send_recover_command(text: str) -> None:
            outcome = await enqueue_and_dispatch_user_message(
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
            store=store,
            selected=selected,
            token=selected_token,
            chat_id=target_chat_id,
            limit=120,
        )
        logs, embedded_error = await fetch_embedded_audit_logs(
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
                "embedded_error": embedded_error,
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
            raise HTTPException(status_code=404, detail=_unknown_bot_detail(bot_id))
        expected_token = str(selected.get("token") or "").strip()
        selected_token = str(token or expected_token).strip()
        if selected_token != expected_token:
            raise HTTPException(status_code=400, detail=f"token does not match bot_id: {bot_id}")
        target_chat_id = int(chat_id) if chat_id is not None else _latest_chat_id_for_token(store, selected_token)

        diagnostics = await _collect_bot_diagnostics(
            store=store,
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
                "runtime_profile": infer_runtime_profile(),
                "state": state,
                "slo": slo,
                "diagnostics": diagnostics,
                "audit_logs": logs,
                "embedded_error": embedded_error,
                "messages": store.get_messages(token=selected_token, chat_id=target_chat_id, limit=resolved_limit),
                "updates": store.get_recent_updates(token=selected_token, chat_id=target_chat_id, limit=resolved_limit),
            },
        }
