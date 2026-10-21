"""Movies and TV from TMDB: the query each filter makes, dating returning shows, the detail."""

import json
from datetime import date
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, hidden, tmdb
from tests.conftest import stub_http

# A v4 Read Access Token is a JWT, which is what makes Robin send it as a bearer token.
TOKEN = "eyJhbGciOiJIUzI1NiJ9.read-access-token"
V3_KEY = "0123456789abcdef0123456789abcdef"
TODAY = date(2026, 10, 7)

FILTERS: dict[str, Any] = {
    "days": 90,
    "page": 1,
    "language": "",
    "release": "",
    "today": TODAY,
}


def params(kind: tmdb.Kind, **changes: Any) -> dict[str, Any]:
    return tmdb.discover_params(db.get_settings(), kind, **{**FILTERS, **changes})


def hide(**lists: list[Any]) -> None:
    """What Settings hides on the Screens tab, and the genres it always shows, by field."""
    db.save_settings({f"tmdb_{name}_json": json.dumps(value) for name, value in lists.items()})


def test_a_movie_is_upcoming_where_you_are() -> None:
    query = params("movie")
    assert query["region"] == "US"
    assert (query["release_date.gte"], query["release_date.lte"]) == ("2026-10-07", "2027-01-05")
    # Most anticipated first, unless the page is ordered by date.
    assert query["sort_by"] == params("tv")["sort_by"] == "popularity.desc"
    assert params("movie", sort="date")["sort_by"] == "release_date.asc"
    assert params("tv", sort="date")["sort_by"] == "first_air_date.asc"
    # Out nowhere yet, so a film already in cinemas does not come back for its digital release.
    assert query["primary_release_date.gte"] == "2026-10-08"


def test_nothing_hidden_keeps_everything() -> None:
    query = params("movie", languages=["en", "es"])
    assert query["with_release_type"] == "2|3|4"
    assert query["without_genres"] == query["with_original_language"] == ""


def test_what_settings_hides_is_asked_of_tmdb() -> None:
    hide(
        hidden_movie_genres=[10749],
        hidden_tv_genres=[18],
        hidden_languages=["es"],
        hidden_release_types=["theatrical"],
    )
    movie = params("movie", languages=["en", "es", "ja"])
    assert (movie["without_genres"], movie["with_release_type"]) == ("10749", "4")
    # Every language TMDB knows but those hidden, so a page comes back full.
    assert movie["with_original_language"] == "en|ja"
    assert params("tv")["without_genres"] == "18"

    # The page narrows to one language or one release type Settings shows, never back to one it
    # hides.
    assert params("movie", language="ko")["with_original_language"] == "ko"
    for hidden_pick in ({"language": "es"}, {"language": "any"}):
        assert (
            params("movie", languages=["en", "es", "ja"], **hidden_pick)["with_original_language"]
            == "en|ja"
        )
    assert params("movie", release="digital")["with_release_type"] == "4"
    assert params("movie", release="theatrical")["with_release_type"] == "4"


def test_the_page_narrows_to_one_genre() -> None:
    assert params("movie", genre_id=28)["with_genres"] == "28"
    assert "with_genres" not in params("movie")


def test_a_genre_always_shown_brings_back_what_another_hides() -> None:
    hide(hidden_movie_genres=[10749], hidden_languages=["es"], shown_movie_genres=[878])
    # TMDB cannot say "unless", so the page is filtered in Robin instead.
    movie = params("movie", languages=["en", "es"])
    assert movie["without_genres"] == movie["with_original_language"] == ""

    def kept(genres: list[int], language: str = "en") -> bool:
        title = {"kind": "movie", "genre_ids": genres, "language": language}
        return hidden.screen(db.get_settings(), title)

    assert not kept([10749]), "a romance is hidden"
    assert kept([10749, 878]), "unless it is science fiction too"
    assert not kept([18], "es"), "a Spanish drama is hidden"
    assert kept([18, 878], "es"), "a Spanish science fiction film is not"
    assert kept([18]), "nothing hidden on it"


