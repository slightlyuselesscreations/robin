"""Hardcover, the data source for upcoming books.

Discovery and one write. Robin lists what is coming, monitors a book for a
notice, and shelves a book as Want to Read on the user's own Hardcover account, which is the
only thing it ever writes there.

Hardcover is Hasura GraphQL. Every top level field of a query is one request against its limit
of 60 a minute, so each call here carries exactly one, and `upstream` paces them under it. The
site shows a key with `Bearer ` in front of it, which is taken off before it is sent again.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from robin import db, hidden, upstream

API = "https://api.hardcover.app/v1/graphql"
SITE = "https://hardcover.app"
TIMEOUT = 30.0

# A filtered page moves slowly, an hour of it is not stale. A book's detail even less so.
PAGE_TTL = 3600
DETAIL_TTL = 12 * 3600
# Genres change a few times a year.
REFERENCE_TTL = 7 * 24 * 3600

PAGE_SIZE = 40

# Hardcover's literary types as the page names them.
LITERARY_TYPES = {"fiction": 1, "nonfiction": 2}

# Hardcover's user book status for Want to Read.
WANT_TO_READ = 1

Kind = Literal["", "fiction", "nonfiction"]

# Anyone can add a book to Hardcover, and self published and generated titles sit at no one or
# one reader. A real book is shelved by a few before it is out.
MIN_READERS = 3

BOOK_FIELDS = """
    id title subtitle slug release_date description pages rating users_count
    literary_type_id book_category_id cached_contributors cached_tags
    image { url }
    featured_book_series { position series { id name primary_books_count } }
