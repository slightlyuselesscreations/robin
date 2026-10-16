"""Upcoming movies and TV from TMDB, filtered, and the reminders set on them."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from robin import arr, db, reminders, tmdb
from robin.routes.common import notify_now, tracked_routes

router = APIRouter(prefix="/api/screens", tags=["screens"])

Kind = Literal["movie", "tv"]


class NewReminder(BaseModel):
    kind: Kind
    tmdb_id: int
    # A movie's release type. A show's reminder covers its season premieres and takes none.
    release_type: tmdb.Release | None = None


# Declared before `/{kind}/{tmdb_id}`, which would otherwise take `/reminders/<id>`.
tracked_routes(
    router,
    "/reminders",
    "reminders",
    lambda settings, row: reminders.shown(settings, row["kind"], int(row["tmdb_id"])),
)


@router.post("/reminders")
async def add_reminder(body: NewReminder) -> dict[str, Any]:
    """Remind me of a film's release of one type, or of a show's season premieres."""
    settings = db.get_settings()
    if settings.notices("screens") is None:
        raise HTTPException(status_code=409, detail="Turn on Screens notifications first.")
    if (body.kind == "movie") != (body.release_type is not None):
        raise HTTPException(status_code=422, detail="A movie takes a release type, a show none.")
    detail = await tmdb.title(settings, body.kind, body.tmdb_id)
    if body.kind == "tv" and not reminders.monitorable("tv", detail):
        raise HTTPException(status_code=409, detail=f"{detail['title']} has no season ahead")
    when, platform = reminders.premiere_date(detail), detail["platform"]
    if body.kind == "movie":
        release = next((r for r in detail["releases"] if r["type"] == body.release_type), None)
        if release is None:
            raise HTTPException(status_code=422, detail="No such release in your region.")
        when, platform = release["date"], release["platform"]
    row = db.add_reminder(
        kind=body.kind,
        tmdb_id=body.tmdb_id,
        release_type=body.release_type or "",
        title=detail["title"],
        poster=detail["poster"],
        date=when,
        platform=platform,
    )
    await arr.follow(settings, body.kind, body.tmdb_id)
    await notify_now(reminders.notify_reminders, f"adding {detail['title']}")
    return db.row("reminders", int(row["id"])) or row


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=100)) -> list[dict[str, Any]]:
    settings = db.get_settings()
    titles = await tmdb.search(settings, q.strip())
    await tmdb.star(settings, titles, db.favourites("screens"))
    return titles


@router.get("/languages")
async def languages() -> list[dict[str, Any]]:
    return await tmdb.languages(db.get_settings())


@router.get("/{kind}/genres")
async def genres(kind: Kind) -> list[dict[str, Any]]:
    return await tmdb.genres(db.get_settings(), kind)


@router.get("/{kind}/discover")
async def discover(
    kind: Literal["movie", "tv", "all"],
    days: int = Query(default=90, ge=1, le=730),
    page: int = Query(default=1, ge=1, le=500),
    language: str = Query(default="", pattern=r"^([a-z]{2}|any)?$"),
    release: tmdb.Release | Literal[""] = "",
) -> dict[str, Any]:
    """Genres, original languages and release types are the ones kept in Settings.

    `language` is one original language instead of those, or `any` for every language.
    `release` is one release type of a movie instead of those. TV is only ever scripted series
    and miniseries. `all` is both kinds, a page of each.
    """
    settings = db.get_settings()
    if kind == "all":
        page_of = await tmdb.discover_all(
            settings, days=days, page=page, language=language, release=release
        )
    else:
        page_of = await tmdb.discover(
            settings, kind, days=days, page=page, language=language, release=release
        )
    await tmdb.star(settings, page_of["titles"], db.favourites("screens"))
    return page_of


@router.get("/{kind}/{tmdb_id}")
async def title(kind: Kind, tmdb_id: int) -> dict[str, Any]:
    return await tmdb.title(db.get_settings(), kind, tmdb_id)