def test_a_show_starts_in_the_window() -> None:
    new = params("tv")
    assert (new["first_air_date.gte"], new["first_air_date.lte"]) == ("2026-10-07", "2027-01-05")

    # Only scripted series and miniseries, so talk shows do not fill it.
    assert new["with_type"] == "2|4"


@pytest.fixture
def tmdb_stub(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        bearer = request.headers.get("authorization") == f"Bearer {TOKEN}"
        if not bearer and request.url.params.get("api_key") != V3_KEY:
            return httpx.Response(401)
        path = request.url.path.removeprefix("/3")
        if path == "/watch/providers/movie":
            services = [
                {"provider_name": "Apple TV", "logo_path": "/atv.jpg"},
                {"provider_name": "Apple TV+", "logo_path": "/atvp.jpg"},
            ]
            return httpx.Response(200, json={"results": services})
        if path == "/search/multi":
            found = [
                {"id": 550, "media_type": "movie", "title": "A Film", "release_date": "2026-12-04"},
                {"id": 1399, "media_type": "tv", "name": "House of the Dragon"},
                {"id": 7, "media_type": "person", "name": "Someone"},
            ]
            return httpx.Response(200, json={"results": found})
        if path == "/discover/tv":
            return httpx.Response(
                200,
                json={
                    "page": 1,
                    "total_pages": 3,
                    "results": [
                        {
                            "id": 1399,
                            "name": "House of the Dragon",
                            "first_air_date": "2022-08-21",
                            "poster_path": "/p.jpg",
                            "genre_ids": [18],
                            "vote_average": 8.4,
                        },
                        # A fan series anyone can add to TMDB, which no network airs.
                        {"id": 327346, "name": "Astral Watch", "first_air_date": "2026-11-30"},
                    ],
                },
            )
        if path == "/tv/327346":
            return httpx.Response(
                200,
                json={
                    "id": 327346,
                    "name": "Astral Watch",
                    "first_air_date": "2026-11-30",
                    "networks": [],
                },
            )
        if path == "/tv/1399":
            return httpx.Response(
                200,
                json={
                    "id": 1399,
                    "name": "House of the Dragon",
                    "first_air_date": "2022-08-21",
                    "poster_path": "/p.jpg",
                    "next_episode_to_air": {
                        "air_date": "2026-11-02",
                        "season_number": 3,
                        "episode_number": 1,
                        "name": "Premiere",
                    },
                    "created_by": [{"id": 9, "name": "Ryan Condal"}],
                    "networks": [{"id": 49, "name": "HBO", "logo_path": "/hbo.png"}],
                    "content_ratings": {"results": [{"iso_3166_1": "US", "rating": "TV-MA"}]},
                    "watch/providers": {
                        "results": {"US": {"flatrate": [{"provider_name": "Max"}]}}
                    },
                    "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": "abc"}]},
                },
            )
        if path == "/discover/movie":
            films = [{"id": 550, "title": "A Film"}]
            return httpx.Response(200, json={"page": 1, "total_pages": 1, "results": films})
        if path == "/movie/550":
            return httpx.Response(
                200,
                json={
                    "id": 550,
                    "title": "A Film",
                    "status": "Post Production",
                    "release_date": "2026-11-20",
                    "release_dates": {
                        "results": [
                            {
                                "iso_3166_1": "GB",
                                "release_dates": [
                                    {"certification": "15", "release_date": "2026-11-13T00:00"}
                                ],
                            },
                            {
                                "iso_3166_1": "US",
                                "release_dates": [
                                    {"type": 1, "release_date": "2026-09-01T00:00"},
                                    {
                                        "type": 4,
                                        "release_date": "2026-12-25T00:00",
                                        "note": "Apple TV+",
                                    },
                                    {
                                        "type": 3,
                                        "certification": "R",
                                        "release_date": "2026-12-04T00:00",
                                    },
                                ],
                            },
                        ]
                    },
                    "credits": {
                        "crew": [{"id": 7, "job": "Director", "name": "Someone"}],
                        "cast": [],
                    },
                },
            )
        return httpx.Response(404)

    stub_http(monkeypatch, handler)
    return asked


