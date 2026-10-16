"""The indexers Prowlarr holds, for Settings to pick from."""

from typing import Any

from fastapi import APIRouter

from robin import prowlarr

router = APIRouter(prefix="/api/prowlarr", tags=["prowlarr"])


@router.get("/indexers")
async def indexers() -> list[dict[str, Any]]:
    return await prowlarr.indexers()
