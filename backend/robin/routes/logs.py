"""The lines Robin logged lately, for the Logs page to follow."""

from typing import Any

from fastapi import APIRouter, Query

from robin import logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def recent(after: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
    """Every kept line after the one numbered `after`, so a page asks only for what is new."""
    return logs.since(after)
