"""qBittorrent: the API key, listing the games category's downloads, silent while unset."""

from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import stub_http

KEY = "qbt_live_key_123456"


def torrent(name: str, **fields: Any) -> dict[str, Any]:
    """One entry of /api/v2/torrents/info, trimmed to what Robin reads."""
    return {
        "hash": name.casefold(),
        "name": name,
        "progress": 0.42,
        "dlspeed": 12_500_000,
        "upspeed": 800_000,
        "eta": 300,
        "size": 70_000_000_000,
        "state": "downloading",
        **fields,
    }


@pytest.fixture
def qbt(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """A qBittorrent that answers only requests carrying the API key."""
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401, text="Unauthorized")
        return httpx.Response(200, json=[torrent("Metro.2039-RUNE"), torrent("Fable-TENOKE")])

    stub_http(monkeypatch, handler)
    return asked


async def configure(client: AsyncClient, key: str = KEY, **extra: str) -> None:
    await client.put(
        "/api/settings",
        json={"qbittorrent_url": "http://qbt.test:8080/", "qbittorrent_api_key": key, **extra},
    )


async def test_every_download_in_the_category_is_listed(
    client: AsyncClient, qbt: list[httpx.Request]
) -> None:
    await configure(client)

    listed = (await client.get("/api/qbittorrent/downloads")).json()
    assert [t["name"] for t in listed] == ["Metro.2039-RUNE", "Fable-TENOKE"]
    assert (listed[0]["progress"], listed[0]["dlspeed"], listed[0]["upspeed"]) == (
        0.42,
        12_500_000,
        800_000,
    )
    [request] = qbt
    assert request.url.path == "/api/v2/torrents/info"
    assert dict(request.url.params) == {
        "filter": "downloading",
        "category": "games",
        "sort": "added_on",
        "reverse": "true",
    }


async def test_the_category_comes_from_settings(
    client: AsyncClient, qbt: list[httpx.Request]
) -> None:
    await configure(client, qbittorrent_category="pc-games")
    await client.get("/api/qbittorrent/downloads")
    assert qbt[0].url.params["category"] == "pc-games"
    assert (await client.get("/api/settings")).json()["qbittorrent_category"] == "pc-games"


async def test_a_wrong_key_is_reported_and_never_shown(
    client: AsyncClient, qbt: list[httpx.Request]
) -> None:
    await configure(client, key="not-the-right-key")
    resp = await client.get("/api/qbittorrent/downloads")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "qBittorrent rejected the API key"
    settings = (await client.get("/api/settings")).json()
    assert settings["has_qbittorrent_api_key"] is True
    assert "not-the-right-key" not in str(settings)


async def test_without_a_key_no_header_is_sent(
    client: AsyncClient, qbt: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"qbittorrent_url": "http://qbt.test:8080"})
    resp = await client.get("/api/qbittorrent/downloads")
    assert "authorization" not in qbt[0].headers
    assert resp.json()["detail"].startswith("qBittorrent wants an API key")


async def test_nothing_is_asked_while_qbittorrent_is_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected outbound request to {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    assert (await client.get("/api/qbittorrent/downloads")).json() == []
    assert (await client.get("/api/settings")).json()["qbittorrent_ready"] is False
