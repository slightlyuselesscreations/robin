"""Comics favourites on Metron: series, creators and publishers, their stars, hiding them, and
monitoring a series for every new issue."""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from robin import comics, db, favourites
from tests import metron
from tests.conftest import notify_to


@pytest.fixture
def fake(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> metron.Metron:
    """Metron with this week's three #1s and the next issue of the first a week on."""
    db.save_settings({"metron_token": metron.KEY})
    return metron.stub(monkeypatch)


async def test_search_finds_series_creators_and_publishers(
    client: AsyncClient, fake: metron.Metron
) -> None:
    found = (
        await client.get("/api/favourites/search", params={"category": "comics", "q": "mar"})
    ).json()
    assert [(e["kind"], e["id"]) for e in found] == [("publisher", 1)]
    found = (
        await client.get("/api/favourites/search", params={"category": "comics", "q": "midnight"})
    ).json()
    assert [(e["kind"], e["id"], e["name"]) for e in found] == [
        ("series", 100, "Midnight Spider-Man (2026)")
    ]
    assert found[0]["meta"] == "Marvel · 2026 · 2 issues"
    asked = {r.url.path for r in fake.asked}
    assert asked == {"/api/series/", "/api/creator/", "/api/publisher/"}


async def test_a_series_favourite_has_its_issues_coming_starred(
    client: AsyncClient, fake: metron.Metron
) -> None:
    made = (
        await client.post(
            "/api/favourites", json={"category": "comics", "kind": "series", "id": 100}
        )
    ).json()
    assert made["name"] == "Midnight Spider-Man (2026)"
    detail = (await client.get("/api/favourites/comics/series/100")).json()
    assert [r["title"] for r in detail["releases"]] == [
        "Midnight Spider-Man #1",
        "Midnight Spider-Man #2",
    ]
    assert {r["favourite"] for r in detail["releases"]} == {"Midnight Spider-Man (2026)"}
    assert {r["publisher"] for r in detail["releases"]} == {"Marvel"}


async def test_a_writer_and_a_publisher_list_issues_weeks_ahead_and_star_the_week(
    client: AsyncClient, fake: metron.Metron
) -> None:
    await comics.prefetch_weeks()
    await client.post("/api/favourites", json={"category": "comics", "kind": "publisher", "id": 1})
    publisher = (await client.get("/api/favourites")).json()[0]
    assert publisher["image"] is None, "a publisher is a name, never a logo"
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["favourite"] for c in week] == ["Marvel", None, None]
    fake.asked.clear()
    coming = (await client.get("/api/favourites/comics/publisher/1")).json()["releases"]
    assert [c["id"] for c in coming] == ["1", "4"], "the publisher's issue a week on too"
    assert {c["publisher"] for c in coming} == {"Marvel"}
    assert not [r for r in fake.asked if r.url.path.startswith("/api/series/")], (
        "a publisher's issues need no series asked for their publisher"
    )

    await client.delete(f"/api/favourites/{publisher['id']}")
    await client.post("/api/favourites", json={"category": "comics", "kind": "person", "id": 41})
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["favourite"] for c in week] == ["Phillip Kennedy Johnson", None, None]
    coming = (await client.get("/api/favourites/comics/person/41")).json()["releases"]
    assert [c["id"] for c in coming] == ["1", "4"], "the writer's issue a week on too"
    assert any(r.url.params.get("creator_id") == "41" for r in fake.asked)


async def test_a_hidden_publisher_leaves_the_week(client: AsyncClient, fake: metron.Metron) -> None:
    await comics.prefetch_weeks()
    body = {"mode": "hide", "category": "comics", "kind": "publisher", "id": 1}
    assert (await client.post("/api/favourites/filters", json=body)).status_code == 200
    week = (await client.get("/api/comics/issues")).json()["issues"]
    assert [c["publisher"] for c in week] == ["DC Comics", "Some Manga House"]


async def test_a_series_is_monitored_once_and_every_new_issue_announced(
    client: AsyncClient, fake: metron.Metron, delivered: list[dict[str, Any]]
) -> None:
    await client.put("/api/settings", json=notify_to())
    first = {
        "id": "1",
        "title": "Midnight Spider-Man #1",
        "url": "https://metron.cloud/issue/1/",
        "series_id": 100,
        "week": metron.this_week().isoformat(),
    }
    again = {**first, "id": "4", "title": "Midnight Spider-Man #2"}
    one = (await client.post("/api/comics/monitored", json=first)).json()
    two = (await client.post("/api/comics/monitored", json=again)).json()
    assert one["id"] == two["id"], "a series is monitored once, from any of its issues"
    assert one["series"] == "Midnight Spider-Man"

    [row] = (await client.get("/api/comics/monitored")).json()
    assert row["next"]["title"] in ("Midnight Spider-Man #1", "Midnight Spider-Man #2")

    sent = await favourites.notify_series()
    assert sent == len(delivered) >= 1
    assert await favourites.notify_series() == 0


async def test_any_issue_opens_away_from_a_list(client: AsyncClient, fake: metron.Metron) -> None:
    found = (await client.get("/api/comics/comic/1")).json()
    assert found["title"] == "Midnight Spider-Man #1"
    assert (found["publisher"], found["series_id"]) == ("Marvel", 100)
    assert found["url"] == "https://metron.cloud/issue/1/"
    assert found["detail"]["people"]["Writer"] == [{"id": 41, "name": "Phillip Kennedy Johnson"}]


async def test_an_issue_whose_date_moves_is_told_once(
    client: AsyncClient,
    fake: metron.Metron,
    delivered: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await client.put("/api/settings", json=notify_to())
    first = {"id": "1", "title": "Midnight Spider-Man #1", "url": "https://metron.cloud/issue/1/"}
    await client.post(
        "/api/comics/monitored",
        json={**first, "series_id": 100, "week": metron.this_week().isoformat()},
    )
    ahead = date.today() + timedelta(days=60)
    coming: dict[str, Any] = {
        **first,
        "id": "9",
        "title": "Midnight Spider-Man #9",
        "date": ahead.isoformat(),
        "publisher": "Marvel",
        "cover": None,
    }

    async def issues(*args: Any) -> list[dict[str, Any]]:
        return [coming]

    monkeypatch.setattr(favourites, "coming", issues)

    async def told() -> list[str]:
        delivered.clear()
        await favourites.notify_series()
        return [d["title"] for d in delivered]

    assert await told() == [], "nothing is said the first time it is read"
    later = ahead + timedelta(days=14)
    coming["date"] = later.isoformat()
    assert await told() == [f"Midnight Spider-Man #9 moved to {later.isoformat()}"]
    assert await told() == [], "each change is told once"


async def test_a_search_of_one_kind_is_one_call(client: AsyncClient, fake: metron.Metron) -> None:
    params = {"category": "comics", "q": "johnson", "kind": "person"}
    found = (await client.get("/api/favourites/search", params=params)).json()
    assert [(e["kind"], e["id"]) for e in found] == [("person", 41)]
    assert [r.url.path for r in fake.asked] == ["/api/creator/"]
