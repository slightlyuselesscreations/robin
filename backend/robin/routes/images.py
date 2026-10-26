"""Local image cache.

Every cover and photo the browser shows comes from here, so it never reaches a source itself.
IGDB's by size and id, every other source's by its URL, fetched once and served from disk.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from robin import comics, db, igdb, upstream
from robin.config import env

log = logging.getLogger(__name__)

router = APIRouter(prefix="/img", tags=["images"])

# Only the sizes the UI renders.
ALLOWED_SIZES = {
    "cover_small",
    "cover_big",
    "cover_big_2x",
    "screenshot_med",
    "screenshot_big",
    "screenshot_huge",
    "720p",
    "1080p",
}

IMAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# IGDB removes replaced images after 30 days, so a cached file is not valid forever.
MAX_AGE_SECONDS = 25 * 24 * 3600


# The image hosts of the external sources, kept beside Suwayomi's own covers, which Robin already
# reaches. Anything else, another integration's, is left to the browser.
REMOTE_HOSTS = {
    "image.tmdb.org",
    "assets.hardcover.app",
    "static.metron.cloud",
    "artworks.thetvdb.com",
}

# A file not served for this long is deleted, and past the cap the least recently served go
# first. A served file has its mtime touched at most once a day, which is what "served" reads.
UNUSED_DAYS = 60
CAP_BYTES = 256 * 1024**2


def _root() -> Path:
    return Path(env.robin_data_dir) / "images"


def _inside(*parts: str) -> Path:
    """The path under the cache root, never above it."""
    root = os.path.normpath(_root())
    full = os.path.normpath(os.path.join(root, *parts))
    if not full.startswith(root + os.sep):
        raise HTTPException(status_code=400, detail="Unknown image")
    return Path(full)


def _cache_path(size: str, image_id: str) -> Path:
    return _inside(size, f"{image_id}.jpg")


def _write(path: Path, content: bytes) -> None:
    """Beside the target then renamed, so a torn download is never a cache hit, under a name of
    its own so two requests for one image do not write one file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    with os.fdopen(fd, "wb") as out:
        out.write(content)
    os.replace(temp, path)


def _served(path: Path) -> None:
    if time.time() - path.stat().st_mtime > 86_400:
        path.touch()


def prune() -> int:
    """Deletes what has not been served in `UNUSED_DAYS`, then the least recently served until
    the cache is under `CAP_BYTES`. Returns how many files went."""
    files = [(f.stat(), f) for f in _root().rglob("*") if f.is_file()]
    files.sort(key=lambda sf: sf[0].st_mtime)
    cutoff = time.time() - UNUSED_DAYS * 86_400
    total = sum(st.st_size for st, _ in files)
    gone = 0
    for st, f in files:
        if st.st_mtime >= cutoff and total <= CAP_BYTES:
            break
        f.unlink(missing_ok=True)
        total -= st.st_size
        gone += 1
    return gone


@router.get("/remote", response_model=None)
async def remote(url: str) -> FileResponse | RedirectResponse:
    """A source's image by its URL, or one under Suwayomi's address. Any other is redirected to.

    A Suwayomi cover has no extension and is kept as .jpg, which the browser reads by its bytes.
    """
    parsed = httpx.URL(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Not an image URL")
    suwayomi = db.get_settings().suwayomi_url
    if parsed.host not in REMOTE_HOSTS and not (suwayomi and url.startswith(f"{suwayomi}/")):
        return RedirectResponse(url)

    suffix = Path(parsed.path).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        suffix = ".jpg"
    key = hashlib.sha256(url.encode()).hexdigest()
    path = _inside("remote", key[:2], f"{key}{suffix}")

    if path.exists():
        _served(path)
    else:
        try:
            # Robin names itself to every source, as Metron asks.
            resp = await upstream._client().get(
                url, headers={"User-Agent": comics.USER_AGENT}, timeout=20
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach {parsed.host}") from exc
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
            raise HTTPException(status_code=404, detail="No such image")
        _write(path, resp.content)

    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@router.get("/{size}/{image_id}.jpg")
async def image(size: str, image_id: str) -> FileResponse:
    if size not in ALLOWED_SIZES or not IMAGE_ID.fullmatch(image_id):
        raise HTTPException(status_code=400, detail="Unknown image size or id")

    path = _cache_path(size, image_id)
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < MAX_AGE_SECONDS

    if not fresh:
        try:
            resp = await igdb.client().get(igdb.image_url(image_id, size))
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"Could not reach IGDB images: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="No such image")
        _write(path, resp.content)

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )
