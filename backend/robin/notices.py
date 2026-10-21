"""When a notice set ahead of a date goes out, the same for every category.

A category's schedule is a list of notices, each some days before the date at an hour of the
server's local time, which in the container is UTC unless `TZ` is set. One the day before is
always among them, `db.Settings.schedule`. An item's marker is `<date>|<slot>`, the date and
the latest notice sent for it, so each notice goes once, a container that was off sends only
the latest it missed, and a date that moves is announced again. A marker dated `*` stands for
every date.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from robin import db

# A full day, YYYY-MM-DD, as opposed to TBA, kept empty, or a game's partial date, "Q2 2026".
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Change:
    """A monitored item's date that changed, as its notice says it."""

    title: str
    message: str


def date_change(name: str, before: str | None, now: str, today: date) -> Change | None:
    """The notice for an item whose date reads `now` and last read `before`, or None.

    A date is a full day, a game's partial date such as "Q2 2026", or empty while there is
    none. Nothing is said the first time an item is read, `before` None, nor once the day it
    had is today or past: that release has come, and whatever is dated next is news of its
    own. A full day where there was none is a release date, none where there was one is no
    longer dated, and anything else, a full or partial date for another, is a move.
    """
    if before is None or before == now:
        return None
    if _DAY.fullmatch(before) and before <= today.isoformat():
        return None
    if _DAY.fullmatch(now) and not _DAY.fullmatch(before):
        return Change(f"{name} has a release date", f"Releases {now}.")
    if not now:
        return Change(f"{name} is no longer dated", f"Was {before}.")
    return Change(f"{name} moved to {now}", f"Was {before or 'TBA'}.")


async def tell_change(
    name: str,
    before: str | None,
    now: str,
    today: date,
    send: Callable[[Change], Awaitable[None]] | None,
    store: Callable[[str], None],
) -> int:
    """Tell of an item's date changing, `date_change`, then keep what it reads now. Returns
    how many were sent. Without `send` nothing is told and the date is still kept. A send
    that raises keeps nothing, so the next pass tells it again."""
    change = date_change(name, before, now, today)
    if change and send:
        await send(change)
    if now != before:
        store(now)
    return 1 if change and send else 0


def relative(when: date, today: date) -> str:
    gap = (when - today).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    return f"in {gap} days"


@dataclass(frozen=True)
class Due:
    """A notice to send: its marker, and whether it is the last the schedule has for its date."""

    marker: str
    last: bool


@dataclass(frozen=True)
class Window:
    """Now, and the schedule the category's notices follow."""

    now: datetime
    slots: list[tuple[int, int]]

    @property
    def today(self) -> date:
        return self.now.date()

    def pending(self, when: date, sent: str | None, grace: int = 0) -> Due | None:
        """The notice for `when` to send now, or None when none is due or it was sent. An item
        is followed until its date has passed by `grace` days."""
        if self.today > when + timedelta(days=grace):
            return None
        times = sorted(
            datetime.combine(when - timedelta(days=days), time(hour), self.now.tzinfo)
            for days, hour in self.slots
        )
        passed = [t for t in times if t <= self.now]
        if not passed:
            return None
        due = Due(f"{when.isoformat()}|{passed[-1]:%Y-%m-%dT%H}", passed[-1] == times[-1])
        if sent:
            sent_when, _, sent_slot = sent.partition("|")
            same_date = sent_when in ("*", when.isoformat())
            if same_date and due.marker.partition("|")[2] <= sent_slot:
                return None
        return due

    def relative(self, when: date) -> str:
        return relative(when, self.today)


def local_now() -> datetime:
    return datetime.now().astimezone()


def window(
    settings: db.Settings, category: db.Category, now: datetime | None = None
) -> Window | None:
    """The window a pass reads, or None while the category's notices are off."""
    if settings.notices(category) is None:
        return None
    return Window(now=now or local_now(), slots=settings.schedule(category))
