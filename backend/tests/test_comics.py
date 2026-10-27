"""Comics from Metron: a week and the weeks ahead, an issue's details, the publisher each list
lacks, and the #1 digest sent once."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import comics, db, upstream
from tests import metron
from tests.conftest import notify_to, stub_http

# 10:00 on the Friday of the week of 7 October 2026.
FRIDAY = datetime(2026, 10, 9, 10)
FRIDAY_WEEK = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def comics_on() -> None:
    db.save_settings({"metron_token": metron.KEY})


def test_an_issue_is_read_for_everything_the_listing_lacks() -> None:
    found = metron.Metron(metron.week_of_series(), metron.week_of_issues(FRIDAY_WEEK))
    raw = found._detail(found.issues[0])
    assert comics.parse_detail(raw) == {
        "name": "Into the Night",
        "creators": {"Writer": ["Phillip Kennedy Johnson"], "Artist": ["ScieTronc"]},
        "people": {
            "Writer": [{"id": 41, "name": "Phillip Kennedy Johnson"}],
            "Artist": [{"id": 42, "name": "ScieTronc"}],
        },
        "person_ids": [41, 42],
        "series_id": 100,
        "series": "Midnight Spider-Man",
        "year": 2026,
        "publisher": {"id": 1, "name": "Marvel"},
        "imprint": "Black Label",
        "number": "1",
        "date": "2026-10-07",
        "cover": "https://static.metron.test/1.jpg",
        "url": "https://metron.cloud/issue/1/",
        "modified": "2026-10-01T09:00:00-04:00",
        "synopsis": "A young Peter Parker is transformed & more.",
        "story_arcs": ["Midnight"],
        "characters": [{"id": 2, "name": "Spider-Man"}],
        "teams": [],
        "universes": [{"id": 122, "name": "Earth 616"}],
        "first_appearances": [],
        "variants": [{"name": "Cover B", "image": "https://static.metron.test/1b.jpg"}],
    }


def test_metron_roles_are_named_as_the_dialog_names_them() -> None:
    raw = {
        "id": 1,
        "credits": [
            {"id": 7, "creator": "A", "role": [{"name": "Script"}, {"name": "Cover"}]},
            {"id": 8, "creator": "B", "role": [{"name": "Penciller"}]},
        ],
    }
    found = comics.parse_detail(raw) or {}
    assert found["creators"] == {"Writer": ["A"], "Cover Artist": ["A"], "Penciller": ["B"]}


def test_an_issue_metron_does_not_have_is_not_kept() -> None:
    assert comics.parse_detail(None) is None


@pytest.mark.parametrize(
    ("today", "monday"),
    [
        (date(2026, 10, 5), date(2026, 10, 5)),
        (date(2026, 10, 7), date(2026, 10, 5)),
        (date(2026, 10, 11), date(2026, 10, 5)),
        (date(2026, 10, 12), date(2026, 10, 12)),
    ],
)
def test_the_week_starts_on_monday(today: date, monday: date) -> None:
    assert comics.week_of(today) == monday
    assert comics.ships(monday) == monday + timedelta(days=2)


def test_the_digest_is_one_block_per_publisher() -> None:
    body = comics.digest(
        {
            "Marvel": [{"title": "Alien vs. X-Men #1"}],
            "DC Comics": [{"title": "Batman #1"}, {"title": "Superman #1"}],
        }
    )
    assert body == "MARVEL (1)\n• Alien vs. X-Men\n\nDC COMICS (2)\n• Batman\n• Superman"


def test_a_long_digest_is_cut_short() -> None:
    many = {f"Publisher {p}": [{"title": "a" * 80 + " #1"}] * 20 for p in range(10)}
    body = comics.digest(many)
    assert len(body.encode()) < 4096
    assert body.endswith("more")


async def test_a_weeks_firsts_are_grouped_by_publisher_the_main_first(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = metron.stub(monkeypatch, FRIDAY_WEEK)

    found = await comics.week_listing(FRIDAY_WEEK)
    assert list(found) == ["1", "2", "4", "20", "9999"], "every publisher, the main first"
    assert found["1"][0]["title"] == "Midnight Spider-Man #1"
    assert found["2"][0]["publisher"] == "DC Comics"

    listing = fake.asked[0]
    assert listing.url.path == "/api/issue/"
    assert listing.url.params["number"] == "1"
    assert listing.url.params["store_date_range_after"] == "2026-10-05"
    assert listing.url.params["store_date_range_before"] == "2026-10-11"
    assert {r.url.path for r in fake.asked[1:]} == {f"/api/series/{s}/" for s in (100, 200, 300)}
    for request in fake.asked:
        assert request.headers["authorization"] == f"Bearer {metron.KEY}"
        assert request.headers["user-agent"] == comics.USER_AGENT

    # The second look is answered from what is kept, publishers included.
    asked = len(fake.asked)
    await comics.week_listing(FRIDAY_WEEK)
    assert len(fake.asked) == asked


async def test_a_week_is_one_digest_sent_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, delivered: list[dict[str, Any]]
) -> None:
    await client.put("/api/settings", json=notify_to(comics="comics"))
    metron.stub(monkeypatch, FRIDAY_WEEK)

    # The Friday of the week, its Wednesday past.
    assert await comics.notify_new_firsts(FRIDAY) == 1
    [sent] = delivered
    assert sent["url"].startswith("ntfys://ntfy.test/comics?")
    assert sent["title"] == "3 new #1s this week"
    assert sent["body"].startswith("MARVEL (1)\n• Midnight Spider-Man\n\nDC COMICS (1)\n")

    assert await comics.notify_new_firsts(FRIDAY) == 0


async def test_the_digest_names_only_the_picked_publishers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, delivered: list[dict[str, Any]]
) -> None:
    await client.put("/api/settings", json=notify_to(comics="comics"))
    picked = {"comics_digest_publishers": [{"id": 2, "name": "DC Comics"}]}
    assert (await client.put("/api/settings", json=picked)).status_code == 200
    metron.stub(monkeypatch, FRIDAY_WEEK)

    assert await comics.notify_new_firsts(FRIDAY) == 1
    [sent] = delivered
    assert sent["title"] == "1 new #1 this week"
    assert "MARVEL" not in sent["body"]


def test_a_pass_reads_the_weeks_its_schedule_reaches() -> None:
    sunday = date(2026, 10, 11)
    assert comics.weeks_ahead(sunday, [(1, 9)]) == [date(2026, 10, 5), date(2026, 10, 12)]
    assert comics.weeks_ahead(date(2026, 10, 9), [(1, 9)]) == [date(2026, 10, 5)]


async def test_an_unreachable_metron_is_an_error_not_an_empty_week(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, lambda _: httpx.Response(503))
    assert (await client.get("/api/comics/issues")).status_code == 502
    assert db.cache_get(f"comics:issues:v4:{metron.this_week()}") is None


async def test_a_refusal_pauses_metron_and_nothing_asks_it_until_the_pause_ends(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = metron.stub(monkeypatch)
    fake.refuse = 429

    resp = await client.get("/api/comics/issues")
    assert resp.status_code == 429
    assert resp.json()["detail"] == "Metron asked Robin to slow down"
    assert resp.json()["paused_until"]
    assert int(resp.headers["retry-after"]) > 50
    assert len(fake.asked) == 1

    with pytest.raises(upstream.RateLimited):
        await comics.prefetch_weeks()
    assert (await client.get("/api/comics/issues")).status_code == 429
    assert len(fake.asked) == 1, "nothing reaches Metron while it is paused"


async def test_the_current_week_and_two_ahead_are_listed_and_no_issue_is_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = metron.stub(monkeypatch)
    # Each week's issues, then each series once, which names its publisher.
    assert await comics.prefetch_weeks() == 3
    assert sorted(r.url.path for r in fake.asked if r.url.path != "/api/issue/") == [
        f"/api/series/{n}/" for n in (100, 200, 300)
    ]
    assert len([r for r in fake.asked if r.url.path == "/api/issue/"]) == 3

    fake.asked.clear()
    assert await comics.prefetch_weeks() == 0
    every = (await client.get("/api/comics/issues")).json()
    assert fake.asked == []
    marvel, dc, manga = every["issues"]
    assert marvel["detail"] is None, "an issue is read when it is opened"
    assert (marvel["publisher"], marvel["publisher_id"]) == ("Marvel", 1)
    assert (manga["publisher"], manga["publisher_id"], manga["series_id"]) == (
        "Some Manga House",
        9999,
        300,
    )


async def test_a_week_lists_at_once_and_reads_the_publishers_it_lacks_behind(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = metron.stub(monkeypatch)
    first = (await client.get("/api/comics/issues")).json()
    assert [c["publisher"] for c in first["issues"]] == ["", "", ""]
    assert first["reading"]
    # The read behind the answer, given its turns.
    for _ in range(200):
        if not (await client.get("/api/comics/issues")).json()["reading"]:
            break
        await asyncio.sleep(0)
    again = (await client.get("/api/comics/issues")).json()
    assert not again["reading"]
    assert not any(c["detail"] for c in again["issues"])
    assert [c["publisher"] for c in again["issues"]] == [
        "Marvel",
        "DC Comics",
        "Some Manga House",
    ]
    assert all(r.url.host == "metron.cloud" for r in fake.asked)
    assert not [
        r
        for r in fake.asked
        if r.url.path.startswith("/api/issue/") and r.url.path != "/api/issue/"
    ]


async def test_the_arrows_step_to_a_week_ahead_never_before_the_month(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    week = metron.this_week()
    metron.stub(monkeypatch)
    ahead = (await client.get(f"/api/comics/issues?week={week + timedelta(days=9)}")).json()
    assert ahead["week"] == (week + timedelta(days=7)).isoformat()
    assert ahead["previous"] == week.isoformat()
    assert [c["title"] for c in ahead["issues"]] == ["Midnight Spider-Man #2"]

    earliest = (await client.get("/api/comics/issues?week=2020-01-01")).json()
    assert earliest["week"] == comics.first_week().isoformat()
    assert earliest["previous"] is None


async def test_an_issue_is_read_once_when_opened(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = metron.stub(monkeypatch)
    first = await client.get("/api/comics/issue/1")
    again = await client.get("/api/comics/issue/1")
    assert first.json() == again.json()
    assert "cover_date" not in first.json(), "only the date it is on shelves"
    assert len(fake.asked) == 1
    listed = "/api/comics/issue/1?modified=2026-10-01T09:00:00-04:00"
    assert (await client.get(listed)).json()["synopsis"]
    assert (await client.get(listed)).json()["synopsis"]
    assert len(fake.asked) == 2, "read once at the modified its list names"
    await client.get("/api/comics/issue/1?modified=2026-10-20T09:00:00-04:00")
    assert len(fake.asked) == 3, "read again once Metron edited it"
    assert (await client.get("/api/comics/issue/77")).status_code == 404
    assert (await client.get("/api/comics/issue/..%2Fx")).status_code in (404, 422)


def test_the_current_week_is_kept_until_it_ends_one_ahead_a_day_any_before_a_few_hours() -> None:
    wednesday_noon = datetime(2026, 10, 7, 12, tzinfo=UTC)
    current = comics.week_ttl(date(2026, 10, 5), wednesday_noon)
    assert current == int(4.5 * 24 * 3600)
    sunday_night = datetime(2026, 10, 11, 23, 30, tzinfo=UTC)
    assert comics.week_ttl(date(2026, 10, 5), sunday_night) == 1800
    assert comics.week_ttl(date(2026, 9, 28), wednesday_noon) == comics.ON_DEMAND_TTL
    assert comics.week_ttl(date(2026, 10, 12), wednesday_noon) == comics.AHEAD_TTL


def test_a_listing_is_kept_a_day_at_most_and_an_hour_while_empty() -> None:
    week = comics.week_of(datetime.now(UTC).date())
    assert comics.listing_ttl(week, []) == comics.EMPTY_TTL
    assert comics.listing_ttl(week, {"1": [], "2": []}) == comics.EMPTY_TTL
    assert comics.listing_ttl(week, [{"id": "1"}]) <= comics.AHEAD_TTL
    assert comics.listing_ttl(week, {"1": [{"id": "1"}]}) <= comics.AHEAD_TTL


def test_rows_expired_past_the_stale_keep_are_dropped() -> None:
    db.cache_put("comics:detail:v5:old", {"synopsis": ""}, -int(db.STALE_KEEP.total_seconds()) - 1)
    db.cache_put("comics:detail:v5:stale", {"synopsis": ""}, -1)
    db.cache_put("comics:detail:v5:new", {"synopsis": ""}, 60)
    db.cache_purge()
    with db.conn() as c:
        keys = {row["key"] for row in c.execute("SELECT key FROM cache")}
    assert "comics:detail:v5:old" not in keys
    assert {"comics:detail:v5:stale", "comics:detail:v5:new"} <= keys


async def test_the_hourly_loop_gives_way_to_a_page(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = metron.stub(monkeypatch)
    monkeypatch.setattr(comics, "_pages_waiting", 1)
    behind = asyncio.create_task(comics.ping())
    await asyncio.sleep(0.7)
    assert fake.asked == [], "the loop waits while a page is"
    monkeypatch.setattr(comics, "_pages_waiting", 0)
    await behind
    assert len(fake.asked) == 1


async def test_a_fetch_a_page_waits_on_keeps_its_turn_ahead_of_the_loop() -> None:
    marks: list[db.Stale | None] = []

    async def fetch() -> int:
        marks.append(db.STALE.get())
        return 1

    token = db.STALE.set(db.Stale())
    try:
        await db.remember("test:page", 60, fetch)
    finally:
        db.STALE.reset(token)
    await db.remember("test:loop", 60, fetch)
    assert marks[0] is not None, "a page waiting on it goes ahead"
    assert marks[1] is None, "the loop's own fetch stays behind"
