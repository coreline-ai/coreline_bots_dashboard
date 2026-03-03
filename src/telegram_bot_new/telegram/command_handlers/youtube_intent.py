from __future__ import annotations

import re


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
        "유튜브",
        "유투브",
        "유트브",
        "유트뷰",
    )
    has_youtube = any(variant in lowered for variant in youtube_variants)
    if not has_youtube:
        return (False, None)

    search_hints = (
        "search",
        "find",
        "recommend",
        "show",
        "찾아",
        "검색",
        "추천",
        "보여",
    )
    if not any(hint in lowered for hint in search_hints):
        return (False, None)

    cleaned = text
    for pattern in (
        r"(?i)\byoutube\b",
        "유튜브",
        "유투브",
        "유트브",
        "유트뷰",
        "동영상",
        "영상",
        "찾아줘",
        "찾아 줘",
        "찾아",
        "검색해줘",
        "검색해 줘",
        "검색",
        "추천해줘",
        "추천해 줘",
        "추천",
        "보여줘",
        "보여 줘",
        "보여",
        "미리보기",
        "미리 보기",
        "형식으로",
        "형식",
        "이런",
        "같은",
        "please",
        "for me",
    ):
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?\n\t")
    return (True, cleaned or None)

