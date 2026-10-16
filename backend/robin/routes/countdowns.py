"""Countdowns to a release, for Home."""

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from robin import countdowns, db

router = APIRouter(prefix="/api/countdowns", tags=["countdowns"])


class NewCountdown(BaseModel):
    category: str = Field(max_length=40)
    target: str = Field(pattern=r"^[a-z]+=[A-Za-z0-9_-]+$", max_length=100)
    title: str = Field(max_length=300)
    image: str | None = Field(default=None, max_length=1000)
    tag: str | None = Field(default=None, max_length=40)
    date: date


@router.get("")
async def listed() -> list[dict[str, Any]]:
    return await countdowns.listed()


@router.post("")
def add(body: NewCountdown) -> dict[str, Any]:
    """Count down to an item's release, which has to be ahead."""
    if body.date < date.today():
        raise HTTPException(status_code=409, detail="Already out")
    return db.add_countdown(
        body.category, body.target, body.title, body.image, body.tag, body.date.isoformat()
    )


@router.delete("/{countdown_id}", status_code=204)
def remove(countdown_id: int) -> Response:
    db.delete_countdown(countdown_id)
    return Response(status_code=204)
