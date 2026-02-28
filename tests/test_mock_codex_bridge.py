from __future__ import annotations

from pathlib import Path

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.mock_messenger.codex_bridge import (
    MAX_MESSAGE_LEN,
    _augment_prompt_for_generation_request,
    _build_codex_command,
    _extract_local_html_paths,
    _extract_local_image_paths,
    _find_recent_html_files,
    _find_recent_image_files,
    _format_event_lines,
    _looks_like_html_request,
    _looks_like_image_request,
    _parse_youtube_search_request,
    build_parser,
)


def test_build_codex_command_new_turn() -> None:
    cmd = _build_codex_command(
        codex_bin="codex",
        prompt="hello",
        thread_id=None,
        model="gpt-5",
        sandbox="danger-full-access",
    )
    assert cmd == [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-m",
        "gpt-5",
        "-s",
        "danger-full-access",
        "hello",
    ]


def test_build_codex_command_resume_turn() -> None:
    cmd = _build_codex_command(
        codex_bin="codex",
        prompt="continue",
        thread_id="thread-1",
        model=None,
        sandbox="danger-full-access",
    )
    assert cmd == [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-s",
        "danger-full-access",
        "resume",
        "thread-1",
        "continue",
    ]


def test_format_event_lines_chunks_long_payload() -> None:
    long_text = "x" * (MAX_MESSAGE_LEN * 2)
    event = AdapterEvent(
        seq=7,
        ts="2026-01-01T00:00:00+00:00",
        event_type="assistant_message",
        payload={"text": long_text},
    )

    lines = _format_event_lines(event)
    assert len(lines) == 1
    assert lines[0].startswith("[7][00:00:00][assistant_message] ")
    assert "[truncated" in lines[0]


def test_format_event_lines_truncates_command_output() -> None:
    event = AdapterEvent(
        seq=3,
        ts="2026-01-01T00:00:00+00:00",
        event_type="command_completed",
        payload={
            "command": "rg --files",
            "exit_code": 0,
            "aggregated_output": "x" * 5000,
        },
    )

    lines = _format_event_lines(event)
    combined = "\n".join(lines)
    assert "exit_code=0" in combined
    assert "[truncated" in combined


def test_extract_local_image_paths_from_markdown(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "result.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)

    text = "Generated image: ![preview](./result.png)"
    paths = _extract_local_image_paths(text)
    assert len(paths) == 1
    assert paths[0].name == "result.png"


def test_extract_local_html_paths_from_markdown(tmp_path: Path, monkeypatch) -> None:
    html = tmp_path / "landing.html"
    html.write_text("<html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    text = "Generated page: [landing](./landing.html)"
    paths = _extract_local_html_paths(text)
    assert len(paths) == 1
    assert paths[0].name == "landing.html"


def test_looks_like_image_request_korean_phrase() -> None:
    assert _looks_like_image_request("꽃 이미지 만들고 현재 이미지 창에 보여줘")


def test_looks_like_html_request_korean_phrase() -> None:
    assert _looks_like_html_request("랜딩 페이지 html css로 만들어서 보여줘")


def test_augment_prompt_for_generation_request_adds_contracts() -> None:
    prompt = "꽃 이미지와 html 랜딩 페이지를 만들어줘"
    augmented = _augment_prompt_for_generation_request(prompt)
    assert prompt in augmented
    assert "Image Delivery Contract" in augmented
    assert "HTML Delivery Contract" in augmented


def test_find_recent_image_files_with_roots(tmp_path: Path) -> None:
    img = tmp_path / "flower.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    files = _find_recent_image_files(since_epoch=img.stat().st_mtime - 1, roots=[tmp_path], limit=3)
    assert any(path.name == "flower.png" for path in files)


def test_find_recent_html_files_with_roots(tmp_path: Path) -> None:
    html = tmp_path / "landing.html"
    html.write_text("<html></html>", encoding="utf-8")

    files = _find_recent_html_files(since_epoch=html.stat().st_mtime - 1, roots=[tmp_path], limit=3)
    assert any(path.name == "landing.html" for path in files)


def test_parse_youtube_search_request_with_korean_phrase() -> None:
    intent, query = _parse_youtube_search_request("\ubc31\uc885\uc6d0 PAIK JONG WON \uc720\ud29c\ube0c \ucc3e\uc544\uc918")
    assert intent is True
    assert query is not None
    assert "PAIK JONG WON" in query
    assert "\uc720\ud29c\ube0c" not in query


def test_parse_youtube_search_request_with_common_typo_and_preview_phrase() -> None:
    intent, query = _parse_youtube_search_request("\ubc31\uc885\uc6d0 \uc720\ud22c\ube0c \ubbf8\ub9ac \ubcf4\uae30 \ud615\uc2dd\uc73c\ub85c \ubcf4\uc5ec\uc918")
    assert intent is True
    assert query == "\ubc31\uc885\uc6d0"


def test_codex_bridge_default_sandbox_is_workspace_write() -> None:
    args = build_parser().parse_args([])
    assert args.sandbox == "workspace-write"
