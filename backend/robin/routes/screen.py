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
    if not detail["monitorable"]:
        raise HTTPException(status_code=409, detail=f"{detail['title']} is out already")
    when, platform = reminders.premiere_date(detail), detail["platform"]
    if body.kind == "movie":
        if body.release_type not in detail["open_releases"]:
            raise HTTPException(status_code=409, detail="That release is out already.")
        # A release type the region has not dated yet is monitored undated, until it is.
        release: dict[str, Any] = next(
            (r for r in detail["releases"] if r["type"] == body.release_type), {}
        )
        when, platform = release.get("date"), release.get("platform")
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
    page: int = Query(default=1, ge=1, le=500),
    language: str = Query(default="", pattern=r"^([a-z]{2}|any)?$"),
    release: tmdb.Release | Literal[""] = "",
    genre: str = Query(default="", max_length=60),
    sort: db.Sort = "popularity",
) -> dict[str, Any]:
    """What Settings leaves of genres, original languages and release types, narrowed by the
    page: `language` one original language, `release` one release type of a movie, `genre` one
    genre by name.

    `sort` is popularity, most anticipated first, or date, soonest first. TV is only ever
    scripted series and miniseries. `all` is both kinds, a page of each.
    """
    settings = db.get_settings()
    filters: dict[str, Any] = {
        "days": db.AHEAD_DAYS,
        "page": page,
        "language": language,
        "release": release,
        "genre": genre,
        "sort": sort,
    }
    if kind == "all":
        page_of = await tmdb.discover_all(settings, **filters)
    else:
        page_of = await tmdb.discover(settings, kind, **filters)
    await tmdb.star(settings, page_of["titles"], db.favourites("screens"))
    return page_of


@router.get("/{kind}/{tmdb_id}")
async def title(kind: Kind, tmdb_id: int) -> dict[str, Any]:
    return await tmdb.title(db.get_settings(), kind, tmdb_id)
