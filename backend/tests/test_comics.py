"""New #1 comics: reading Comic Vine's week, labelling, and announcing each issue once."""

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import comics, db, upstream
from tests.conftest import notify_to, stub_http

KEY = "cv-key-1"
# 10:00 on the Friday of the week of 7 October 2026.
FRIDAY = datetime(2026, 10, 9, 10)


@pytest.fixture(autouse=True)
def comics_on() -> None:
    db.save_settings({"comicvine_token": KEY})


def issue(issue_id: int, volume_id: int) -> dict[str, Any]:
    """One row of Comic Vine's issue list, as it answers it."""
    return {
        "id": issue_id,
        "issue_number": "1",
        "image": {"super_url": f"https://comicvine.test/scale_large/{issue_id}.jpg"},
        "site_detail_url": f"https://comicvine.gamespot.com/x-1/4000-{issue_id}/",
        "volume": {"id": volume_id, "name": "ignored, the volume list names it"},
    }


def volume(volume_id: int, name: str, publisher_id: int, publisher: str) -> dict[str, Any]:
    return {
        "id": volume_id,
        "name": name,
        "publisher": {"id": publisher_id, "name": publisher},
        "site_detail_url": f"https://comicvine.gamespot.com/x/4050-{volume_id}/",
    }


# Trimmed from a real Comic Vine issue.
DETAIL = {
    "name": "Into the Night",
    "cover_date": "2026-12-01",
    "deck": None,
    "description": "<p>A young Peter Parker is <em>transformed</em> &amp; more.</p>",
    "person_credits": [
        {"id": 41, "name": "Phillip Kennedy Johnson", "role": "writer"},
        {"id": 42, "name": "ScieTronc", "role": "penciler, inker"},
        {"id": 43, "name": "One Hand", "role": "colorist, letterer"},
        {"id": 44, "name": "Mark Brooks", "role": "cover"},
    ],
    "volume": {"id": 100, "name": "Midnight Spider-Man"},
    "issue_number": "1",
    "store_date": "2026-10-07",
    "image": {"super_url": "https://comicvine.test/scale_large/1.jpg"},
    "site_detail_url": "https://comicvine.gamespot.com/x-1/4000-1/",
    "story_arc_credits": [{"id": 1, "name": "Midnight"}],
    "character_credits": [{"id": 2, "name": "Spider-Man"}, {"id": 3, "name": "Mary Jane"}],
    "team_credits": None,
    "first_appearance_characters": None,
    "associated_images": [{"id": 4}, {"id": 5}],
}


def answer(results: Any) -> httpx.Response:
    total = len(results) if isinstance(results, list) else 1
    return httpx.Response(
        200,
        json={
            "error": "OK",
            "status_code": 1,
            "number_of_total_results": total,
            "results": results,
        },
    )


def comicvine_stub(
    monkeypatch: pytest.MonkeyPatch,
    issues: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    sent: list[httpx.Request] | None = None,
) -> list[httpx.Request]:
    """Comic Vine answering `issues` for any week and `volumes` for any ids."""
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ntfy.test":
            if sent is not None:
                sent.append(request)
            return httpx.Response(200)
        asked.append(request)
        if request.url.path == "/api/issues/":
            return answer(issues)
        if request.url.path == "/api/volumes/":
            wanted = request.url.params["filter"].removeprefix("id:").split("|")
            return answer([v for v in volumes if str(v["id"]) in wanted])
        return answer(DETAIL)

    stub_http(monkeypatch, handler)
    return asked


WEEK = (
    [issue(1, 100), issue(2, 200), issue(3, 300)],
    [
        volume(100, "Midnight Spider-Man", 31, "Marvel"),
        volume(200, "The Demon", 10, "DC Comics"),
        volume(300, "Chotto Kiiteyo! Miyazawa-san", 9999, "Some Manga House"),
    ],
)


