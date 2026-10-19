"""Encrypted backups of the database, kept in `backups` on the data volume, and their restore.

A backup is the database without what Robin asks its sources again: kept answers, sessions and
games nothing monitors. The memory of what was announced stays, so a restored instance repeats
no notice. It is sealed with AES-GCM under a key Argon2id derives from the backup passphrase,
behind a header naming the Robin that made it, which is read without the passphrase and
authenticated with it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from robin import __version__, auth, db
from robin.config import env

log = logging.getLogger(__name__)

MAGIC = b"ROBINBAK1\n"
NAME = re.compile(r"^robin-\d{8}-\d{6}\.robin$")
# Argon2id at the cost of a sign in, so a passphrase is as slow to guess as the password.
KDF = {"time_cost": 3, "memory_cost": 65536, "parallelism": 4}
# What the cache keeps that is a memory rather than an answer: the comics already announced.
KEPT_CACHE = "comics:seen:%"
# Why the last backup failed, kept until one succeeds.
ERROR_KEY = "backups:error"
ERROR_TTL = int(timedelta(days=365).total_seconds())


class BackupError(ValueError):
    """A backup that cannot be read or restored, worded for the user."""


@dataclass(frozen=True)
class Backup:
    name: str
    size: int
    version: str
    created: str


def folder() -> Path:
    return Path(env.robin_data_dir) / "backups"


def _key(passphrase: str, salt: bytes, kdf: dict[str, int]) -> bytes:
    # A header asking for far more than Robin writes would take the host's memory with it.
    if any(not 0 < int(kdf[name]) <= 4 * cost for name, cost in KDF.items()):
        raise BackupError("Not a Robin backup")
    costs = {name: int(kdf[name]) for name in KDF}
    with auth._hashing:
        return hash_secret_raw(passphrase.encode(), salt, hash_len=32, type=Type.ID, **costs)


def seal(data: bytes, passphrase: str) -> bytes:
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = json.dumps(
        {
            "version": __version__,
            "created": db.now(),
            "salt": base64.b64encode(salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "kdf": KDF,
        }
    ).encode()
    head = MAGIC + len(header).to_bytes(4, "big") + header
    return head + AESGCM(_key(passphrase, salt, KDF)).encrypt(nonce, data, head)


def _header(blob: bytes) -> tuple[dict[str, Any], int]:
    """The header and where the sealed data starts."""
    if not blob.startswith(MAGIC):
        raise BackupError("Not a Robin backup")
    start = len(MAGIC) + 4
    end = start + int.from_bytes(blob[len(MAGIC) : start], "big")
    try:
        header: dict[str, Any] = json.loads(blob[start:end])
    except ValueError as exc:
        raise BackupError("Not a Robin backup") from exc
    return header, end


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def unseal(blob: bytes, passphrase: str) -> bytes:
    header, end = _header(blob)
    if not isinstance(header.get("version"), str):
        raise BackupError("Not a Robin backup")
    if _release(header["version"]) > _release(__version__):
        raise BackupError(f"Made by Robin {header['version']}, update Robin first")
    key = _key(passphrase, base64.b64decode(header["salt"]), header["kdf"])
    try:
        return AESGCM(key).decrypt(base64.b64decode(header["nonce"]), blob[end:], blob[:end])
    except InvalidTag as exc:
        raise BackupError("Wrong passphrase") from exc


def snapshot() -> bytes:
    """The database as a backup holds it, unsealed."""
    with tempfile.TemporaryDirectory(dir=env.robin_data_dir) as tmp:
        path = Path(tmp) / "robin.db"
        copy = sqlite3.connect(path)
        try:
            with db.conn() as live:
                live.backup(copy)
            copy.execute("PRAGMA journal_mode = DELETE")
            copy.execute("DELETE FROM cache WHERE key NOT LIKE ?", (KEPT_CACHE,))
            copy.execute("DELETE FROM sessions")
            copy.execute("DELETE FROM games WHERE igdb_id NOT IN (SELECT igdb_id FROM requests)")
            copy.commit()
            copy.execute("VACUUM")
        finally:
            copy.close()
        return path.read_bytes()


def listing() -> list[Backup]:
    """Every backup in the folder, newest first."""
    found = []
    for path in folder().glob("robin-*.robin"):
        if not NAME.match(path.name):
            continue
        try:
            with path.open("rb") as f:
                header, _ = _header(f.read(4096))
        except (OSError, BackupError, KeyError):
            continue
        found.append(Backup(path.name, path.stat().st_size, header["version"], header["created"]))
    return sorted(found, key=lambda b: b.name, reverse=True)


def path_of(name: str) -> Path:
    root = os.path.normpath(folder())
    full = os.path.normpath(os.path.join(root, name))
    if not NAME.fullmatch(name) or not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise BackupError("No such backup")
    return Path(full)


def write(settings: db.Settings) -> Backup:
    """Write a backup now, then delete the oldest past what Settings keeps."""
    if not settings.backups_ready:
        raise BackupError("Set a backup passphrase first")
    try:
        blob = seal(snapshot(), settings.backup_passphrase)
        folder().mkdir(mode=0o700, exist_ok=True)
        name = f"robin-{datetime.now(UTC):%Y%m%d-%H%M%S}.robin"
        path = folder() / name
        partial = path.with_suffix(".part")
        partial.touch(mode=0o600)
        partial.write_bytes(blob)
        partial.replace(path)
    except Exception as exc:
        db.cache_put(ERROR_KEY, str(exc) or type(exc).__name__, ERROR_TTL)
        raise
    db.cache_drop(ERROR_KEY)
    for old in listing()[settings.backup_keep :]:
        (folder() / old.name).unlink(missing_ok=True)
    log.info("backups: wrote %s", name)
    return listing()[0]


async def health() -> None:
    """Faulty while the last backup failed."""
    if error := db.cache_get(ERROR_KEY):
        raise BackupError(str(error))


def due(settings: db.Settings, now: datetime) -> bool:
    """Whether the daily backup is owed: none since the last time its hour came round."""
    if not (settings.backups_ready and settings.backups):
        return False
    slot = now.replace(hour=settings.backup_hour, minute=0, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    newest = listing()
    return not newest or datetime.fromisoformat(newest[0].created) < slot.astimezone(UTC)


async def scheduled() -> int:
    """The daily backup, at its hour of server local time. Returns how many were written."""
    settings = db.get_settings()
    if not due(settings, datetime.now().astimezone()):
        return 0
    write(settings)
    return 1


def restore(blob: bytes, passphrase: str) -> None:
    """Replace the database with a backup's. Every session ends, the backup's included."""
    data = unseal(blob, passphrase)
    with tempfile.TemporaryDirectory(dir=env.robin_data_dir) as tmp:
        path = Path(tmp) / "robin.db"
        path.write_bytes(data)
        source = sqlite3.connect(path)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("This backup is damaged")
            account = source.execute("SELECT password_hash FROM account WHERE id = 1").fetchone()
            if account is None or not account[0]:
                raise BackupError("This backup has no account")
            with db.conn() as live:
                source.backup(live)
        except sqlite3.DatabaseError as exc:
            raise BackupError("This backup is damaged") from exc
        finally:
            source.close()
    db.init_db()
    db.delete_sessions()
    log.info("backups: restored a backup made by Robin %s", _header(blob)[0]["version"])
