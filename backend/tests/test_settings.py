import httpx
import pytest
from httpx import AsyncClient

from robin import db
from robin.routes.settings import Health
from tests.conftest import stub_http


async def test_defaults_are_empty_and_not_ready(client: AsyncClient) -> None:
    body = (await client.get("/api/settings")).json()
    assert body["has_prowlarr_api_key"] is False
    assert body["has_twitch_client_secret"] is False
    assert body["igdb_ready"] is False
    assert body["prowlarr_ready"] is False
    assert (body["qbittorrent_category"], body["freeleech_only"]) == ("games", True)


async def test_secrets_persist_but_never_come_back(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/settings",
        json={
            "prowlarr_url": "http://prowlarr.local:9696/",
            "prowlarr_api_key": "super-secret-token-value",
            "qbittorrent_url": "http://qbittorrent.local:8080",
            "twitch_client_id": "client-id-123",
            "twitch_client_secret": "client-secret-456789",
            "prowlarr_indexer_ids": [3, 7],
        },
    )
    body = resp.json()

    assert body["prowlarr_url"] == "http://prowlarr.local:9696"
    assert body["twitch_client_id"] == "client-id-123"
    assert body["has_prowlarr_api_key"] is True
    assert body["has_twitch_client_secret"] is True
    assert body["prowlarr_indexer_ids"] == [3, 7]
    assert body["igdb_ready"] and body["prowlarr_ready"]

    raw = resp.text
    assert "super-secret-token-value" not in raw
    assert "client-secret-456789" not in raw

    stored = db.get_settings()
    assert stored.prowlarr_api_key == "super-secret-token-value"
    assert stored.twitch_client_secret == "client-secret-456789"


async def test_blank_secret_does_not_wipe_the_stored_one(client: AsyncClient) -> None:
    await client.put("/api/settings", json={"prowlarr_api_key": "keep-me-around"})
    await client.put("/api/settings", json={"prowlarr_url": "http://elsewhere:9696"})
    assert db.get_settings().prowlarr_api_key == "keep-me-around"

    await client.put("/api/settings", json={"prowlarr_api_key": ""})
    assert db.get_settings().prowlarr_api_key == "keep-me-around"


def test_a_new_column_is_added_to_an_existing_database() -> None:
    """The settings table gains columns over time, without a rebuild."""
    with db.conn() as c:
        c.execute("ALTER TABLE settings DROP COLUMN comics_notify")
        assert "hide_online_only" not in {
            r["name"] for r in c.execute("PRAGMA table_info(settings)")
        }

    db.init_db()

    with db.conn() as c:
        columns = {r["name"] for r in c.execute("PRAGMA table_info(settings)")}
    assert "comics_notify" in columns
    assert db.get_settings().comics_notify is True


async def test_where_a_grab_goes_and_freeleech_are_settings(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/settings", json={"qbittorrent_category": "pc-games", "freeleech_only": False}
    )
    assert (resp.json()["qbittorrent_category"], resp.json()["freeleech_only"]) == (
        "pc-games",
        False,
    )
    assert (await client.put("/api/settings", json={"qbittorrent_category": ""})).status_code == 422


async def test_the_home_layout_is_kept(client: AsyncClient) -> None:
    layout = [
        {"id": "calendar", "hidden": False, "beside": False, "size": 62.5},
        {"id": "health", "hidden": True, "beside": True, "size": 37.5},
    ]
    await client.put("/api/settings", json={"home_layout": layout})
    assert (await client.get("/api/settings")).json()["home_layout"] == layout


async def test_the_theme_is_kept_and_only_a_known_one(client: AsyncClient) -> None:
    body = (await client.get("/api/settings")).json()
    assert (body["theme"], body["scheme"]) == ("european", "dark")
    await client.put("/api/settings", json={"theme": "pink", "scheme": "system"})
    body = (await client.get("/api/settings")).json()
    assert (body["theme"], body["scheme"]) == ("pink", "system")
    assert (await client.put("/api/settings", json={"theme": "scarlet"})).status_code == 422


async def test_a_layout_saved_before_rows_leaves_them_to_the_defaults(
    client: AsyncClient,
) -> None:
    await client.put("/api/settings", json={"home_layout": [{"id": "next", "hidden": False}]})
    [panel] = (await client.get("/api/settings")).json()["home_layout"]
    assert (panel["beside"], panel["size"]) == (None, None)

    bad = [{"id": "next", "hidden": False, "size": 140}]
    assert (await client.put("/api/settings", json={"home_layout": bad})).status_code == 422


