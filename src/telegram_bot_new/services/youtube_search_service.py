from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import httpx


_VIDEO_ID_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_WATCH_URL_RE = re.compile(r"https?://(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
_SHORT_URL_RE = re.compile(r"https?://youtu\.be/([A-Za-z0-9_-]{11})")


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


@dataclass
class YoutubeSearchResult:
    video_id: str
    url: str
    title: Optional[str] = None
    author_name: Optional[str] = None


class YoutubeSearchService:
    def __init__(self, *, timeout_sec: float = 10.0, max_candidates: int = 20) -> None:
        self._timeout_sec = timeout_sec
        self._max_candidates = max(1, max_candidates)
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

    async def search_first_video(self, query: str) -> Optional[YoutubeSearchResult]:
        normalized = " ".join(query.split())
        if not normalized:
            return None

        video_id = await self._resolve_video_id(normalized)
        if not video_id:
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"
        title, author_name = await self._fetch_oembed(url)
        return YoutubeSearchResult(
            video_id=video_id,
            url=url,
            title=title,
            author_name=author_name,
        )

    async def _resolve_video_id(self, query: str) -> Optional[str]:
        for resolver in (self._search_from_youtube_results, self._search_from_duckduckgo):
            try:
                video_id = await resolver(query)
            except Exception:
                continue
            if video_id:
                return video_id
        return None

    async def _search_from_youtube_results(self, query: str) -> Optional[str]:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        async with httpx.AsyncClient(
            timeout=self._timeout_sec,
            follow_redirects=True,
            headers=self._headers,
        ) as client:
            response = await client.get(url)
        response.raise_for_status()

        video_ids = _dedupe_keep_order(_VIDEO_ID_RE.findall(response.text))
        if not video_ids:
            return None
        return video_ids[0]

    async def _search_from_duckduckgo(self, query: str) -> Optional[str]:
        q = f"site:youtube.com/watch {query}"
        url = f"https://duckduckgo.com/html/?q={quote_plus(q)}"
        async with httpx.AsyncClient(
            timeout=self._timeout_sec,
            follow_redirects=True,
            headers=self._headers,
        ) as client:
            response = await client.get(url)
        response.raise_for_status()

        candidates = _WATCH_URL_RE.findall(response.text)
        candidates.extend(_SHORT_URL_RE.findall(response.text))
        video_ids = _dedupe_keep_order(candidates)
        if not video_ids:
            return None
        return video_ids[0]

    async def _fetch_oembed(self, url: str) -> tuple[Optional[str], Optional[str]]:
        endpoint = f"https://www.youtube.com/oembed?url={quote_plus(url)}&format=json"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec, headers=self._headers) as client:
                response = await client.get(endpoint)
            response.raise_for_status()
            body = response.json()
        except Exception:
            return (None, None)

        if not isinstance(body, dict):
            return (None, None)
        title = body.get("title")
        author_name = body.get("author_name")
        return (
            title if isinstance(title, str) and title.strip() else None,
            author_name if isinstance(author_name, str) and author_name.strip() else None,
        )

