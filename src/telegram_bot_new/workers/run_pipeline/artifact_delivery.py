from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


async def deliver_generated_artifacts(
    *,
    bot_id: str,
    chat_id: int,
    turn_id: str,
    user_text: str,
    assistant_text: str,
    run_started_epoch: float,
    artifact_output_dir: Path | None,
    telegram_client: Any,
    streamer: Any,
    sent_registry: dict[str, set[str]],
    image_suffixes: set[str],
    html_suffixes: set[str],
    extract_local_paths_fn,
    find_recent_files_fn,
    find_recent_files_in_roots_fn,
    artifact_dedupe_key_fn,
    looks_like_image_request_fn,
    looks_like_html_request_fn,
    telegram_api_error_type: type[Exception],
    logger: logging.Logger,
) -> None:
    image_paths = extract_local_paths_fn(assistant_text, suffixes=image_suffixes)
    html_paths = extract_local_paths_fn(assistant_text, suffixes=html_suffixes)

    if not image_paths and looks_like_image_request_fn(user_text):
        if artifact_output_dir is None:
            image_paths = find_recent_files_fn(since_epoch=run_started_epoch, suffixes=image_suffixes, limit=3)
        else:
            image_paths = find_recent_files_in_roots_fn(
                since_epoch=run_started_epoch,
                suffixes=image_suffixes,
                scan_roots=[artifact_output_dir],
                limit=3,
            )

    if not html_paths and looks_like_html_request_fn(user_text):
        if artifact_output_dir is None:
            html_paths = find_recent_files_fn(since_epoch=run_started_epoch, suffixes=html_suffixes, limit=2)
        else:
            html_paths = find_recent_files_in_roots_fn(
                since_epoch=run_started_epoch,
                suffixes=html_suffixes,
                scan_roots=[artifact_output_dir],
                limit=2,
            )

    unique_files: list[tuple[Path, str]] = []
    sent_for_chat = sent_registry.setdefault(f"{bot_id}:{chat_id}", set())

    for image_path in image_paths:
        key = artifact_dedupe_key_fn(image_path)
        if key in sent_for_chat:
            continue
        sent_for_chat.add(key)
        unique_files.append((image_path, "image"))

    for html_path in html_paths:
        key = artifact_dedupe_key_fn(html_path)
        if key in sent_for_chat:
            continue
        sent_for_chat.add(key)
        unique_files.append((html_path, "html"))

    for path, kind in unique_files:
        try:
            if kind == "image":
                try:
                    await telegram_client.send_photo(
                        chat_id=chat_id,
                        file_path=str(path),
                        caption=f"[artifact:image] {path.name}",
                    )
                except telegram_api_error_type:
                    await telegram_client.send_document(
                        chat_id=chat_id,
                        file_path=str(path),
                        caption=f"[artifact:image] {path.name}",
                    )
            else:
                await telegram_client.send_document(
                    chat_id=chat_id,
                    file_path=str(path),
                    caption=f"[artifact:html] {path.name}",
                )
        except Exception as error:
            logger.warning("artifact delivery failed bot=%s chat=%s path=%s err=%s", bot_id, chat_id, path, error)
            await streamer.append_delivery_error(
                turn_id=turn_id,
                chat_id=chat_id,
                message=f"artifact delivery failed for {path.name}: {error}",
            )
