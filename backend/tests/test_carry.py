"""The carry-over from Comic Vine to Metron: every Comic Vine id Robin held comes out a Metron
id, or gone, and nothing of Comic Vine is left."""

import asyncio
import json
from typing import Any

import pytest
from httpx import AsyncClient

from robin import carry, comics, db
from tests import metron


def comicvine_install() -> None:
    """A database as the last Robin that read Comic Vine left it."""
    week = metron.this_week().isoformat()
    with db.conn() as c:
        c.execute("ALTER TABLE settings ADD COLUMN comicvine_token TEXT NOT NULL DEFAULT ''")
        c.execute(
            "UPDATE settings SET comicvine_token = 'cv-key', comics_digest_publishers_json = ?",
            (json.dumps([{"id": 31, "name": "Marvel"}]),),
        )
        c.execute("DROP INDEX IF EXISTS comics_series")
        c.execute("ALTER TABLE comics RENAME COLUMN series_id TO volume_id")
        for kind, cv_id, name in (
            ("series", 5100, "Midnight Spider-Man"),
            ("person", 9041, "Phillip Kennedy Johnson"),
            ("publisher", 31, "Marvel"),
            ("series", 7777, "Gone From Metron"),
        ):
            c.execute(
                "INSERT INTO favourites (category, kind, source_id, source_ids_json, name,"
                " created_at) VALUES ('comics', ?, ?, ?, ?, '2026-10-01')",
                (kind, cv_id, json.dumps([cv_id]), name),
            )
        c.execute(
            "INSERT INTO maker_filters (mode, category, kind, source_id, source_ids_json, name,"
            " created_at) VALUES ('hide', 'comics', 'publisher', 10, '[10]', 'DC', '2026-10-01')"
        )
        c.execute(
            "INSERT INTO comics (issue_id, volume_id, title, series, year, publisher, url, cover,"
            " status, created_at) VALUES ('9001', 5100, 'Midnight Spider-Man #1',"
            " 'Midnight Spider-Man', 2026, 'Marvel',"
            " 'https://comicvine.gamespot.com/x/4000-9001/',"
            " 'https://comicvine.gamespot.com/a/uploads/scale_large/1.jpg', 'monitored',"
            " '2026-10-01')"
        )
        c.execute(
            "INSERT INTO favourite_monitored (category, title, created_at)"
            " VALUES ('comics', 'volume-5200', '2026-10-01')"
        )
        c.execute(
            "INSERT INTO countdowns (category, target, title, date, created_at)"
            " VALUES ('comics', 'comic=9002', 'The Demon #1', ?, '2026-10-01')",
            (week,),
        )
    db.cache_put("comics:seen:9001", f"{week}|0", 90 * 24 * 3600)
    db.cache_put("comics:seen:12345", "2020-01-01|0", 90 * 24 * 3600)
    db.cache_put("comics:issues:v2:2026-10-21", [], 3600)
    db.cache_put("limit:v1:comicvine", {"until": "2099-01-01T00:00:00+00:00"}, 3600)


def rows(sql: str) -> list[dict[str, Any]]:
    with db.conn() as c:
        return [dict(r) for r in c.execute(sql)]


async def test_every_comic_vine_id_becomes_metron_or_goes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    comicvine_install()
    db.init_db()
    assert "comicvine_token" not in [r["name"] for r in rows("PRAGMA table_info(settings)")]
    assert db.comicvine_pending()
    assert db.cache_get("comics:issues:v2:2026-10-21") is None, "Comic Vine's answers go"
    assert db.cache_get("comics:seen:9001") is None, "moved aside, not left where Metron's live"

    # Nothing happens until a Metron key is set.
    assert await carry.run() == 0
    db.save_settings({"metron_token": metron.KEY})
    fake = metron.stub(monkeypatch)
    assert await carry.run() == 10

    favourites = {
        (f["kind"], f["source_id"], f["name"])
        for f in rows("SELECT * FROM favourites WHERE category = 'comics'")
    }
    assert favourites == {
        ("series", 100, "Midnight Spider-Man (2026)"),
        ("person", 41, "Phillip Kennedy Johnson"),
        ("publisher", 1, "Marvel"),
    }, "the series Metron lacks is dropped"
    [hidden] = rows("SELECT * FROM maker_filters WHERE category = 'comics'")
    assert (hidden["source_id"], json.loads(hidden["source_ids_json"])) == (2, [2])
    assert db.get_settings().comics_digest_publishers == [{"id": 1, "name": "Marvel"}]

    [comic] = rows("SELECT * FROM comics")
    assert (comic["series_id"], comic["issue_id"]) == (100, "1")
    assert comic["url"] == "https://metron.cloud/issue/1/"
    assert comic["cover"] == "https://static.metron.test/1.jpg"
    assert rows("SELECT title FROM favourite_monitored") == [{"title": "series-200"}]
    assert rows("SELECT target FROM countdowns") == [{"target": "comic=2"}]
    assert comics.seen({"id": "1"}) == f"{metron.this_week().isoformat()}|0"

    assert not db.comicvine_pending()
    assert not rows("SELECT name FROM sqlite_master WHERE name = 'comicvine_carry'")
    with db.conn() as c:
        kept = [r["key"] for r in c.execute("SELECT key FROM cache")]
    assert not [k for k in kept if "comicvine" in k or k.startswith("comics:seen:9")]

    settings = (await client.get("/api/settings")).json()
    assert not [k for k in settings if "comicvine" in k]

    # A second start asks Metron nothing.
    fake.asked.clear()
    db.init_db()
    assert await carry.run() == 0
    assert fake.asked == []


async def test_a_fresh_install_has_nothing_to_carry(monkeypatch: pytest.MonkeyPatch) -> None:
    db.save_settings({"metron_token": metron.KEY})
    fake = metron.stub(monkeypatch)
    assert not db.comicvine_pending()
    assert await carry.run() == 0
    assert fake.asked == []


async def test_two_starts_at_once_carry_once(monkeypatch: pytest.MonkeyPatch) -> None:
    comicvine_install()
    db.init_db()
    db.save_settings({"metron_token": metron.KEY})
    metron.stub(monkeypatch)
    assert sorted(await asyncio.gather(carry.run(), carry.run())) == [0, 10]
    assert not db.comicvine_pending()
