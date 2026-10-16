"""Books from Hardcover: the upcoming filter, the book shape, the shelf, and a wrong key."""

import json
from datetime import date
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, hardcover, hidden
from tests.conftest import stub_http

TOKEN = "hc_pat_test-token"
TODAY = date(2026, 10, 7)

BOOK: dict[str, Any] = {
    "id": 427,
    "title": "A Book",
    "subtitle": None,
    "slug": "a-book",
    "release_date": "2026-11-03",
    "description": "What happens.",
    "pages": 412,
    "rating": 4.256,
    "users_count": 1800,
    "literary_type_id": 1,
    "book_category_id": 1,
    "headline": "",
    "cached_contributors": [
        {"author": {"name": "Some Writer"}, "contribution": None},
        {"author": {"name": "A Translator"}, "contribution": "Translator"},
    ],
    "cached_tags": {"Genre": [{"tag": "Fantasy", "tagSlug": "fantasy"}], "Mood": []},
    "image": {"url": "https://assets.hardcover.app/a.jpg"},
    "featured_book_series": {
        "position": 3,
        "series": {"id": 99, "name": "A Series", "primary_books_count": 7},
    },
}


def settings(**extra: Any) -> db.Settings:
    db.save_settings({"hardcover_token": TOKEN, **extra})
    return db.get_settings()


def test_the_window_starts_tomorrow_and_keeps_everything_by_default() -> None:
    where = hardcover.discover_where(
        settings(books_hidden_categories_json="[]"), days=30, kind="", genre="", today=TODAY
    )
    assert where["release_date"] == {"_gte": "2026-10-08", "_lte": "2026-11-06"}
    assert "_and" not in where
    assert "cached_tags" not in where


def test_only_books_with_readers_a_cover_and_an_isbn_are_listed() -> None:
    where = hardcover.discover_where(settings(), days=30, kind="", genre="any", today=TODAY)
    assert where["users_count"] == {"_gte": hardcover.MIN_READERS}
    assert where["image_id"] == {"_is_null": False}
    assert where["editions"] == {
        "_or": [{"isbn_13": {"_is_null": False}}, {"isbn_10": {"_is_null": False}}]
    }


def test_a_fresh_install_hides_everything_but_books() -> None:
    where = hardcover.discover_where(settings(), days=30, kind="", genre="", today=TODAY)
    # A book with no category set is kept, which `_nin` alone would leave out.
    assert where["_and"] == [
        {
            "_or": [
                {"book_category_id": {"_nin": list(range(2, 11))}},
                {"book_category_id": {"_is_null": True}},
            ]
        }
    ]


def test_settings_hide_and_the_page_picks() -> None:
    hid = settings(books_hidden_literary_types_json="[2]", books_hidden_categories_json="[]")
    where = hardcover.discover_where(hid, days=30, kind="", genre="", today=TODAY)
    assert where["_and"][0]["_or"][0] == {"literary_type_id": {"_nin": [2]}}

    picked = hardcover.discover_where(hid, days=30, kind="nonfiction", genre="horror")
    assert picked["literary_type_id"] == {"_eq": 2}
    assert picked["cached_tags"] == {"_contains": {"Genre": [{"tagSlug": "horror"}]}}
    assert "cached_tags" not in hardcover.discover_where(hid, days=30, kind="", genre="any")


def test_a_hidden_genre_hides_a_book_unless_another_is_always_shown() -> None:
    hid = settings(
        books_hidden_genres_json='["romance"]', books_shown_genres_json='["science-fiction"]'
    )

    def kept(*genres: str, category: int = 1) -> bool:
        return hidden.book(hid, {"genres": list(genres), "category": category})

    assert not kept("Romance", "Fantasy"), "any hidden genre hides it"
    assert kept("Romance", "Science Fiction"), "unless one always shown is there too"
    assert kept("Fantasy")
    assert not kept("Fantasy", category=4), "a hidden category hides it"


def test_a_pasted_bearer_prefix_is_dropped() -> None:
    assert settings(hardcover_token=f"Bearer {TOKEN}").hardcover_key == TOKEN


