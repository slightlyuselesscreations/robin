"""A title out before this month: search finds it, to favourite who made it, and nothing
monitors it."""

from typing import Any

import pytest
from httpx import AsyncClient

from robin import db, hardcover, igdb, reminders, tmdb
from tests.conftest import notify_to

PAST = "2019-11-27"
AHEAD = "2099-01-01"


async def test_search_finds_titles_out_before_this_month(monkeypatch: pytest.MonkeyPatch) -> None:
    async def films(*args: Any) -> dict[str, Any]:
        return {
            "results": [
                {"media_type": "movie", "id": 546554, "title": "Knives Out", "release_date": PAST}
            ]
        }

    async def books(*args: Any) -> dict[str, Any]:
        doc = {"id": "1", "title": "Old Book", "slug": "old-book", "release_date": PAST}
        return {"results": {"hits": [{"document": doc}]}}

    async def games(endpoint: str, body: str) -> list[dict[str, Any]]:
        return [{"id": 7, "name": "Old Game", "first_release_date": 1500000000}]

    monkeypatch.setattr(tmdb, "_cached", films)
    monkeypatch.setattr(hardcover, "_cached", books)
    monkeypatch.setattr(igdb, "query", games)
    settings = db.get_settings()

    assert [t["date"] for t in await tmdb.search(settings, "knives out")] == [PAST]
    assert [b["date"] for b in await hardcover.search(settings, "old book")] == [PAST]
    assert [g["igdb_id"] for g in await igdb.search("old game")] == [7]


@pytest.mark.parametrize(
    ("kind", "detail", "expected"),
    [
        ("movie", {"releases": [{"date": AHEAD}]}, True),
        ("movie", {"releases": []}, False),
        ("tv", {"next_episode": {"episode": 1, "date": AHEAD}, "date": AHEAD}, True),
        ("tv", {"next_episode": {"episode": 4, "date": AHEAD}, "date": AHEAD}, False),
        ("tv", {"next_episode": None, "date": PAST}, False),
        ("tv", {"next_episode": None, "date": AHEAD}, True),
        ("tv", {"next_episode": None, "date": None}, True),
    ],
)
def test_only_a_title_with_something_ahead_is_monitorable(
    kind: str, detail: dict[str, Any], expected: bool
) -> None:
    assert reminders.monitorable(kind, detail) is expected


async def test_a_game_out_before_this_month_is_never_monitored(client: AsyncClient) -> None:
    db.upsert_games(
        [{"igdb_id": 7, "name": "Old Game", "first_release_date": 1500000000, "cached_at": ""}]
    )
    assert (await client.post("/api/monitored", json={"igdb_id": 7})).status_code == 409
    assert db.list_requests() == []


async def test_a_show_with_no_season_ahead_is_never_monitored(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.save_settings({"tmdb_token": "token", **notify_to()})

    async def title(settings: Any, kind: str, tmdb_id: int) -> dict[str, Any]:
        return {
            "title": "Old Show",
            "next_episode": None,
            "date": PAST,
            "platform": None,
            "poster": None,
            "releases": [],
        }

    monkeypatch.setattr(tmdb, "title", title)
    resp = await client.post("/api/screens/reminders", json={"kind": "tv", "tmdb_id": 1})
    assert resp.status_code == 409
    assert db.rows("reminders") == []


async def test_a_book_out_before_this_month_is_never_monitored(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.save_settings({"hardcover_token": "token", **notify_to()})

    async def book(settings: Any, book_id: int) -> dict[str, Any]:
        return {"title": "Old Book", "date": PAST, "cover": None}

    monkeypatch.setattr(hardcover, "book", book)
    assert (await client.post("/api/books/reminders", json={"book_id": 1})).status_code == 409
    assert db.rows("book_reminders") == []
