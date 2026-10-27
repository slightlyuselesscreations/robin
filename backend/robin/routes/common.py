"""Helpers shared by more than one route module."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from robin import db, igdb

log = logging.getLogger(__name__)


# The ids a game names for each kind of favourite.
GAME_IDS = {"company": "company_ids", "franchise": "franchise_ids", "collection": "collection_ids"}


def decorate(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tell each game whether it is already being monitored, in one query for the whole list,
    and which favourite it comes from: a company that made or publishes it, its franchise or
    its series."""
    statuses = db.request_status_map([g["igdb_id"] for g in games])
    stars = {(f["kind"], i): f["name"] for f in db.favourites("games") for i in f["ids"]}
    return [
        {
            **g,
            "request_status": statuses.get(g["igdb_id"]),
            "favourite": next(
                (
                    stars[(kind, i)]
                    for kind, field in GAME_IDS.items()
                    for i in g.get(field) or []
                    if (kind, i) in stars
                ),
                None,
            ),
        }
        for g in games
    ]


async def load_game(igdb_id: int) -> dict[str, Any]:
    """A game from the cache, fetched from IGDB when it is not there yet."""
    game = db.get_game(igdb_id) or await igdb.game(igdb_id)
    if game is None:
        raise HTTPException(status_code=404, detail="No such game on IGDB")
    return game


# What removing a row of each table undoes first, as `tracked_routes` registers it.
FORGET: dict[db.Table, Callable[[db.Settings, dict[str, Any]], Awaitable[None]]] = {}


def tracked_routes(
    router: APIRouter,
    path: str,
    table: db.Table,
    shown: Callable[[db.Settings, dict[str, Any]], Awaitable[bool]] | None = None,
    forget: Callable[[db.Settings, dict[str, Any]], Awaitable[None]] | None = None,
    before: Callable[[db.Settings], Awaitable[None]] | None = None,
) -> None:
    """What every category lists on Monitored: its rows but those Settings hides, `shown`,
    Clear notified, and removing one.

    Removing one makes Robin forget it, and runs `forget` first, which undoes what Robin handed
    off. Without it, anything handed off stays where it went. `before` runs ahead of the list,
    to bring the rows up to date with where they were handed off.
    """
    if forget is not None:
        FORGET[table] = forget

    async def listed() -> list[dict[str, Any]]:
        settings = db.get_settings()
        if before is not None:
            await before(settings)
        rows = db.rows(table)
        if shown is None:
            return rows
        keep = await asyncio.gather(*(shown(settings, row) for row in rows))
        return [row for row, kept in zip(rows, keep, strict=True) if kept]

    def clear_found() -> Response:
        db.clear_found(table)
        return Response(status_code=204)

    async def remove(row_id: int) -> Response:
        found = db.row(table, row_id)
        if found is not None and forget is not None:
            await forget(db.get_settings(), found)
        db.delete_row(table, row_id)
        return Response(status_code=204)

    name = table.replace("_", "-")
    router.add_api_route(path, listed, methods=["GET"], name=f"list-{name}")
    router.add_api_route(
        f"{path}/clear-found", clear_found, methods=["POST"], status_code=204, name=f"clear-{name}"
    )
    router.add_api_route(
        f"{path}/{{row_id}}", remove, methods=["DELETE"], status_code=204, name=f"remove-{name}"
    )


async def notify_now(check: Callable[[], Awaitable[int]], what: str) -> None:
    """Run a check at once rather than on its loop, so what is already due happens now."""
    try:
        await check()
    except Exception:  # noqa: BLE001
        log.exception("%s: pass after %s failed", check.__name__, what)
