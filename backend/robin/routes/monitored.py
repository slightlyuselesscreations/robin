from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from robin import db, grabs, hidden, igdb
from robin.routes.common import load_game

router = APIRouter(prefix="/api/monitored", tags=["monitored"])


class MonitorIn(BaseModel):
    igdb_id: int


@router.get("")
async def list_monitored() -> list[dict[str, Any]]:
    """Each game but those Settings hides, with its download as qBittorrent has it now, once it
    is grabbed."""
    settings = db.get_settings()
    shown = [row for row in db.list_requests() if hidden.game(settings, row)]
    return await grabs.with_downloads(shown)


@router.post("", status_code=201)
async def start_monitoring(body: MonitorIn, background: BackgroundTasks) -> dict[str, Any]:
    """Track a game. One already out is searched for at once, after the answer goes back."""
    game = await load_game(body.igdb_id)
    if igdb.out(game):
        raise HTTPException(status_code=409, detail=f"{game['name']} is out already")
    if db.live_request_for(body.igdb_id) is not None:
        raise HTTPException(status_code=409, detail=f"{game['name']} is already monitored")

    request_id = db.create_request(body.igdb_id)
    background.add_task(grabs.search_waiting, body.igdb_id)
    stored = db.get_request(request_id)
    assert stored is not None
    return stored


@router.post("/{request_id}/confirm")
async def confirm_release(request_id: int) -> dict[str, Any]:
    """Grab the release held for the user to confirm."""
    if not await grabs.confirm(request_id):
        raise HTTPException(status_code=409, detail="No release is waiting to be confirmed")
    confirmed = db.get_request(request_id)
    assert confirmed is not None
    return confirmed


@router.post("/{request_id}/reject")
def reject_release(request_id: int) -> dict[str, Any]:
    """Never offer the held release again, and leave the game waiting."""
    db.reject_review(request_id)
    rejected = db.get_request(request_id)
    if rejected is None:
        raise HTTPException(status_code=404, detail="No such monitored game")
    return rejected


@router.post("/clear-found", status_code=204)
def clear_found() -> None:
    """Hide every grabbed game from the Monitored page."""
    db.clear_found("requests")


@router.delete("/{request_id}", status_code=204)
def stop_monitoring(request_id: int) -> None:
    """Forget the game. Whatever was already grabbed stays with the download client."""
    if db.get_request(request_id) is None:
        raise HTTPException(status_code=404, detail="No such monitored game")
    db.delete_row("requests", request_id)
