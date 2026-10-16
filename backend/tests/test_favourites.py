"""Favourites: starring what releases come from, and the notice for each new release."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from robin import db, favourites, hardcover, hidden, igdb, tmdb
from robin.routes.common import decorate
from tests.conftest import notify_to

# 10:00 on the day, past the default hour of 9.
NOW = datetime(2026, 10, 7, 10)


def configure(**extra: Any) -> None:
    db.save_settings(
        {
            "hardcover_token": "hc_pat_test",
            "tmdb_token": "eyJ.token",
            **notify_to(),
            **extra,
        }
    )


def book(book_id: int, when: str) -> dict[str, Any]:
    return {
        "id": book_id,
        "title": f"Book {book_id}",
        "date": when,
        "cover": None,
        "hardcover": f"https://hardcover.app/books/{book_id}",
    }


@pytest.fixture
def coming(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """What each favourite has coming, set by a test."""
    state: dict[str, list[dict[str, Any]]] = {"books": [], "screens": []}

    async def books(settings: Any, kind: str, source_ids: list[int]) -> Any:
        return state["books"]

    async def screens(settings: Any, kind: str, source_ids: list[int]) -> Any:
        return state["screens"]

    monkeypatch.setattr(hardcover, "favourite_releases", books)
    monkeypatch.setattr(tmdb, "favourite_releases", screens)
    return state


async def test_a_new_release_is_announced_once(
    notified: list[dict[str, Any]], coming: dict[str, Any]
) -> None:
    configure()
    db.add_favourite("books", "author", 7, "Some Writer", None)
    coming["books"] = [book(1, "2026-10-08"), book(2, "2026-12-01")]
    assert await favourites.notify_favourites(NOW) == 1
    assert notified[0]["title"] == "Book 1 is out tomorrow"
    assert notified[0]["message"] == "From Some Writer. Releases 2026-10-08."
    assert notified[0]["category"] == "books"
    assert await favourites.notify_favourites(NOW) == 0


async def test_a_monitored_title_keeps_its_own_notice(
    notified: list[dict[str, Any]], coming: dict[str, Any]
) -> None:
    configure()
    db.add_favourite("books", "author", 7, "Some Writer", None)
    db.add_book_reminder(
        kind="book", hardcover_id=1, book_id=1, title="Book 1", cover=None, date="2026-10-08"
    )
    coming["books"] = [book(1, "2026-10-08")]
    assert await favourites.notify_favourites(NOW) == 0


async def test_the_switch_turns_them_off(
    notified: list[dict[str, Any]], coming: dict[str, Any]
) -> None:
    configure(books_favourites=False)
    db.add_favourite("books", "series", 99, "A Series", None)
    coming["books"] = [book(1, "2026-10-08")]
    assert await favourites.notify_favourites(NOW) == 0


async def test_a_show_waits_for_the_hour(
    notified: list[dict[str, Any]], coming: dict[str, Any]
) -> None:
    configure(screen_schedule=[{"days": 1, "hour": 18}])
    db.add_favourite("screens", "network", 213, "Netflix", None)
    coming["screens"] = [
        {"kind": "tv", "id": 5, "title": "A Show", "date": "2026-10-08", "poster": None}
    ]
    assert await favourites.notify_favourites(NOW) == 0
    assert await favourites.notify_favourites(NOW.replace(hour=18)) == 1
    assert notified[0]["title"] == "A Show is out tomorrow"
    assert db.favourite_noticed("screens") == {"tv-5": "2026-10-08|2026-10-07T18"}


async def test_a_release_can_be_monitored_instead(
    notified: list[dict[str, Any]], coming: dict[str, Any]
) -> None:
    configure(books_favourites_monitor=True)
    db.add_favourite("books", "author", 7, "Some Writer", None)
    coming["books"] = [book(1, "2026-10-08"), book(2, "2026-12-01")]
    assert await favourites.monitor_favourites() == 2
    assert await favourites.monitor_favourites() == 0
    # Monitored, so each has its own notice and none from the favourite.
    assert await favourites.notify_favourites(NOW) == 0

    # One the user stops monitoring stays stopped.
    [first] = [r for r in db.rows("book_reminders") if r["hardcover_id"] == 1]
    db.delete_row("book_reminders", int(first["id"]))
    assert await favourites.monitor_favourites() == 0
    assert {r["hardcover_id"] for r in db.rows("book_reminders")} == {2}


async def test_nothing_is_monitored_while_the_switch_is_off(coming: dict[str, Any]) -> None:
    configure()
    db.add_favourite("books", "author", 7, "Some Writer", None)
    coming["books"] = [book(1, "2026-10-08")]
    assert await favourites.monitor_favourites() == 0
    assert db.rows("book_reminders") == []


async def test_favourites_are_added_shown_and_removed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TMDB lists the studio under two ids, and it is opened by the higher one.
    async def entity(settings: Any, category: str, kind: str, source_id: int) -> Any:
        return {
            "category": category,
            "kind": kind,
            "id": 145174,
            "ids": [145174, 178464],
            "name": "Netflix",
            "image": None,
            "meta": "Studio",
            "url": None,
        }

    asked: list[list[int]] = []

    async def coming(settings: Any, category: str, kind: str, ids: list[int]) -> Any:
        asked.append(ids)
        return []

    monkeypatch.setattr(favourites, "entity", entity)
    monkeypatch.setattr(favourites, "coming", coming)

    body = {"category": "screens", "kind": "studio", "id": 178464}
    made = (await client.post("/api/favourites", json=body)).json()
    assert (made["name"], made["source_id"], made["ids"]) == ("Netflix", 145174, [145174, 178464])
    assert asked == [[145174, 178464]]
    assert (await client.post("/api/favourites", json=body)).json()["id"] == made["id"]
    wrong = {"category": "games", "kind": "network", "id": 213}
    assert (await client.post("/api/favourites", json=wrong)).status_code == 422

    shown = (await client.get("/api/favourites/screens/studio/178464")).json()
    assert shown["favourite"]["id"] == made["id"]
    assert shown["releases"] == []

    assert (await client.delete(f"/api/favourites/{made['id']}")).status_code == 204
    assert (await client.get("/api/favourites")).json() == []


def test_a_book_is_starred_by_its_author_or_its_series() -> None:
    stars = [
        db.add_favourite("books", "author", 7, "Some Writer", None),
        db.add_favourite("books", "series", 99, "A Series", None),
    ]
    books: list[dict[str, Any]] = [
        {"authors": ["X"], "author_ids": [7], "series": None},
        {"authors": ["some writer"], "author_ids": [], "series": None},
        {"authors": [], "author_ids": [], "series": {"id": 99}},
        {"authors": ["Nobody"], "author_ids": [3], "series": {"id": 1}},
    ]
    hardcover.star(books, stars)
    assert [b["favourite"] for b in books] == ["Some Writer", "Some Writer", "A Series", None]


def test_a_company_says_which_roles_it_has() -> None:
    both = igdb._company({"id": 70, "name": "FromSoftware", "developed": [1], "published": [2]})
    assert (both["meta"], both["roles"]) == ("Developer and Publisher", ["developer", "publisher"])
    assert igdb._company({"id": 8, "name": "2K", "published": [3]})["roles"] == ["publisher"]


def test_a_game_is_starred_by_its_company() -> None:
    db.add_favourite("games", "company", 70, "FromSoftware", None)
    games = decorate([{"igdb_id": 1, "company_ids": [3, 70]}, {"igdb_id": 2, "company_ids": []}])
    assert [g["favourite"] for g in games] == ["FromSoftware", None]


def test_a_title_is_credited_to_its_people_studios_and_network() -> None:
    made = hidden.credited(
        {
            "credits": {
                "cast": [{"id": 1}],
                "crew": [{"id": 2, "job": "Director"}, {"id": 3, "job": "Composer"}],
            },
            "created_by": [{"id": 4}],
            "production_companies": [{"id": 178464}],
            "networks": [{"id": 213}],
        }
    )
    assert made == {"person": {1, 2, 4}, "studio": {178464}, "network": {213}}


def test_a_network_is_found_by_name_exact_first() -> None:
    names = ["Netflix Kids", "Hulu", "Netflix", "Netflix Japan"]
    ranked = sorted(
        (n for n in names if tmdb._match(n, "netflix") is not None),
        key=lambda n: tmdb._match(n, "netflix") or (0, 0, 0),
        reverse=True,
    )
    assert ranked[0] == "Netflix"
    assert "Hulu" not in ranked


def test_studios_sharing_a_name_are_one_favourite() -> None:
    found = tmdb._studios(
        [
            {"id": 178464, "name": "NETFLIX"},
            {"id": 145174, "name": "Netflix"},
            {"id": 5, "name": "Netflix Animation"},
        ]
    )
    assert [(s["id"], s["ids"], s["name"]) for s in found] == [
        (145174, [145174, 178464], "Netflix"),
        (5, [5], "Netflix Animation"),
    ]


async def test_a_studio_asks_for_every_id_it_covers(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[dict[str, Any]] = []

    async def cached(settings: Any, key: str, ttl: int, path: str, params: Any = None) -> Any:
        asked.append(params)
        return {"results": []}

    async def nothing(*args: Any) -> None:
        return None

    monkeypatch.setattr(tmdb, "_cached", cached)
    monkeypatch.setattr(tmdb, "_date_by_region", nothing)
    monkeypatch.setattr(tmdb, "_networks", nothing)
    await tmdb.favourite_releases(db.get_settings(), "studio", [178464, 145174])
    assert {p["with_companies"] for p in asked} == {"145174|178464"}


def test_a_game_is_starred_by_its_franchise_or_its_series() -> None:
    db.add_favourite("games", "franchise", 8, "Souls", None)
    db.add_favourite("games", "collection", 9, "Dark Souls", None)
    games = decorate(
        [
            {"igdb_id": 1, "franchise_ids": [8]},
            {"igdb_id": 2, "collection_ids": [9]},
            {"igdb_id": 3, "franchise_ids": [9], "collection_ids": [8]},
        ]
    )
    assert [g["favourite"] for g in games] == ["Souls", "Dark Souls", None]


def test_a_game_names_its_franchises_and_series_by_id() -> None:
    game = igdb.normalise(
        {
            "id": 1,
            "name": "A Game",
            "franchises": [{"id": 8, "name": "Souls"}],
            "collections": [9],
            "involved_companies": [
                {"company": {"id": 70, "name": "FromSoftware"}, "developer": True},
            ],
        },
        detailed=True,
    )
    assert (game["franchise_ids"], game["collection_ids"]) == ([8], [9])
    assert game["extra"]["developers"] == [{"id": 70, "name": "FromSoftware"}]
    assert game["extra"]["franchises"] == [{"id": 8, "name": "Souls"}]
    db.upsert_games([game])
    assert db.get_game(1)["franchise_ids"] == [8]  # type: ignore[index]


async def test_what_a_favourite_has_coming_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[frozenset[int]] = []

    async def releases(kind: str, ids: list[int], shown: frozenset[int]) -> Any:
        calls.append(shown)
        return []

    monkeypatch.setattr(igdb, "favourite_releases", releases)
    settings = db.get_settings()
    await favourites.coming(settings, "games", "company", [70])
    await favourites.coming(settings, "games", "company", [70])
    assert calls == [igdb.SHOWN_PLATFORMS]

    db.save_settings({"games_hidden_platforms": ["playstation", "xbox", "nintendo"]})
    await favourites.coming(db.get_settings(), "games", "company", [70])
    assert calls[-1] == {6}, "hiding other platforms asks again"


async def test_home_gets_each_dated_release_once(
    client: AsyncClient, coming: dict[str, Any]
) -> None:
    configure()
    db.add_favourite("books", "author", 7, "Some Writer", None)
    db.add_favourite("books", "series", 99, "A Series", None)
    coming["books"] = [book(1, "2026-12-01"), {**book(2, "2026-10-08"), "date": None}]
    rows = (await client.get("/api/favourites/coming")).json()
    assert [(r["key"], r["to"], r["date"]) for r in rows] == [("1", "book=1", "2026-12-01")]
    assert rows[0]["favourite"] in {"Some Writer", "A Series"}


async def test_home_leaves_out_a_category_whose_source_is_unset(client: AsyncClient) -> None:
    db.add_favourite("games", "company", 70, "FromSoftware", None)
    resp = await client.get("/api/favourites/coming")
    assert (resp.status_code, resp.json()) == (200, [])


async def test_what_a_favourite_has_coming_leaves_out_what_settings_hides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def shows(settings: Any, kind: str, ids: list[int]) -> list[dict[str, Any]]:
        return [
            {"kind": "tv", "id": 1, "title": "English", "genre_ids": [18], "language": "en"},
            {"kind": "tv", "id": 2, "title": "Spanish", "genre_ids": [18], "language": "es"},
        ]

    monkeypatch.setattr(tmdb, "favourite_releases", shows)
    db.save_settings({"tmdb_hidden_languages": ["es"]})
    found = await favourites.coming(db.get_settings(), "screens", "network", [2739])
    assert [t["title"] for t in found] == ["English"]

    # The cache keeps everything, so showing Spanish again applies at once.
    db.save_settings({"tmdb_hidden_languages": []})
    found = await favourites.coming(db.get_settings(), "screens", "network", [2739])
    assert [t["title"] for t in found] == ["English", "Spanish"]


@pytest.mark.parametrize(
    ("category", "release", "expected"),
    [
        ("games", {"exclusive": ["playstation", "xbox"], "release_status": None}, "PS · X"),
        ("games", {"exclusive": ["pc"], "release_status": "Early Access"}, "PC · EA"),
        ("games", {"exclusive": [], "release_status": None}, None),
        ("comics", {"number": "1", "publisher": "DC Comics"}, "#1 · DC"),
        ("comics", {"number": "4", "publisher": "Marvel"}, "Marvel"),
        ("screens", {"kind": "movie", "release": "Cinema"}, "Cinema"),
        ("screens", {"kind": "tv", "release": None}, "Series"),
        ("books", {"series": {"name": "Dune"}}, "Series"),
        ("books", {"series": None}, None),
    ],
)
def test_a_release_is_tagged_with_what_kind_it_is(
    category: Any, release: dict[str, Any], expected: str | None
) -> None:
    assert favourites.tag(category, release) == expected


async def test_a_person_has_coming_what_they_are_starred_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A show's creator is starred on it, so it is among the creator's releases too."""
    ahead = (datetime.now(UTC) + timedelta(days=60)).date().isoformat()
    show = {"id": 9, "media_type": "tv", "name": "Frisco King", "first_air_date": ahead}

    async def person(settings: db.Settings, person_id: int) -> dict[str, Any]:
        return {"combined_credits": {"cast": [], "crew": [{**show, "job": "Creator"}]}}

    async def nothing(*args: Any) -> None:
        return None

    monkeypatch.setattr(tmdb, "_person_detail", person)
    monkeypatch.setattr(tmdb, "_networks", nothing)
    monkeypatch.setattr(tmdb, "_date_by_region", nothing)
    coming = await tmdb.favourite_releases(db.get_settings(), "person", [1])
    assert [t["title"] for t in coming] == ["Frisco King"]
    assert hidden.credited({"created_by": [{"id": 1}]})["person"] == {1}
