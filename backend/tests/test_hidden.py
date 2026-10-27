"""What Settings hides shows nowhere: not on Monitored, not in a notice, and nothing hidden is
ever added to Radarr or Sonarr."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from robin import db, favourites, hidden, igdb, reminders, tmdb
from tests.conftest import notify_to

SPANISH = {"id": 1, "title": "Película", "genres": [{"id": 18}], "original_language": "es"}


@pytest.fixture
def screens(monkeypatch: pytest.MonkeyPatch) -> None:
    db.save_settings(
        {
            "tmdb_token": "token",
            **notify_to(),
            "tmdb_hidden_languages": ["es"],
        }
    )

    async def movie(settings: Any, tmdb_id: int) -> dict[str, Any]:
        return SPANISH

    monkeypatch.setattr(tmdb, "movie", movie)
    db.add_reminder(
        kind="movie",
        tmdb_id=1,
        release_type="digital",
        title="Película",
        poster=None,
        date=(datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
        platform=None,
    )


@pytest.mark.usefixtures("screens")
async def test_a_hidden_title_leaves_monitored_and_comes_back(client: AsyncClient) -> None:
    assert (await client.get("/api/screens/reminders")).json() == []
    assert await reminders.notify_reminders() == 0, "and sends nothing"

    db.save_settings({"tmdb_hidden_languages": []})
    assert [r["tmdb_id"] for r in (await client.get("/api/screens/reminders")).json()] == [1]


@pytest.mark.usefixtures("screens")
async def test_a_hidden_title_is_never_added_to_radarr(client: AsyncClient) -> None:
    db.save_settings({"radarr_url": "http://radarr.test", "radarr_api_key": "key"})
    resp = await client.post("/api/arr/radarr", json={"tmdb_id": 1})
    assert resp.status_code == 409


async def test_a_game_only_on_hidden_platforms_leaves_monitored(client: AsyncClient) -> None:
    db.upsert_games(
        [
            {
                "igdb_id": 9,
                "name": "Console Only",
                "platforms": ["PS5"],
                "exclusive": ["playstation"],
                "cached_at": "",
            }
        ]
    )
    db.create_request(9)
    assert [g["igdb_id"] for g in (await client.get("/api/monitored")).json()] == [9]
    db.save_settings({"games_hidden_platforms": ["playstation"]})
    assert (await client.get("/api/monitored")).json() == []


async def test_a_maker_hidden_hides_all_it_made_and_stops_being_a_favourite(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    studio = {"category": "games", "kind": "company", "id": 7, "name": "Studio", "image": None}

    async def entity(settings: Any, category: str, kind: str, source_id: int) -> Any:
        return {**studio, "ids": [7]}

    async def search(query: str) -> Any:
        return [{**studio}, {**studio, "id": 8, "name": "Other"}]

    monkeypatch.setattr(favourites, "entity", entity)
    db.add_favourite("games", "company", 7, "Studio", None)
    made = {"igdb_id": 1, "company_ids": [7], "franchise_ids": [], "collection_ids": []}

    resp = await client.post(
        "/api/favourites/filters",
        json={"mode": "hide", "category": "games", "kind": "company", "id": 7},
    )
    assert resp.status_code == 200
    assert db.favourites("games") == [], "a maker hidden is no favourite"
    settings = db.get_settings()
    assert not hidden.game(settings, made)
    assert hidden.game(settings, {**made, "company_ids": [8]})

    # Nor is it offered by a search until it is shown again.
    monkeypatch.setattr(igdb, "search_favourites", search)
    found = await favourites.search(settings, "games", "studio")
    assert [e["id"] for e in found] == [8]

    [maker] = (await client.get("/api/favourites/filters")).json()
    assert (await client.delete(f"/api/favourites/filters/{maker['id']}")).status_code == 204
    assert hidden.game(db.get_settings(), made)


def test_a_maker_hidden_hides_a_title_or_a_book_unless_a_genre_is_always_shown() -> None:
    db.filter_maker("hide", "screens", "person", 10, "Actor", [10])
    db.filter_maker("hide", "books", "series", 5, "Saga", [5])
    db.save_settings({"tmdb_shown_movie_genres": [878]})
    settings = db.get_settings()
    film = {"kind": "movie", "genre_ids": [18], "language": "en"}
    assert not hidden.screen(settings, film, {"person": {10}})
    assert hidden.screen(settings, {**film, "genre_ids": [18, 878]}, {"person": {10}})
    assert hidden.screen(settings, film, {"person": {11}})
    assert not hidden.book(settings, {"series": {"id": 5}, "genres": []})
    assert hidden.book(settings, {"series": {"id": 6}, "genres": []})


def test_a_maker_always_shown_brings_back_what_a_filter_hides() -> None:
    db.save_settings({"tmdb_hidden_movie_genres": [10749], "books_hidden_genres": ["romance"]})
    db.filter_maker("show", "screens", "person", 10, "Actor", [10])
    db.filter_maker("show", "books", "author", 3, "Writer", [3])
    settings = db.get_settings()
    romance = {"kind": "movie", "genre_ids": [10749], "language": "en"}
    assert hidden.screen(settings, romance, {"person": {10}})
    assert not hidden.screen(settings, romance, {"person": {11}})
    assert hidden.book(settings, {"author_ids": [3], "genres": ["Romance"]})
    assert not hidden.book(settings, {"author_ids": [4], "genres": ["Romance"]})
    # TMDB cannot say "unless", so the page is filtered in Robin.
    assert tmdb._rescues(settings, "movie")


def test_a_maker_moves_between_hidden_and_shown() -> None:
    db.filter_maker("hide", "games", "company", 7, "Studio", [7])
    db.filter_maker("show", "games", "company", 7, "Studio", [7])
    [maker] = db.maker_filters()
    assert maker["mode"] == "show", "one mode at a time"
