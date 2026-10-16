"""qBittorrent client: what is downloading in the games category, and the grabs Robin adds.

Home lists the one category set in Settings, whatever lands there, monitored or not. A grab
for a monitored game is added with the tag `robin` and `robin-<request id>`, which is how its
download is found again whatever category it went to.

qBittorrent 5.2 and newer issue an API key in the WebUI settings, sent on every request as a
bearer token, so there is no sign in and no session to keep. Without a key Robin sends no
header at all, for a qBittorrent that lets the LAN in without authentication.
"""

from __future__ import annotations

from typing import Any

import httpx

from robin import db, upstream

TIMEOUT = 15.0

TAG = "robin"


async def _request(settings: db.Settings, method: str, path: str, **kwargs: Any) -> httpx.Response:
    key = settings.qbittorrent_api_key
    return await upstream.request(
        upstream.UpstreamError,
        "qBittorrent",
        method,
        f"{settings.qbittorrent_url}/api/v2{path}",
        timeout=TIMEOUT,
        rejected="qBittorrent rejected the API key"
        if key
        else "qBittorrent wants an API key. Generate one in its WebUI settings.",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        **kwargs,
    )


async def _get(
    settings: db.Settings, path: str, params: dict[str, str] | None = None
) -> httpx.Response:
    return await _request(settings, "GET", path, params=params)


async def version(settings: db.Settings) -> str:
    return (await _get(settings, "/app/version")).text.strip()


async def downloading(settings: db.Settings) -> list[dict[str, Any]]:
    """Every torrent downloading in the configured category, newest first.

    qBittorrent's own `downloading` filter, so a stalled, queued or paused download counts and
    a finished one does not.
    """
    resp = await _get(
        settings,
        "/torrents/info",
        {
            "filter": "downloading",
            "category": settings.qbittorrent_category,
            "sort": "added_on",
            "reverse": "true",
        },
    )
    return [
        {
            "hash": str(t.get("hash", "")),
            "name": str(t.get("name", "")),
            "progress": float(t.get("progress", 0)),
            "dlspeed": int(t.get("dlspeed", 0)),
            "upspeed": int(t.get("upspeed", 0)),
            "eta": int(t.get("eta", 0)),
            "size": int(t.get("size", 0)),
            "state": str(t.get("state", "")),
        }
        for t in resp.json()
    ]


async def categories(settings: db.Settings) -> list[str]:
    """The categories qBittorrent has, by name."""
    return sorted((await _get(settings, "/torrents/categories")).json())


async def add(
    settings: db.Settings, torrent: str | bytes, *, category: str, request_id: int
) -> None:
    """Add a magnet link or a .torrent file under a category, tagged for the monitored game.

    qBittorrent creates a category it does not have yet.
    """
    data = {"category": category, "tags": f"{TAG},{TAG}-{request_id}"}
    if isinstance(torrent, str):
        resp = await _request(settings, "POST", "/torrents/add", data={**data, "urls": torrent})
    else:
        files = {"torrents": ("release.torrent", torrent, "application/x-bittorrent")}
        resp = await _request(settings, "POST", "/torrents/add", data=data, files=files)
    if resp.text.strip() == "Fails.":
        raise upstream.UpstreamError("qBittorrent refused the torrent")


async def grabs(settings: db.Settings) -> dict[int, dict[str, Any]]:
    """Every download Robin added that qBittorrent still holds, by request id."""
    found: dict[int, dict[str, Any]] = {}
    for t in (await _get(settings, "/torrents/info", {"tag": TAG})).json():
        for tag in str(t.get("tags", "")).split(","):
            request_id = tag.strip().removeprefix(f"{TAG}-")
            if request_id.isdigit():
                found[int(request_id)] = {
                    "state": str(t.get("state", "")),
                    "progress": float(t.get("progress", 0)),
                    "eta": int(t.get("eta", 0)),
                }
    return found
