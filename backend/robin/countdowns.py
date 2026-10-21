"""Countdowns to a release, kept for Home's Countdowns panel.

A countdown is any item with a release date, known by the dialog parameter that opens it,
`game=<igdb id>`, `title=movie-<id>`, `book=<id>`, `comic=<id>`. Each is dated again from its
category's own cached detail on every read, and so are its tag, title and image, so Home shows
the item as its source has it now. A new category adds its parameter to `DATES`, and one it has
no entry for keeps what it was set with.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from robin import db, favourites, hardcover, tmdb, upstream

log = logging.getLogger(__name__)

# What a countdown shows of its item, as its source has it now. A value the source does not
# have is None, and the countdown keeps the one it was set with.
Read = dict[str, str | None]


async def _game(settings: db.Settings, value: str) -> Read:
    game = db.get_game(int(value))
    if game is None:
        return {}
    stamp, cover = game.get("first_release_date"), game.get("cover_image_id")
    return {
        "date": datetime.fromtimestamp(stamp, tz=UTC).date().isoformat() if stamp else None,
        "tag": favourites.tag("games", game),
        "title": game.get("name"),
        "image": f"/img/cover_big/{cover}.jpg" if cover else None,
    }


async def _title(settings: db.Settings, value: str) -> Read:
    kind, tmdb_id = value.split("-")
    found = await tmdb.title(settings, "movie" if kind == "movie" else "tv", int(tmdb_id))
    return {
        "date": found["date"],
        "tag": favourites.tag("screens", found),
        "title": found["title"],
        "image": found["poster"],
    }


async def _book(settings: db.Settings, value: str) -> Read:
    found = await hardcover.book(settings, int(value))
    return {
        "date": found["date"],
        "tag": favourites.tag("books", found),
        "title": found["title"],
        "image": found["cover"],
    }


# What a countdown shows of an item, by the parameter that opens its dialog.
DATES: dict[str, Callable[[db.Settings, str], Awaitable[Read]]] = {
    "game": _game,
    "title": _title,
    "book": _book,
}


async def listed() -> list[dict[str, Any]]:
    """Every countdown read again from its category, its date, tag, title and image. One that
    cannot be read just now keeps what it had."""
    settings = db.get_settings()

    async def dated(row: dict[str, Any]) -> dict[str, Any]:
        key, _, value = row["target"].partition("=")
        resolve = DATES.get(key)
        if resolve is not None:
            try:
                read = await resolve(settings, value)
                for field in ("date", "tag", "title", "image"):
                    row[field] = read.get(field) or row[field]
            except upstream.UpstreamError as exc:
                log.info("countdowns: could not date %s: %s", row["target"], exc)
        return row

    rows = await asyncio.gather(*(dated(r) for r in db.countdowns()))
    return sorted(rows, key=lambda r: str(r["date"]))