def test_an_issue_is_read_for_everything_the_listing_lacks() -> None:
    assert comics.parse_detail(DETAIL) == {
        "name": "Into the Night",
        "people": {
            "Writer": [{"id": 41, "name": "Phillip Kennedy Johnson"}],
            "Penciller": [{"id": 42, "name": "ScieTronc"}],
            "Inker": [{"id": 42, "name": "ScieTronc"}],
            "Colorist": [{"id": 43, "name": "One Hand"}],
            "Letterer": [{"id": 43, "name": "One Hand"}],
            "Cover Artist": [{"id": 44, "name": "Mark Brooks"}],
        },
        "person_ids": [41, 42, 43, 44],
        "volume_id": 100,
        "series": "Midnight Spider-Man",
        "number": "1",
        "date": "2026-10-07",
        "cover": "https://comicvine.test/scale_large/1.jpg",
        "url": "https://comicvine.gamespot.com/x-1/4000-1/",
        "synopsis": "A young Peter Parker is transformed & more.",
        "cover_date": "2026-12-01",
        "creators": {
            "Writer": ["Phillip Kennedy Johnson"],
            "Penciller": ["ScieTronc"],
            "Inker": ["ScieTronc"],
            "Colorist": ["One Hand"],
            "Letterer": ["One Hand"],
            "Cover Artist": ["Mark Brooks"],
        },
        "story_arcs": ["Midnight"],
        "characters": ["Spider-Man", "Mary Jane"],
        "teams": [],
        "first_appearances": [],
        "variants": 2,
    }


def test_an_issue_comic_vine_does_not_have_is_not_kept() -> None:
    assert comics.parse_detail(None) is None


@pytest.mark.parametrize(
    ("today", "wednesday"),
    [
        (date(2026, 9, 30), date(2026, 9, 30)),
        (date(2026, 10, 4), date(2026, 9, 30)),
        (date(2026, 10, 6), date(2026, 9, 30)),
        (date(2026, 10, 7), date(2026, 10, 7)),
    ],
)
def test_the_week_is_the_last_wednesday(today: date, wednesday: date) -> None:
    assert comics.week_of(today) == wednesday


def test_a_long_digest_is_cut_short() -> None:
    many = [{"title": f"Comic {i} #1", "url": "https://x.test/" + "a" * 80} for i in range(200)]
    body = comics.digest(many)
    assert len(body.encode()) < 4096
    assert body.endswith("more")


