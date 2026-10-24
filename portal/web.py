"""Local browser application with short-lived, single-use Excel and PDF downloads."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from urllib.parse import quote

import flet.fastapi as flet_api
import uvicorn
from fastapi import HTTPException
from fastapi.responses import Response

from automations.bordero.panel_data import ConferenceRow, export_conferences
from portal.app import main

ASSETS_DIR = Path(__file__).with_name("assets")


class Downloads:
    """Keep at most eight reports in memory for five minutes; no public files."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, bytes, str]] = {}
        self._lock = Lock()

    def issue(
        self, rows: tuple[ConferenceRow, ...], start: date, end: date, hotel: str
    ) -> str:
        name = f"conferencias-{start:%Y%m%d}-{end:%Y%m%d}.xlsx"
        with TemporaryDirectory(prefix="bordero-export-") as folder:
            path = Path(folder) / name
            export_conferences(rows, path, hotel=hotel, start_date=start, end_date=end)
            content = path.read_bytes()
        return self.issue_file(content, name)

    def issue_file(self, content: bytes, name: str) -> str:
        # Never interpret file names from the database as paths or HTTP headers.
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        name = (
            "".join(char for char in name if ord(char) >= 32 and ord(char) != 127)
            or "anexo"
        )
        token = token_urlsafe(32)
        with self._lock:
            now = monotonic()
            self._items = {
                key: value for key, value in self._items.items() if value[0] > now
            }
            if len(self._items) >= 8:
                del self._items[next(iter(self._items))]
            self._items[token] = (now + 300, content, name)
        return f"/downloads/{token}"

    def take(self, token: str) -> tuple[bytes, str]:
        with self._lock:
            item = self._items.pop(token, None)
        if item is None or item[0] <= monotonic():
            raise HTTPException(
                status_code=404, detail="Download expirado. Gere o Excel novamente."
            )
        return item[1], item[2]


def create_app():
    downloads = Downloads()
    app = flet_api.FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/downloads/{token}")
    def download(token: str):
        content, name = downloads.take(token)
        return Response(
            content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app.mount(
        "/",
        flet_api.app(
            lambda page: main(
                page,
                web_download=downloads.issue,
                attachment_download=downloads.issue_file,
            ),
            assets_dir=str(ASSETS_DIR),
        ),
    )
    return app


def serve() -> None:
    # Local only: exposing financial data on the network requires authentication/TLS.
    uvicorn.run(create_app(), host="127.0.0.1", port=8550, access_log=False)


if __name__ == "__main__":
    serve()
