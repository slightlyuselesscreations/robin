"""Radarr and Sonarr: what their calendars put on Home, what their libraries mark, and the add."""

import json
from datetime import date
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import arr, db, reminders, tmdb
from tests.conftest import stub_http

RADARR = "http://radarr.test"
SONARR = "http://sonarr.test"
TODAY = date(2026, 10, 9)


# Titles Settings hides, by `movie-<id>` or `tv-<id>`.
HIDDEN: set[str] = set()


@pytest.fixture(autouse=True)
def shown(monkeypatch: pytest.MonkeyPatch) -> None:
    """What Settings hides is read from TMDB's detail, tested apart. Here only HIDDEN is."""
    HIDDEN.clear()

    async def judge(settings: Any, kind: str, tmdb_id: int) -> bool:
        return f"{kind}-{tmdb_id}" not in HIDDEN

    monkeypatch.setattr(reminders, "shown", judge)


def configure(**extra: Any) -> None:
    db.save_settings(
        {
            "tmdb_token": "eyJ.token",
            "radarr_url": RADARR,
            "radarr_api_key": "radarr-key-123",
            "sonarr_url": SONARR,
            "sonarr_api_key": "sonarr-key-123",
            **extra,
        }
    )


def poster(url: str) -> list[dict[str, str]]:
    return [{"coverType": "fanart", "remoteUrl": "x"}, {"coverType": "poster", "remoteUrl": url}]


MOVIES = [
    {
        "tmdbId": 550,
        "title": "A Film",
        "inCinemas": "2026-10-20T00:00:00Z",
        "digitalRelease": "2026-12-01T00:00:00Z",
        "physicalRelease": "2026-12-15T00:00:00Z",
        "images": poster("https://image.tmdb.org/t/p/original/f.jpg"),
    },
    # Out in cinemas long before the window.
    {"tmdbId": 551, "title": "Old", "inCinemas": "2025-01-01T00:00:00Z", "images": []},
]

EPISODES = [
    {"seasonNumber": 2, "episodeNumber": 1, "airDate": "2026-10-12", "series": {
        "tmdbId": 1399, "title": "A Show", "images": poster("https://art.test/s.jpg")}},
    {"seasonNumber": 2, "episodeNumber": 2, "airDate": "2026-10-19", "series": {
        "tmdbId": 1399, "title": "A Show"}},
    {"seasonNumber": 0, "episodeNumber": 1, "airDate": "2026-10-13", "series": {
        "tmdbId": 1400, "title": "Specials"}},
]  # fmt: skip