async def test_a_weeks_firsts_are_two_calls_with_the_main_publishers_first(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = comicvine_stub(monkeypatch, *WEEK)

    found = await comics.week_listing(date(2026, 9, 30))
    assert list(found) == ["31", "10", "513", "1868", "9999"], "every publisher, the main first"
    assert found["31"][0]["title"] == "Midnight Spider-Man #1"
    assert found["10"][0]["publisher"] == "DC Comics"

    issues, volumes = asked
    assert issues.url.params["filter"] == "store_date:2026-09-30|2026-10-06,issue_number:1"
    assert volumes.url.params["filter"] == "id:100|200|300"
    for request in asked:
        assert request.url.params["api_key"] == KEY
        assert request.headers["user-agent"] == comics.USER_AGENT

    # The second look is answered from the cache.
    await comics.week_listing(date(2026, 9, 30))
    assert len(asked) == 2


async def test_each_issue_is_announced_once_under_its_own_publisher(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, delivered: list[dict[str, Any]]
) -> None:
    await client.put("/api/settings", json=notify_to(comics="comics"))
    dc = [issue(n, 200 + n) for n in range(10, 14)]
    dc_volumes = [volume(200 + n, f"Batman {n}", 10, "DC Comics") for n in range(10, 14)]
    comicvine_stub(
        monkeypatch,
        [issue(1, 100), *dc],
        [volume(100, "Alien vs. X-Men", 31, "Marvel"), *dc_volumes],
    )

    # The Friday of the week, its Wednesday past.
    assert await comics.notify_new_firsts(FRIDAY) == 2
    single, batch = delivered
    assert single["url"].startswith("ntfys://ntfy.test/comics?")
    assert single["title"] == "Alien vs. X-Men #1"
    assert "attach=https%3A%2F%2Fcomicvine.test%2Fscale_large%2F1.jpg" in single["url"]
    assert "Peter Parker" in single["body"]
    assert batch["title"] == "4 new #1s from DC Comics"

    assert await comics.notify_new_firsts(FRIDAY) == 0


def test_a_pass_reads_the_weeks_its_schedule_reaches() -> None:
    tuesday = date(2026, 10, 13)
    assert comics.weeks_ahead(tuesday, [(1, 9)]) == [date(2026, 10, 7), date(2026, 10, 14)]
    assert comics.weeks_ahead(date(2026, 10, 9), [(1, 9)]) == [date(2026, 10, 7)]


async def test_an_unreachable_comic_vine_is_an_error_not_an_empty_week(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, lambda _: httpx.Response(503))
    assert (await client.get("/api/comics/issues")).status_code == 502
    assert db.cache_get(f"comics:issues:v1:{comics.week_of(date.today())}") is None


async def test_an_error_in_the_body_is_an_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(
        monkeypatch,
        lambda _: httpx.Response(200, json={"error": "Invalid API Key", "status_code": 100}),
    )
    assert (await client.get("/api/comics/issues")).status_code == 502


async def test_a_refusal_pauses_comic_vine_and_nothing_asks_it_until_the_pause_ends(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(420)

    stub_http(monkeypatch, handler)

    resp = await client.get("/api/comics/issues")
    assert resp.status_code == 429
    assert resp.json()["detail"] == "Comic Vine asked Robin to slow down"
    assert resp.json()["paused_until"]
    assert int(resp.headers["retry-after"]) > 3500
    assert len(asked) == 1

    with pytest.raises(upstream.RateLimited):
        await comics.prefetch_week()
    assert (await client.get("/api/comics/issues")).status_code == 429
    assert len(asked) == 1, "nothing reaches Comic Vine while it is paused"


async def test_the_current_week_is_read_in_full_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = comicvine_stub(monkeypatch, *WEEK)
    # The #1s, then every issue of every publisher, then each issue once.
    assert await comics.prefetch_week() == 3
    assert [r.url.path for r in asked[4:]] == [f"/api/issue/4000-{n}/" for n in (1, 2, 3)]

    asked.clear()
    assert await comics.prefetch_week() == 0
    every = (await client.get("/api/comics/issues")).json()
    assert asked == []
    marvel = every["issues"][0]
    assert marvel["detail"]["creators"]["Writer"] == ["Phillip Kennedy Johnson"]
    manga = every["issues"][2]
    assert (manga["publisher"], manga["publisher_id"], manga["volume_id"]) == (
        "Some Manga House",
        9999,
        300,
    )
    assert manga["detail"] is not None


async def test_another_week_lists_without_reading_issues(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = comicvine_stub(monkeypatch, *WEEK)
    await comics.week_listing(date(2025, 3, 5))
    assert len(asked) == 2

    # Opening an issue reads it once.
    first = await client.get("/api/comics/issue/1")
    again = await client.get("/api/comics/issue/1")
    assert first.json() == again.json()
    assert first.json()["cover_date"] == "2026-12-01"
    assert len(asked) == 3

    assert (await client.get("/api/comics/issue/..%2Fx")).status_code in (404, 422)


def test_the_current_week_is_kept_until_it_ends_one_ahead_a_day_any_before_a_few_hours() -> None:
    wednesday_noon = datetime(2026, 10, 7, 12, tzinfo=UTC)
    current = comics.week_ttl(date(2026, 10, 7), wednesday_noon)
    assert current == int(6.5 * 24 * 3600)
    tuesday_night = datetime(2026, 10, 13, 23, 30, tzinfo=UTC)
    assert comics.week_ttl(date(2026, 10, 7), tuesday_night) == 1800
    assert comics.week_ttl(date(2026, 9, 30), wednesday_noon) == comics.ON_DEMAND_TTL
    assert comics.week_ttl(date(2026, 10, 14), wednesday_noon) == comics.AHEAD_TTL


def test_rows_expired_past_the_stale_keep_are_dropped() -> None:
    db.cache_put("comics:detail:v4:old", {"synopsis": ""}, -int(db.STALE_KEEP.total_seconds()) - 1)
    db.cache_put("comics:detail:v4:stale", {"synopsis": ""}, -1)
    db.cache_put("comics:detail:v4:new", {"synopsis": ""}, 60)
    db.cache_purge()
    with db.conn() as c:
        keys = {row["key"] for row in c.execute("SELECT key FROM cache")}
    assert "comics:detail:v4:old" not in keys
    assert {"comics:detail:v4:stale", "comics:detail:v4:new"} <= keys