"""


class HardcoverError(upstream.UpstreamError):
    pass


async def gql(settings: db.Settings, query: str, variables: dict[str, Any] | None = None) -> Any:
    """Run one operation and return its one top level field."""
    if not settings.hardcover_ready:
        raise upstream.NotConfigured("Books is off. Add a Hardcover API key in Settings, Books.")
    data = await upstream.graphql(
        HardcoverError,
        "Hardcover",
        API,
        query,
        variables or {},
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {settings.hardcover_key}", "User-Agent": "Robin"},
        source="hardcover",
    )
    [value] = data.values()
    return value


async def _cached(
    settings: db.Settings, key: str, ttl: db.Lifetime, query: str, variables: dict[str, Any]
) -> Any:
    return await db.remember(f"hardcover:v2:{key}", ttl, lambda: gql(settings, query, variables))


async def ping(settings: db.Settings) -> None:
    await gql(settings, "{ me { id } }")


async def genres(settings: db.Settings) -> list[dict[str, Any]]:
    """The genre tags, most used first."""
    data = await _cached(
        settings,
        "genres",
        REFERENCE_TTL,
        """query { tags(
            where: {tag_category: {slug: {_eq: "genre"}}},
            order_by: {count: desc}, limit: 200
        ) { tag slug } }""",
        {},
    )
    return [{"slug": t["slug"], "name": t["tag"]} for t in data]


def discover_where(
    settings: db.Settings, *, days: int, kind: str, genre: str, today: date | None = None
) -> dict[str, Any]:
    """The filter for the upcoming list. Kept apart from the call so a test can read it.

    The literary types and categories Settings hides are asked of Hardcover, a book carrying
    neither kept. Hidden genres are left to `hidden.book` on the answer, since a genre always
    shown can bring a book back. `kind` is one literary type instead, `genre` one genre slug,
    or `any` for every genre. A book's release date is its first publication anywhere, so from
    tomorrow on means not out yet.

    A listed book has readers, a cover and an edition with an ISBN, which leaves out what
    anyone can add: self published ebooks carry only an ASIN.
    """
    start = today or datetime.now(UTC).date()
    where: dict[str, Any] = {
        "release_date": {
            "_gte": (start + timedelta(days=1)).isoformat(),
            "_lte": (start + timedelta(days=days)).isoformat(),
        },
        "book_status_id": {"_eq": 1},
        "canonical_id": {"_is_null": True},
        "users_count": {"_gte": MIN_READERS},
        "image_id": {"_is_null": False},
        "editions": {"_or": [{"isbn_13": {"_is_null": False}}, {"isbn_10": {"_is_null": False}}]},
    }
    hides: list[dict[str, Any]] = []
    if kind in LITERARY_TYPES:
        where["literary_type_id"] = {"_eq": LITERARY_TYPES[kind]}
    elif settings.books_hidden_literary_types:
        hides.append(_not_in("literary_type_id", settings.books_hidden_literary_types))
    if settings.books_hidden_categories:
        hides.append(_not_in("book_category_id", settings.books_hidden_categories))
    if hides:
        where["_and"] = hides
    if genre and genre != "any":
        where["cached_tags"] = {"_contains": {"Genre": [{"tagSlug": genre}]}}
    return where


def _not_in(field: str, hidden: list[int]) -> dict[str, Any]:
    """None of `hidden`, or nothing set at all, which `_nin` alone would leave out."""
    return {"_or": [{field: {"_nin": hidden}}, {field: {"_is_null": True}}]}


async def discover(
    settings: db.Settings, *, days: int, page: int, kind: str, genre: str
) -> dict[str, Any]:
    """One page of upcoming books, most anticipated first."""
    where = discover_where(settings, days=days, kind=kind, genre=genre)
    key = f"discover:{page}:" + repr(sorted(where.items()))
    data = await _cached(
        settings,
        key,
        PAGE_TTL,
        f"""query Discover($where: books_bool_exp!, $limit: Int!, $offset: Int!) {{
            books(where: $where, order_by: [{{users_count: desc}}, {{id: asc}}],
                  limit: $limit, offset: $offset) {{ {BOOK_FIELDS} }}
        }}""",
        {"where": where, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
    )
    # A genre the page picks, or any, stands in for those Settings hides.
    judged = replace(settings, books_hidden_genres=[]) if genre else settings
    books = [b for b in (_book(raw) for raw in data) if hidden.book(judged, b)]
    for book in books:
        _check(book)
    # No total, which would be a second request. A page that ends exactly on the
    # last book costs one empty load.
    return {"books": books, "page": page, "more": len(data) == PAGE_SIZE}


def _check(book: dict[str, Any]) -> None:
    """Expire a book's kept detail when the list just read says otherwise, its cover or its
    date, so the detail and its dialog follow the list."""

    def outdated(raw: Any) -> bool:
        said = ((raw.get("image") or {}).get("url"), raw.get("release_date")) if raw else None
        return said is not None and said != (book["cover"], book["date"])

    db.expire_if(f"hardcover:v2:book:{book['id']}", outdated)


async def search(settings: db.Settings, query: str) -> list[dict[str, Any]]:
    """Books matching `query`, as Hardcover's own search ranks them, but what Settings hides. A
    book out before this month is found too, to be favourited by its authors and series, and is
    never monitored."""
    found = await _cached(
        settings,
        f"search:{query.casefold()}",
        PAGE_TTL,
        """query Search($q: String!) {
            search(query: $q, query_type: "Book", per_page: 40, page: 1) { results }
        }""",
        {"q": query},
    )
    hits = ((found or {}).get("results") or {}).get("hits") or []
    books = [_document(hit["document"]) for hit in hits if hit.get("document")]
    return [b for b in books if hidden.book(settings, b)]


def _document(doc: dict[str, Any]) -> dict[str, Any]:
    """A search hit, which is Hardcover's search index and not a GraphQL book, as a book."""
    featured = doc.get("featured_series") or {}
    series = featured.get("series") or None
    contributors = doc.get("contributions")
    return {
        "id": int(doc["id"]),
        "title": doc.get("title") or "",
        "subtitle": doc.get("subtitle") or "",
        "date": doc.get("release_date") or None,
        "cover": (doc.get("image") or {}).get("url"),
        "overview": doc.get("description") or "",
        "authors": _authors(contributors) if contributors else list(doc.get("author_names") or []),
        "author_ids": _author_ids(contributors),
        "genres": list(doc.get("genres") or []),
        "literary_type": None,
        "category": None,
        "series": _series(featured) if series and "id" in series else None,
        "pages": doc.get("pages"),
        "rating": round(float(doc["rating"]), 2) if doc.get("rating") else None,
        "readers": doc.get("users_count") or 0,
        "hardcover": f"{SITE}/books/{doc.get('slug') or doc['id']}",
        "favourite": None,
    }


async def book(settings: db.Settings, book_id: int) -> dict[str, Any]:
    """One book, cached."""
    raw = await _cached(
        settings,
        f"book:{book_id}",
        # A book Hardcover has no cover for yet is asked again as often as a page.
        lambda raw: DETAIL_TTL if raw and raw.get("image") else PAGE_TTL,
        f"query Book($id: Int!) {{ books_by_pk(id: $id) {{ headline {BOOK_FIELDS} }} }}",
        {"id": book_id},
    )
    if raw is None:
        raise HardcoverError("Hardcover has no such book")
    return {**_book(raw), "headline": raw.get("headline") or ""}