def arrs(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    radarr = request.url.host == "radarr.test"
    if path.endswith("/calendar"):
        return httpx.Response(200, json=MOVIES if radarr else EPISODES)
    if path.endswith("/movie") and request.method == "GET":
        return httpx.Response(200, json=[{"tmdbId": 550, "id": 11}])
    if path.endswith("/series") and request.method == "GET":
        return httpx.Response(200, json=[{"tmdbId": 1399, "id": 21}, {"tmdbId": 0, "id": 22}])
    if path.endswith("/qualityprofile"):
        return httpx.Response(200, json=[{"id": 4, "name": "HD"}, {"id": 6, "name": "4K"}])
    if path.endswith("/rootfolder"):
        return httpx.Response(200, json=[{"path": "/movies"}, {"path": "/more"}])
    if path.endswith("/movie/lookup/tmdb"):
        return httpx.Response(200, json={"tmdbId": 77, "title": "New"})
    if path.endswith("/series/lookup"):
        return httpx.Response(200, json=[{"tvdbId": 81189, "title": "New Show"}])
    if request.method == "POST":
        return httpx.Response(201, json={})
    if request.method == "DELETE":
        return httpx.Response(200)
    return httpx.Response(404)


async def test_the_calendar_keeps_cinema_digital_and_premieres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure()
    seen = stub_http(monkeypatch, arrs)
    found = await arr.calendar(db.get_settings(), TODAY)
    assert [(e["library"], e["to"], e["date"]) for e in found] == [
        ("radarr", "title=movie-550", "2026-10-20"),
        ("radarr", "title=movie-550", "2026-12-01"),
        ("sonarr", "title=tv-1399", "2026-10-12"),
    ]
    assert found[0]["image"] == "https://image.tmdb.org/t/p/w342/f.jpg"
    assert found[2]["image"] == "https://art.test/s.jpg"
    assert all(r.headers["X-Api-Key"] for r in seen)
    assert {r.url.params["start"] for r in seen} == {"2026-10-01"}, "nothing before this month"
    # Kept, so Home asks neither again within the hour.
    await arr.calendar(db.get_settings(), TODAY)
    assert len(seen) == 2


async def test_the_library_names_the_app_holding_each_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure()
    stub_http(monkeypatch, arrs)
    assert await arr.library(db.get_settings()) == {"movie-550": "radarr", "tv-1399": "sonarr"}


async def test_a_title_is_removed_from_the_app_holding_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure()
    asked = stub_http(monkeypatch, arrs)
    assert (
        await client.delete("/api/arr/movie/550", params={"delete_files": True})
    ).status_code == 204
    [gone] = [r for r in asked if r.method == "DELETE"]
    assert (gone.url.host, gone.url.path) == ("radarr.test", "/api/v3/movie/11")
    assert gone.url.params["deleteFiles"] == "true"
    assert gone.url.params["addImportExclusion"] == "false"

    # Read again rather than from the cache, so the title loses its colour at once.
    asked.clear()
    await arr.library(db.get_settings())
    assert any(r.url.path == "/api/v3/movie" for r in asked)

    # A title neither holds is answered 404, and nothing is deleted.
    assert (await client.delete("/api/arr/tv/9")).status_code == 404
    assert not any(r.method == "DELETE" for r in asked)


async def test_one_app_failing_leaves_the_other(monkeypatch: pytest.MonkeyPatch) -> None:
    configure()

    def sonarr_down(request: httpx.Request) -> httpx.Response:
        return arrs(request) if request.url.host == "radarr.test" else httpx.Response(500)

    stub_http(monkeypatch, sonarr_down)
    assert await arr.library(db.get_settings()) == {"movie-550": "radarr"}


async def test_a_film_is_added_under_the_first_profile_and_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure()
    seen = stub_http(monkeypatch, arrs)
    await arr.add(db.get_settings(), "radarr", 77)
    [post] = [r for r in seen if r.method == "POST"]
    body = json.loads(post.content)
    assert post.url.path == "/api/v3/movie"
    assert (body["tmdbId"], body["qualityProfileId"], body["rootFolderPath"]) == (77, 4, "/movies")
    assert body["monitored"] is True
    assert body["addOptions"] == {"searchForMovie": True}


async def test_a_show_is_added_by_its_tvdb_id_under_the_saved_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(sonarr_profile_id=6, sonarr_root="/more")

    async def show(settings: Any, tmdb_id: int) -> Any:
        return {"external_ids": {"tvdb_id": 81189}}

    monkeypatch.setattr(tmdb, "show", show)
    seen = stub_http(monkeypatch, arrs)
    await arr.add(db.get_settings(), "sonarr", 1399)
    [lookup] = [r for r in seen if r.url.path.endswith("/lookup")]
    assert lookup.url.params["term"] == "tvdb:81189"
    [post] = [r for r in seen if r.method == "POST"]
    body = json.loads(post.content)
    assert (body["tvdbId"], body["qualityProfileId"], body["rootFolderPath"]) == (81189, 6, "/more")
    assert body["addOptions"]["monitor"] == "all"


@pytest.mark.parametrize(("switch", "added"), [(True, 1), (False, 0)])
async def test_monitoring_adds_only_with_the_switch_on(
    monkeypatch: pytest.MonkeyPatch, switch: bool, added: int
) -> None:
    configure(radarr_add=switch)
    seen = stub_http(monkeypatch, arrs)
    await arr.follow(db.get_settings(), "movie", 77)
    assert len([r for r in seen if r.method == "POST"]) == added


async def test_monitoring_skips_what_the_library_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(radarr_add=True)
    seen = stub_http(monkeypatch, arrs)
    await arr.follow(db.get_settings(), "movie", 550)
    assert not [r for r in seen if r.method == "POST"]


async def test_a_failed_add_never_fails_monitoring(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(radarr_add=True)
    stub_http(monkeypatch, lambda request: httpx.Response(500))
    await arr.follow(db.get_settings(), "movie", 77)


def test_neither_is_ready_without_tmdb() -> None:
    # A blank secret is not written, so this leaves TMDB unset.
    configure(tmdb_token="")
    settings = db.get_settings()
    assert not (settings.tmdb_ready or settings.radarr_ready or settings.sonarr_ready)


LIBRARY = {
    "radarr.test": [
        {"tmdbId": 550, "id": 1, "status": "announced"},
        {"tmdbId": 551, "id": 2, "status": "inCinemas"},
        {"tmdbId": 552, "id": 3, "status": "released"},
    ],
    "sonarr.test": [
        {"tmdbId": 1399, "id": 4, "status": "continuing"},
        {"tmdbId": 1400, "id": 5, "status": "ended"},
        {"tmdbId": 1401, "id": 6, "status": "continuing"},
    ],
}

# Titles TMDB has no release dated for: a film with none in the region, a show with no season
# premiere announced.
UNDATED: set[int] = set()


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Both libraries as LIBRARY has them, and TMDB dating every title but film 551 and show
    1401, or what UNDATED names."""
    configure()
    stub_http(
        monkeypatch,
        lambda request: httpx.Response(200, json=LIBRARY[str(request.url.host)]),
    )
    UNDATED.clear()
    UNDATED.update({551, 1401})
    asked: list[tuple[str, int]] = []

    async def title(settings: Any, kind: str, tmdb_id: int) -> dict[str, Any]:
        asked.append((kind, tmdb_id))
        dated = tmdb_id not in UNDATED
        release = {"type": "digital", "date": "2026-12-01", "platform": None}
        return {
            "title": f"{kind} {tmdb_id}",
            "poster": None,
            "date": "2026-12-01",
            "platform": None,
            "releases": [release] if dated else [],
            "open_releases": ["digital"],
            "monitorable": True,
            "next_episode": {"episode": 1, "date": "2026-12-01"} if dated else None,
        }

    monkeypatch.setattr(tmdb, "title", title)
    return asked


def monitored() -> set[str]:
    return {f"{r['kind']}-{r['tmdb_id']}" for r in db.rows("reminders")}


async def test_what_the_libraries_hold_with_a_release_ahead_is_monitored(
    held: list[tuple[str, int]],
) -> None:
    assert await arr.monitor_library() == 2
    # Released and ended titles are never read from TMDB. Film 551 has no release left here,
    # and show 1401 no season announced.
    assert set(held) == {("movie", 550), ("movie", 551), ("tv", 1399), ("tv", 1401)}
    assert monitored() == {"movie-550", "tv-1399"}


async def test_what_settings_hides_is_never_monitored_from_a_library(
    held: list[tuple[str, int]],
) -> None:
    HIDDEN.add("movie-550")
    assert await arr.monitor_library() == 1
    assert monitored() == {"tv-1399"}


async def test_a_show_waits_for_its_next_season_to_be_dated(held: list[tuple[str, int]]) -> None:
    await arr.monitor_library()
    UNDATED.discard(1401)
    assert await arr.monitor_library() == 1
    assert "tv-1401" in monitored()

    # The premiere airs and no next one is dated: the show is let go until one is.
    UNDATED.add(1401)
    row = next(r for r in db.rows("reminders") if r["tmdb_id"] == 1401)
    db.update_reminder(int(row["id"]), None, None, row["title"], row["poster"])
    await arr.monitor_library()
    assert "tv-1401" not in monitored()
    UNDATED.discard(1401)
    assert await arr.monitor_library() == 1
    assert "tv-1401" in monitored()


async def test_a_title_stopped_in_robin_stays_stopped(held: list[tuple[str, int]]) -> None:
    await arr.monitor_library()
    for reminder in db.rows("reminders"):
        db.delete_row("reminders", int(reminder["id"]))
    assert await arr.monitor_library() == 0
    assert monitored() == set()


async def test_a_title_with_nothing_dated_is_tried_again(held: list[tuple[str, int]]) -> None:
    await arr.monitor_library()
    held.clear()
    await arr.monitor_library()
    assert held == [("movie", 551), ("tv", 1401)]


async def test_nothing_is_monitored_without_either_app(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_http(monkeypatch, lambda request: pytest.fail(f"asked {request.url}"))
    assert await arr.monitor_library() == 0
