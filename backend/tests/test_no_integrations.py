"""Robin with every source and integration unset starts, answers and asks nothing outside.

Any request that leaves the process fails the test, so a feature that quietly needs IGDB,
TMDB, Hardcover, Comic Vine, Prowlarr, qBittorrent, Radarr, Sonarr, Suwayomi or a notification
destination shows up here.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, notify
from robin.main import CHECKS, FREQUENT
from tests.conftest import notify_to

GAME = {"igdb_id": 1877, "name": "Cyberpunk 2077", "first_release_date": None}


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected outbound request to {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


async def test_monitoring_lists_and_stops_with_nothing_configured(client: AsyncClient) -> None:
    db.upsert_games([GAME])

    created = await client.post("/api/monitored", json={"igdb_id": 1877})
    assert created.status_code == 201
    assert created.json()["status"] == "monitored"

    listed = (await client.get("/api/monitored")).json()
    assert [r["game_name"] for r in listed] == ["Cyberpunk 2077"]

    assert (await client.delete(f"/api/monitored/{created.json()['id']}")).status_code == 204
    assert (await client.get("/api/monitored")).json() == []


async def test_every_background_check_is_a_no_op(client: AsyncClient) -> None:
    db.upsert_games([GAME])
    await client.post("/api/monitored", json={"igdb_id": 1877})

    for check in (*CHECKS, *FREQUENT):
        assert await check() == 0, check.__name__


async def test_every_check_stays_quiet_with_a_destination_and_no_source(
    client: AsyncClient,
) -> None:
    """A destination is not enough, the category's source has to be set too."""
    await client.put("/api/settings", json=notify_to())
    settings = db.get_settings()
    for category in ("games", "comics", "screens", "books"):
        assert settings.notices(category) is None, category
    for check in (*CHECKS, *FREQUENT):
        assert await check() == 0, check.__name__


@pytest.mark.parametrize(
    "path",
    [
        "/api/games/discover",
        "/api/games/search?q=cyberpunk",
        "/api/prowlarr/indexers",
        "/api/arr/radarr/profiles",
        "/api/arr/radarr/folders",
        "/api/arr/sonarr/profiles",
        "/api/arr/sonarr/folders",
        "/api/screens/movie/discover",
        "/api/screens/all/discover",
        "/api/screens/movie/550",
        "/api/books/discover",
        "/api/books/1",
        "/api/books/genres",
        "/api/comics/issue/1",
        "/api/comics/search?q=raven",
        "/api/comics/latest",
        "/api/comics/issues",
        "/api/comics/comic/1",
        "/api/favourites/search?category=comics&q=raven",
        "/api/favourites/comics/series/100",
        "/api/favourites/search?category=games&q=fromsoftware",
        "/api/favourites/search?category=screens&q=netflix",
        "/api/favourites/search?category=books&q=rowling",
        "/api/favourites/games/company/70",
        "/api/favourites/screens/network/213",
        "/api/favourites/books/author/7",
    ],
)
async def test_an_unset_source_answers_409_and_asks_nothing(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status_code == 409, resp.text
    assert "Settings" in resp.json()["detail"]


async def test_the_settings_say_what_is_shown(client: AsyncClient) -> None:
    body = (await client.get("/api/settings")).json()
    for flag in (
        "igdb_ready",
        "tmdb_ready",
        "hardcover_ready",
        "comics_ready",
        "prowlarr_ready",
        "qbittorrent_ready",
        "radarr_ready",
        "sonarr_ready",
        "suwayomi_ready",
        "notify_ready",
    ):
        assert body[flag] is False, flag
    assert (await client.get("/api/qbittorrent/downloads")).json() == []
    assert (await client.get("/api/qbittorrent/categories")).json() == []
    assert (await client.get("/api/arr/calendar")).json() == []
    assert (await client.get("/api/arr/library")).json() == {}
    added = await client.post("/api/arr/sonarr", json={"tmdb_id": 1})
    assert added.status_code == 409
    assert (await client.delete("/api/arr/movie/1")).status_code == 409
    health = (await client.get("/api/settings/health")).json()
    assert health["radarr"]["state"] == health["sonarr"]["state"] == "unset"
    assert (await client.get("/api/settings/health")).json()["igdb"]["state"] == "unset"


async def test_a_game_is_announced_without_prowlarr(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put(
        "/api/settings",
        json={
            **notify_to(),
            # IGDB is the data source of the category, not an integration.
            "twitch_client_id": "client",
            "twitch_client_secret": "secret",
            # The day before at midnight, so the notice is due at any hour the test runs.
            "games_schedule": [{"days": 1, "hour": 0}],
        },
    )
    tomorrow = int((datetime.now(UTC) + timedelta(days=1)).timestamp())
    db.upsert_games([{**GAME, "first_release_date": tomorrow}])
    await client.post("/api/monitored", json={"igdb_id": 1877})

    sent: list[dict[str, Any]] = []

    async def capture(settings: Any, channel: Any, **kwargs: Any) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(notify, "send", capture)

    assert await notify.notify_upcoming_releases() == 1
    assert sent[0]["title"] == "Cyberpunk 2077 is out tomorrow"
