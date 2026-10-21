"""Monitoring a game, the grab that follows once it is out, and its download.

The regex itself is covered in test_filters. What matters here is the wiring: a monitored game
is matched against what Prowlarr lists, checked against PreDB or the groups outside the scene,
grabbed once ever into qBittorrent or held for the user, and followed until it is downloaded.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from robin import db, grabs, igdb, notify, predb, prowlarr, qbittorrent, upstream
from tests.conftest import notify_to, stub_http

# Out on the first of this month: out already, so it is searched for, and still monitored.
RELEASED = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
DAY = RELEASED.date().isoformat()

GAME = {
    "igdb_id": 1877,
    "name": "Cyberpunk 2077",
    "slug": "cyberpunk-2077",
    "summary": "Night City.",
    "first_release_date": int(RELEASED.timestamp()),
    "cover_image_id": "co1234",
    "artwork_image_id": "ar1234",
    "platforms": ["PC"],
    "genres": ["RPG"],
    "rating": 80.0,
    "url": "https://www.igdb.com/games/cyberpunk-2077",
    "extra": {"v": db.EXTRA_VERSION, "developers": ["CD Projekt Red"]},
}


def release(
    title: str,
    seeders: int = 10,
    flags: tuple[str, ...] = ("freeleech",),
    published: str | None = None,
) -> dict[str, Any]:
    """A release as Prowlarr returns it."""
    return {
        "guid": title,
        "indexerId": 3,
        "title": title,
        "seeders": seeders,
        "indexerFlags": list(flags),
        "publishDate": published,
    }


@pytest.fixture(autouse=True)
def cached_game() -> None:
    db.upsert_games([GAME])


@pytest.fixture
def indexers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Prowlarr and qBittorrent set. Prowlarr answers every query with `releases`, PreDB with
    `pres` by release name, or raises `predb_down`. qBittorrent records every grab, holds
    `held`, and every notice is kept."""
    db.save_settings(
        {
            "prowlarr_url": "http://prowlarr.test",
            "prowlarr_api_key": "key",
            "qbittorrent_url": "http://qbittorrent.test",
        }
    )
    seen: dict[str, Any] = {
        "releases": [],
        "pres": {},
        "predb_down": None,
        "searched": [],
        "asked": [],
        "added": [],
        "held": {},
        "told": [],
    }

    async def raw(term: str) -> list[dict[str, Any]]:
        seen["searched"].append(term)
        return list(seen["releases"])

    async def pres(term: str, group: str) -> dict[str, tuple[str, int]]:
        seen["asked"].append((term, group))
        if seen["predb_down"]:
            raise seen["predb_down"]
        # A bare status is a release in GAMES.
        return {
            predb.key(name): pre if isinstance(pre, tuple) else ("GAMES", pre)
            for name, pre in seen["pres"].items()
            if name.lower().endswith(f"-{group.lower()}")
        }

    async def torrent(release: dict[str, Any]) -> bytes:
        return f"torrent of {release['title']}".encode()

    async def add(settings: Any, torrent: bytes, *, category: str, request_id: int) -> None:
        seen["added"].append((torrent.decode().removeprefix("torrent of "), category))

    async def held(settings: Any) -> dict[int, dict[str, Any]]:
        return dict(seen["held"])

    async def tell(settings: Any, channel: Any, **notice: Any) -> None:
        seen["told"].append(notice["title"])

    monkeypatch.setattr(prowlarr, "raw", raw)
    monkeypatch.setattr(predb, "pres", pres)
    monkeypatch.setattr(prowlarr, "torrent", torrent)
    monkeypatch.setattr(qbittorrent, "add", add)
    monkeypatch.setattr(qbittorrent, "grabs", held)
    monkeypatch.setattr(notify, "send", tell)
    return seen


@pytest.fixture
def notices(client: AsyncClient) -> None:
    """Game notices on, so what Robin tells the user can be read."""
    db.save_settings(
        {
            **notify_to(),
            "twitch_client_id": "client",
            "twitch_client_secret": "secret",
        }
    )


def grabbed(indexers: dict[str, Any]) -> list[str]:
    return [title for title, _ in indexers["added"]]


