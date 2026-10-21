from typing import Any

from fastapi import APIRouter, HTTPException, Query

from robin import db, hidden, igdb
from robin.routes.common import decorate

router = APIRouter(prefix="/api", tags=["games"])


@router.get("/games/discover")
async def discover(
    limit: int = Query(default=36, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=1000),
    platform: igdb.Platform | None = None,
    type: igdb.GameType = "upcoming",
    genre: str = Query(default="", max_length=60),
    sort: db.Sort = "date",
) -> dict[str, Any]:
    """Upcoming from tomorrow, or out since the first of January, so a game out this year can
    be monitored to be grabbed. `platform` and `genre` narrow what Settings
    leaves."""
    settings = db.get_settings()
    shown = igdb.platforms(settings.games_hidden_platforms, platform or "")
    page = await igdb.discover(
        limit=limit, offset=offset, shown=shown, game_type=type, genre=genre, sort=sort
    )
    games = [g for g in page["games"] if hidden.game(settings, g)]
    return {"games": decorate(games), "next_offset": page["next_offset"]}


@router.get("/games/genres")
async def genres() -> list[str]:
    return await igdb.genres()


@router.get("/games/search")
async def search(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=24, ge=1, le=50),
) -> list[dict[str, Any]]:
    settings = db.get_settings()
    shown = igdb.platforms(settings.games_hidden_platforms)
    games = await igdb.search(q, limit, shown)
    return decorate([g for g in games if hidden.game(settings, g)])


@router.get("/games/{igdb_id}")
async def game_detail(igdb_id: int) -> dict[str, Any]:
    found = await igdb.detail(igdb_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such game on IGDB")
    return decorate([found])[0]