async def _shelved(settings: db.Settings, book_id: int) -> dict[str, Any] | None:
    me = await gql(
        settings,
        """query Shelf($id: Int!) {
            me { user_books(where: {book_id: {_eq: $id}}) { id status_id } }
        }""",
        {"id": book_id},
    )
    # `me` is a list of one.
    user = me[0] if isinstance(me, list) else me
    return next(iter((user or {}).get("user_books") or []), None)


async def shelf(settings: db.Settings, book_id: int) -> dict[str, Any]:
    """Whether the book is on the user's Want to Read shelf."""
    row = await _shelved(settings, book_id)
    return {"want": bool(row and row["status_id"] == WANT_TO_READ)}


async def set_shelf(settings: db.Settings, book_id: int, want: bool) -> dict[str, Any]:
    """Shelve a book as Want to Read, or take it off.

    A book the user already shelved another way, read or reading, is left as it is: only a
    Want to Read is ever added or removed.
    """
    row = await _shelved(settings, book_id)
    if want and row is None:
        made = await gql(
            settings,
            """mutation Want($id: Int!) {
                insert_user_book(object: {book_id: $id, status_id: 1}) { id error }
            }""",
            {"id": book_id},
        )
        if made.get("error"):
            raise HardcoverError(f"Hardcover: {made['error']}")
    elif not want and row is not None and row["status_id"] == WANT_TO_READ:
        await gql(
            settings,
            "mutation Unwant($id: Int!) { delete_user_book(id: $id) { id } }",
            {"id": row["id"]},
        )
    return await shelf(settings, book_id)


def _authors(contributors: Any) -> list[str]:
    """The authors, leaving out illustrators, translators and narrators."""
    return [
        c["author"]["name"]
        for c in contributors or []
        if (c.get("author") or {}).get("name") and c.get("contribution") in (None, "", "Author")
    ]


def _author_ids(contributors: Any) -> list[int]:
    return [
        int(c["author"]["id"])
        for c in contributors or []
        if isinstance((c.get("author") or {}).get("id"), int)
        and c.get("contribution") in (None, "", "Author")
    ]


def _author_refs(contributors: Any) -> list[dict[str, Any]]:
    """The authors with their ids, for a dialog to open each as a favourite."""
    return [
        {"id": int(c["author"]["id"]), "name": c["author"]["name"]}
        for c in contributors or []
        if isinstance((c.get("author") or {}).get("id"), int)
        and (c.get("author") or {}).get("name")
        and c.get("contribution") in (None, "", "Author")
    ]


def _series(featured: dict[str, Any]) -> dict[str, Any]:
    """A book's place in its series, and how many books the series has, companions left out."""
    series = featured["series"]
    return {
        "id": series["id"],
        "name": series["name"],
        "position": featured.get("position"),
        "count": series.get("primary_books_count"),
    }


def _book(raw: dict[str, Any]) -> dict[str, Any]:
    featured = raw.get("featured_book_series") or {}
    series = featured.get("series") or None
    return {
        "id": raw["id"],
        "title": raw.get("title") or "",
        "subtitle": raw.get("subtitle") or "",
        "date": raw.get("release_date"),
        "cover": (raw.get("image") or {}).get("url"),
        "overview": raw.get("description") or "",
        "authors": _authors(raw.get("cached_contributors")),
        "author_ids": _author_ids(raw.get("cached_contributors")),
        "author_refs": _author_refs(raw.get("cached_contributors")),
        "genres": [g["tag"] for g in (raw.get("cached_tags") or {}).get("Genre", []) if "tag" in g],
        "literary_type": raw.get("literary_type_id"),
        "category": raw.get("book_category_id"),
        "series": _series(featured) if series else None,
        "pages": raw.get("pages"),
        "rating": round(float(raw["rating"]), 2) if raw.get("rating") else None,
        "readers": raw.get("users_count") or 0,
        "hardcover": f"{SITE}/books/{raw.get('slug') or raw['id']}",
        # The favourite it comes from, by name, set by `star`.
        "favourite": None,
    }


# ---------------------------------------------------------------- favourites