async def test_monitoring_records_the_game(client: AsyncClient) -> None:
    resp = await client.post("/api/monitored", json={"igdb_id": 1877})
    assert resp.status_code == 201
    assert resp.json()["status"] == "monitored"
    assert resp.json()["game_name"] == "Cyberpunk 2077"

    listed = db.list_requests()
    assert [(r["game_name"], r["status"]) for r in listed] == [("Cyberpunk 2077", "monitored")]


async def test_a_second_request_for_the_same_game_is_refused(client: AsyncClient) -> None:
    await client.post("/api/monitored", json={"igdb_id": 1877})
    again = await client.post("/api/monitored", json={"igdb_id": 1877})
    assert again.status_code == 409
    assert len(db.list_requests()) == 1


async def test_unknown_game_is_a_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def nothing(_: int) -> None:
        return None

    monkeypatch.setattr(igdb, "game", nothing)
    resp = await client.post("/api/monitored", json={"igdb_id": 999999})
    assert resp.status_code == 404


async def test_request_status_shows_up_on_game_detail(client: AsyncClient) -> None:
    await client.post("/api/monitored", json={"igdb_id": 1877})
    detail = (await client.get("/api/games/1877")).json()
    assert detail["request_status"] == "monitored"


async def test_removing_a_monitored_game_forgets_it(client: AsyncClient) -> None:
    created = (await client.post("/api/monitored", json={"igdb_id": 1877})).json()
    assert (await client.delete(f"/api/monitored/{created['id']}")).status_code == 204
    assert db.list_requests() == []


async def test_clearing_found_hides_grabbed_games_only(client: AsyncClient) -> None:
    for igdb_id in (1877, 1020):
        db.upsert_games([{"igdb_id": igdb_id, "name": f"Game {igdb_id}", "cached_at": ""}])
        db.create_request(igdb_id)
    found = next(r["id"] for r in db.list_requests() if r["igdb_id"] == 1877)
    assert db.claim_grab(found, "Game.1877-RUNE")

    assert (await client.post("/api/monitored/clear-found")).status_code == 204
    cleared = {r["igdb_id"] for r in db.list_requests() if r["cleared_at"]}
    assert cleared == {1877}
    assert len(db.list_requests()) == 2, "the rows stay, so the game still reads as found"


