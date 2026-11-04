"""What Robin told the user lately, for Recently notified on Home."""

from typing import Any

from fastapi import APIRouter

from robin import db

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("")
def sent() -> list[dict[str, Any]]:
    return db.sent_notices()
