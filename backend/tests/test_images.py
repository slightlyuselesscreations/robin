"""Source images served from Robin's own cache, so the browser never asks the source."""

import os
import time

import httpx
import pytest
from httpx import AsyncClient

from robin import db, igdb
from robin.routes import images
from tests.conftest import stub_http

POSTER = "https://image.tmdb.org/t/p/w342/abc.jpg"


async def test_a_source_image_is_fetched_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = stub_http(
        monkeypatch,
        lambda _: httpx.Response(200, content=b"jpeg", headers={"content-type": "image/jpeg"}),
    )
    for _ in range(2):
        resp = await client.get("/img/remote", params={"url": POSTER})
        assert resp.status_code == 200
        assert resp.content == b"jpeg"
    assert [str(r.url) for r in seen] == [POSTER]


async def test_another_host_is_left_to_the_browser(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.save_settings({"radarr_url": "http://192.168.1.2:7878"})
    seen = stub_http(monkeypatch, lambda _: httpx.Response(500))
    url = "http://192.168.1.2:7878/MediaCover/1/poster.jpg"
    resp = await client.get("/img/remote", params={"url": url})
    assert resp.status_code == 307
    assert resp.headers["location"] == url
    assert seen == []
    local = await client.get("/img/remote", params={"url": "file:///etc/passwd"})
    assert local.status_code == 400
    broken = await client.get("/img/remote", params={"url": "http://x.test:port/"})
    assert broken.status_code == 400


async def test_no_other_address_is_redirected_to(client: AsyncClient) -> None:
    db.save_settings({"radarr_url": "http://radarr.test"})
    for url in ("https://evil.example/x.jpg", "http://radarr.test.evil.example/x.jpg"):
        assert (await client.get("/img/remote", params={"url": url})).status_code == 404


async def test_an_old_cover_is_served_while_igdb_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down:
        async def get(self, url: str) -> httpx.Response:
            raise httpx.ConnectError("down")

    monkeypatch.setattr(igdb, "client", Down)
    path = images._cache_path("cover_big", "abc")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")
    os.utime(path, (0, 0))
    assert (await client.get("/img/cover_big/abc.jpg")).content == b"old"
    assert (await client.get("/img/cover_big/none.jpg")).status_code == 502


def test_prune_drops_the_unused_then_the_oldest_past_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = images._root() / "remote"
    root.mkdir(parents=True)
    now = time.time()
    ages = {"stale": images.UNUSED_DAYS + 1, "old": 3, "new": 1}
    for name, days in ages.items():
        path = root / name
        path.write_bytes(b"x" * 10)
        os.utime(path, (now - days * 86_400, now - days * 86_400))
    monkeypatch.setattr(images, "CAP_BYTES", 10)
    assert images.prune() == 2
    assert [p.name for p in root.iterdir()] == ["new"]


async def test_suwayomi_covers_are_kept_too(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.save_settings({"suwayomi_url": "http://192.168.1.2:4567"})
    seen = stub_http(
        monkeypatch,
        lambda _: httpx.Response(200, content=b"png", headers={"content-type": "image/png"}),
    )
    cover = "http://192.168.1.2:4567/api/v1/manga/1/thumbnail"
    for _ in range(2):
        assert (await client.get("/img/remote", params={"url": cover})).content == b"png"
    assert [str(r.url) for r in seen] == [cover]

    # Only under its address: the same host on another port is not Suwayomi.
    other = "http://192.168.1.2:8080/secret.png"
    assert (await client.get("/img/remote", params={"url": other})).status_code == 404
