"""Prowlarr client.

Prowlarr fans one query out to every indexer it holds and returns the releases, and grabbing
one hands it to Prowlarr's own download client. Both live on the same path: GET /api/v1/search
runs the search, POST /api/v1/search with a release grabs it.
"""

from __future__ import annotations

from typing import Any

import httpx

from robin import db, upstream

TIMEOUT = 60.0

# Prowlarr queries every indexer in turn, so a search is slow by nature. Sonarr and Radarr
# show a spinner for the same reason.
SEARCH_LIMIT = 100

# Newznab's PC/Games, and nothing else. The parent PC category, 4000, is not included on
# purpose: its other children are 4010 PC/0day, 4020 PC/ISO and 4030 PC/Mac, so asking for it
# fills the results with application software. An indexer that files games only under the
# parent is not worth that.
PC_GAME_CATEGORIES = (4050,)


def _config() -> tuple[str, dict[str, str]]:
    settings = db.get_settings()
    if not settings.prowlarr_ready:
        raise upstream.NotConfigured(
            "Prowlarr is not configured. Add its URL and API key, and qBittorrent, in Settings."
        )
    return settings.prowlarr_url, {"X-Api-Key": settings.prowlarr_api_key}


async def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    base, headers = _config()
    return await upstream.request(
        upstream.UpstreamError,
        "Prowlarr",
        method,
        f"{base}/api/v1{path}",
        timeout=TIMEOUT,
        rejected="Prowlarr rejected the API key",
        headers=headers,
        **kwargs,
    )


async def ping() -> int:
    """Returns how many indexers Prowlarr holds, which proves the key as well as the URL."""
    resp = await _request("GET", "/indexer")
    return len(list(resp.json()))


async def indexers() -> list[dict[str, Any]]:
    """Every indexer Prowlarr holds, so the settings page can offer them to pick from."""
    resp = await _request("GET", "/indexer")
    return [
        {
            "id": int(i.get("id", 0)),
            "name": i.get("name", ""),
            "enabled": bool(i.get("enable", True)),
        }
        for i in resp.json()
        if isinstance(i, dict)
    ]


async def raw(term: str) -> list[dict[str, Any]]:
    """Releases as Prowlarr returns them. Each download URL carries Prowlarr's key, so these
    never leave Robin. An empty term is what the indexers listed lately."""
    params: dict[str, Any] = {
        "query": term,
        "type": "search",
        "limit": SEARCH_LIMIT,
        "categories": list(PC_GAME_CATEGORIES),
    }
    # Prowlarr searches everything it holds unless told otherwise, and plenty of trackers
    # carry no games at all. Scoping here rather than filtering the results keeps those
    # indexers out of the fan out, so the search is faster as well as cleaner.
    chosen = db.get_settings().prowlarr_indexer_ids
    if chosen:
        params["indexerIds"] = chosen

    resp = await _request("GET", "/search", params=params)
    return [r for r in resp.json() if isinstance(r, dict)]


async def torrent(release: dict[str, Any]) -> str | bytes:
    """A release's magnet link, or its .torrent file fetched through Prowlarr, so the download
    client never needs to reach Prowlarr itself. Prowlarr answers a download whose indexer
    hands out magnets with a redirect to the magnet."""
    url = str(release.get("magnetUrl") or release.get("downloadUrl") or "")
    for _ in range(5):
        if url.startswith("magnet:"):
            return url
        resp = await upstream.request(
            upstream.UpstreamError, "Prowlarr", "GET", url, timeout=TIMEOUT
        )
        if not resp.is_redirect:
            return resp.content
        url = str(resp.url.join(resp.headers["location"]))
    raise upstream.UpstreamError(f"Prowlarr redirected {release.get('title')} too many times")
