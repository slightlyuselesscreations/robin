"""What qBittorrent is downloading in the games category."""

from typing import Any

from fastapi import APIRouter

from robin import db, qbittorrent

router = APIRouter(prefix="/api/qbittorrent", tags=["qbittorrent"])


@router.get("/downloads")
async def downloads() -> list[dict[str, Any]]:
    """Empty while qBittorrent is unset, so nothing is asked of it."""
    settings = db.get_settings()
    if not settings.qbittorrent_ready:
        return []
    return await qbittorrent.downloading(settings)


@router.get("/categories")
async def categories() -> list[str]:
    """What a monitored game's grab can be filed under. Empty while qBittorrent is unset."""
    settings = db.get_settings()
    if not settings.qbittorrent_ready:
        return []
    return await qbittorrent.categories(settings)
