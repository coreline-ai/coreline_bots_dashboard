from __future__ import annotations

from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse


def register_ui_routes(app: FastAPI, *, web_file: Callable[[str], str]) -> None:
    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/_mock/ui", status_code=307)

    @app.get("/_mock/ui")
    async def ui_index() -> FileResponse:
        return FileResponse(web_file("index.html"))

    @app.get("/_mock/ui/app.js")
    async def ui_app_js() -> FileResponse:
        return FileResponse(web_file("app.js"), media_type="application/javascript")

    @app.get("/_mock/ui/styles.css")
    async def ui_styles_css() -> FileResponse:
        return FileResponse(web_file("styles.css"), media_type="text/css")

    @app.get("/_mock/ui/favicon.svg")
    async def ui_favicon() -> FileResponse:
        return FileResponse(web_file("favicon.svg"), media_type="image/svg+xml")