async def test_a_show_is_listed_and_detailed(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})

    page = (await client.get("/api/screens/tv/discover")).json()
    [show] = page["titles"]
    # The list leaves the network out, so it is read from the show.
    assert show["platform"] == {"name": "HBO"}
    assert show["poster"] == "https://image.tmdb.org/t/p/w342/p.jpg"
    assert page["total_pages"] == 3

    # The page is cached, so asking again goes nowhere.
    asked = len(tmdb_stub)
    await client.get("/api/screens/tv/discover")
    assert len(tmdb_stub) == asked

    detail = (await client.get("/api/screens/tv/1399")).json()
    assert detail["date"] == "2026-11-02"
    assert detail["next_episode"]["season"] == 3
    assert detail["certification"] == "TV-MA"
    assert detail["makers"] == [{"id": 9, "name": "Ryan Condal"}]
    assert detail["watch"]["stream"] == ["Max"]
    assert detail["trailer"] == "https://www.youtube.com/watch?v=abc"


async def test_a_film_takes_the_regions_first_release_past_its_premiere(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})
    detail = (await client.get("/api/screens/movie/550")).json()
    assert (detail["date"], detail["certification"], detail["release"]) == (
        "2026-12-04",
        "R",
        "Cinema",
    )
    assert detail["makers"] == [{"id": 7, "name": "Someone"}]
    # Each kept release type with a date in the region, the ones a reminder can be set for.
    assert [(r["type"], r["date"]) for r in detail["releases"]] == [
        ("theatrical", "2026-12-04"),
        ("digital", "2026-12-25"),
    ]
    # A digital release is on the platform its note names, the longest name that fits.
    assert detail["releases"][1]["platform"] == {"name": "Apple TV+"}


async def test_the_page_can_pick_one_release_type(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})
    [film] = (await client.get("/api/screens/movie/discover?release=digital")).json()["titles"]
    assert (film["date"], film["release"]) == ("2026-12-25", "Digital")
    assert film["platform"]["name"] == "Apple TV+"
    asked = next(r for r in tmdb_stub if r.url.path == "/3/discover/movie")
    assert asked.url.params["with_release_type"] == "4"


async def test_a_film_carries_the_release_that_puts_it_in_the_window(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put(
        "/api/settings", json={"tmdb_token": TOKEN, "tmdb_hidden_release_types": ["theatrical"]}
    )
    [film] = (await client.get("/api/screens/movie/discover")).json()["titles"]
    assert film["id"] == 550
    # Only digital releases are kept, so the cinema release before it does not date it.
    assert (film["date"], film["release"]) == ("2026-12-25", "Digital")


async def test_all_lists_movies_and_shows_together(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})
    page = (await client.get("/api/screens/all/discover")).json()
    assert {(t["kind"], t["id"]) for t in page["titles"]} == {("movie", 550), ("tv", 1399)}
    # The longer of the two decides how far it pages.
    assert page["total_pages"] == 3


async def test_a_wrong_token_is_reported_and_never_shown(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": "wrong-token-value"})
    resp = await client.get("/api/screens/movie/discover")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "TMDB rejected the API key"
    assert "wrong-token-value" not in str((await client.get("/api/settings")).json())


async def test_nothing_is_asked_without_a_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected outbound request to {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    resp = await client.get("/api/screens/movie/discover")
    assert resp.status_code == 409
    assert "TMDB" in resp.json()["detail"]
    assert (await client.get("/api/settings")).json()["tmdb_ready"] is False


async def test_a_v3_key_goes_as_a_query_parameter(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": V3_KEY})
    assert (await client.get("/api/screens/movie/550")).status_code == 200
    assert "authorization" not in tmdb_stub[0].headers


async def test_a_search_finds_movies_and_shows_and_no_people(
    client: AsyncClient, tmdb_stub: list[httpx.Request]
) -> None:
    await client.put("/api/settings", json={"tmdb_token": TOKEN})
    found = (await client.get("/api/screens/search", params={"q": "dragon"})).json()
    assert [(t["kind"], t["id"]) for t in found] == [("movie", 550), ("tv", 1399)]
    assert tmdb_stub[-1].url.params["query"] == "dragon"
