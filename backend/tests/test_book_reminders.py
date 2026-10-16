"""Monitor on Books: a book's release is announced once."""

from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient

from robin import book_reminders, db, hardcover
from tests.conftest import notify_to

TOKEN = "hc_pat_test-token"
# 10:00 on the day, past the default hour of 9.
NOW = datetime(2026, 10, 7, 10)


def book(when: str | None, series: bool = True) -> dict[str, Any]:
    return {
        "id": 427,
        "title": "A Book",
        "date": when,
        "cover": None,
        "series": {"id": 99, "name": "A Series", "position": 3} if series else None,
        "hardcover": "https://hardcover.app/books/a-book",
    }


def configure(**extra: Any) -> None:
    db.save_settings({"hardcover_token": TOKEN, **notify_to(books="books"), **extra})


@pytest.fixture
def sent(notified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return notified


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What Hardcover answers, changed by a test to move a date."""
    state: dict[str, Any] = {"book": book("2026-10-08")}

    async def one(settings: Any, book_id: int) -> Any:
        return state["book"]

    monkeypatch.setattr(hardcover, "book", one)
    return state


def remind() -> None:
    db.add_book_reminder(
        kind="book", hardcover_id=427, book_id=427, title="A Book", cover=None, date=None
    )


async def test_a_book_is_announced_once(sent: list[dict[str, Any]], held: dict[str, Any]) -> None:
    configure()
    remind()
    assert await book_reminders.notify_book_reminders(NOW) == 1
    assert sent[0]["title"] == "A Book is out tomorrow"
    assert sent[0]["category"] == "books"
    assert await book_reminders.notify_book_reminders(NOW) == 0
    [row] = db.rows("book_reminders")
    assert row["status"] == "sent"


async def test_a_moved_date_is_followed(sent: list[dict[str, Any]], held: dict[str, Any]) -> None:
    configure()
    remind()
    held["book"] = book("2026-12-01")
    assert await book_reminders.notify_book_reminders(NOW) == 0
    [row] = db.rows("book_reminders")
    assert (row["status"], row["date"]) == ("waiting", "2026-12-01")


async def test_nothing_goes_out_before_the_hour(
    sent: list[dict[str, Any]], held: dict[str, Any]
) -> None:
    configure(books_schedule=[{"days": 1, "hour": 18}])
    remind()
    assert await book_reminders.notify_book_reminders(NOW) == 0
    assert await book_reminders.notify_book_reminders(NOW.replace(hour=18)) == 1


async def test_nothing_is_sent_with_notifications_off(
    sent: list[dict[str, Any]], held: dict[str, Any]
) -> None:
    configure(books_notify=False)
    remind()
    assert await book_reminders.notify_book_reminders(NOW) == 0
    assert sent == []


async def test_a_reminder_needs_notifications(client: AsyncClient) -> None:
    db.save_settings({"hardcover_token": TOKEN})
    resp = await client.post("/api/books/reminders", json={"book_id": 427, "kind": "book"})
    assert resp.status_code == 409
    assert (await client.get("/api/settings")).json()["books_notices_ready"] is False


async def test_reminders_are_set_listed_and_removed(
    client: AsyncClient, sent: list[dict[str, Any]], held: dict[str, Any]
) -> None:
    configure()
    held["book"] = book("2099-01-01")
    resp = await client.post("/api/books/reminders", json={"book_id": 427})
    assert resp.status_code == 200
    assert (resp.json()["title"], resp.json()["kind"]) == ("A Book", "book")

    [row] = (await client.get("/api/books/reminders")).json()
    assert (await client.delete(f"/api/books/reminders/{row['id']}")).status_code == 204
    assert (await client.get("/api/books/reminders")).json() == []
