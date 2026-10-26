"""The carry-over from Comic Vine to Metron, once.

`db._comicvine_aside` moved every Comic Vine id Robin held into `db.COMICVINE_CARRY` on the
first start of a Robin that reads Metron. Once a Metron key is set, this looks each up on Metron
by its Comic Vine id, the one thing Metron's `cv_id` is read for, and puts the Metron id back
where the Comic Vine one was. One Metron does not have is dropped and named in the log. Each is
taken off the carry as it is done, so a restart goes on where it stopped, and the carry table is
dropped once it is empty. This module goes once every install has had that start.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from typing import Any

import httpx

from robin import comics, db, upstream

log = logging.getLogger(__name__)

# Where each thing carried is looked up on Metron by its Comic Vine id.
_LOOKUP = {
    "series": "/series/",
    "person": "/creator/",
    "publisher": "/publisher/",
    "issue": "/issue/",
}


async def _find(http: httpx.AsyncClient, kind: str, cv_id: int) -> dict[str, Any] | None:
    body = await comics._get(http, _LOOKUP[kind], cv_id=cv_id) or {}
    found = body.get("results") or []
    return found[0] if found else None


def _take(row_id: int) -> None:
    with db.conn() as c:
        c.execute(f"DELETE FROM {db.COMICVINE_CARRY} WHERE id = ?", (row_id,))


def _put_favourite(table: str, row: sqlite3.Row, found: dict[str, Any] | None) -> None:
    """A favourite or a filter on its Metron id, or gone when Metron lacks it or already has
    one of the same."""
    with db.conn() as c:
        if found is None:
            c.execute(f"DELETE FROM {table} WHERE id = ?", (row["row_id"],))
            return
        name = found.get("name") or found.get("series") or ""
        try:
            c.execute(
                f"UPDATE {table} SET source_id = ?, source_ids_json = ?, name = ? WHERE id = ?",
                (found["id"], json.dumps([found["id"]]), name, row["row_id"]),
            )
        except sqlite3.IntegrityError:
            c.execute(f"DELETE FROM {table} WHERE id = ?", (row["row_id"],))


# One carry-over at a time, however it is started.
_running = asyncio.Lock()


async def run() -> int:
    """Carry every Comic Vine id still aside over to Metron. Returns how many were carried."""
    async with _running:
        if not db.comicvine_pending() or not db.get_settings().comics_ready:
            return 0
        return await _carry()


async def _carry() -> int:
    with db.conn() as c:
        rows = c.execute(f"SELECT * FROM {db.COMICVINE_CARRY} ORDER BY id").fetchall()
        kinds = {
            table: {
                r["id"]: r["kind"]
                for r in c.execute(f"SELECT id, kind FROM {table} WHERE category = 'comics'")
            }
            for table in ("favourites", "maker_filters")
        }
    carried = dropped = 0
    async with comics.client() as http:
        for row in rows:
            what, cv_id = row["what"], int(row["cv_id"])
            data = json.loads(row["data_json"] or "null")
            try:
                if what in ("favourites", "maker_filters"):
                    kind = kinds[what].get(row["row_id"])
                    found = await _find(http, kind, cv_id) if kind in _LOOKUP else None
                    _put_favourite(what, row, found)
                elif what == "digest":
                    found = await _find(http, "publisher", cv_id)
                    if found:
                        _add_digest_publisher(found)
                elif what == "series":
                    found = await _find(http, "series", cv_id)
                    _put_series(row["row_id"], found)
                elif what == "issue":
                    found = await _find(http, "issue", cv_id)
                    _put_issue(row["row_id"], found)
                elif what == "monitored":
                    found = await _find(http, "series", cv_id)
                    if found:
                        db.mark_favourite_monitored("comics", f"series-{found['id']}")
                elif what == "countdown":
                    found = await _find(http, "issue", cv_id)
                    _put_countdown(row["row_id"], found)
                else:
                    found = await _find(http, "issue", cv_id)
                    if found:
                        _put_mark(what, str(found["id"]), data)
            except upstream.RateLimited:
                # Metron asked Robin to wait. What is left is carried on the next pass.
                log.info("carry-over: Metron paused it, %s carried so far", carried)
                return carried
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("carry-over: %s %s failed, tried again later: %s", what, cv_id, exc)
                continue
            _take(row["id"])
            if found:
                carried += 1
            else:
                dropped += 1
                log.info("carry-over: Metron has no %s for Comic Vine %s, dropped", what, cv_id)
    if not db.comicvine_pending():
        with db.conn() as c:
            c.execute(f"DROP TABLE IF EXISTS {db.COMICVINE_CARRY}")
        log.info("carry-over from Comic Vine done: %s carried, %s dropped", carried, dropped)
    return carried


def _add_digest_publisher(found: dict[str, Any]) -> None:
    settings = db.get_settings()
    picked = [p for p in settings.comics_digest_publishers if p.get("id") != found["id"]]
    picked.append({"id": found["id"], "name": found["name"]})
    db.save_settings({"comics_digest_publishers": picked})


def _put_series(comic_row: int, found: dict[str, Any] | None) -> None:
    """A monitored series on its Metron series, or no longer monitored when Metron lacks it
    or another row already follows it."""
    with db.conn() as c:
        if found is None:
            c.execute("DELETE FROM comics WHERE id = ?", (comic_row,))
            return
        try:
            c.execute("UPDATE comics SET series_id = ? WHERE id = ?", (found["id"], comic_row))
        except sqlite3.IntegrityError:
            c.execute("DELETE FROM comics WHERE id = ?", (comic_row,))


def _put_issue(comic_row: int, found: dict[str, Any] | None) -> None:
    """The issue a series was monitored from, as Metron has it. When Metron lacks it, the row
    opens its Metron series instead, keeping nothing of Comic Vine."""
    with db.conn() as c, contextlib.suppress(sqlite3.IntegrityError):
        if found is None:
            c.execute(
                "UPDATE comics SET issue_id = 'series-' || series_id,"
                " url = ? || '/series/' || series_id || '/', cover = NULL"
                " WHERE id = ? AND series_id IS NOT NULL",
                (comics.SITE, comic_row),
            )
            return
        c.execute(
            "UPDATE comics SET issue_id = ?, url = ?, cover = ? WHERE id = ?",
            (
                str(found["id"]),
                f"{comics.SITE}/issue/{found['id']}/",
                found.get("image"),
                comic_row,
            ),
        )


def _put_countdown(row_id: int, found: dict[str, Any] | None) -> None:
    with db.conn() as c:
        if found is None:
            c.execute("DELETE FROM countdowns WHERE id = ?", (row_id,))
            return
        try:
            c.execute(
                "UPDATE countdowns SET target = ? WHERE id = ?", (f"comic={found['id']}", row_id)
            )
        except sqlite3.IntegrityError:
            c.execute("DELETE FROM countdowns WHERE id = ?", (row_id,))


def _put_mark(what: str, issue_id: str, data: Any) -> None:
    """What was announced of an issue, kept under its Metron id."""
    issue = {"id": issue_id}
    if what == "seen":
        comics.mark_seen(issue, str(data))
    elif what == "dated":
        comics.mark_dated_as(issue, str(data))
    elif what == "notice":
        db.mark_favourite_noticed("comics", issue_id, str(data["notified_for"]))
