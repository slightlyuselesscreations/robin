"""Remind me on Screens: when a notice is due, and that it is sent once."""

from datetime import date, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from robin import db, notices, reminders, tmdb
from tests.conftest import notify_to

TOKEN = "eyJhbGciOiJIUzI1NiJ9.read-access-token"
# 10:00 on the day, past the default hour of 9.
NOW = datetime(2026, 10, 7, 10)

FILM: dict[str, Any] = {
    "id": 550,
    "title": "A Film",
    "poster_path": "/f.jpg",
    "release_dates": {
        "results": [
            {
                "iso_3166_1": "US",
                "release_dates": [
                    {"type": 3, "release_date": "2026-10-08T00:00"},
                    {"type": 4, "release_date": "2026-12-25T00:00", "note": "Netflix"},
                ],
            }
        ]
    },
}


def show(season: int, episode: int, air_date: str) -> dict[str, Any]:
    return {
        "id": 1399,
        "name": "A Show",
        "next_episode_to_air": {
            "season_number": season,
            "episode_number": episode,
            "air_date": air_date,
        },
    }


def configure(**extra: Any) -> None:
    db.save_settings({"tmdb_token": TOKEN, **notify_to(screens="screen"), **extra})


@pytest.fixture
def sent(notified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return notified


@pytest.fixture
def titles(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What TMDB answers, changed by a test to move a date."""
    held: dict[str, Any] = {"movie": FILM, "tv": show(3, 1, "2026-10-08")}

    async def movie(settings: Any, tmdb_id: int) -> Any:
        return held["movie"]

    async def tv(settings: Any, tmdb_id: int) -> Any:
        return held["tv"]

    async def platforms(settings: Any) -> list[dict[str, Any]]:
        return [{"name": "Netflix"}]

    monkeypatch.setattr(tmdb, "movie", movie)
    monkeypatch.setattr(tmdb, "show", tv)
    monkeypatch.setattr(tmdb, "platforms", platforms)
    return held


WEEK_AND_DAY = notices.Window(now=NOW, slots=[(1, 9), (7, 9)])


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (date(2026, 10, 8), "2026-10-08|2026-10-07T09"),
        # Today and never announced: the day before is caught up.
        (date(2026, 10, 7), "2026-10-07|2026-10-06T09"),
        (date(2026, 10, 9), "2026-10-09|2026-10-02T09"),
        (date(2026, 10, 14), "2026-10-14|2026-10-07T09"),
        (date(2026, 10, 15), None),
        (date(2026, 10, 6), None),
    ],
)
def test_the_latest_notice_due_is_the_one_sent(when: date, expected: str | None) -> None:
    due = WEEK_AND_DAY.pending(when, None)
    assert (due.marker if due else None) == expected


def test_each_notice_goes_once() -> None:
    when = date(2026, 10, 8)
    assert WEEK_AND_DAY.pending(when, "2026-10-08|2026-10-07T09") is None
    # The week before was sent, the day before is due and is the last.
    due = WEEK_AND_DAY.pending(when, "2026-10-08|2026-10-01T09")
    assert due is not None and due.last
    # A date that moved is announced again.
    assert WEEK_AND_DAY.pending(when, "2026-10-20|2026-10-19T09") is not None
    # A marker for every date and every notice.
    assert WEEK_AND_DAY.pending(when, f"*|{db.SENT_ALL}") is None


def remind(kind: str, release_type: str = "") -> int:
    tmdb_id = 550 if kind == "movie" else 1399
    return int(
        db.add_reminder(
            kind=kind, tmdb_id=tmdb_id, release_type=release_type, title="T", poster=None, date=None
        )["id"]
    )


async def test_a_movie_is_announced_once_for_its_release_type(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure()
    remind("movie", "theatrical")
    remind("movie", "digital")
    assert await reminders.notify_reminders(NOW) == 1
    assert sent[0]["title"] == "T is in cinemas tomorrow"
    assert sent[0]["category"] == "screens"
    # Sent, so done. Digital is months away and still waiting.
    assert await reminders.notify_reminders(NOW) == 0
    rows = {r["release_type"]: r for r in db.rows("reminders")}
    assert rows["theatrical"]["status"] == "sent"
    assert (rows["digital"]["status"], rows["digital"]["date"]) == ("waiting", "2026-12-25")


async def test_a_digital_release_names_its_platform(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure(screen_schedule=[{"days": 0, "hour": 9}])
    remind("movie", "digital")
    assert await reminders.notify_reminders(NOW.replace(month=12, day=25)) == 1
    assert sent[0]["title"] == "T is on Netflix today"
    [row] = db.rows("reminders")
    assert row["platform"] == "Netflix"


async def test_nothing_goes_out_before_the_hour(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure(screen_schedule=[{"days": 1, "hour": 18}])
    remind("movie", "theatrical")
    assert await reminders.notify_reminders(NOW) == 0
    assert await reminders.notify_reminders(NOW.replace(hour=18)) == 1


async def test_each_notice_of_the_schedule_goes_out(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure(screen_schedule=[{"days": 1, "hour": 9}, {"days": 0, "hour": 9}])
    remind("movie", "theatrical")
    assert await reminders.notify_reminders(NOW) == 1
    assert await reminders.notify_reminders(NOW) == 0
    # The day before was not the last, so it still waits.
    [row] = db.rows("reminders")
    assert row["status"] == "waiting"
    assert await reminders.notify_reminders(NOW.replace(day=8)) == 1
    assert [s["title"] for s in sent] == ["T is in cinemas tomorrow", "T is in cinemas today"]
    [row] = db.rows("reminders")
    assert row["status"] == "sent"


async def test_the_day_before_cannot_be_left_out() -> None:
    configure(screen_schedule=[{"days": 7, "hour": 20}])
    assert db.get_settings().schedule("screens") == [(1, 9), (7, 20)]


async def test_a_show_is_announced_on_each_season_premiere(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure()
    remind("tv")
    assert await reminders.notify_reminders(NOW) == 1
    assert sent[0]["title"] == "T season 3 premieres tomorrow"
    assert await reminders.notify_reminders(NOW) == 0

    # A mid season episode is not a premiere, nor what the reminder is dated by.
    titles["tv"] = show(3, 2, "2026-10-08")
    assert await reminders.notify_reminders(NOW) == 0
    assert db.rows("reminders")[0]["date"] is None

    # The next season is, and the reminder is still on.
    titles["tv"] = show(4, 1, "2026-10-07")
    assert await reminders.notify_reminders(NOW) == 1
    [row] = db.rows("reminders")
    assert (row["status"], row["notified_for"]) == ("waiting", "2026-10-07|2026-10-06T09")
    assert row["date"] == "2026-10-07"


def test_a_show_is_dated_by_its_next_premiere_alone() -> None:
    assert reminders.premiere_date({"next_episode": {"episode": 1, "date": "2026-10-20"}}) == (
        "2026-10-20"
    )
    assert reminders.premiere_date({"next_episode": {"episode": 4, "date": "2026-10-14"}}) is None
    assert reminders.premiere_date({"next_episode": None}) is None


async def test_nothing_is_sent_with_notifications_off(
    sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    configure(screen_notify=False)
    remind("movie", "theatrical")
    assert await reminders.notify_reminders(NOW) == 0
    assert sent == []


async def test_a_reminder_needs_notifications(client: AsyncClient) -> None:
    db.save_settings({"tmdb_token": TOKEN})
    resp = await client.post(
        "/api/screens/reminders", json={"kind": "movie", "tmdb_id": 550, "release_type": "digital"}
    )
    assert resp.status_code == 409
    assert (await client.get("/api/settings")).json()["screen_notices_ready"] is False


async def test_reminders_are_set_listed_and_removed(
    client: AsyncClient, sent: list[dict[str, Any]], titles: dict[str, Any]
) -> None:
    # Far off, so setting it sends nothing yet.
    configure()
    resp = await client.post(
        "/api/screens/reminders", json={"kind": "movie", "tmdb_id": 550, "release_type": "digital"}
    )
    assert resp.status_code == 200
    assert (resp.json()["date"], resp.json()["status"]) == ("2026-12-25", "waiting")

    # A movie needs a release type the region has.
    bad = await client.post(
        "/api/screens/reminders", json={"kind": "movie", "tmdb_id": 550, "release_type": "physical"}
    )
    assert bad.status_code == 422
    assert (
        await client.post("/api/screens/reminders", json={"kind": "movie", "tmdb_id": 550})
    ).status_code == 422

    [row] = (await client.get("/api/screens/reminders")).json()
    assert (await client.delete(f"/api/screens/reminders/{row['id']}")).status_code == 204
    assert (await client.get("/api/screens/reminders")).json() == []
