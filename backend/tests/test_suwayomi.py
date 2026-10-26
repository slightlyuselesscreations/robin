"""Monitored comic series: matching a #1 to a source series, adding it once readable, and
following the library from then on."""

import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, suwayomi
from tests.conftest import notify_to, stub_http

SOURCE = "7185601298150078890"


def test_the_series_is_the_issue_without_its_number() -> None:
    assert suwayomi.series_title("Midnight X-Men #1") == "Midnight X-Men"
    assert suwayomi.series_title("G.I. Joe: A Real American Hero / Tomb Raider #1") == (
        "G.I. Joe: A Real American Hero / Tomb Raider"
    )


def test_a_punctuated_title_is_also_searched_by_its_plain_words() -> None:
    assert suwayomi.queries("DC's Quoth the Raven... Whatever") == [
        "DC's Quoth the Raven... Whatever",
        "Quoth the Raven",
    ]
    assert suwayomi.queries("Avengelyne") == ["Avengelyne"]


def manga(manga_id: int, title: str, in_library: bool = False) -> dict[str, Any]:
    return {"id": manga_id, "title": title, "inLibrary": in_library}


def test_the_match_is_the_same_name_from_the_year_of_its_first_issue() -> None:
    results = [
        manga(1, "Batman: Tales of the Demon (2020)"),
        manga(2, "The Demon (1990-1995)"),
        manga(3, "The Demon (2026-)"),
        manga(4, "The Demon: Hell is Earth (2017-)"),
    ]
    assert suwayomi.pick(results, "The Demon", 2026) == results[2]
    # Only the older run is up, so nothing is taken.
    assert suwayomi.pick(results[:2], "The Demon", 2026) is None


def test_punctuation_does_not_stop_a_match() -> None:
    results = [manga(9, "DC's Quoth the Raven… Whatever (2026-)")]
    assert suwayomi.pick(results, "DC's Quoth the Raven... Whatever", 2026) == results[0]


