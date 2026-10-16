"""Radarr's and Sonarr's calendars and libraries, and adding a title to either or removing it."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from robin import arr, db, reminders

router = APIRouter(prefix="/api/arr", tags=["arr"])


class NewTitle(BaseModel):
    tmdb_id: int


@router.get("/calendar")
async def calendar() -> list[dict[str, Any]]:
    """Empty while neither is set, so Home asks it whatever is set."""
    return await arr.calendar(db.get_settings())


@router.get("/library")
async def library() -> dict[str, arr.App]:
    """Which app holds each title, by `movie-<id>` or `tv-<id>`. Empty while neither is set."""
    return await arr.library(db.get_settings())


@router.get("/{app}/profiles")
async def profiles(app: arr.App) -> list[dict[str, Any]]:
    return await arr.profiles(db.get_settings(), app)


@router.get("/{app}/folders")
async def folders(app: arr.App) -> list[str]:
    return await arr.folders(db.get_settings(), app)


@router.post("/{app}", status_code=204)
async def add(app: arr.App, body: NewTitle) -> None:
    """Add a title to Radarr or Sonarr, never one Settings hides."""
    settings = db.get_settings()
    if not await reminders.shown(settings, arr.KIND[app], body.tmdb_id):
        raise HTTPException(status_code=409, detail="Your filters hide it")
    await arr.add(settings, app, body.tmdb_id)


@router.delete("/{kind}/{tmdb_id}", status_code=204)
async def remove(kind: Literal["movie", "tv"], tmdb_id: int, delete_files: bool = False) -> None:
    """Remove a title from Radarr or Sonarr. Robin's own reminders on it are left as they are."""
    if not await arr.remove(db.get_settings(), kind, tmdb_id, delete_files):
        raise HTTPException(status_code=404, detail="Neither Radarr nor Sonarr holds it")
