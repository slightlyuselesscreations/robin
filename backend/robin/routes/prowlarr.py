"""The indexers Prowlarr holds, and a game searched for on them by hand."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from robin import filters, grabs, igdb, prowlarr
from robin.routes.common import load_game

router = APIRouter(prefix="/api/prowlarr", tags=["prowlarr"])


class GrabIn(BaseModel):
    igdb_id: int
    guid: str = Field(min_length=1, max_length=2000)


@router.get("/indexers")
async def indexers() -> list[dict[str, Any]]:
    return await prowlarr.indexers()


async def _pc_game(igdb_id: int) -> dict[str, Any]:
    game = await load_game(igdb_id)
    if igdb.PC not in game["platforms"]:
        raise HTTPException(status_code=409, detail="Only a game on PC is grabbed")
    return game


@router.get("/search")
async def search(igdb_id: int = Query()) -> dict[str, Any]:
    """The chosen indexers searched for a game by the term a grab matches on."""
    game = await _pc_game(igdb_id)
    term = filters.search_term_for(game["name"])
    return {"term": term, "releases": await prowlarr.search(term)}


@router.post("/grab", status_code=204)
async def grab(body: GrabIn) -> None:
    """Grab the picked release, monitoring the game when it is not."""
    game = await _pc_game(body.igdb_id)
    if not await grabs.grab_picked(game, body.guid):
        raise HTTPException(status_code=409, detail=f"{game['name']} has its release already")
