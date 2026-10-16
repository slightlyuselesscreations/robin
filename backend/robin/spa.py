"""Serve the built frontend.

In development Vite serves the SPA and proxies /api here, so this is inert. In the container
the built assets sit beside the package and FastAPI serves them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

# ROBIN_STATIC_DIR overrides this. The Dockerfile points it at /app/static.
DEFAULT_STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class _HashedAssets(StaticFiles):
    """Assets carry a content hash in the filename, so a copy the browser holds is never wrong.

    Without this every asset costs a revalidation round trip on each visit.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
        **kwargs: Any,
    ) -> Response:
        resp = super().file_response(full_path, stat_result, scope, status_code, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def mount(app: FastAPI, static_dir: Path) -> bool:
    """Mount the SPA if a build exists. Returns whether anything was mounted."""
    index = static_dir / "index.html"
    if not index.is_file():
        return False

    app.mount("/assets", _HashedAssets(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # Client side routes such as /games have no file, so they fall back to the shell.
        # Anything under /api or /img is already routed above and never reaches here.
        candidate = (static_dir / path).resolve()
        if path and static_dir in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        if path.startswith(("api/", "img/")):
            raise HTTPException(status_code=404, detail="Not found")
        # The shell names the hashed assets, so a stale copy points at a bundle that a deploy
        # has already removed. Revalidating it every time is one cheap request.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
