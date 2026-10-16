"""Countdowns to a release, kept for Home's Countdowns panel.

A countdown is any item with a release date, known by the dialog parameter that opens it,
`game=<igdb id>`, `title=movie-<id>`, `book=<id>`, `comic=<id>`. Each is dated again from its
category's own cached detail on every read, so a release that moves takes the countdown with
it, and so does its tag. A new category adds its parameter to `DATES`, and one it has no entry
for keeps the date and tag it was set with.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from robin import db, favourites, hardcover, tmdb, upstream

log = logging.getLogger(__name__)

# An item's release date and tag.
Dated = tuple[str | None, str | None]


async def _game(settings: db.Settings, value: str) -> Dated:
    game = db.get_game(int(value))
    stamp = (game or {}).get("first_release_date")
    date = datetime.fromtimestamp(stamp, tz=UTC).date().isoformat() if stamp else None
    return date, favourites.tag("games", game) if game else None


async def _title(settings: db.Settings, value: str) -> Dated:
    kind, tmdb_id = value.split("-")
    found = await tmdb.title(settings, "movie" if kind == "movie" else "tv", int(tmdb_id))
    return found["date"], favourites.tag("screens", found)


async def _book(settings: db.Settings, value: str) -> Dated:
    found = await hardcover.book(settings, int(value))
    return found["date"], favourites.tag("books", found)


# The release date and tag of an item, by the parameter that opens its dialog.
DATES: dict[str, Callable[[db.Settings, str], Awaitable[Dated]]] = {
    "game": _game,
    "title": _title,
    "book": _book,
}


async def listed() -> list[dict[str, Any]]:
    """Every countdown, dated again from its category. One that cannot be read just now keeps
    the date it had."""
    settings = db.get_settings()

    async def dated(row: dict[str, Any]) -> dict[str, Any]:
        key, _, value = row["target"].partition("=")
        resolve = DATES.get(key)
        if resolve is not None:
            try:
                date, tag = await resolve(settings, value)
                row["date"] = date or row["date"]
                row["tag"] = tag or row["tag"]
            except upstream.UpstreamError as exc:
                log.info("countdowns: could not date %s: %s", row["target"], exc)
        return row

    rows = await asyncio.gather(*(dated(r) for r in db.countdowns()))
    return sorted(rows, key=lambda r: str(r["date"]))
