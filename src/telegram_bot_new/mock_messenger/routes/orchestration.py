from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from telegram_bot_new.mock_messenger.bot_catalog import build_bot_catalog
from telegram_bot_new.mock_messenger.cowork import (
    ActiveCoworkExistsError,
    CoworkNotFoundError,
    CoworkOrchestrator,
)
from telegram_bot_new.mock_messenger.debate import (
    ActiveDebateExistsError,
    DebateNotFoundError,
    DebateOrchestrator,
)
from telegram_bot_new.mock_messenger.runtime_profile import explain_unknown_bot_id, infer_runtime_profile
from telegram_bot_new.mock_messenger.schemas import CoworkStartRequest, DebateStartRequest


def register_orchestration_routes(
    app: FastAPI,
    *,
    debate_orchestrator: DebateOrchestrator,
    cowork_orchestrator: CoworkOrchestrator,
    bots_config_path: Union[str, Path],
    embedded_host: str,
    embedded_base_port: int,
) -> None:
    def _unknown_bot_detail(bot_id: str) -> str:
        profile = infer_runtime_profile(
            bots_config_path=bots_config_path,
            embedded_host=embedded_host,
            embedded_base_port=embedded_base_port,
        )
        return explain_unknown_bot_id(bot_id=str(bot_id or "").strip(), runtime_profile=profile)

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
                raise HTTPException(status_code=400, detail=_unknown_bot_detail(profile.bot_id))
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
    async def get_active_debate(scope_key: str | None = None) -> dict[str, Any]:
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

    @app.post("/_mock/cowork/start")
    async def start_cowork(request: CoworkStartRequest) -> dict[str, Any]:
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
                raise HTTPException(status_code=400, detail=_unknown_bot_detail(profile.bot_id))
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
                    "role": str(profile.role),
                    "adapter": str(row.get("default_adapter") or ""),
                }
            )

        try:
            result = await cowork_orchestrator.start_cowork(
                request=request,
                participants=participants,
            )
        except ActiveCoworkExistsError as error:
            raise HTTPException(status_code=409, detail=f"active cowork already exists: {error}") from error
        return {"ok": True, "result": result}

    @app.get("/_mock/cowork/active")
    async def get_active_cowork() -> dict[str, Any]:
        return {"ok": True, "result": cowork_orchestrator.get_active_cowork_snapshot()}

    @app.get("/_mock/cowork/{cowork_id}")
    async def get_cowork(cowork_id: str) -> dict[str, Any]:
        snapshot = cowork_orchestrator.get_cowork_snapshot(cowork_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"unknown cowork_id: {cowork_id}")
        return {"ok": True, "result": snapshot}

    @app.post("/_mock/cowork/{cowork_id}/stop")
    async def stop_cowork(cowork_id: str) -> dict[str, Any]:
        try:
            result = await cowork_orchestrator.stop_cowork(cowork_id)
        except CoworkNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"unknown cowork_id: {error}") from error
        return {"ok": True, "result": result}

    @app.get("/_mock/cowork/{cowork_id}/artifacts")
    async def get_cowork_artifacts(cowork_id: str) -> dict[str, Any]:
        result = cowork_orchestrator.get_cowork_artifacts(cowork_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"unknown cowork_id: {cowork_id}")
        return {"ok": True, "result": result}

    @app.get("/_mock/cowork/{cowork_id}/artifact/{filename:path}")
    async def get_cowork_artifact_file(cowork_id: str, filename: str) -> FileResponse:
        path = cowork_orchestrator.resolve_artifact_path(cowork_id, filename)
        if path is None:
            raise HTTPException(status_code=404, detail=f"unknown cowork artifact: {cowork_id}/{filename}")
        media_type = "application/octet-stream"
        suffix = path.suffix.lower()
        if suffix == ".json":
            media_type = "application/json"
        elif suffix in {".md", ".markdown"}:
            media_type = "text/markdown"
        elif suffix in {".txt", ".log"}:
            media_type = "text/plain"
        return FileResponse(path, media_type=media_type)
