import asyncio
from collections.abc import Awaitable, Callable

import pytest

from robin import db


def counting(answers: list[object]) -> tuple[list[int], Callable[[], Awaitable[object]]]:
    calls: list[int] = []

    async def fetch() -> object:
        calls.append(1)
        await asyncio.sleep(0)
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return calls, fetch


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_page_is_answered_with_the_old_value_at_once_and_it_is_fetched_again() -> None:
    db.cache_put("k", "old", -1)
    calls, fetch = counting(["new"])
    mark = db.Stale()
    token = db.STALE.set(mark)
    try:
        assert await db.remember("k", 60, fetch) == "old"
    finally:
        db.STALE.reset(token)
    assert mark.served
    await settle()
    assert calls == [1]
    assert db.cache_get("k") == "new"


async def test_outside_a_page_an_expired_value_waits_for_the_fetch() -> None:
    db.cache_put("k", "old", -1)
    _, fetch = counting(["new"])
    assert await db.remember("k", 60, fetch) == "new"


async def test_a_page_asking_for_the_fresh_value_waits_for_it() -> None:
    db.cache_put("k", "old", -1)
    _, fetch = counting(["new"])
    mark = db.Stale(wait=True)
    token = db.STALE.set(mark)
    try:
        assert await db.remember("k", 60, fetch) == "new"
    finally:
        db.STALE.reset(token)
    assert not mark.served


async def test_requests_at_once_fetch_once() -> None:
    calls, fetch = counting(["new", "again"])
    got = await asyncio.gather(*(db.remember("k", 60, fetch) for _ in range(5)))
    assert got == ["new"] * 5
    assert calls == [1]


async def test_a_failed_fetch_keeps_the_old_value() -> None:
    db.cache_put("k", "old", -1)
    _, fetch = counting([RuntimeError("down")])
    assert await db.remember("k", 60, fetch) == "old"
    found, live, value = db._cache_peek("k")
    assert (found, live, value) == (True, False, "old")


async def test_a_failed_fetch_with_nothing_kept_fails() -> None:
    _, fetch = counting([RuntimeError("down")])
    with pytest.raises(RuntimeError):
        await db.remember("k", 60, fetch)


def test_a_list_that_contradicts_a_kept_detail_expires_it() -> None:
    """The list is asked hourly and a detail half a day, so the list says first when a poster
    or a date has moved, and the detail is asked again."""
    from robin import hardcover, tmdb

    settings = db.get_settings()
    key = tmdb._key(settings, "detail:v2:tv:1")
    kept = {"id": 1, "poster_path": "/old.jpg", "first_air_date": "2026-12-01"}
    db.cache_put(key, kept, 3600)
    agreeing = {
        "id": 1,
        "kind": "tv",
        "poster": tmdb.image("/old.jpg", "w342"),
        "date": "2026-12-01",
    }
    tmdb._check(settings, agreeing, kept)
    assert db.cache_lookup(key)[0], "a detail the list agrees with is kept"
    tmdb._check(settings, {**agreeing, "poster": tmdb.image("/new.jpg", "w342")}, kept)
    assert not db.cache_lookup(key)[0]

    book_key = "hardcover:v2:book:2"
    db.cache_put(book_key, {"image": {"url": "a.jpg"}, "release_date": "2026-12-01"}, 3600)
    hardcover._check({"id": 2, "cover": "a.jpg", "date": "2026-12-01"})
    assert db.cache_lookup(book_key)[0]
    hardcover._check({"id": 2, "cover": "a.jpg", "date": "2027-01-05"})
    assert not db.cache_lookup(book_key)[0]