def _author(raw: dict[str, Any]) -> dict[str, Any]:
    count = raw.get("books_count")
    return {
        "category": "books",
        "kind": "author",
        "id": int(raw["id"]),
        "name": raw.get("name") or "",
        "image": (raw.get("image") or {}).get("url"),
        "meta": f"Author of {count} books" if count else "Author",
        "url": f"{SITE}/authors/{raw.get('slug') or raw['id']}",
    }


def _series_entity(raw: dict[str, Any]) -> dict[str, Any]:
    count = raw.get("primary_books_count") or raw.get("books_count")
    by = (raw.get("author") or {}).get("name") or raw.get("author_name")
    return {
        "category": "books",
        "kind": "series",
        "id": int(raw["id"]),
        "name": raw.get("name") or "",
        "image": None,
        "meta": ", ".join(
            part
            for part in (f"{count} books" if count else "Series", f"by {by}" if by else "")
            if part
        ),
        "url": f"{SITE}/series/{raw.get('slug') or raw['id']}",
    }


async def search_favourites(settings: db.Settings, query: str) -> list[dict[str, Any]]:
    """Authors and series matching `query`, as Hardcover's own search ranks them."""

    async def kind(query_type: str) -> list[dict[str, Any]]:
        found = await _cached(
            settings,
            f"search:{query_type}:{query.casefold()}",
            PAGE_TTL,
            """query Search($q: String!, $type: String!) {
                search(query: $q, query_type: $type, per_page: 12, page: 1) { results }
            }""",
            {"q": query, "type": query_type},
        )
        hits = ((found or {}).get("results") or {}).get("hits") or []
        return [hit["document"] for hit in hits if hit.get("document")]

    authors, series = await asyncio.gather(kind("Author"), kind("Series"))
    return [_author(a) for a in authors] + [_series_entity(s) for s in series]


async def favourite(settings: db.Settings, kind: str, source_id: int) -> dict[str, Any] | None:
    """An author or a series as a favourite is shown."""
    if kind == "author":
        raw = await _cached(
            settings,
            f"author:{source_id}",
            DETAIL_TTL,
            "query Author($id: Int!) { authors_by_pk(id: $id) {"
            " id name slug books_count image { url } } }",
            {"id": source_id},
        )
        return _author(raw) if raw else None
    raw = await _cached(
        settings,
        f"series:{source_id}",
        DETAIL_TTL,
        "query Series($id: Int!) { series_by_pk(id: $id) {"
        " id name slug books_count primary_books_count author { name } } }",
        {"id": source_id},
    )
    return _series_entity(raw) if raw else None


async def favourite_releases(
    settings: db.Settings, kind: str, source_ids: list[int]
) -> list[dict[str, Any]]:
    """The books these authors or series have coming, soonest first, in one call."""
    if not source_ids:
        return []
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    made = (
        {"contributions": {"author_id": {"_in": source_ids}}}
        if kind == "author"
        else {"book_series": {"series_id": {"_in": source_ids}}}
    )
    where = {
        **made,
        "release_date": {"_gte": tomorrow},
        "book_status_id": {"_eq": 1},
        "canonical_id": {"_is_null": True},
    }
    rows = await _cached(
        settings,
        f"favourite:{kind}:" + ",".join(map(str, sorted(source_ids))),
        PAGE_TTL,
        f"""query Coming($where: books_bool_exp!) {{
            books(where: $where, order_by: [{{release_date: asc}}, {{id: asc}}], limit: 60) {{
                {BOOK_FIELDS} book_series {{ series_id }}
            }}
        }}""",
        {"where": where},
    )
    books = []
    for raw in rows:
        book = _book(raw)
        book["series_ids"] = [s["series_id"] for s in raw.get("book_series") or []]
        books.append(book)
    return books


def star(books: list[dict[str, Any]], favourites: list[dict[str, Any]]) -> None:
    """Name on each book the favourite it comes from: one of its authors, or its series.

    A search hit names its authors without ids, so an author is matched on the name too.
    """
    for book in books:
        series = {(book.get("series") or {}).get("id"), *book.get("series_ids", [])}
        names = {name.casefold() for name in book.get("authors", [])}
        book["favourite"] = next(
            (
                f["name"]
                for f in favourites
                if (f["kind"] == "series" and f["source_id"] in series)
                or (
                    f["kind"] == "author"
                    and (
                        f["source_id"] in book.get("author_ids", [])
                        or f["name"].casefold() in names
                    )
                )
            ),
            None,
        )