@pytest.fixture
def hc_stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Hardcover, answering each query by its one top level field."""
    state: dict[str, Any] = {"asked": [], "shelf": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        state["asked"].append(request)
        if request.headers["authorization"] != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "invalid_token"})
        # Before `books(`, which `user_books(` also contains.
        if "me {" in query:
            return httpx.Response(200, json={"data": {"me": [{"user_books": state["shelf"]}]}})
        if "search(" in query:
            doc = {
                "id": "427",
                "title": "A Book",
                "slug": "a-book",
                "release_date": "2026-11-03",
                "author_names": ["Some Writer"],
                "image": {"url": "https://assets.hardcover.app/a.jpg"},
                "featured_series": {"position": 3, "series": {"id": 99, "name": "A Series"}},
                "users_count": 1800,
            }
            found = {"search": {"results": {"hits": [{"document": doc}], "found": 1}}}
            return httpx.Response(200, json={"data": found})
        if "books_by_pk" in query:
            return httpx.Response(200, json={"data": {"books_by_pk": BOOK}})
        if "books(" in query:
            return httpx.Response(200, json={"data": {"books": [BOOK]}})
        if "insert_user_book" in query:
            state["shelf"].append({"id": 5, "status_id": 1})
            made = {"insert_user_book": {"id": 5, "error": None}}
            return httpx.Response(200, json={"data": made})
        if "delete_user_book" in query:
            state["shelf"].clear()
            return httpx.Response(200, json={"data": {"delete_user_book": {"id": 5}}})
        return httpx.Response(200, json={"errors": [{"message": "unexpected query"}]})

    stub_http(monkeypatch, handler)
    return state


async def test_upcoming_books_are_listed_and_cached(
    client: AsyncClient, hc_stub: dict[str, Any]
) -> None:
    await client.put("/api/settings", json={"hardcover_token": TOKEN})

    page = (await client.get("/api/books/discover")).json()
    [book] = page["books"]
    assert book["authors"] == ["Some Writer"]
    assert book["genres"] == ["Fantasy"]
    assert book["series"] == {"id": 99, "name": "A Series", "position": 3, "count": 7}
    assert book["hardcover"] == "https://hardcover.app/books/a-book"
    assert book["rating"] == 4.26
    # One book back is less than a page, so there is no more.
    assert page["more"] is False

    asked = len(hc_stub["asked"])
    await client.get("/api/books/discover")
    assert len(hc_stub["asked"]) == asked

    detail = (await client.get("/api/books/427")).json()
    assert detail["date"] == "2026-11-03"


async def test_want_to_read_is_set_and_taken_off(
    client: AsyncClient, hc_stub: dict[str, Any]
) -> None:
    await client.put("/api/settings", json={"hardcover_token": TOKEN})
    assert (await client.get("/api/books/427/shelf")).json() == {"want": False}
    assert (await client.put("/api/books/427/shelf", json={"want": True})).json() == {"want": True}
    assert (await client.put("/api/books/427/shelf", json={"want": False})).json() == {
        "want": False
    }


async def test_a_book_read_already_is_never_taken_off(
    client: AsyncClient, hc_stub: dict[str, Any]
) -> None:
    await client.put("/api/settings", json={"hardcover_token": TOKEN})
    hc_stub["shelf"].append({"id": 8, "status_id": 3})
    await client.put("/api/books/427/shelf", json={"want": False})
    assert hc_stub["shelf"] == [{"id": 8, "status_id": 3}]


async def test_a_wrong_token_is_reported_and_never_shown(
    client: AsyncClient, hc_stub: dict[str, Any]
) -> None:
    await client.put("/api/settings", json={"hardcover_token": "wrong-token-value"})
    resp = await client.get("/api/books/discover")
    assert resp.status_code == 502
    assert "401" in resp.json()["detail"]
    assert "wrong-token-value" not in str((await client.get("/api/settings")).json())


async def test_nothing_is_asked_without_a_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected outbound request to {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    resp = await client.get("/api/books/discover")
    assert resp.status_code == 409
    assert "Hardcover" in resp.json()["detail"]
    assert (await client.get("/api/settings")).json()["hardcover_ready"] is False


async def test_a_search_reads_hardcovers_index_as_books(
    client: AsyncClient, hc_stub: dict[str, Any]
) -> None:
    await client.put("/api/settings", json={"hardcover_token": TOKEN})
    [book] = (await client.get("/api/books/search", params={"q": "a book"})).json()
    assert (book["id"], book["authors"], book["date"]) == (427, ["Some Writer"], "2026-11-03")
    assert book["series"] == {"id": 99, "name": "A Series", "position": 3, "count": None}
    assert book["hardcover"] == "https://hardcover.app/books/a-book"
