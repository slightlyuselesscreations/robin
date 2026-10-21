"""Upcoming books from Hardcover, the reminders set on them, and the Want to Read shelf."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from robin import book_reminders, db, hardcover
from robin.routes.common import notify_now, tracked_routes

router = APIRouter(prefix="/api/books", tags=["books"])


class NewReminder(BaseModel):
    book_id: int


class Shelf(BaseModel):
    want: bool


# Declared before `/{book_id}`, which would otherwise take `/reminders`.
tracked_routes(
    router,
    "/reminders",
    "book_reminders",
    lambda settings, row: book_reminders.shown(settings, int(row["hardcover_id"])),
)


@router.post("/reminders")
async def add_reminder(body: NewReminder) -> dict[str, Any]:
    """Remind me of a book's release. A series is followed by favouriting it."""
    settings = db.get_settings()
    if settings.notices("books") is None:
        raise HTTPException(status_code=409, detail="Turn on Books notifications first.")
    book = await hardcover.book(settings, body.book_id)
    if db.before_month(book["date"]):
        raise HTTPException(status_code=409, detail=f"{book['title']} is out already")
    row = db.add_book_reminder(
        kind="book",
        hardcover_id=body.book_id,
        book_id=body.book_id,
        title=book["title"],
        cover=book["cover"],
        date=book["date"],
    )
    await notify_now(book_reminders.notify_book_reminders, f"adding {book['title']}")
    return db.row("book_reminders", int(row["id"])) or row


@router.get("/genres")
async def genres() -> list[dict[str, Any]]:
    return await hardcover.genres(db.get_settings())


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=100)) -> list[dict[str, Any]]:
    books = await hardcover.search(db.get_settings(), q.strip())
    hardcover.star(books, db.favourites("books"))
    return books


@router.get("/discover")
async def discover(
    page: int = Query(default=1, ge=1, le=100),
    kind: hardcover.Kind = "",
    genre: str = Query(default="", pattern=r"^[a-z0-9-]*$", max_length=60),
    sort: db.Sort = "popularity",
) -> dict[str, Any]:
    """What Settings leaves of literary types, categories and genres, narrowed by the page:
    `kind` fiction or nonfiction, `genre` one genre slug. `sort` is popularity, most
    anticipated first, or date, soonest first.
    """
    page_of = await hardcover.discover(
        db.get_settings(), days=db.AHEAD_DAYS, page=page, kind=kind, genre=genre, sort=sort
    )
    hardcover.star(page_of["books"], db.favourites("books"))
    return page_of


@router.get("/{book_id}")
async def book(book_id: int) -> dict[str, Any]:
    return await hardcover.book(db.get_settings(), book_id)


@router.get("/{book_id}/shelf")
async def shelf(book_id: int) -> dict[str, Any]:
    return await hardcover.shelf(db.get_settings(), book_id)


@router.put("/{book_id}/shelf")
async def set_shelf(book_id: int, body: Shelf) -> dict[str, Any]:
    """Shelve the book as Want to Read on Hardcover, or take it off."""
    return await hardcover.set_shelf(db.get_settings(), book_id, body.want)
