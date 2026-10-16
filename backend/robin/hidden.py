"""What Settings hides, left out of everything Robin shows: a category's page, its title
search, what a favourite has coming, Monitored, Home with Radarr and Sonarr's calendars, and
every notice about any of them. Nothing is deleted: what is monitored and hidden comes back,
notices and all, once Settings shows it again, and a grab already under way goes on.

Something carrying a hidden genre, language, literary type or category, or made by a maker
hidden, is left out, unless it also carries a genre or a maker always shown. A platform or a
release type is not carried that way: a game still on a platform shown stays,
`igdb.platforms`, and a film is dated by a release type still shown, `tmdb.kept_releases`.
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from robin import db


def _made(
    makers: dict[str, dict[str, frozenset[int]]],
    category: str,
    made: Mapping[str, Iterable[int]] | None,
) -> bool:
    """Whether one of `makers`, hidden or shown, made it, `made` being its makers' ids by kind of
    favourite, None while they are not known."""
    if made is None:
        return False
    listed = makers.get(category, {})
    return any(not listed.get(kind, frozenset()).isdisjoint(ids) for kind, ids in made.items())


# The crew a person is credited for as a maker, beside the cast. TMDB files a show's creator
# under `created_by` on the show, and as the job Creator in the person's own credits.
MAKER_JOBS = {"Director", "Creator"}


def credited(raw: dict[str, Any]) -> dict[str, set[int]]:
    """Who and what made a movie or show, by kind of favourite, from its TMDB detail."""
    credits = raw.get("credits", {})
    people = {c["id"] for c in credits.get("cast", [])}
    people |= {c["id"] for c in credits.get("crew", []) if c.get("job") in MAKER_JOBS}
    people |= {c["id"] for c in raw.get("created_by", [])}
    return {
        "person": people,
        "studio": {c["id"] for c in raw.get("production_companies", [])},
        "network": {n["id"] for n in raw.get("networks", [])},
    }


def screen(
    settings: db.Settings, title: dict[str, Any], made: dict[str, set[int]] | None = None
) -> bool:
    """Whether a movie or show stays, by its genre ids, original language and, with `made`
    read from its detail, who made it."""
    movie = title["kind"] == "movie"
    hidden = settings.tmdb_hidden_movie_genres if movie else settings.tmdb_hidden_tv_genres
    shown = settings.tmdb_shown_movie_genres if movie else settings.tmdb_shown_tv_genres
    genres = title.get("genre_ids") or []
    hit = (
        not set(genres).isdisjoint(hidden)
        or title.get("language") in settings.tmdb_hidden_languages
        or _made(settings.hidden_makers, "screens", made)
    )
    return (
        not hit
        or not set(genres).isdisjoint(shown)
        or _made(settings.shown_makers, "screens", made)
    )


def detail(settings: db.Settings, kind: str, raw: dict[str, Any]) -> bool:
    """Whether a movie or show stays, read from its TMDB detail, which names its genres."""
    title = {
        "kind": kind,
        "genre_ids": [g["id"] for g in raw.get("genres") or []],
        "language": raw.get("original_language"),
    }
    return screen(settings, title, credited(raw))


def game(settings: db.Settings, found: dict[str, Any]) -> bool:
    """Whether a game stays, by who made it and the platform families it is only on. Read from
    IGDB's shape or from a stored row's JSON columns alike.

    A game on more than two families stores none of them, and stays while any family is shown.
    One on exactly the families hidden then shows, which a list of every family would fix.
    """

    def ids(key: str, column: str) -> list[int]:
        return list(found.get(key) or json.loads(found.get(column) or "[]"))

    made = {
        "company": ids("company_ids", "companies_json"),
        "franchise": ids("franchise_ids", "franchises_json"),
        "collection": ids("collection_ids", "collections_json"),
    }
    if _made(settings.hidden_makers, "games", made) and not _made(
        settings.shown_makers, "games", made
    ):
        return False
    only = found.get("exclusive") or json.loads(found.get("exclusive_json") or "[]")
    return not only or not set(only) <= set(settings.games_hidden_platforms)


def _genre(name: str) -> str:
    """A genre as both a tag slug and a tag name read: "science-fiction", "Science Fiction"."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def book(settings: db.Settings, found: dict[str, Any]) -> bool:
    """Whether a book stays, by its literary type, category, genres, authors and series. A
    search hit names neither type nor category, so only the rest can hide it."""
    genres = {_genre(g) for g in found.get("genres") or []}
    hidden = {_genre(g) for g in settings.books_hidden_genres}
    series = (found.get("series") or {}).get("id")
    made = {
        "author": found.get("author_ids") or [],
        "series": [*found.get("series_ids", []), *([series] if series else [])],
    }
    hit = (
        found.get("literary_type") in settings.books_hidden_literary_types
        or found.get("category") in settings.books_hidden_categories
        or not genres.isdisjoint(hidden)
        or _made(settings.hidden_makers, "books", made)
    )
    return (
        not hit
        or not genres.isdisjoint({_genre(g) for g in settings.books_shown_genres})
        or _made(settings.shown_makers, "books", made)
    )


def comic(settings: db.Settings, made: dict[str, list[int]]) -> bool:
    """Whether an issue stays, by its series, publisher and creators, `comics.made`."""
    return not _made(settings.hidden_makers, "comics", made) or _made(
        settings.shown_makers, "comics", made
    )