async def test_a_notified_game_prowlarr_still_searches_for_is_tracking(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    db.upsert_games([{**GAME, "igdb_id": 1020, "name": "Console Game", "platforms": ["PS5"]}])
    for igdb_id in (1877, 1020):
        db.mark_release_notified(db.create_request(igdb_id), "2020-12-10|0", done=True)

    def statuses(listed: list[dict[str, Any]]) -> dict[int, str]:
        return {r["igdb_id"]: r["status"] for r in listed}

    tracked = {1877: "tracking", 1020: "notified"}
    assert statuses((await client.get("/api/monitored")).json()) == tracked
    assert db.request_status_map([1877, 1020]) == tracked
    assert {r["status"] for r in db.waiting_requests()} == {"notified"}, "stored as notified"

    assert (await client.post("/api/monitored/clear-found")).status_code == 204
    cleared = {r["igdb_id"] for r in db.list_requests() if r["cleared_at"]}
    assert cleared == {1020}, "a game still tracked is not cleared"

    db.save_settings({"prowlarr_url": ""})
    assert db.request_status_map([1877])[1877] == "notified", "nothing searches without Prowlarr"


def test_a_cleared_game_comes_back_once_it_needs_the_user() -> None:
    db.upsert_games([{"igdb_id": 1877, "name": "Game", "cached_at": ""}])
    db.create_request(1877)
    game = db.list_requests()[0]["id"]

    def cleared() -> bool:
        return bool(db.list_requests()[0]["cleared_at"])

    db.mark_release_notified(game, "2026-10-01|0", done=True)
    db.clear_found("requests")
    db.mark_release_notified(game, "2026-10-01|0", done=True)
    assert cleared(), "a notice for the same date changes nothing"

    db.mark_release_notified(game, "2026-11-01|0", done=False)
    assert not cleared(), "a moved date waits again"

    for comes_back in (
        lambda: db.put_in_review(game, {"title": "Game-GROUP"}),
        lambda: db.set_request_error(game, "refused"),
        lambda: db.claim_grab(game, "Game-GROUP"),
    ):
        db.mark_release_notified(game, "2026-11-01|0", done=True)
        db.clear_found("requests")
        assert cleared()
        comes_back()
        assert not cleared()


async def test_a_release_predb_vouches_for_is_grabbed_as_the_game_is_monitored(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [
        release("Cyberpunk.2077.Update.v2.1-RUNE", published=f"{DAY}T02:00:00Z"),
        release("Cyberpunk.2077.REPACK-RUNE", published=f"{DAY}T03:00:00Z"),
        release("Cyberpunk 2077-CODEX", published=f"{DAY}T04:00:00Z"),
        release("Cyberpunk.2077-RUNE", published=f"{DAY}T05:00:00Z"),
    ]
    indexers["pres"] = {"Cyberpunk.2077-CODEX": 0, "Cyberpunk.2077-RUNE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})

    assert indexers["searched"] == ["Cyberpunk 2077"]
    # The RUNE update and repack are excluded before PreDB is asked, and CODEX is listed first.
    assert indexers["asked"] == [("Cyberpunk 2077", "CODEX")]
    assert indexers["added"] == [("Cyberpunk 2077-CODEX", "games")], "the first listed counts"
    stored = db.list_requests()[0]
    assert (stored["status"], stored["matched_release"]) == ("matched", "Cyberpunk 2077-CODEX")


async def test_a_game_is_grabbed_once_ever(client: AsyncClient, indexers: dict[str, Any]) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0, "Cyberpunk.2077-TENOKE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})
    indexers["releases"] = [release("Cyberpunk.2077-TENOKE")]

    assert await grabs.rss_sync() == 0
    assert grabbed(indexers) == ["Cyberpunk.2077-RUNE"]
    assert indexers["searched"] == ["Cyberpunk 2077"], "nothing waits, so nothing is synced"


async def test_a_game_on_consoles_alone_is_never_grabbed(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    db.upsert_games([{**GAME, "platforms": ["PS5", "Switch"]}])
    indexers["releases"] = [release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})

    assert await grabs.rss_sync() == 0
    assert grabbed(indexers) == []
    assert indexers["searched"] == []


async def test_the_sync_grabs_what_lands_later(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    await client.post("/api/monitored", json={"igdb_id": 1877})
    assert grabbed(indexers) == []

    indexers["releases"] = [release("Starfield-RUNE"), release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    assert await grabs.rss_sync() == 1
    assert indexers["searched"][-1] == "", "the sync reads what was listed lately"
    assert grabbed(indexers) == ["Cyberpunk.2077-RUNE"]


async def test_a_nuked_release_is_passed_over_for_its_proper(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-TENOKE")]
    indexers["pres"] = {"Cyberpunk.2077-TENOKE": 1}
    await client.post("/api/monitored", json={"igdb_id": 1877})
    entry = db.list_requests()[0]
    assert (entry["status"], entry["review_release"]) == ("monitored", None)

    indexers["releases"].append(release("Cyberpunk.2077.PROPER-RUNE"))
    indexers["pres"]["Cyberpunk.2077.PROPER-RUNE"] = 0
    assert await grabs.rss_sync() == 1
    assert grabbed(indexers) == ["Cyberpunk.2077.PROPER-RUNE"]


async def test_an_update_predb_lists_as_one_is_passed_over(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    """A bare version slips past the exclusions. PreDB files it under GAMES-DOX."""
    indexers["releases"] = [release("Cyberpunk.2077.v1.31-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077.v1.31-RUNE": ("GAMES-DOX", 0)}
    await client.post("/api/monitored", json={"igdb_id": 1877})
    entry = db.list_requests()[0]
    assert (entry["status"], entry["review_release"]) == ("monitored", None)


async def test_a_group_outside_the_scene_needs_no_predb(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [release("Cyberpunk 2077-voices38"), release("Cyberpunk.2077-rlsgrp")]
    indexers["predb_down"] = AssertionError("PreDB must not be asked")
    await client.post("/api/monitored", json={"igdb_id": 1877})

    assert grabbed(indexers) == ["Cyberpunk 2077-voices38"]
    assert indexers["asked"] == []


async def test_the_groups_outside_the_scene_are_a_setting(client: AsyncClient) -> None:
    assert db.get_settings().p2p_groups == ["GOG", "voices38"]
    resp = await client.put("/api/settings", json={"p2p_groups": ["GOG", "KaOs"]})
    assert resp.json()["p2p_groups"] == ["GOG", "KaOs"]
    bad = await client.put("/api/settings", json={"p2p_groups": ["two words"]})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "down",
    [None, upstream.UpstreamError("Could not reach PreDB: timed out")],
    ids=["unknown to predb", "predb unreachable"],
)
async def test_a_release_predb_cannot_vouch_for_waits_for_the_user(
    client: AsyncClient, indexers: dict[str, Any], notices: None, down: Exception | None
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-NEWGRP")]
    indexers["predb_down"] = down
    await client.post("/api/monitored", json={"igdb_id": 1877})

    assert grabbed(indexers) == []
    listed = (await client.get("/api/monitored")).json()[0]
    assert (listed["status"], listed["review_release"]) == ("monitored", "Cyberpunk.2077-NEWGRP")
    assert "review_json" not in listed, "the held release carries Prowlarr's key"
    assert indexers["told"] == ["Confirm a release for Cyberpunk 2077"]

    assert await grabs.rss_sync() == 0
    assert indexers["told"] == ["Confirm a release for Cyberpunk 2077"], "told once"


async def test_a_confirmed_release_is_grabbed(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-NEWGRP")]
    created = (await client.post("/api/monitored", json={"igdb_id": 1877})).json()

    resp = await client.post(f"/api/monitored/{created['id']}/confirm")
    assert resp.status_code == 200
    assert (resp.json()["status"], resp.json()["review_release"]) == ("matched", None)
    assert grabbed(indexers) == ["Cyberpunk.2077-NEWGRP"]
    assert (await client.post(f"/api/monitored/{created['id']}/confirm")).status_code == 409


async def test_a_rejected_release_is_never_offered_again(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-NEWGRP")]
    created = (await client.post("/api/monitored", json={"igdb_id": 1877})).json()

    resp = await client.post(f"/api/monitored/{created['id']}/reject")
    assert (resp.json()["status"], resp.json()["review_release"]) == ("monitored", None)
    assert await grabs.rss_sync() == 0
    assert db.list_requests()[0]["review_release"] is None, "not held a second time"

    indexers["releases"].append(release("Cyberpunk.2077-OTHER"))
    await grabs.rss_sync()
    assert db.list_requests()[0]["review_release"] == "Cyberpunk.2077-OTHER"

    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    indexers["releases"].append(release("Cyberpunk.2077-RUNE"))
    assert await grabs.rss_sync() == 1, "a clean release still goes through while one is held"
    assert db.rejected(created["id"]) == set(), "forgotten once the game is found"


async def test_freeleech_only_is_a_setting(client: AsyncClient, indexers: dict[str, Any]) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-RUNE", flags=())]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})
    assert grabbed(indexers) == [], "freeleech only, by default"

    db.save_settings({"freeleech_only": False})
    assert await grabs.rss_sync() == 1


async def test_a_release_listed_before_the_game_is_out_is_grabbed(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    """Cyberpunk 2077 was out on 10 December 2020. One listed a week before is still grabbed."""
    await client.post("/api/monitored", json={"igdb_id": 1877})
    indexers["releases"] = [release("Cyberpunk.2077-RUNE", published="2020-12-03T00:00:00Z")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    assert await grabs.rss_sync() == 1
    assert grabbed(indexers) == ["Cyberpunk.2077-RUNE"]


async def test_a_game_not_out_is_not_searched_but_is_synced(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    db.upsert_games(
        [
            {"igdb_id": 1, "name": "Someday", "first_release_date": None, "platforms": ["PC"]},
            {
                "igdb_id": 2,
                "name": "Next Year",
                "first_release_date": 4102444800,
                "platforms": ["PC"],
            },
        ]
    )
    for igdb_id in (1, 2):
        await client.post("/api/monitored", json={"igdb_id": igdb_id})
    assert indexers["searched"] == []

    indexers["releases"] = [release("Someday-TENOKE")]
    indexers["pres"] = {"Someday-TENOKE": 0}
    assert await grabs.rss_sync() == 1
    assert grabbed(indexers) == ["Someday-TENOKE"]


async def test_a_failed_grab_waits_for_the_next_sync(
    client: AsyncClient, indexers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(*_: Any, **__: Any) -> None:
        raise upstream.UpstreamError("qBittorrent refused the torrent")

    monkeypatch.setattr(qbittorrent, "add", refused)
    indexers["releases"] = [release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})

    stored = db.list_requests()[0]
    assert (stored["status"], stored["matched_release"]) == ("monitored", None)
    assert "refused the torrent" in stored["error"]

    async def fine(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(qbittorrent, "add", fine)
    assert await grabs.rss_sync() == 1
    assert db.list_requests()[0]["error"] is None


async def test_a_grab_is_followed_to_downloaded_and_the_user_told(
    client: AsyncClient, indexers: dict[str, Any], notices: None
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    db.save_settings({"qbittorrent_category": "pc-games"})
    created = await client.post("/api/monitored", json={"igdb_id": 1877})
    request_id = created.json()["id"]
    assert indexers["added"] == [("Cyberpunk.2077-RUNE", "pc-games")]

    listed = (await client.get("/api/monitored")).json()[0]
    assert listed["status"] == "matched", "found as it is grabbed, whatever the download does"
    assert listed["download"] is None, "added, not seen in qBittorrent yet"

    indexers["held"] = {request_id: {"state": "downloading", "progress": 0.45, "eta": 600}}
    listed = (await client.get("/api/monitored")).json()[0]
    assert listed["download"]["progress"] == 0.45
    assert listed["downloaded_at"] is None

    indexers["held"] = {request_id: {"state": "uploading", "progress": 1.0, "eta": 0}}
    assert await grabs.track_downloads() == 1
    assert await grabs.track_downloads() == 0, "told once"
    assert indexers["told"] == ["Cyberpunk 2077 is downloading", "Cyberpunk 2077 is downloaded"]
    indexers["held"] = {}
    listed = (await client.get("/api/monitored")).json()[0]
    assert listed["downloaded_at"], "still downloaded once the torrent is gone"


def test_only_one_pass_claims_a_game() -> None:
    request_id = db.create_request(1877)
    assert db.claim_grab(request_id, "A-RUNE")
    assert not db.claim_grab(request_id, "B-RUNE")


async def test_without_qbittorrent_prowlarr_downloads_and_nothing_is_followed(
    client: AsyncClient,
    indexers: dict[str, Any],
    notices: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[str] = []

    async def grab(found: dict[str, Any]) -> None:
        pushed.append(found["title"])

    async def never(settings: Any) -> dict[int, dict[str, Any]]:
        raise AssertionError("qBittorrent must not be asked")

    monkeypatch.setattr(prowlarr, "grab", grab)
    monkeypatch.setattr(qbittorrent, "grabs", never)
    db.save_settings({"qbittorrent_url": ""})
    assert db.get_settings().prowlarr_ready
    indexers["releases"] = [release("Cyberpunk.2077-RUNE")]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}

    await client.post("/api/monitored", json={"igdb_id": 1877})
    assert (pushed, indexers["added"]) == (["Cyberpunk.2077-RUNE"], [])
    assert indexers["told"] == ["Cyberpunk 2077 is downloading"]
    assert (await client.get("/api/monitored")).json()[0]["download"] is None
    assert await grabs.track_downloads() == 0


async def test_a_held_release_is_found_again_before_prowlarr_downloads_it(
    client: AsyncClient, indexers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    pushed: list[str] = []

    async def grab(found: dict[str, Any]) -> None:
        pushed.append(found["title"])

    monkeypatch.setattr(prowlarr, "grab", grab)
    db.save_settings({"qbittorrent_url": ""})
    indexers["releases"] = [release("Cyberpunk.2077-NEWGRP")]
    created = (await client.post("/api/monitored", json={"igdb_id": 1877})).json()
    searched = len(indexers["searched"])

    assert (await client.post(f"/api/monitored/{created['id']}/confirm")).status_code == 200
    assert len(indexers["searched"]) == searched + 1, "searched again, Prowlarr forgets"
    assert pushed == ["Cyberpunk.2077-NEWGRP"]


async def test_predb_is_read_by_section_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"release": "Lost.Soul.Aside.PROPER-RUNE", "section": "GAMES", "status": 0},
        {"release": "Lost.Soul.Aside-TENOKE", "section": "GAMES", "status": 1},
        {"release": "Lost.Soul.Aside.Update.v1.104-RUNE", "section": "GAMES-DOX", "status": 0},
        {"release": "Static_Dread_The_Submarine-Razor1911", "section": "GAMES", "status": 0},
    ]
    seen = stub_http(
        monkeypatch, lambda _: httpx.Response(200, json={"status": "success", "data": rows})
    )
    known = await predb.pres("Lost Soul Aside", "RUNE")
    assert (seen[0].url.params["q"], seen[0].url.params["group"]) == ("Lost Soul Aside", "RUNE")
    assert predb.verdict("Lost.Soul.Aside.PROPER-RUNE", known) == "clean"
    assert predb.verdict("Lost Soul Aside-TENOKE", known) == "bad"
    assert predb.verdict("Lost.Soul.Aside.Update.v1.104-RUNE", known) == "bad"
    assert predb.verdict("Lost.Soul.Aside-NEWGRP", known) == "unknown"
    assert predb.verdict("Static Dread The Submarine-Razor1911", known) == "clean"


async def test_a_magnet_redirect_is_followed_and_a_file_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/1/download":
            return httpx.Response(301, headers={"location": "magnet:?xt=urn:btih:abc"})
        return httpx.Response(200, content=b"d8:announce")

    stub_http(monkeypatch, answer)
    magnet = {"title": "A-RUNE", "downloadUrl": "http://prowlarr.test/1/download?apikey=k"}
    assert await prowlarr.torrent(magnet) == "magnet:?xt=urn:btih:abc"
    file = {"title": "A-RUNE", "downloadUrl": "http://prowlarr.test/2/download?apikey=k"}
    assert await prowlarr.torrent(file) == b"d8:announce"


async def test_qbittorrent_finds_each_grab_by_its_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    db.save_settings({"qbittorrent_url": "http://qbittorrent.test"})
    seen = stub_http(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            json=[
                {"tags": "robin, robin-12", "state": "downloading", "progress": 0.5, "eta": 9},
                {"tags": "robin", "state": "uploading", "progress": 1, "eta": 0},
            ],
        ),
    )
    found = await qbittorrent.grabs(db.get_settings())
    assert found == {12: {"state": "downloading", "progress": 0.5, "eta": 9}}
    assert seen[0].url.params["tag"] == "robin"


async def test_the_logs_say_why_a_release_was_passed_over(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    db.save_settings({"prowlarr_api_key": "a-very-secret-key"})
    indexers["releases"] = [release("Cyberpunk.2077-RUNE", flags=())]
    after = max([0, *(line["id"] for line in (await client.get("/api/logs")).json())])
    await client.post("/api/monitored", json={"igdb_id": 1877})
    db.get_settings()
    upstream.log.warning("sent a-very-secret-key")

    lines = (await client.get("/api/logs", params={"after": after})).json()
    said = [line["message"] for line in lines]
    assert "grabs: skipped Cyberpunk.2077-RUNE: not freeleech" in said
    assert "sent [redacted]" in said
    assert all(line["id"] > after for line in lines)


async def test_turning_freeleech_only_off_searches_again(
    client: AsyncClient, indexers: dict[str, Any]
) -> None:
    indexers["releases"] = [release("Cyberpunk.2077-RUNE", flags=())]
    indexers["pres"] = {"Cyberpunk.2077-RUNE": 0}
    await client.post("/api/monitored", json={"igdb_id": 1877})
    assert grabbed(indexers) == []

    await client.put("/api/settings", json={"freeleech_only": True})
    assert grabbed(indexers) == [], "nothing changed, nothing searched"
    await client.put("/api/settings", json={"freeleech_only": False})
    assert grabbed(indexers) == ["Cyberpunk.2077-RUNE"]


def test_a_game_out_is_monitored_only_to_be_grabbed() -> None:
    old = {**GAME, "first_release_date": int(datetime(2024, 1, 1, tzinfo=UTC).timestamp())}
    assert not igdb.monitorable(db.get_settings(), old)

    db.save_settings({"prowlarr_url": "http://prowlarr.test", "prowlarr_api_key": "key"})
    settings = db.get_settings()
    assert igdb.monitorable(settings, old)
    assert not igdb.monitorable(settings, {**old, "platforms": ["PS5"]}), "never grabbed"
    assert igdb.monitorable(settings, {**GAME, "platforms": ["PS5"]}), "coming"
