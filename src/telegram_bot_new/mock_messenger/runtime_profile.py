from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from telegram_bot_new.mock_messenger.bot_catalog import build_bot_catalog


def _read_bot_ids_from_config(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(loaded, dict):
        return []
    bots = loaded.get("bots")
    if not isinstance(bots, list):
        return []
    result: list[str] = []
    for item in bots:
        if not isinstance(item, dict):
            continue
        bot_id = str(item.get("bot_id") or "").strip()
        if bot_id:
            result.append(bot_id)
    return result


def resolve_source_config_path(*, bots_config_path: str | Path) -> Path | None:
    config_path = Path(bots_config_path).expanduser().resolve()
    default_source = Path.cwd() / "config" / "bots.multibot.yaml"
    if config_path.name == "bots.effective.yaml" and default_source.exists():
        return default_source.resolve()
    if config_path.exists():
        return config_path
    return None


def infer_runtime_profile(
    *,
    bots_config_path: str | Path,
    embedded_host: str,
    embedded_base_port: int,
) -> dict[str, Any]:
    catalog = build_bot_catalog(
        bots_config_path=bots_config_path,
        embedded_host=embedded_host,
        embedded_base_port=embedded_base_port,
    )
    effective_bots = len(catalog)
    config_path = Path(bots_config_path).expanduser().resolve()

    source_path = resolve_source_config_path(bots_config_path=config_path)
    source_ids = _read_bot_ids_from_config(source_path)
    source_bots = len(source_ids) if source_ids else effective_bots

    max_bots_env = (os.getenv("MAX_BOTS") or "").strip()
    max_bots = int(max_bots_env) if max_bots_env.isdigit() else (effective_bots if source_bots > effective_bots else None)
    return {
        "effective_bots": effective_bots,
        "source_bots": source_bots,
        "max_bots": max_bots,
        "is_capped": bool(source_bots > effective_bots),
        "bots_config_path": str(config_path),
        "source_config_path": str(source_path) if source_path is not None else None,
    }


def source_bot_index(*, bot_id: str, source_config_path: str | Path | None) -> int | None:
    source_path = Path(source_config_path).expanduser().resolve() if source_config_path else None
    source_ids = _read_bot_ids_from_config(source_path)
    try:
        return source_ids.index(bot_id)
    except ValueError:
        return None


def explain_unknown_bot_id(*, bot_id: str, runtime_profile: dict[str, Any]) -> str:
    base = f"unknown bot_id: {bot_id}"
    if not bool(runtime_profile.get("is_capped")):
        return base

    source_path = runtime_profile.get("source_config_path")
    position = source_bot_index(bot_id=bot_id, source_config_path=source_path)
    if position is None:
        return base

    required_max_bots = position + 1
    effective = int(runtime_profile.get("effective_bots") or 0)
    source = int(runtime_profile.get("source_bots") or 0)
    return (
        f"{base} (excluded by MAX_BOTS cap: effective={effective}/{source}, "
        f"required MAX_BOTS>={required_max_bots}). Restart with MAX_BOTS=0 (all bots) "
        f"or MAX_BOTS>={required_max_bots}."
    )
