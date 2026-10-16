import base64
import hashlib
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from robin import backups, db
from robin.config import env

PASSPHRASE = "a long backup passphrase"
GAME = {"igdb_id": 1877, "name": "Cyberpunk 2077", "first_release_date": None}
# Every table a backup does not carry as it is.
LEFT_OUT = {"cache", "sessions", "games", "sqlite_sequence"}


def _tables() -> dict[str, list[tuple[Any, ...]]]:
    with db.conn() as c:
        names = [
            r[0]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if r[0] not in LEFT_OUT
        ]
        return {n: sorted(map(tuple, c.execute(f"SELECT * FROM {n}"))) for n in names}


async def _instance(client: AsyncClient) -> None:
    """An instance with something in every kind of table a restore has to bring back."""
    db.upsert_games([GAME, {**GAME, "igdb_id": 2, "name": "Unmonitored"}])
    assert (await client.post("/api/monitored", json={"igdb_id": 1877})).status_code == 201
    db.save_settings({"tmdb_token": "tmdb-key", "backup_passphrase": PASSPHRASE})
    db.update_account(setup_step=None, totp_secret="SECRET")
    db.cache_put("comics:seen:7", "2026-10-14|*", 3600)
    db.cache_put("tmdb:v1:detail:movie-1", {"title": "kept answer"}, 3600)


async def test_a_restore_brings_back_everything_but_what_is_asked_again(
    client: AsyncClient, tmp_path: Path
) -> None:
    await _instance(client)
    before = _tables()
    written = backups.write(db.get_settings())
    blob = (backups.folder() / written.name).read_bytes()
    assert b"tmdb-key" not in blob

    env.robin_data_dir = tmp_path / "fresh"
    db.init_db()
    backups.restore(blob, PASSPHRASE)

    assert _tables() == before
    assert db.cache_get("comics:seen:7") == "2026-10-14|*"
    assert db.cache_get("tmdb:v1:detail:movie-1") is None
    with db.conn() as c:
        assert [r[0] for r in c.execute("SELECT igdb_id FROM games")] == [1877]
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert db.get_settings().tmdb_token == "tmdb-key"


async def test_a_wrong_passphrase_changes_nothing(client: AsyncClient, tmp_path: Path) -> None:
    await _instance(client)
    blob = backups.seal(backups.snapshot(), PASSPHRASE)
    env.robin_data_dir = tmp_path / "fresh"
    db.init_db()
    with pytest.raises(backups.BackupError, match="Wrong passphrase"):
        backups.restore(blob, "not the passphrase")
    assert db.get_settings().tmdb_token == ""


def test_a_backup_from_a_newer_robin_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backups, "__version__", "99.0.0")
    blob = backups.seal(b"", PASSPHRASE)
    monkeypatch.undo()
    with pytest.raises(backups.BackupError, match="Robin 99.0.0"):
        backups.unseal(blob, PASSPHRASE)


def test_what_is_not_a_backup_is_refused() -> None:
    with pytest.raises(backups.BackupError, match="Not a Robin backup"):
        backups.unseal(b"SQLite format 3\x00", PASSPHRASE)


def test_only_as_many_as_settings_keep_stay() -> None:
    db.save_settings({"backup_passphrase": PASSPHRASE, "backup_keep": 2})
    first = backups.write(db.get_settings())
    for older in ("robin-20200101-000000.robin", "robin-20200102-000000.robin"):
        shutil.copy(backups.folder() / first.name, backups.folder() / older)
    backups.write(db.get_settings())
    names = [b.name for b in backups.listing()]
    assert len(names) == 2 and "robin-20200101-000000.robin" not in names


def test_the_daily_backup_is_due_once_its_hour_came_round() -> None:
    db.save_settings({"backup_hour": 3})
    noon = datetime(2026, 10, 16, 12).astimezone()
    assert not backups.due(db.get_settings(), noon)
    db.save_settings({"backup_passphrase": PASSPHRASE})
    assert backups.due(db.get_settings(), noon)
    backups.write(db.get_settings())
    assert not backups.due(db.get_settings(), datetime.now().astimezone())
    assert backups.due(db.get_settings(), datetime.now().astimezone() + timedelta(days=1))
    db.save_settings({"backups": False})
    assert not backups.due(db.get_settings(), datetime.now().astimezone() + timedelta(days=1))


async def test_nothing_is_written_without_a_passphrase(client: AsyncClient) -> None:
    assert (await client.post("/api/backups")).status_code == 409
    assert await backups.scheduled() == 0
    assert (await client.get("/api/backups")).json() == []


async def test_restore_is_only_offered_on_setup_s_first_step(
    client: AsyncClient, tmp_path: Path
) -> None:
    await _instance(client)
    name = backups.write(db.get_settings()).name
    body = {"name": name, "passphrase": PASSPHRASE}
    assert (await client.post("/api/backups/restore", json=body)).status_code == 409

    shutil.copytree(backups.folder(), tmp_path / "fresh" / "backups")
    env.robin_data_dir = tmp_path / "fresh"
    db.init_db()
    db.update_account(password_hash="new", setup_step="")
    db.create_session(hashlib.sha256(b"test-session").hexdigest(), "9999-12-31T00:00:00+00:00")
    upload = {"data": base64.b64encode(b"nonsense").decode(), "passphrase": PASSPHRASE}
    assert (await client.post("/api/backups/restore", json=upload)).status_code == 409

    restored = await client.post("/api/backups/restore", json=body)
    assert restored.status_code == 204
    assert db.get_account()["setup_step"] is None
    assert db.get_account()["totp_secret"] == "SECRET"
    assert (await client.get("/api/settings")).status_code == 401


async def test_a_backup_downloads_and_deletes(client: AsyncClient) -> None:
    db.save_settings({"backup_passphrase": PASSPHRASE})
    created = await client.post("/api/backups")
    assert created.status_code == 201
    name = created.json()["name"]
    got = await client.get(f"/api/backups/{name}")
    assert got.content.startswith(backups.MAGIC)
    assert (await client.get("/api/backups/..%2Frobin.db")).status_code == 404
    assert (await client.delete(f"/api/backups/{name}")).status_code == 204
    assert (await client.get("/api/backups")).json() == []


def test_a_restored_database_is_a_database() -> None:
    db.save_settings({"backup_passphrase": PASSPHRASE})
    data = backups.unseal(backups.seal(backups.snapshot(), PASSPHRASE), PASSPHRASE)
    path = Path(env.robin_data_dir) / "check.db"
    path.write_bytes(data)
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
