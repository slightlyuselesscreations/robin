"""A week of comics from Metron, an issue, Suwayomi, and the series monitored."""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from robin import comics, db, favourites, hidden, suwayomi, upstream
from robin.routes.common import tracked_routes

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["comics"])


# Background reads of the publishers a week's issues lack, by week, kept so they are not
# collected mid-read and a page asking again does not start a second.
_reading: dict[date, asyncio.Task[None]] = {}


@router.get("/comics/issues")
async def week_issues(week: date | None = None) -> dict[str, Any]:
    """Every issue of a week, of every publisher. `week` is any day of it, defaulting to today,
    and the answer is keyed by its Monday. The earliest is the week the first of this month
    falls in, an earlier one answers as that, and its `previous` is null.

    An issue carries its details only when it was opened before, and its publisher as far as
    one is kept. The publishers it lacks are read behind the answer, and `reading` says so, for
    the page to ask again."""
    first = comics.first_week()
    monday = max(first, comics.week_of(week or datetime.now(UTC).date()))
    try:
        found = await comics.week_issues(monday)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=502, detail="Metron is unreachable") from exc
    suwayomi.link(found)
    lacking = comics.lacking_publishers(found)
    if lacking and monday not in _reading:
        task = asyncio.create_task(comics.read_publishers_behind(lacking))
        _reading[monday] = task
        task.add_done_callback(lambda _: _reading.pop(monday, None))
    return {
        "week": monday.isoformat(),
        "reading": monday in _reading,
        "previous": (monday - timedelta(days=7)).isoformat() if monday > first else None,
        "next": (monday + timedelta(days=7)).isoformat(),
        "issues": await _listed(found),
    }


async def _listed(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Issues as a list shows them: with their details when opened before, starred, and
    without what Settings hides."""
    settings = db.get_settings()
    read = comics.details(issues)
    listed = await comics.credit(settings, [{**c, "detail": read.get(c["id"])} for c in issues])
    shown = [c for c in listed if hidden.comic(settings, comics.made(c))]
    return comics.star(shown, db.favourites("comics"))


@router.get("/comics/comic/{comic_id}")
async def any_issue(comic_id: str = Path(pattern=r"^\d+$")) -> dict[str, Any]:
    """One issue as a list carries it, for a dialog opened away from any list."""
    try:
        found = await comics.issue(comic_id)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Metron is unreachable") from exc
    if found is None:
        raise HTTPException(status_code=404, detail="Metron has no such issue")
    return comics.star([found], db.favourites("comics"))[0]


@router.get("/comics/issue/{comic_id}")
async def issue_detail(
    comic_id: str = Path(pattern=r"^\d+$"),
    modified: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """One issue, read from Metron when it is opened. `modified` is when its list says Metron
    last edited it: a detail read at that one is kept until a list names a newer one."""
    try:
        found = await comics.detail(comic_id, modified)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Metron is unreachable") from exc
    if found is None:
        raise HTTPException(status_code=404, detail="Metron has no such issue")
    return found


class MonitorComic(BaseModel):
    """An issue as a list gave it, and the week it shipped. Its series is what is monitored."""

    id: str
    title: str
    url: str
    publisher: str = ""
    cover: str | None = None
    series_id: int | None = None
    week: date


@router.get("/comics/search")
async def search_series(q: str = Query(min_length=1, max_length=120)) -> list[dict[str, Any]]:
    """Series on the configured Suwayomi source matching a title."""
    return await suwayomi.search(db.get_settings(), q)


@router.get("/comics/latest")
async def latest_series() -> list[dict[str, Any]]:
    """Series the configured Suwayomi source updated last."""
    return await suwayomi.latest(db.get_settings())


@router.get("/comics/series/{manga_id}")
async def series_detail(manga_id: int) -> dict[str, Any]:
    return await suwayomi.series(db.get_settings(), manga_id)


@router.post("/comics/series/{manga_id}/library")
async def add_series_to_library(manga_id: int) -> dict[str, Any]:
    return await suwayomi.add_to_library(db.get_settings(), manga_id)


def reported(settings: db.Settings, row: dict[str, Any]) -> dict[str, Any]:
    """A monitored series as the API reports it, `tracking` while Suwayomi holds it."""
    return {**row, "status": "tracking"} if db.comic_tracked(settings, row) else row


async def _series_shown(settings: db.Settings, row: dict[str, Any]) -> bool:
    """Whether a monitored series stays on Monitored, by its series. Its next issue, `next`,
    is read beside it from what the series has coming, kept six hours, unless Suwayomi holds
    it, which announces each issue as it lists it."""
    row["next"] = None
    if db.comic_tracked(settings, row):
        row["status"] = "tracking"
    series_id = row.get("series_id")
    if not series_id or row["status"] == "tracking":
        return True
    made = {"series": [series_id], "publisher": [], "person": []}
    if not hidden.comic(settings, made):
        return False
    try:
        coming = await favourites.coming(settings, "comics", "series", [series_id])
    except upstream.UpstreamError:
        return True
    today = datetime.now(UTC).date().isoformat()
    row["next"] = next(
        (
            {"id": c["id"], "title": c["title"], "date": c["date"]}
            for c in coming
            if c["date"] and c["date"] >= today
        ),
        None,
    )
    return True


async def _out_of_library(settings: db.Settings, row: dict[str, Any]) -> None:
    """A series Robin stops monitoring leaves the Suwayomi library too."""
    if row["suwayomi_id"] and settings.suwayomi_ready:
        await suwayomi.remove_from_library(settings, int(row["suwayomi_id"]))


tracked_routes(router, "/comics/monitored", "comics", _series_shown, _out_of_library)


@router.post("/comics/monitored")
async def monitor_comic(body: MonitorComic) -> dict[str, Any]:
    """Monitor the series an issue is of. Each new issue is announced, and with Suwayomi set
    it is looked for there at once, then on every hourly pass."""
    issue = {
        "id": body.id,
        "title": body.title,
        "url": body.url,
        "publisher": body.publisher,
        "cover": body.cover,
        "series_id": body.series_id,
        "date": body.week.isoformat(),
    }
    settings = db.get_settings()
    return reported(settings, await favourites.monitor_series(settings, issue))
