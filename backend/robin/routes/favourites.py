"""Favourites in every category: finding them, starring them, and what each has coming."""

import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from robin import db, favourites, upstream
from robin.routes.common import FORGET, notify_now

router = APIRouter(prefix="/api/favourites", tags=["favourites"])


class NewFavourite(BaseModel):
    category: favourites.Category
    kind: str
    id: int


def _kind(category: favourites.Category, kind: str) -> None:
    if kind not in favourites.KINDS[category]:
        raise HTTPException(status_code=422, detail=f"{category} has no favourite of kind {kind}.")


async def _entity(category: favourites.Category, kind: str, source_id: int) -> dict[str, Any]:
    _kind(category, kind)
    found = await favourites.entity(db.get_settings(), category, kind, source_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such favourite on the source.")
    return found


@router.get("")
def listed() -> list[dict[str, Any]]:
    """Each favourite, with how many titles Robin has monitored from it."""
    counts = db.origin_counts()
    return [{**f, "monitored": counts.get(f["id"], 0)} for f in db.favourites()]


@router.get("/coming")
async def coming() -> list[dict[str, Any]]:
    """Every favourite's dated releases, soonest first, read from the six hour cache."""
    return await favourites.dated(db.get_settings())


@router.get("/search")
async def search(
    category: favourites.Category,
    q: str = Query(min_length=1, max_length=100),
    everything: bool = False,
    kind: str | None = Query(default=None, max_length=20),
) -> list[dict[str, Any]]:
    """What can be favourited in the category: companies, franchises, series, people, studios,
    networks and authors, each with its kind. `kind` narrows it to one, where that spares the
    source a call."""
    return await favourites.search(db.get_settings(), category, q.strip(), everything, kind)


@router.post("")
async def add(body: NewFavourite) -> dict[str, Any]:
    """Stored under the id the source names it by, which for a studio TMDB lists under several
    ids is the lowest of them, whichever one it was opened by."""
    found = await _entity(body.category, body.kind, body.id)
    made = db.add_favourite(
        body.category, body.kind, found["id"], found["name"], found["image"], found["ids"]
    )
    # Fetched now, so Home has its releases at once.
    with contextlib.suppress(upstream.UpstreamError):
        await favourites.coming(db.get_settings(), body.category, body.kind, made["ids"])
    await notify_now(favourites.monitor_favourites, f"adding {made['name']}")
    return made


class MakerFilter(NewFavourite):
    mode: db.MakerMode


@router.get("/filters")
def maker_filters() -> list[dict[str, Any]]:
    return db.maker_filters()


@router.post("/filters")
async def filter_maker(body: MakerFilter) -> dict[str, Any]:
    """Always hide or always show a maker as a genre is: everything it made, wherever Settings
    filters. Stored under the id the source names it by, as a favourite is."""
    found = await _entity(body.category, body.kind, body.id)
    return db.filter_maker(
        body.mode, body.category, body.kind, found["id"], found["name"], found["ids"]
    )


@router.delete("/filters/{maker_id}", status_code=204)
def unfilter_maker(maker_id: int) -> Response:
    db.unfilter_maker(maker_id)
    return Response(status_code=204)


@router.delete("/{favourite_id}", status_code=204)
def remove(favourite_id: int) -> Response:
    db.delete_favourite(favourite_id)
    return Response(status_code=204)


@router.get("/{category}/{kind}/{source_id}")
async def detail(category: favourites.Category, kind: str, source_id: int) -> dict[str, Any]:
    """One favourite, starred or not, with what it has coming."""
    found = await _entity(category, kind, source_id)
    starred = next(
        (f for f in db.favourites(category) if f["kind"] == kind and source_id in f["ids"]),
        None,
    )
    ids = starred["ids"] if starred else found["ids"]
    return {
        "entity": found,
        "favourite": starred,
        "releases": await favourites.releases(db.get_settings(), category, kind, ids),
    }


@router.post("/{favourite_id}/stop")
async def stop_monitored(favourite_id: int) -> dict[str, int]:
    """Stop monitoring every title Robin monitored from a favourite, as each one's Stop
    monitoring would, the favourite itself kept or not. Returns how many rows went."""
    settings = db.get_settings()
    stopped = 0
    for category, rows in db.monitored_from(favourite_id).items():
        table = db.ORIGIN_ROWS[category][0]
        for row in rows:
            forget = FORGET.get(table)
            if forget is not None:
                await forget(settings, row)
            db.delete_row(table, int(row["id"]))
            stopped += 1
    return {"stopped": stopped}
