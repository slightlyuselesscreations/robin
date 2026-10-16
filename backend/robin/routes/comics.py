"""New #1 comics for one week, by publisher, and the series monitored from them."""

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from robin import comics, db, favourites, hidden, suwayomi, upstream
from robin.routes.common import tracked_routes

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["comics"])


@router.get("/comics/issues")
async def week_issues() -> dict[str, Any]:
    """Every issue of the current week, of every publisher. An issue carries its details only
    when they are already cached."""
    wednesday = comics.week_of(datetime.now(UTC).date())
    try:
        found = await comics.week_issues(wednesday)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=502, detail="Comic Vine is unreachable") from exc
    return {"week": wednesday.isoformat(), "issues": _listed(found)}


def _listed(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Issues as a list shows them: with their details when already cached, starred, and
    without what Settings hides."""
    settings = db.get_settings()
    shown = [
        {**c, "detail": comics.cached_detail(c["id"])}
        for c in issues
        if hidden.comic(settings, comics.made(c))
    ]
    return comics.star(shown, db.favourites("comics"))


@router.get("/comics/comic/{comic_id}")
async def any_issue(comic_id: str = Path(pattern=r"^\d+$")) -> dict[str, Any]:
    """One issue as a list carries it, for a dialog opened away from any list."""
    try:
        found = await comics.issue(comic_id)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Comic Vine is unreachable") from exc
    if found is None:
        raise HTTPException(status_code=404, detail="Comic Vine has no such issue")
    return comics.star([found], db.favourites("comics"))[0]


@router.get("/comics/issue/{comic_id}")
async def issue_detail(comic_id: str = Path(pattern=r"^\d+$")) -> dict[str, Any]:
    """One issue, read from Comic Vine when it is not cached and kept a few hours after."""
    try:
        found = await comics.detail(comic_id, comics.ON_DEMAND_TTL)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Comic Vine is unreachable") from exc
    if found is None:
        raise HTTPException(status_code=404, detail="Comic Vine has no such issue")
    return found


class MonitorComic(BaseModel):
    """An issue as a list gave it, and the week it shipped. Its series is what is monitored."""

    id: str
    title: str
    url: str
    publisher: str = ""
    cover: str | None = None
    volume_id: int | None = None
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


async def _series_shown(settings: db.Settings, row: dict[str, Any]) -> bool:
    """Whether a monitored series stays on Monitored, by its series. Its next issue, `next`,
    is read beside it from what the series has coming, kept six hours."""
    row["next"] = None
    volume_id = row.get("volume_id")
    if not volume_id:
        return True
    made = {"series": [volume_id], "publisher": [], "person": []}
    if not hidden.comic(settings, made):
        return False
    try:
        coming = await favourites.coming(settings, "comics", "series", [volume_id])
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


# A series already added stays in the Suwayomi library when Robin forgets it.
tracked_routes(router, "/comics/monitored", "comics", _series_shown)


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
        "volume_id": body.volume_id,
        "date": body.week.isoformat(),
    }
    return await favourites.monitor_series(db.get_settings(), issue)
