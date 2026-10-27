"""A database from an older Robin is brought up to the schema file, or left as it was."""

import sqlite3
from datetime import date, timedelta

import pytest

from robin import db

OLD = "CREATE TABLE things (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"


def _old() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(OLD)
    c.execute("INSERT INTO things (name) VALUES ('kept')")
    return c


def test_a_unique_column_is_added_by_making_the_table_again() -> None:
    c = _old()
    schema = """CREATE TABLE IF NOT EXISTS things (
    id    INTEGER PRIMARY KEY,
    name  TEXT    NOT NULL,
    code  TEXT    UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS things_name ON things (name);
"""
    db._add_missing_columns(c, schema, "things")
    assert [tuple(r) for r in c.execute("SELECT id, name, code FROM things")] == [(1, "kept", None)]
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO things (name) VALUES ('kept')")


def test_rows_it_cannot_keep_leave_the_table_as_it_was() -> None:
    c = _old()
    schema = """CREATE TABLE IF NOT EXISTS things (
    id    INTEGER PRIMARY KEY,
    name  TEXT    NOT NULL,
    code  TEXT    NOT NULL UNIQUE
);
"""
    with pytest.raises(SystemExit, match="things"):
        db._add_missing_columns(c, schema, "things")
    stored = c.execute("SELECT sql FROM sqlite_master WHERE name = 'things'").fetchone()[0]
    assert stored == OLD
    assert [r["name"] for r in c.execute("SELECT name FROM things")] == ["kept"]


def test_the_database_runs_in_wal() -> None:
    with db.conn() as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_every_table_gains_the_columns_the_schema_added() -> None:
    """A countdowns table from before `tag` takes it on the next start."""
    with db.conn() as c:
        c.execute("DROP TABLE countdowns")
        c.execute(
            "CREATE TABLE countdowns (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,"
            " target TEXT NOT NULL UNIQUE, title TEXT NOT NULL, image TEXT, date TEXT NOT NULL,"
            " created_at TEXT NOT NULL)"
        )
    db.init_db()
    made = db.add_countdown("screens", "title=movie-1", "Dune", None, "Cinema", "2026-12-16")
    assert made["tag"] == "Cinema"


def test_no_migration_outlives_its_window() -> None:
    """A migration past its window is put to the owner: an install that skipped every release
    since loses what it changes, so dropping it is their call."""
    for shipped, migrate in db.MIGRATIONS:
        due = date.fromisoformat(shipped) + timedelta(days=db.MIGRATION_DAYS)
        assert date.today() < due, f"{migrate.__name__} shipped {shipped}: ask the owner to drop it"
