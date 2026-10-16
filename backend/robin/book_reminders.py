"""Monitor notices for Books, on the Books topic.

A book's reminder is for its release and ends once its last notice is sent. Each pass follows
a moved date, and sends each notice of the Books schedule as `notices.Window` says it is due. A
series is followed by favouriting it, in `robin.favourites`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from robin import db, hardcover, hidden, notices, notify, upstream

log = logging.getLogger(__name__)


async def notify_book_reminders(now: datetime | None = None) -> int:
    """Send each reminder that is due. Returns how many were sent."""
    settings = db.get_settings()
    window = notices.window(settings, "books", now)
    if window is None:
        return 0
    rows = db.waiting("book_reminders")
    sent = 0
    for row in rows:
        if not await shown(settings, int(row["hardcover_id"])):
            continue
        try:
            sent += await _book(settings, row, window)
        except hardcover.HardcoverError as exc:
            log.warning("books: could not read %s: %s", row["title"], exc)
        except notify.NotifyError as exc:
            # Nothing is marked, so the next pass tries again.
            log.warning("books: could not notify for %s: %s", row["title"], exc)
    return sent


async def shown(settings: db.Settings, book_id: int) -> bool:
    """Whether Settings leaves a book shown, read from its cached detail. One Hardcover cannot
    be asked about just now stays."""
    try:
        return hidden.book(settings, await hardcover.book(settings, book_id))
    except upstream.UpstreamError:
        return True


async def _book(settings: db.Settings, row: dict[str, Any], window: notices.Window) -> int:
    found = await hardcover.book(settings, int(row["hardcover_id"]))
    when = found["date"]
    if when != row["date"]:
        db.update_book_reminder(int(row["id"]), when, None)
    due = window.pending(date.fromisoformat(when), row["notified_for"]) if when else None
    if due is None:
        return 0
    await _send(
        settings,
        title=f"{row['title']} is out {window.relative(date.fromisoformat(when))}",
        message=f"Releases {when}.",
        click=found["hardcover"],
        cover=found["cover"],
    )
    db.mark_notified("book_reminders", int(row["id"]), due.marker, done=due.last)
    return 1


async def _send(
    settings: db.Settings, *, title: str, message: str, click: str, cover: str | None
) -> None:
    await notify.send(
        settings,
        settings.channel("books"),
        title=title,
        message=message,
        tags="books",
        click=click,
        attach=cover,
    )
    log.info("books: %s", title)