async def test_page_defaults_are_kept(client: AsyncClient) -> None:
    assert (await client.get("/api/settings")).json()["page_defaults"] == {}

    defaults = {"screens": {"view": "list", "days": "30"}, "monitored": {"type": "games"}}
    await client.put("/api/settings", json={"page_defaults": defaults})
    assert (await client.get("/api/settings")).json()["page_defaults"] == defaults

    bad = {"screens": {"days": "x" * 41}}
    assert (await client.put("/api/settings", json={"page_defaults": bad})).status_code == 422


async def test_health_reports_what_is_not_set_up(client: AsyncClient) -> None:
    body = (await client.get("/api/settings/health", params={"refresh": True})).json()
    assert body["suwayomi"] == {"state": "unset", "error": "", "until": None}
    assert body["notify"] == {"state": "unset", "error": "", "until": None}


async def test_a_service_that_does_not_answer_is_faulty_with_the_reason(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    stub_http(monkeypatch, refuse)
    await client.put("/api/settings", json={"qbittorrent_url": "https://qbittorrent.test"})
    body = (await client.get("/api/settings/health", params={"refresh": True})).json()
    assert body["qbittorrent"]["state"] == "faulty"
    assert body["qbittorrent"]["error"].endswith("Connection refused")


def test_comics_is_shown_once_its_key_is_set() -> None:
    assert db.get_settings().comics_ready is False
    db.save_settings({"comicvine_token": " cv-key "})
    assert db.get_settings().comicvine_key == "cv-key"
    assert db.get_settings().comics_ready is True


async def test_a_key_never_follows_its_address_to_another_host(client: AsyncClient) -> None:
    await client.put(
        "/api/settings",
        json={"prowlarr_url": "http://prowlarr.lan:9696", "prowlarr_api_key": "prowlarr-key-1"},
    )
    # The form sends the address back unchanged with every save, which keeps the key.
    await client.put("/api/settings", json={"prowlarr_url": "http://prowlarr.lan:9696/"})
    assert db.get_settings().prowlarr_api_key == "prowlarr-key-1"

    moved = await client.put("/api/settings", json={"prowlarr_url": "http://elsewhere.test"})
    assert moved.json()["has_prowlarr_api_key"] is False
    assert db.get_settings().prowlarr_api_key == ""

    # A new address with its own key keeps that key.
    await client.put(
        "/api/settings",
        json={"prowlarr_url": "http://prowlarr.new:9696", "prowlarr_api_key": "prowlarr-key-2"},
    )
    assert db.get_settings().prowlarr_api_key == "prowlarr-key-2"


async def test_a_key_saved_before_its_address_stays(client: AsyncClient) -> None:
    await client.put("/api/settings", json={"qbittorrent_api_key": "qbittorrent-key-1"})
    await client.put("/api/settings", json={"qbittorrent_url": "http://qbittorrent.lan:8080"})
    assert db.get_settings().qbittorrent_api_key == "qbittorrent-key-1"


def test_what_settings_kept_becomes_what_they_hide() -> None:
    with db.conn() as c:
        for column, value in (
            ("tmdb_languages_json", '["en"]'),
            ("tmdb_movie_genres_json", "[28]"),
            ("tmdb_release_types_json", '["digital"]'),
            ("books_categories_json", "[1]"),
            ("games_platforms_json", '["pc"]'),
        ):
            c.execute(f"ALTER TABLE settings ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'")
            c.execute(f"UPDATE settings SET {column} = ? WHERE id = 1", (value,))
        languages = '[{"iso_639_1": "en"}, {"iso_639_1": "es"}, {"iso_639_1": "ja"}]'
        c.execute(
            "INSERT INTO cache (key, value_json, expires_at) VALUES (?, ?, ?)",
            ("tmdb:v1:en-US:languages", languages, "2000-01-01T00:00:00"),
        )
    db.init_db()
    s = db.get_settings()
    assert s.tmdb_hidden_languages == ["es", "ja"]
    assert s.tmdb_hidden_release_types == ["theatrical"]
    assert s.books_hidden_categories == list(range(2, 11))
    assert s.games_hidden_platforms == ["playstation", "xbox", "nintendo"]
    # Keeping one genre never meant hiding every other, so genres start over.
    assert s.tmdb_hidden_movie_genres == []
    with db.conn() as c:
        assert "tmdb_languages_json" not in db._columns(c, "settings")


def test_every_source_and_integration_is_checked() -> None:
    """Each `*_ready` has a health probe, which is what setup's last step and Home show."""
    ready = {
        name.removesuffix("_ready")
        for name, value in vars(db.Settings).items()
        if name.endswith("_ready") and isinstance(value, property)
    }
    assert "igdb" in ready and "notify" in ready
    named = {"comics": "comicvine"}
    assert {named.get(name, name) for name in ready} <= set(Health.model_fields)