@pytest.fixture
def suwayomi_stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A Suwayomi with one series on its source."""
    state: dict[str, Any] = {
        "listed": True,
        "chapters": [],
        "added": [],
        "searches": [],
        "kinds": [],
        "downloads": [],
        "removed": [],
        "library": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if "fetchSourceManga" in body["query"]:
            assert variables["source"] == SOURCE
            state["kinds"].append(variables.get("type", "SEARCH"))
            if variables.get("type") != "LATEST":
                state["searches"].append(variables["query"])
            listed = [manga(1954, "Midnight X-Men (2026-)", 1954 in state["added"])]
            found = listed if state["listed"] else []
            return httpx.Response(200, json={"data": {"fetchSourceManga": {"mangas": found}}})
        if "fetchMangaAndChapters" in body["query"]:
            chapters = [{"id": c} for c in state["chapters"]]
            data = {"fetchMangaAndChapters": {"chapters": chapters}}
            errors = [] if chapters else [{"message": "No chapters found"}]
            return httpx.Response(200, json={"data": data, "errors": errors})
        if "fetchManga(" in body["query"]:
            series = {**manga(variables["id"], "Midnight X-Men (2026-)", True), "thumbnailUrl": ""}
            return httpx.Response(200, json={"data": {"fetchManga": {"manga": series}}})
        if "enqueueChapterDownloads" in body["query"]:
            assert "startDownloader" in body["query"]
            state["downloads"].append(variables["ids"])
            done = {"clientMutationId": None}
            queued = {"enqueueChapterDownloads": done, "startDownloader": done}
            return httpx.Response(200, json={"data": queued})
        if "mangas(condition" in body["query"]:
            assert variables["source"] == SOURCE
            return httpx.Response(200, json={"data": {"mangas": {"nodes": state["library"]}}})
        if "inLibrary: false" in body["query"]:
            state["removed"].append(variables["id"])
            manga_row = {"id": variables["id"], "inLibrary": False}
            return httpx.Response(200, json={"data": {"updateManga": {"manga": manga_row}}})
        if "updateManga" in body["query"]:
            state["added"].append(variables["id"])
            manga_row = {"id": variables["id"], "inLibrary": True}
            return httpx.Response(200, json={"data": {"updateManga": {"manga": manga_row}}})
        raise AssertionError(body["query"])

    stub_http(monkeypatch, handler)
    return state


async def test_a_series_is_added_as_soon_as_the_source_lists_it(
    client: AsyncClient, suwayomi_stub: dict[str, Any], delivered: list[dict[str, Any]]
) -> None:
    await client.put(
        "/api/settings",
        json={
            "metron_token": "metron-key",
            "suwayomi_url": "https://suwayomi.test/",
            "suwayomi_source_id": SOURCE,
            **notify_to(comics="comics"),
        },
    )
    first = {
        "id": "8870001",
        "title": "Midnight X-Men #1",
        "url": "https://leagueofcomicgeeks.com/comic/8870001/midnight-x-men-1",
        "publisher": "Marvel Comics",
        "cover": "https://s3.test/large-8870001.jpg",
        "week": "2026-10-07",
    }

    # Not on the source yet, so it waits.
    suwayomi_stub["listed"] = False
    monitored = (await client.post("/api/comics/monitored", json=first)).json()
    assert (monitored["status"], monitored["series"], monitored["year"]) == (
        "monitored",
        "Midnight X-Men",
        2026,
    )
    assert suwayomi_stub["searches"] == ["Midnight X-Men", "Midnight"]
    assert suwayomi_stub["added"] == []

    # Listed, with no issue out yet, which is enough.
    suwayomi_stub["listed"] = True
    assert await suwayomi.add_found_series() == 1
    assert suwayomi_stub["added"] == [1954]
    [notice] = delivered
    assert notice["url"].startswith("ntfys://ntfy.test/comics?")
    assert notice["title"] == "Midnight X-Men is in your library"
    assert "click=https%3A%2F%2Fsuwayomi.test%2Fmanga%2F1954" in notice["url"]
    assert "no issue is out yet" in notice["body"]

    [row] = (await client.get("/api/comics/monitored")).json()
    assert (row["status"], row["suwayomi_id"], row["issues"]) == ("tracking", 1954, 0)
    assert row["next"] is None, "Suwayomi announces its issues, it is not dated"

    # Suwayomi follows it now. Nothing looks for it again, monitoring it again changes nothing.
    searches = len(suwayomi_stub["searches"])
    assert await suwayomi.add_found_series() == 0
    again = (await client.post("/api/comics/monitored", json=first)).json()
    assert again["status"] == "tracking"
    assert len(suwayomi_stub["searches"]) == searches

    # Stopping it takes it out of the library too.
    assert (await client.delete(f"/api/comics/monitored/{row['id']}")).status_code == 204
    assert (await client.get("/api/comics/monitored")).json() == []
    assert suwayomi_stub["removed"] == [1954]


async def test_the_issue_count_is_taken_when_the_series_is_added(
    client: AsyncClient, suwayomi_stub: dict[str, Any], delivered: list[dict[str, Any]]
) -> None:
    await client.put(
        "/api/settings",
        json={
            "metron_token": "metron-key",
            "suwayomi_url": "https://suwayomi.test",
            "suwayomi_source_id": SOURCE,
        },
    )
    suwayomi_stub["chapters"] = [4100, 4101]
    first = {"id": "2", "title": "Midnight X-Men #1", "url": "https://x.test", "week": "2026-10-07"}
    added = (await client.post("/api/comics/monitored", json=first)).json()
    assert (added["status"], added["issues"]) == ("tracking", 2)
    assert suwayomi_stub["downloads"] == [[4100, 4101]], "every issue downloads at once"
    assert delivered == []


async def test_nothing_is_looked_for_until_suwayomi_is_configured(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    first = {"id": "1", "title": "Avengelyne #1", "url": "https://x.test", "week": "2026-10-07"}
    assert (await client.post("/api/comics/monitored", json=first)).json()["status"] == "monitored"
    assert await suwayomi.add_found_series() == 0
    assert suwayomi_stub["searches"] == []


async def test_the_comics_search_answers_with_covers_suwayomi_can_serve(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    resp = await client.get("/api/comics/search", params={"q": "Midnight"})
    assert resp.status_code == 409, "a search needs a source to ask"

    await client.put(
        "/api/settings",
        json={
            "metron_token": "metron-key",
            "suwayomi_url": "https://suwayomi.test/",
            "suwayomi_source_id": SOURCE,
        },
    )
    [found] = (await client.get("/api/comics/search", params={"q": "Midnight"})).json()
    assert found["title"] == "Midnight X-Men (2026-)"
    assert found["url"] == "https://suwayomi.test/manga/1954"
    assert suwayomi_stub["added"] == [], "searching adds nothing to the library"

    suwayomi_stub["chapters"] = [4100]
    added = (await client.post("/api/comics/series/1954/library")).json()
    assert added["inLibrary"] is True
    assert added["issues"] == 1
    assert suwayomi_stub["downloads"] == [[4100]], "adding from a search downloads too"

    [recent] = (await client.get("/api/comics/latest")).json()
    assert recent["url"] == "https://suwayomi.test/manga/1954"
    assert recent["issues"] == 1, "a series with one issue is tagged #1"
    assert suwayomi_stub["kinds"] == ["SEARCH", "LATEST"]


async def test_clearing_found_comics_hides_them_and_keeps_their_status(client: AsyncClient) -> None:
    for issue_id, status in (("1", "added"), ("2", "monitored")):
        comic = db.monitor_comic(
            issue_id=issue_id,
            title=f"Series {issue_id} #1",
            series=f"Series {issue_id}",
            year=2026,
            publisher="DC Comics",
            url=f"https://leagueofcomicgeeks.com/comic/{issue_id}/x",
            cover=None,
        )
        if status == "added":
            db.mark_comic_added(int(comic["id"]), 77, 1)

    assert (await client.post("/api/comics/monitored/clear-found")).status_code == 204
    rows = {c["issue_id"]: c for c in db.rows("comics")}
    assert rows["1"]["cleared_at"] and rows["1"]["status"] == "added"
    assert rows["2"]["cleared_at"] is None


async def test_latest_is_kept_and_answered_at_once_while_it_is_asked_again(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    await client.put(
        "/api/settings",
        json={
            "metron_token": "metron-key",
            "suwayomi_url": "https://suwayomi.test/",
            "suwayomi_source_id": SOURCE,
        },
    )
    first = await client.get("/api/comics/latest")
    assert "x-robin-stale" not in first.headers
    await client.get("/api/comics/latest")
    assert suwayomi_stub["kinds"] == ["LATEST"], "kept, not asked again"

    with db.conn() as c:
        c.execute("UPDATE cache SET expires_at = '2000-01-01' WHERE key LIKE 'suwayomi:latest:%'")
    suwayomi_stub["listed"] = False
    stale = await client.get("/api/comics/latest")
    assert stale.headers["x-robin-stale"] == "1"
    assert stale.json() == first.json()

    fresh = await client.get("/api/comics/latest", headers={"X-Robin-Fresh": "1"})
    assert "x-robin-stale" not in fresh.headers
    assert fresh.json() == []
    assert suwayomi_stub["kinds"] == ["LATEST", "LATEST"], "asked once for both"


def shelved(manga_id: int, title: str, issues: int, latest: str | None = None) -> dict[str, Any]:
    return {
        "id": manga_id,
        "title": title,
        "thumbnailUrl": f"/api/v1/manga/{manga_id}/thumbnail",
        "chapters": {"totalCount": issues},
        "latestUploadedChapter": {"name": latest or f"#{issues}"},
    }


async def suwayomi_on(client: AsyncClient) -> None:
    await client.put(
        "/api/settings",
        json={
            "metron_token": "metron-key",
            "suwayomi_url": "https://suwayomi.test",
            "suwayomi_source_id": SOURCE,
            **notify_to(comics="comics"),
        },
    )


async def test_the_library_is_monitored_and_each_new_issue_announced_once(
    client: AsyncClient, suwayomi_stub: dict[str, Any], delivered: list[dict[str, Any]]
) -> None:
    await suwayomi_on(client)
    suwayomi_stub["library"] = [shelved(209, "Corpse Knight (2026-)", 6)]

    # Taken in as it is, nothing announced.
    assert await suwayomi.sync_library() == 0
    [row] = (await client.get("/api/comics/monitored")).json()
    assert (row["status"], row["series"], row["year"], row["suwayomi_id"]) == (
        "tracking",
        "Corpse Knight",
        2026,
        209,
    )
    assert row["cover"] == "https://suwayomi.test/api/v1/manga/209/thumbnail"
    assert delivered == []

    suwayomi_stub["library"] = [shelved(209, "Corpse Knight (2026-)", 7)]
    assert await suwayomi.sync_library() == 1
    [notice] = delivered
    assert notice["title"] == "Corpse Knight #7"
    assert "click=https%3A%2F%2Fsuwayomi.test%2Fmanga%2F209" in notice["url"]
    assert await suwayomi.sync_library() == 0, "an issue is announced once"

    suwayomi_stub["library"] = [shelved(209, "Corpse Knight (2026-)", 9)]
    assert await suwayomi.sync_library() == 1
    assert delivered[-1]["title"] == "2 new issues of Corpse Knight"

    # Gone from the library, gone from Robin.
    suwayomi_stub["library"] = []
    assert await suwayomi.sync_library() == 0
    assert (await client.get("/api/comics/monitored")).json() == []
    assert suwayomi_stub["removed"] == []


async def test_a_waiting_series_the_library_holds_is_tracked_not_taken_in_twice(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    first = {"id": "2", "title": "Midnight X-Men #1", "url": "https://x.test", "week": "2026-10-07"}
    waiting = (await client.post("/api/comics/monitored", json=first)).json()
    assert waiting["status"] == "monitored"

    await suwayomi_on(client)
    suwayomi_stub["library"] = [shelved(1954, "Midnight X-Men (2026-)", 1)]
    await suwayomi.sync_library()
    [row] = (await client.get("/api/comics/monitored")).json()
    assert (row["id"], row["status"], row["suwayomi_id"]) == (waiting["id"], "tracking", 1954)


async def test_a_week_names_the_metron_series_of_a_library_series(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    await suwayomi_on(client)
    suwayomi_stub["library"] = [
        shelved(209, "Corpse Knight (2026-)", 6),
        shelved(300, "The Demon (1990-)", 4),
    ]
    await suwayomi.sync_library()
    week = [
        {"series_id": 77, "series": "Corpse Knight", "year": 2026, "publisher": "Image"},
        {"series_id": 78, "series": "The Demon", "year": 2026, "publisher": "DC Comics"},
    ]
    suwayomi.link(week)
    linked = {r["series"]: (r["series_id"], r["publisher"]) for r in db.rows("comics")}
    assert linked == {"Corpse Knight": (77, "Image"), "The Demon": (None, "")}, (
        "another run of the same name is not it"
    )


async def test_the_library_is_not_asked_without_suwayomi(
    client: AsyncClient, suwayomi_stub: dict[str, Any]
) -> None:
    assert await suwayomi.sync_library() == 0
    assert suwayomi_stub["kinds"] == []
