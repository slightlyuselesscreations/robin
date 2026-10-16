"""The pace and the pause on the data sources Robin borrows from, and never on integrations."""

import asyncio
import dataclasses
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, upstream
from tests.conftest import stub_http

TOKEN = "eyJhbGciOiJIUzI1NiJ9.read-access-token"


def answering(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response) -> list[str]:
    """Every request answered in turn by `responses`, the last one repeating."""
    asked: list[str] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    stub_http(monkeypatch, handler)
    return asked


async def tmdb(path: str = "/configuration") -> httpx.Response:
    return await upstream.request(
        upstream.UpstreamError,
        "TMDB",
        "GET",
        f"https://api.themoviedb.org/3{path}",
        timeout=5,
        source="tmdb",
    )


async def test_a_source_never_starts_more_than_its_rate_in_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        upstream.LIMITS, "tmdb", dataclasses.replace(upstream.LIMITS["tmdb"], rate=2, per=0.3)
    )
    answering(monkeypatch, httpx.Response(200, json={}))

    started = time.monotonic()
    await asyncio.gather(*(tmdb() for _ in range(5)))
    # Two in the first window, two in the second, one in the third.
    assert time.monotonic() - started >= 0.6


async def test_a_source_holds_no_more_than_its_cap_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        upstream.LIMITS, "tmdb", dataclasses.replace(upstream.LIMITS["tmdb"], in_flight=2)
    )
    flying = 0
    most = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal flying, most
        flying += 1
        most = max(most, flying)
        await asyncio.sleep(0.02)
        flying -= 1
        return httpx.Response(200, json={})

    stub_http(monkeypatch, handler)
    await asyncio.gather(*(tmdb() for _ in range(6)))
    assert most == 2


async def test_slow_down_pauses_the_source_for_the_time_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = answering(monkeypatch, httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(upstream.RateLimited) as caught:
        await tmdb()
    wait = (caught.value.until - datetime.now(UTC)).total_seconds()
    assert 110 < wait <= 120

    # Paused: nothing leaves, and the error says until when.
    with pytest.raises(upstream.RateLimited):
        await tmdb()
    assert len(asked) == 1
    assert upstream.paused_until("tmdb") == caught.value.until
    assert upstream.paused_until("hardcover") is None


async def test_a_refusal_naming_no_time_pauses_longer_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answering(monkeypatch, httpx.Response(429))
    first = upstream.LIMITS["tmdb"].first_pause

    with pytest.raises(upstream.RateLimited) as one:
        await tmdb()
    assert (one.value.until - datetime.now(UTC)).total_seconds() == pytest.approx(first, abs=5)

    # The pause has passed, and the source refuses again.
    held = db.cache_get("limit:v1:tmdb")
    assert isinstance(held, dict)
    held["until"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    db.cache_put("limit:v1:tmdb", held, 600)
    with pytest.raises(upstream.RateLimited) as two:
        await tmdb()
    assert (two.value.until - datetime.now(UTC)).total_seconds() == pytest.approx(first * 2, abs=5)


async def test_a_retry_after_date_is_read_too(monkeypatch: pytest.MonkeyPatch) -> None:
    when = datetime.now(UTC) + timedelta(minutes=10)
    stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    answering(monkeypatch, httpx.Response(503, headers={"Retry-After": stamp}))
    with pytest.raises(upstream.RateLimited) as caught:
        await tmdb()
    assert abs((caught.value.until - when).total_seconds()) < 5


async def test_an_outage_without_a_time_is_an_error_not_a_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answering(monkeypatch, httpx.Response(503))
    with pytest.raises(upstream.UpstreamError) as caught:
        await tmdb()
    assert not isinstance(caught.value, upstream.RateLimited)
    assert upstream.paused_until("tmdb") is None


async def test_an_integration_is_never_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = answering(monkeypatch, httpx.Response(429, headers={"Retry-After": "600"}))
    for _ in range(3):
        with pytest.raises(upstream.UpstreamError) as caught:
            await upstream.request(
                upstream.UpstreamError, "Prowlarr", "GET", "http://prowlarr.test/api", timeout=5
            )
        assert not isinstance(caught.value, upstream.RateLimited)
    assert len(asked) == 3


async def test_a_paused_source_answers_429_with_when_it_resumes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})
    asked = answering(monkeypatch, httpx.Response(429, headers={"Retry-After": "300"}))

    first = await client.get("/api/screens/movie/genres")
    assert first.status_code == 429
    body: dict[str, Any] = first.json()
    assert body["detail"] == "TMDB asked Robin to slow down"
    assert body["source"] == "TMDB"
    assert 290 <= int(first.headers["retry-after"]) <= 300
    assert datetime.fromisoformat(body["paused_until"]) > datetime.now(UTC)

    # Health reads the pause rather than asking.
    report = (await client.get("/api/settings/health", params={"refresh": True})).json()
    assert report["tmdb"]["state"] == "faulty"
    assert report["tmdb"]["until"] == body["paused_until"]
    assert len(asked) == 1


async def test_a_pause_outlives_a_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch, httpx.Response(429, headers={"Retry-After": "60"}))
    with pytest.raises(upstream.RateLimited):
        await tmdb()
    # A fresh process holds no pace of its own, the pause is in the database.
    upstream._paces.clear()
    db.init_db()
    assert upstream.paused_until("tmdb") is not None
