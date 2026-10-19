"""Comics favourites on Comic Vine: series, people and publishers, their stars, hiding them, and
monitoring a series for every new issue."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import comics, db, favourites
from tests.conftest import notify_to, stub_http

WEEK = comics.week_of(datetime.now(UTC).date())


def answer(results: Any) -> httpx.Response:
    total = len(results) if isinstance(results, list) else 1
    body = {"error": "OK", "status_code": 1, "number_of_total_results": total, "results": results}
    return httpx.Response(200, json=body)


def issue(issue_id: int, volume_id: int, number: str = "1", day: date = WEEK) -> dict[str, Any]:
    return {
        "id": issue_id,
        "issue_number": number,
        "image": {"super_url": f"https://comicvine.test/scale_large/{issue_id}.jpg"},
        "site_detail_url": f"https://comicvine.gamespot.com/x/4000-{issue_id}/",
        "volume": {"id": volume_id, "name": "ignored"},
        "store_date": day.isoformat(),
    }


VOLUMES = {
    100: {"id": 100, "name": "Midnight Spider-Man", "publisher": {"id": 31, "name": "Marvel"}},
    200: {"id": 200, "name": "The Demon", "publisher": {"id": 10, "name": "DC Comics"}},
}


def credits(issue_id: int) -> dict[str, Any]:
    return {
        "name": None,
        "person_credits": [{"id": 41, "name": "Phillip Kennedy Johnson", "role": "writer"}]
        if issue_id == 1
        else [],
        "volume": {"id": 100 if issue_id in (1, 3) else 200, "name": "Midnight Spider-Man"},
        "issue_number": "1",
        "store_date": WEEK.isoformat(),
        "image": {},
        "site_detail_url": f"https://comicvine.gamespot.com/x/4000-{issue_id}/",
    }


@pytest.fixture
def comicvine(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Comic Vine with a week of two issues, a later issue of the first series, and a search."""
    db.save_settings({"comicvine_token": "cv-key"})
    state: dict[str, Any] = {"asked": []}
    later = WEEK + timedelta(days=7)

    def handler(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        state["asked"].append(path)
        if path == "/api/issues/":
            if params["filter"].startswith("volume:100"):
                return answer([issue(1, 100), issue(3, 100, "2", later)])
            return answer([issue(1, 100), issue(2, 200)])
        if path == "/api/volumes/":
            wanted = params["filter"].removeprefix("id:").split("|")
            return answer([v for i, v in VOLUMES.items() if str(i) in wanted])
        if path.startswith("/api/issue/4000-"):
            return answer(credits(int(path.split("-")[1].strip("/"))))
        if path == "/api/volume/4050-100/":
            return answer({**VOLUMES[100], "start_year": "2026", "count_of_issues": 2})
        if path == "/api/publisher/4010-31/":
            return answer({"id": 31, "name": "Marvel", "image": {"super_url": "logo.png"}})
        if path == "/api/person/4040-41/":
            return answer({"id": 41, "name": "Phillip Kennedy Johnson", "image": None})
        if path == "/api/search/":
            return answer(
                [
                    {**VOLUMES[100], "resource_type": "volume", "start_year": "2026"},
                    {"id": 41, "name": "Phillip Kennedy Johnson", "resource_type": "person"},
                    {"id": 31, "name": "Marvel", "resource_type": "publisher"},
                    {"id": 9, "name": "A character", "resource_type": "character"},
                ]
            )
        if path == "/api/publishers/":
            assert params["filter"] == "name:midnight"
            return answer([{"id": 31, "name": "Marvel"}, {"id": 32, "name": "Midnight Press"}])
        if path == "/api/people/":
            return answer([])
        raise AssertionError(str(request.url))

    stub_http(monkeypatch, handler)
    return state


async def test_search_finds_series_people_and_publishers(
    client: AsyncClient, comicvine: dict[str, Any]
) -> None:
    found = (
        await client.get("/api/favourites/search", params={"category": "comics", "q": "midnight"})
    ).json()
    assert [(e["kind"], e["id"]) for e in found] == [
        ("series", 100),
        ("person", 41),
        ("publisher", 31),
        ("publisher", 32),
    ], "a publisher the search misses comes from the list by name"
    assert found[0]["meta"] == "Marvel · 2026"


async def test_a_series_favourite_has_its_issues_coming_starred(
    client: AsyncClient, comicvine: dict[str, Any]
) -> None:
    made = (
        await client.post(
            "/api/favourites", json={"category": "comics", "kind": "series", "id": 100}
        )
    ).json()
    assert made["name"] == "Midnight Spider-Man"
    detail = (await client.get("/api/favourites/comics/series/100")).json()
    assert [r["title"] for r in detail["releases"]] == [
        "Midnight Spider-Man #1",
        "Midnight Spider-Man #2",
    ]
    assert {r["favourite"] for r in detail["releases"]} == {"Midnight Spider-Man"}


async def test_a_publisher_and_a_writer_star_the_week(
    client: AsyncClient, comicvine: dict[str, Any]
) -> None:
    await comics.prefetch_week()
    await client.post("/api/favourites", json={"category": "comics", "kind": "publisher", "id": 31})
    publisher = (await client.get("/api/favourites")).json()[0]
    assert publisher["image"] is None, "a publisher is a name, never a logo"
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["favourite"] for c in week] == ["Marvel", None]

    await client.delete(f"/api/favourites/{publisher['id']}")
    await client.post("/api/favourites", json={"category": "comics", "kind": "person", "id": 41})
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["favourite"] for c in week] == ["Phillip Kennedy Johnson", None]
    coming = (await client.get("/api/favourites/comics/person/41")).json()["releases"]
    assert [c["id"] for c in coming] == ["1"]


async def test_a_hidden_publisher_leaves_the_week(
    client: AsyncClient, comicvine: dict[str, Any]
) -> None:
    body = {"mode": "hide", "category": "comics", "kind": "publisher", "id": 31}
    assert (await client.post("/api/favourites/filters", json=body)).status_code == 200
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["publisher"] for c in week] == ["DC Comics"]


async def test_a_series_is_monitored_once_and_every_new_issue_announced(
    client: AsyncClient, comicvine: dict[str, Any], delivered: list[dict[str, Any]]
) -> None:
    await client.put("/api/settings", json=notify_to())
    first = {
        "id": "1",
        "title": "Midnight Spider-Man #1",
        "url": "https://x.test/1",
        "volume_id": 100,
        "week": WEEK.isoformat(),
    }
    again = {**first, "id": "3", "title": "Midnight Spider-Man #2"}
    one = (await client.post("/api/comics/monitored", json=first)).json()
    two = (await client.post("/api/comics/monitored", json=again)).json()
    assert one["id"] == two["id"], "a series is monitored once, from any of its issues"
    assert one["series"] == "Midnight Spider-Man"

    [row] = (await client.get("/api/comics/monitored")).json()
    assert row["next"]["title"] in ("Midnight Spider-Man #1", "Midnight Spider-Man #2")

    sent = await favourites.notify_series()
    assert sent == len(delivered) >= 1
    assert await favourites.notify_series() == 0


async def test_any_issue_opens_away_from_a_list(
    client: AsyncClient, comicvine: dict[str, Any]
) -> None:
    found = (await client.get("/api/comics/comic/1")).json()
    assert found["title"] == "Midnight Spider-Man #1"
    assert (found["publisher"], found["volume_id"]) == ("Marvel", 100)
    assert found["detail"]["people"]["Writer"] == [{"id": 41, "name": "Phillip Kennedy Johnson"}]
