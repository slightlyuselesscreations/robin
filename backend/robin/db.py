"""SQLite access. Plain SQL, one short-lived connection per operation.

A connection per operation removes every threading question, which matters because FastAPI
runs sync work on a thread pool.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from robin import redact
from robin.config import env

log = logging.getLogger(__name__)

SCHEMA = Path(__file__).with_name("schema.sql")

# The qBittorrent category Home lists downloads from and a grab is filed under.
DEFAULT_CATEGORY = "games"

# Bumped whenever the stored metadata gains a field or changes shape. A row tagged with an older
# version is treated as not detailed, so it is refetched instead of showing gaps.
EXTRA_VERSION = 4


def db_path() -> Path:
    return Path(env.robin_data_dir) / "robin.db"


def now() -> str:
    return datetime.now(UTC).isoformat()


# How far ahead a grid of what is coming looks, the same on every page.
AHEAD_DAYS = 365

# What a grid is ordered by: most anticipated first, or soonest first.
Sort = Literal["popularity", "date"]


def month_start() -> date:
    """The first day of the current month. Nothing dated before it is listed but in search, and
    nothing dated before it is monitored."""
    return datetime.now(UTC).date().replace(day=1)


def before_month(day: str | None) -> bool:
    """Whether a YYYY-MM-DD names a day before the current month. An undated one never does."""
    return bool(day) and str(day)[:10] < month_start().isoformat()


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(db_path(), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    # Per connection. Under WAL, which `init_db` sets once for the file, NORMAL loses nothing
    # on a crash, at most the last commits on a power cut.
    c.execute("PRAGMA synchronous = NORMAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    data = Path(env.robin_data_dir)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not os.access(data, os.W_OK):
        raise SystemExit(
            f"Robin cannot write to {data}. Give the data folder to the user it runs as,"
            " `user` in docker-compose.yml: chown -R 1000:1000 data"
        )
    # The database holds every key, the password hash and the two factor secret, so only the
    # user Robin runs as reads it. SQLite gives its journal files the database's own mode.
    db_path().touch(mode=0o600, exist_ok=True)
    _private(db_path())
    schema = SCHEMA.read_text(encoding="utf-8")
    with conn() as c:
        # Readers no longer wait on a writer, so a page never waits on the hourly loop.
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(schema)
        # Comics gained favourites, and with them the publisher.
        for table in ("favourites", "maker_filters"):
            _rebuild(c, schema, table, "'publisher'")
        # Every table the schema declares, so a column added to a new one reaches every install.
        for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(", schema):
            _add_missing_columns(c, schema, table)
        _keep_to_hide(c)
        _ntfy_to_destinations(c)
        _unify_page_defaults(c)
        # After the column is added, which an older database has not had.
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS comics_volume ON comics (volume_id)")
        # Makers were only ever hidden before they could be shown too.
        if c.execute("SELECT 1 FROM sqlite_master WHERE name = 'hidden_makers'").fetchone():
            c.execute(
                "INSERT OR IGNORE INTO maker_filters"
                " (mode, category, kind, source_id, source_ids_json, name, created_at)"
                " SELECT 'hide', category, kind, source_id, source_ids_json, name, created_at"
                " FROM hidden_makers"
            )
            c.execute("DROP TABLE hidden_makers")
        c.execute("INSERT OR IGNORE INTO settings (id, updated_at) VALUES (1, ?)", (now(),))
        c.execute("INSERT OR IGNORE INTO account (id, updated_at) VALUES (1, ?)", (now(),))


def _keep_to_hide(c: sqlite3.Connection) -> None:
    """Settings that listed what to keep now list what to hide: whatever a list did not keep,
    of every value it could have. Languages are read from TMDB's list in the cache, and stay
    unhidden without it. Genres start over, a book or a film carries several, so keeping one
    never meant hiding the rest."""
    if "tmdb_languages_json" not in _columns(c, "settings"):
        return
    row = c.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if row is not None:
        known = c.execute(
            "SELECT value_json FROM cache WHERE key LIKE 'tmdb:v1:%:languages' LIMIT 1"
        ).fetchone()
        languages = [lang["iso_639_1"] for lang in json.loads(known[0])] if known else []
        # The list that kept, the one that hides now, and every value either could hold.
        lists: list[tuple[str, str, list[Any]]] = [
            ("tmdb_languages", "tmdb_hidden_languages", languages),
            ("tmdb_release_types", "tmdb_hidden_release_types", ["theatrical", "digital"]),
            ("books_literary_types", "books_hidden_literary_types", [1, 2]),
            ("books_categories", "books_hidden_categories", list(range(1, 11))),
            (
                "games_platforms",
                "games_hidden_platforms",
                ["pc", "playstation", "xbox", "nintendo"],
            ),
        ]
        columns = row.keys()
        for old, new, values in lists:
            if f"{old}_json" not in columns:
                continue
            kept = json.loads(row[f"{old}_json"] or "[]")
            hidden = [v for v in values if v not in kept] if kept else []
            c.execute(f"UPDATE settings SET {new}_json = ? WHERE id = 1", (json.dumps(hidden),))
    _drop_columns(
        c,
        "settings",
        (
            "tmdb_languages_json",
            "tmdb_movie_genres_json",
            "tmdb_tv_genres_json",
            "tmdb_release_types_json",
            "books_literary_types_json",
            "books_categories_json",
            "books_genres_json",
            "games_platforms_json",
        ),
    )


# Page controls saved under the names they had before every grid shared one set: the new name,
# and old values that read differently now.
_RENAMED_CONTROLS: dict[str, tuple[str, dict[str, str]]] = {
    "kind": ("type", {}),
    "sort": ("order", {}),
    "order": ("order", {"popular": "popularity"}),
    "lang": ("language", {}),
    "from": ("type", {"tomorrow": "upcoming", "january": "out"}),
}

# Page controls no grid has any more: how far ahead it looks is the same on every grid.
_DROPPED_CONTROLS = ("days", "window")


def _unify_page_defaults(c: sqlite3.Connection) -> None:
    """Saved page controls take the names every grid shares, Type and Order, a control no grid
    has any more is dropped, and so are the picks that brought back what Settings hides, `kept`
    and `any`, a filter only ever narrowing what Settings leaves."""
    row = c.execute("SELECT page_defaults_json FROM settings WHERE id = 1").fetchone()
    if row is None:
        return
    defaults: dict[str, dict[str, str]] = json.loads(row[0] or "{}")
    unified: dict[str, dict[str, str]] = {}
    for page, controls in defaults.items():
        kept: dict[str, str] = {}
        for name, value in controls.items():
            new, values = _RENAMED_CONTROLS.get(name, (name, {}))
            if name in _DROPPED_CONTROLS or value in ("kept", "any") or new in kept:
                continue
            kept[new] = values.get(value, value)
        if kept:
            unified[page] = kept
    if unified != defaults:
        c.execute("UPDATE settings SET page_defaults_json = ? WHERE id = 1", (json.dumps(unified),))


def _ntfy_to_destinations(c: sqlite3.Connection) -> None:
    """ntfy and a topic per category become an ntfy destination, each category's topic its
    place there and an empty one its switch off. An install that had no ntfy opens setup at
    its notifications step alone, `SETUP_NOTIFICATIONS`."""
    if "ntfy_url" not in _columns(c, "settings"):
        return
    row = c.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if row is not None and row["ntfy_url"]:
        topics: dict[str, str] = {
            "games": row["ntfy_topic"],
            "comics": row["comics_topic"],
            "screens": row["screen_topic"],
            "books": row["books_topic"],
        }
        topic = next((t for t in topics.values() if t), "robin")
        values = {"server": row["ntfy_url"], "topic": topic}
        if row["ntfy_token"]:
            values["token"] = row["ntfy_token"]
        places = {cat: t for cat, t in topics.items() if t and t != topic}
        ntfy = {"id": "ntfy", "service": "ntfy", "values": values, "places": places}
        c.execute(
            "UPDATE settings SET notify_destinations_json = ?, games_notify = ?,"
            " comics_notify = ?, screen_notify = ?, books_notify = ? WHERE id = 1",
            (json.dumps([ntfy]), *(int(bool(t)) for t in topics.values())),
        )
    else:
        c.execute(
            "UPDATE account SET setup_step = ? WHERE id = 1 AND setup_step IS NULL"
            " AND password_hash IS NOT NULL",
            (SETUP_NOTIFICATIONS,),
        )
    _drop_columns(
        c,
        "settings",
        (
            "ntfy_url",
            "ntfy_topic",
            "ntfy_token",
            "ntfy_priority",
            "comics_priority",
            "comics_topic",
            "screen_topic",
            "screen_priority",
            "books_topic",
            "books_priority",
        ),
    )


# The setup step an install that finished setup without a notification destination opens at,
# alone.
SETUP_NOTIFICATIONS = "notifications-only"


def _private(path: Path) -> None:
    """Only the owner reads or writes `path`. A file someone else owns is left as it is."""
    try:
        path.chmod(0o600)
    except PermissionError:
        log.warning("could not make %s private to its owner", path)


def _add_missing_columns(c: sqlite3.Connection, schema: str, table: str) -> None:
    """Add columns the schema file has gained since the database was created. One SQLite cannot
    add in place, UNIQUE or PRIMARY KEY, has the table made again with it.

    A changed constraint still needs `_rebuild`.
    """
    body = schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]
    existing = _columns(c, table)

    for line in body.splitlines():
        definition = line.strip().rstrip(",")
        if not definition or definition.startswith(("PRIMARY", "FOREIGN", "CHECK", "UNIQUE", "--")):
            continue
        name = definition.split()[0]
        if name not in existing:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            except sqlite3.OperationalError:
                _recreate(c, schema, table)
                return
            log.info("added column %s.%s", table, name)


def _columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def _rebuild(c: sqlite3.Connection, schema: str, table: str, needle: str) -> bool:
    """Recreate `table` from the schema file when its stored CHECK lacks `needle`. SQLite
    cannot change a constraint in place, so the rows move to a new table. True when it did."""
    stored = c.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if needle in stored["sql"]:
        return False
    _recreate(c, schema, table)
    return True


def _recreate(c: sqlite3.Connection, schema: str, table: str) -> None:
    """Make `table` again as the schema file declares it, its rows moved over by the columns
    both share. All or nothing: rows the new table refuses, a new NOT NULL column with no
    default, leave the database as it was and stop Robin with what failed."""
    create = (
        f"CREATE TABLE {table} ("
        + schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]
        + ");"
    )
    c.execute("SAVEPOINT recreate")
    try:
        c.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
        c.execute(create)
        kept = ", ".join(sorted(_columns(c, f"{table}_old") & _columns(c, table)))
        c.execute(f"INSERT INTO {table} ({kept}) SELECT {kept} FROM {table}_old")
        c.execute(f"DROP TABLE {table}_old")
        # Its indexes went with the old table.
        for line in schema.splitlines():
            index = line.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX"))
            if index and f" ON {table} (" in line:
                c.execute(line)
    except sqlite3.DatabaseError as exc:
        c.execute("ROLLBACK TO recreate")
        c.execute("RELEASE recreate")
        raise SystemExit(
            f"Robin cannot upgrade its {table} table: {exc}. The database is unchanged,"
            " run the previous version of Robin."
        ) from exc
    c.execute("RELEASE recreate")
    log.info("made %s again for its new columns", table)


def _drop_columns(c: sqlite3.Connection, table: str, names: tuple[str, ...]) -> None:
    """Remove columns the schema file no longer declares."""
    existing = _columns(c, table)
    for name in names:
        if name in existing:
            c.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
            log.info("dropped column %s.%s", table, name)


# ---------------------------------------------------------------- settings

# Never returned by the API, a blank write keeps the stored value, and each is registered for
# log redaction.
SECRET_FIELDS = (
    "twitch_client_secret",
    "prowlarr_api_key",
    "qbittorrent_api_key",
    "tmdb_token",
    "hardcover_token",
    "comicvine_token",
    "radarr_api_key",
    "sonarr_api_key",
    "backup_passphrase",
)
# Stored as JSON in a `<name>_json` column.
LIST_FIELDS = (
    "prowlarr_indexer_ids",
    "p2p_groups",
    "home_layout",
    "page_defaults",
    "tmdb_hidden_languages",
    "tmdb_hidden_movie_genres",
    "tmdb_hidden_tv_genres",
    "tmdb_hidden_release_types",
    "tmdb_shown_movie_genres",
    "tmdb_shown_tv_genres",
    "books_hidden_literary_types",
    "books_hidden_categories",
    "books_hidden_genres",
    "books_shown_genres",
    "games_hidden_platforms",
    "games_schedule",
    "comics_schedule",
    "screen_schedule",
    "books_schedule",
    "games_quiet",
    "comics_quiet",
    "screen_quiet",
    "books_quiet",
    "notify_destinations",
    "comics_digest_publishers",
)
# Stored without a trailing slash, so a path is always appended with one.
URL_FIELDS = (
    "prowlarr_url",
    "suwayomi_url",
    "qbittorrent_url",
    "radarr_url",
    "sonarr_url",
)

Category = Literal["games", "comics", "screens", "books"]
Theme = Literal[
    "european",
    "american",
    "pink",
    "siberian",
    "rufous",
    "flame",
    "red-capped",
    "white-throated",
    "black",
]
Scheme = Literal["dark", "light", "system"]

# A marker's slot after every other: every notice for its date was sent.
SENT_ALL = "9999"

# The notice every schedule holds, a day before, and its hour unless one is set.
DAY_BEFORE = (1, 9)


@dataclass(frozen=True)
class Channel:
    """A category's notices, and the local hours they are held back, [start, end)."""

    category: Category
    quiet: tuple[int, int] | None = None


@dataclass(frozen=True)
class Settings:
    """Effective settings, as stored."""

    twitch_client_id: str
    twitch_client_secret: str
    prowlarr_url: str
    prowlarr_api_key: str
    # Which Prowlarr indexers are searched, for a game's search and what a monitored game is
    # grabbed from. Empty means all of them.
    prowlarr_indexer_ids: list[int]
    # Release groups outside the scene, grabbed without asking PreDB.
    p2p_groups: list[str]
    # Home panels in order, {"id": ..., "hidden": ...}. Empty means the default layout.
    home_layout: list[dict[str, Any]]
    # What each page shows when its address names nothing, {"screens": {"days": "30"}}.
    page_defaults: dict[str, dict[str, str]]
    theme: Theme
    scheme: Scheme
    # Comics, from Comic Vine.
    comicvine_token: str
    # Where monitored comic series are looked for. Both empty means they are not.
    suwayomi_url: str
    suwayomi_source_id: str
    # What is downloading. The key is empty when qBittorrent lets the LAN in without one.
    qbittorrent_url: str
    qbittorrent_api_key: str
    # The category Home lists downloads from, the label grabs are filed under.
    qbittorrent_category: str
    # Whether a monitored game grabs only a release its tracker marks freeleech.
    freeleech_only: bool
    # Movies and TV. The region decides release dates and streaming services, the language
    # what titles and overviews are written in.
    tmdb_token: str
    tmdb_region: str
    tmdb_language: str
    # What Screens hides: original languages as ISO 639-1 codes, TMDB genre ids per kind and
    # release types, theatrical and digital. A title carrying a hidden value is left out
    # unless it carries a genre of its kind always shown.
    tmdb_hidden_languages: list[str]
    tmdb_hidden_movie_genres: list[int]
    tmdb_hidden_tv_genres: list[int]
    tmdb_hidden_release_types: list[str]
    tmdb_shown_movie_genres: list[int]
    tmdb_shown_tv_genres: list[int]
    # Radarr and Sonarr: where a film or show is added, with the quality profile and root
    # folder it is added under, 0 and empty meaning the first the app lists, and whether
    # monitoring one adds it.
    radarr_url: str
    radarr_api_key: str
    radarr_profile_id: int
    radarr_root: str
    radarr_add: bool
    sonarr_url: str
    sonarr_api_key: str
    sonarr_profile_id: int
    sonarr_root: str
    sonarr_add: bool
    # Books. What is hidden: Hardcover literary types (1 fiction, 2 nonfiction), book
    # categories and genre tag slugs, unless a book carries a genre always shown.
    hardcover_token: str
    books_hidden_literary_types: list[int]
    books_hidden_categories: list[int]
    books_hidden_genres: list[str]
    books_shown_genres: list[str]
    # Games. The `igdb.PLATFORMS` families hidden: a game on none other is left out.
    games_hidden_platforms: list[str]
    # When dated notices go out, per category, each {"days": before, "hour": local}.
    games_schedule: list[dict[str, int]]
    comics_schedule: list[dict[str, int]]
    screen_schedule: list[dict[str, int]]
    books_schedule: list[dict[str, int]]
    # The Comic Vine publishers the weekly #1s digest names, each {"id", "name"}, every one
    # while empty.
    comics_digest_publishers: list[dict[str, Any]]
    # Quiet hours per category, [start, end], empty for none.
    games_quiet: list[int]
    comics_quiet: list[int]
    screen_quiet: list[int]
    books_quiet: list[int]
    # Where notifications go, each {"id", "service", "values", "places"}, `places` the
    # service's place per category where it differs, `notify.SERVICES`.
    notify_destinations: list[dict[str, Any]]
    # Whether each category sends notifications.
    games_notify: bool
    comics_notify: bool
    screen_notify: bool
    books_notify: bool
    # Whether a favourite's new releases are announced, per category.
    games_favourites: bool
    screen_favourites: bool
    books_favourites: bool
    comics_favourites: bool
    # Whether a favourite's new releases are monitored, per category.
    games_favourites_monitor: bool
    screen_favourites_monitor: bool
    books_favourites_monitor: bool
    comics_favourites_monitor: bool
    # What backups are sealed with, whether one is written daily at a local hour, and how many
    # are kept.
    backup_passphrase: str
    backups: bool
    backup_hour: int
    backup_keep: int
    # The makers always hidden and always shown, every id they cover by kind of favourite, per
    # category.
    hidden_makers: dict[str, dict[str, frozenset[int]]] = field(default_factory=dict)
    shown_makers: dict[str, dict[str, frozenset[int]]] = field(default_factory=dict)

    # A category is shown only while its data source is ready. Integrations add behaviour and
    # are hidden while unset. Every gate in the backend and the UI reads one of these.

    @property
    def igdb_ready(self) -> bool:
        return bool(self.twitch_client_id and self.twitch_client_secret)

    @property
    def tmdb_ready(self) -> bool:
        return bool(self.tmdb_token)

    @property
    def hardcover_ready(self) -> bool:
        return bool(self.hardcover_key)

    @property
    def comics_ready(self) -> bool:
        return bool(self.comicvine_key)

    @property
    def prowlarr_ready(self) -> bool:
        return bool(self.prowlarr_url and self.prowlarr_api_key)

    @property
    def qbittorrent_ready(self) -> bool:
        return bool(self.qbittorrent_url)

    @property
    def radarr_ready(self) -> bool:
        """Radarr and Sonarr need TMDB, which their titles open in and Sonarr's TVDB id is
        read from."""
        return bool(self.radarr_url and self.radarr_api_key and self.tmdb_ready)

    @property
    def sonarr_ready(self) -> bool:
        return bool(self.sonarr_url and self.sonarr_api_key and self.tmdb_ready)

    @property
    def suwayomi_ready(self) -> bool:
        return bool(self.comics_ready and self.suwayomi_url and self.suwayomi_source_id)

    @property
    def notify_ready(self) -> bool:
        return bool(self.notify_destinations)

    @property
    def backups_ready(self) -> bool:
        return bool(self.backup_passphrase)

    @property
    def hardcover_key(self) -> str:
        """The key without the `Bearer ` Hardcover's site shows in front of it."""
        raw = self.hardcover_token.strip()
        return raw[len("bearer ") :].strip() if raw.lower().startswith("bearer ") else raw

    @property
    def comicvine_key(self) -> str:
        return self.comicvine_token.strip()

    def source_ready(self, category: Category) -> bool:
        return {
            "games": self.igdb_ready,
            "comics": self.comics_ready,
            "screens": self.tmdb_ready,
            "books": self.hardcover_ready,
        }[category]

    def channel(self, category: Category) -> Channel:
        """The category's channel and quiet hours, whether or not its notices are on."""
        quiet = {
            "games": self.games_quiet,
            "comics": self.comics_quiet,
            "screens": self.screen_quiet,
            "books": self.books_quiet,
        }[category]
        held = (quiet[0], quiet[1]) if len(quiet) == 2 and quiet[0] != quiet[1] else None
        return Channel(category=category, quiet=held)

    def notify_on(self, category: Category) -> bool:
        return {
            "games": self.games_notify,
            "comics": self.comics_notify,
            "screens": self.screen_notify,
            "books": self.books_notify,
        }[category]

    def schedule(self, category: Category) -> list[tuple[int, int]]:
        """When the category's dated notices go, (days before, hour), the day before always."""
        entries = {
            "games": self.games_schedule,
            "comics": self.comics_schedule,
            "screens": self.screen_schedule,
            "books": self.books_schedule,
        }[category]
        slots = {(int(e["days"]), int(e["hour"])) for e in entries}
        if not any(days == DAY_BEFORE[0] for days, _ in slots):
            slots.add(DAY_BEFORE)
        return sorted(slots)

    def favourites_monitor(self, category: Category) -> bool:
        """Whether a favourite's new releases are monitored now: its switch is on and the
        category can monitor. A reminder is a notice, so Screens and Books need theirs on."""
        switch = {
            "games": self.games_favourites_monitor,
            "screens": self.screen_favourites_monitor,
            "books": self.books_favourites_monitor,
            "comics": self.comics_favourites_monitor,
        }.get(category, False)
        if category == "games":
            return switch and self.igdb_ready
        return switch and self.notices(category) is not None

    def favourite_notices(self, category: Category) -> Channel | None:
        """Where a favourite's new releases are announced, or None while that is off."""
        switch = {
            "games": self.games_favourites,
            "screens": self.screen_favourites,
            "books": self.books_favourites,
            "comics": self.comics_favourites,
        }.get(category, False)
        return self.notices(category) if switch else None

    def notices(self, category: Category) -> Channel | None:
        """Where the category's notices go, or None while they are off.

        One rule for every category: a destination is set, the category is shown, and its
        switch is on.
        """
        if not (self.notify_ready and self.notify_on(category) and self.source_ready(category)):
            return None
        return self.channel(category)


def get_settings() -> Settings:
    with conn() as c:
        row = c.execute("SELECT * FROM settings WHERE id = 1").fetchone()

    def text(name: str) -> str:
        return str(row[name] or "")

    # Imported here, notify reads this module.
    from robin import notify

    lists = {name: json.loads(row[f"{name}_json"] or "null") for name in LIST_FIELDS}
    destinations = list(lists["notify_destinations"] or [])
    redact.remember(*(text(name) for name in SECRET_FIELDS), *notify.secrets(destinations))
    return Settings(
        twitch_client_id=text("twitch_client_id"),
        twitch_client_secret=text("twitch_client_secret"),
        prowlarr_url=text("prowlarr_url").rstrip("/"),
        prowlarr_api_key=text("prowlarr_api_key"),
        prowlarr_indexer_ids=list(lists["prowlarr_indexer_ids"] or []),
        p2p_groups=list(lists["p2p_groups"] or []),
        home_layout=list(lists["home_layout"] or []),
        page_defaults=dict(lists["page_defaults"] or {}),
        theme=row["theme"],
        scheme=row["scheme"],
        comicvine_token=text("comicvine_token"),
        suwayomi_url=(row["suwayomi_url"] or "").rstrip("/"),
        suwayomi_source_id=row["suwayomi_source_id"] or "",
        qbittorrent_url=text("qbittorrent_url").rstrip("/"),
        qbittorrent_api_key=text("qbittorrent_api_key"),
        qbittorrent_category=row["qbittorrent_category"] or DEFAULT_CATEGORY,
        freeleech_only=bool(row["freeleech_only"]),
        tmdb_token=text("tmdb_token"),
        tmdb_region=row["tmdb_region"] or "US",
        tmdb_language=row["tmdb_language"] or "en-US",
        tmdb_hidden_languages=list(lists["tmdb_hidden_languages"] or []),
        tmdb_hidden_movie_genres=list(lists["tmdb_hidden_movie_genres"] or []),
        tmdb_hidden_tv_genres=list(lists["tmdb_hidden_tv_genres"] or []),
        tmdb_hidden_release_types=list(lists["tmdb_hidden_release_types"] or []),
        tmdb_shown_movie_genres=list(lists["tmdb_shown_movie_genres"] or []),
        tmdb_shown_tv_genres=list(lists["tmdb_shown_tv_genres"] or []),
        radarr_url=text("radarr_url").rstrip("/"),
        radarr_api_key=text("radarr_api_key"),
        radarr_profile_id=int(row["radarr_profile_id"] or 0),
        radarr_root=row["radarr_root"] or "",
        radarr_add=bool(row["radarr_add"]),
        sonarr_url=text("sonarr_url").rstrip("/"),
        sonarr_api_key=text("sonarr_api_key"),
        sonarr_profile_id=int(row["sonarr_profile_id"] or 0),
        sonarr_root=row["sonarr_root"] or "",
        sonarr_add=bool(row["sonarr_add"]),
        hardcover_token=text("hardcover_token"),
        books_hidden_literary_types=list(lists["books_hidden_literary_types"] or []),
        books_hidden_categories=list(lists["books_hidden_categories"] or []),
        books_hidden_genres=list(lists["books_hidden_genres"] or []),
        books_shown_genres=list(lists["books_shown_genres"] or []),
        games_hidden_platforms=list(lists["games_hidden_platforms"] or []),
        games_schedule=list(lists["games_schedule"] or []),
        comics_schedule=list(lists["comics_schedule"] or []),
        screen_schedule=list(lists["screen_schedule"] or []),
        books_schedule=list(lists["books_schedule"] or []),
        comics_digest_publishers=list(lists["comics_digest_publishers"] or []),
        games_quiet=list(lists["games_quiet"] or []),
        comics_quiet=list(lists["comics_quiet"] or []),
        screen_quiet=list(lists["screen_quiet"] or []),
        books_quiet=list(lists["books_quiet"] or []),
        notify_destinations=destinations,
        games_notify=bool(row["games_notify"]),
        comics_notify=bool(row["comics_notify"]),
        screen_notify=bool(row["screen_notify"]),
        books_notify=bool(row["books_notify"]),
        games_favourites=bool(row["games_favourites"]),
        screen_favourites=bool(row["screen_favourites"]),
        books_favourites=bool(row["books_favourites"]),
        games_favourites_monitor=bool(row["games_favourites_monitor"]),
        screen_favourites_monitor=bool(row["screen_favourites_monitor"]),
        books_favourites_monitor=bool(row["books_favourites_monitor"]),
        comics_favourites=bool(row["comics_favourites"]),
        comics_favourites_monitor=bool(row["comics_favourites_monitor"]),
        backup_passphrase=text("backup_passphrase"),
        backups=bool(row["backups"]),
        backup_hour=int(row["backup_hour"]),
        backup_keep=int(row["backup_keep"]),
        hidden_makers=_makers("hide"),
        shown_makers=_makers("show"),
    )


def _makers(mode: str) -> dict[str, dict[str, frozenset[int]]]:
    found: dict[str, dict[str, frozenset[int]]] = {}
    for maker in maker_filters():
        if maker["mode"] == mode:
            kinds = found.setdefault(maker["category"], {})
            kinds[maker["kind"]] = kinds.get(maker["kind"], frozenset()) | frozenset(maker["ids"])
    return found


# Each integration's address and the key that goes with it.
KEYED_URLS = {
    "prowlarr_url": "prowlarr_api_key",
    "qbittorrent_url": "qbittorrent_api_key",
    "radarr_url": "radarr_api_key",
    "sonarr_url": "sonarr_api_key",
}


def save_settings(patch: dict[str, Any], clear: tuple[str, ...] = ()) -> list[str]:
    """Apply a partial update and return the names of the stored fields it changed.

    Keys absent from the patch keep their stored value. A secret sent as an empty string is
    treated as absent, so the UI can round-trip a masked form without wiping the stored key;
    `clear` names the secrets to wipe. Lists are stored as JSON and URLs without a trailing
    slash.
    """
    fields: dict[str, Any] = {name: "" for name in clear if name in SECRET_FIELDS}
    for name, value in patch.items():
        if value is None or (name in SECRET_FIELDS and value == ""):
            continue
        if name in LIST_FIELDS:
            fields[f"{name}_json"] = json.dumps(value)
        elif name in URL_FIELDS:
            fields[name] = str(value).rstrip("/")
        else:
            fields[name] = value
    with conn() as c:
        columns = {r["name"] for r in c.execute("PRAGMA table_info(settings)")}
        columns -= {"id", "updated_at"}
        fields = {k: v for k, v in fields.items() if k in columns}
        if not fields:
            return []
        assignments = ", ".join(f"{k} = ?" for k in fields)
        c.execute(
            f"UPDATE settings SET {assignments}, updated_at = ? WHERE id = 1",
            (*fields.values(), now()),
        )
    return [name.removesuffix("_json") for name in fields]


# ---------------------------------------------------------------- account


def get_account() -> dict[str, Any]:
    with conn() as c:
        row = c.execute("SELECT * FROM account WHERE id = 1").fetchone()
    return dict(row)


def claim_account(username: str, password_hash: str) -> bool:
    """Replace the one-time password. False when it was replaced first, by anyone."""
    with conn() as c:
        cur = c.execute(
            "UPDATE account SET username = ?, password_hash = ?, one_time = 0, updated_at = ?"
            " WHERE id = 1 AND one_time = 1",
            (username, password_hash, now()),
        )
        return cur.rowcount == 1


def set_setup_step(step: str | None) -> None:
    """Move setup to `step`, None to end it. Once ended it never opens again."""
    with conn() as c:
        c.execute(
            "UPDATE account SET setup_step = ?, updated_at = ?"
            " WHERE id = 1 AND setup_step IS NOT NULL",
            (step, now()),
        )


def spend_totp_step(step: int) -> bool:
    """Mark a TOTP step used. False when it, or a later one, was used first."""
    with conn() as c:
        cur = c.execute(
            "UPDATE account SET totp_last_step = ?, updated_at = ?"
            " WHERE id = 1 AND totp_last_step < ?",
            (step, now(), step),
        )
        return cur.rowcount == 1


def update_account(**fields: Any) -> None:
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(
            f"UPDATE account SET {assignments}, updated_at = ? WHERE id = 1",
            (*fields.values(), now()),
        )


def create_session(token_hash: str, expires_at: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO sessions (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (token_hash, now(), expires_at),
        )


def session_expiry(token_hash: str, born_after: str = "") -> str | None:
    """When a live session expires, or None when there is no such live session.

    A session made at or before `born_after` is not live, whatever its expiry.
    """
    with conn() as c:
        row = c.execute(
            "SELECT expires_at FROM sessions WHERE token_hash = ? AND expires_at > ?"
            " AND created_at > ?",
            (token_hash, now(), born_after),
        ).fetchone()
    return None if row is None else str(row["expires_at"])


def extend_session(token_hash: str, expires_at: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (expires_at, token_hash)
        )


def delete_sessions(keep: str | None = None) -> None:
    """End every session, or every one but `keep`. Expired rows go with them."""
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token_hash IS NOT ?", (keep,))


def delete_session(token_hash: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def list_passkeys() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM passkeys ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]


def get_passkey(credential_id: str) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM passkeys WHERE id = ?", (credential_id,)).fetchone()
    return None if row is None else dict(row)


def add_passkey(
    *,
    credential_id: str,
    public_key: bytes,
    sign_count: int,
    rp_id: str,
    transports: list[str],
    label: str,
) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO passkeys (id, public_key, sign_count, rp_id, transports, label,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (credential_id, public_key, sign_count, rp_id, json.dumps(transports), label, now()),
        )


def passkey_used(credential_id: str, sign_count: int) -> None:
    with conn() as c:
        c.execute(
            "UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?",
            (sign_count, now(), credential_id),
        )


def delete_passkeys(credential_id: str | None = None) -> int:
    """Remove one passkey, or every one of them. Returns how many went."""
    with conn() as c:
        if credential_id is None:
            return c.execute("DELETE FROM passkeys").rowcount
        return c.execute("DELETE FROM passkeys WHERE id = ?", (credential_id,)).rowcount


# ---------------------------------------------------------------- cache


def cache_lookup(key: str) -> tuple[bool, Any]:
    """Whether a live row exists under `key`, and its value, which may be a stored None."""
    found, live, value = _cache_peek(key)
    return (True, value) if found and live else (False, None)


def _cache_peek(key: str) -> tuple[bool, bool, Any]:
    """Whether a row exists under `key`, whether it is still live, and its value."""
    with conn() as c:
        row = c.execute("SELECT value_json, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
    if row is None:
        return False, False, None
    return True, row["expires_at"] >= now(), json.loads(row["value_json"])


def expire_if(key: str, outdated: Callable[[Any], bool]) -> None:
    """Expire the answer kept under `key` when a fresher one contradicts it, `outdated`, so the
    next read asks its source again."""
    found, live, value = _cache_peek(key)
    if found and live and outdated(value):
        with conn() as c:
            c.execute("UPDATE cache SET expires_at = ? WHERE key = ?", (now(), key))


def cache_get(key: str) -> Any | None:
    return cache_lookup(key)[1]


@dataclass
class Stale:
    """What one API request may be answered with. Set per request by `main.serve_stale`.

    `wait` is a request asking for the fresh answer, `served` is set once any answer it got was
    past its lifetime.
    """

    wait: bool = False
    served: bool = False


STALE: contextvars.ContextVar[Stale | None] = contextvars.ContextVar("stale", default=None)

_refreshing: dict[str, asyncio.Task[Any]] = {}


# A lifetime, or how long to keep a given answer.
Lifetime = int | Callable[[Any], int]


def _refresh(key: str, ttl: Lifetime, fetch: Callable[[], Awaitable[Any]]) -> asyncio.Task[Any]:
    """One fetch of `key` at a time, however many ask for it, kept once it answers."""
    task = _refreshing.get(key)
    if task is not None:
        return task

    async def run() -> Any:
        value = await fetch()
        cache_put(key, value, ttl(value) if callable(ttl) else ttl)
        return value

    def done(finished: asyncio.Task[Any]) -> None:
        if _refreshing.get(key) is finished:
            del _refreshing[key]
        if not finished.cancelled() and (exc := finished.exception()) is not None:
            log.info("cache: refreshing %s failed: %s", key, exc)

    # A context of its own, so what it reads is asked for fresh and is not marked on the request
    # that started it.
    task = asyncio.create_task(run(), context=contextvars.Context())
    task.add_done_callback(done)
    _refreshing[key] = task
    return task


async def remember(key: str, ttl: Lifetime, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """The value kept under `key`, else what `fetch` answers, kept `ttl` seconds.

    A None answer is kept too, so what a source does not have is not asked for again. Past
    `ttl` the value is fetched again: a page is answered with the old one at once while it is,
    anything else waits for it. A fetch that fails leaves the old value in place and answers it.
    """
    found, live, value = _cache_peek(key)
    if live:
        return value
    task = _refresh(key, ttl, fetch)
    mark = STALE.get()
    if found and mark is not None and not mark.wait:
        mark.served = True
        return value
    try:
        # Shielded, so a page closed while it waits does not cancel the fetch for the rest.
        return await asyncio.shield(task)
    except Exception:
        if not found:
            raise
        return value


def cache_put(key: str, value: Any, ttl_seconds: int) -> None:
    expires = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
    with conn() as c:
        c.execute(
            "INSERT INTO cache (key, value_json, expires_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json,"
            " expires_at = excluded.expires_at",
            (key, json.dumps(value), expires),
        )


def cache_take(key: str) -> Any | None:
    """Read and delete one row in one statement, so a value can be spent only once."""
    with conn() as c:
        row = c.execute(
            "DELETE FROM cache WHERE key = ? RETURNING value_json, expires_at", (key,)
        ).fetchone()
    if row is None or row["expires_at"] < now():
        return None
    return json.loads(row["value_json"])


# How long an expired row is kept for `remember` to answer while it fetches it again.
STALE_KEEP = timedelta(days=30)


def cache_purge() -> None:
    """Delete every row expired past `STALE_KEEP`, and expired sessions. A read already ignores
    an expired row, this only reclaims the space."""
    kept_from = (datetime.now(UTC) - STALE_KEEP).isoformat()
    with conn() as c:
        c.execute("DELETE FROM cache WHERE expires_at < ?", (kept_from,))
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))


def cache_drop(prefix: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))


# ---------------------------------------------------------------- games


def upsert_games(games: list[dict[str, Any]]) -> None:
    """Write many games in one transaction.

    Discover stores hundreds at a time, and a connection per row would take seconds.
    """
    if not games:
        return
    with conn() as c:
        c.executemany(
            "INSERT INTO games (igdb_id, name, slug, summary, first_release_date, release_label,"
            " release_status,"
            " cover_image_id, artwork_image_id, platforms_json, exclusive_json, genres_json,"
            " rating, popularity, url,"
            " extra_json, companies_json, franchises_json, collections_json, cached_at)"
            " VALUES (:igdb_id, :name, :slug, :summary, :first_release_date, :release_label,"
            " :release_status,"
            " :cover_image_id,"
            " :artwork_image_id, :platforms_json, :exclusive_json, :genres_json, :rating,"
            " :popularity, :url,"
            " :extra_json, :companies_json, :franchises_json, :collections_json,"
            " :cached_at)"
            " ON CONFLICT (igdb_id) DO UPDATE SET name = excluded.name, slug = excluded.slug,"
            " summary = excluded.summary, first_release_date = excluded.first_release_date,"
            " release_label = excluded.release_label,"
            " release_status = excluded.release_status,"
            " cover_image_id = excluded.cover_image_id,"
            " artwork_image_id = excluded.artwork_image_id,"
            " platforms_json = excluded.platforms_json,"
            " exclusive_json = excluded.exclusive_json, genres_json = excluded.genres_json,"
            " rating = excluded.rating, popularity = excluded.popularity, url = excluded.url,"
            # The list view fetches a lean field set. Its rows must not wipe the full metadata
            # a detail view already stored.
            " extra_json = CASE WHEN excluded.extra_json = '{}' THEN games.extra_json"
            "  ELSE excluded.extra_json END,"
            " companies_json = excluded.companies_json,"
            " franchises_json = excluded.franchises_json,"
            " collections_json = excluded.collections_json,"
            " cached_at = excluded.cached_at",
            [_game_params(game) for game in games],
        )


def _game_params(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "igdb_id": game["igdb_id"],
        "name": game["name"],
        "slug": game.get("slug"),
        "summary": game.get("summary"),
        "first_release_date": game.get("first_release_date"),
        "release_label": game.get("release_label"),
        "release_status": game.get("release_status"),
        "cover_image_id": game.get("cover_image_id"),
        "artwork_image_id": game.get("artwork_image_id"),
        "platforms_json": json.dumps(game.get("platforms", [])),
        "exclusive_json": json.dumps(game.get("exclusive", [])),
        "genres_json": json.dumps(game.get("genres", [])),
        "rating": game.get("rating"),
        "popularity": game.get("popularity") or 0,
        "url": game.get("url"),
        "extra_json": json.dumps(game.get("extra", {})),
        "companies_json": json.dumps(game.get("company_ids", [])),
        "franchises_json": json.dumps(game.get("franchise_ids", [])),
        "collections_json": json.dumps(game.get("collection_ids", [])),
        "cached_at": now(),
    }


def _row_to_game(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "igdb_id": row["igdb_id"],
        "name": row["name"],
        "slug": row["slug"],
        "summary": row["summary"],
        "first_release_date": row["first_release_date"],
        "release_label": row["release_label"],
        "release_status": row["release_status"],
        "cover_image_id": row["cover_image_id"],
        "artwork_image_id": row["artwork_image_id"],
        "platforms": json.loads(row["platforms_json"]),
        "exclusive": json.loads(row["exclusive_json"]),
        "genres": json.loads(row["genres_json"]),
        "rating": row["rating"],
        "popularity": row["popularity"],
        "url": row["url"],
        "extra": json.loads(row["extra_json"]),
        "company_ids": json.loads(row["companies_json"]),
        "franchise_ids": json.loads(row["franchises_json"]),
        "collection_ids": json.loads(row["collections_json"]),
        "cached_at": row["cached_at"],
    }


def get_game(igdb_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM games WHERE igdb_id = ?", (igdb_id,)).fetchone()
    return None if row is None else _row_to_game(row)


def get_games(igdb_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not igdb_ids:
        return {}
    placeholders = ",".join("?" * len(igdb_ids))
    with conn() as c:
        rows = c.execute(
            f"SELECT * FROM games WHERE igdb_id IN ({placeholders})", igdb_ids
        ).fetchall()
    return {row["igdb_id"]: _row_to_game(row) for row in rows}


def get_detailed_game(igdb_id: int) -> dict[str, Any] | None:
    """A cached game, but only if it was stored with the full metadata.

    Discover stores a lean row for every game it lists. That is not enough for the detail
    view, so a lean row has to miss and be refetched.
    """
    game = get_game(igdb_id)
    if game is None or game["extra"].get("v") != EXTRA_VERSION:
        return None
    return game


# ---------------------------------------------------------------- requests


RequestStatus = Literal["monitored", "notified", "matched"]

LIVE_STATUSES = ("monitored", "notified", "matched")

# A game on PC, the only platform a grab is made for, `g` being its games row.
ON_PC = "EXISTS (SELECT 1 FROM json_each(g.platforms_json) WHERE value = 'PC')"


def _tracking() -> str:
    """Whether the requests row `r` is notified and still searched for, as SQL. Prowlarr
    searches for a notified game on PC until it is grabbed, and the API reports it as
    `tracking`. Stored, it stays `notified`."""
    if not get_settings().prowlarr_ready:
        return "0"
    return f"(r.status = 'notified' AND r.igdb_id IN (SELECT g.igdb_id FROM games g WHERE {ON_PC}))"


# Who made a game, as `hidden.game` reads it, `g` being its games row.
MADE_BY = "g.companies_json, g.franchises_json, g.collections_json"


def create_request(igdb_id: int) -> int:
    stamp = now()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO requests (igdb_id, status, created_at, updated_at)"
            " VALUES (?, 'monitored', ?, ?)",
            (igdb_id, stamp, stamp),
        )
    return int(cur.lastrowid or 0)


def _request(row: sqlite3.Row) -> dict[str, Any]:
    """A request as the API sends it. The release under review carries Prowlarr's key."""
    # A Row iterates its values, so its keys are asked for by name.
    return {k: row[k] for k in row.keys() if k not in ("review_json", "rejected_json")}  # noqa: SIM118


def list_requests() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT r.*, g.name AS game_name, g.cover_image_id, g.first_release_date,"
            f" g.release_label, g.release_status, g.exclusive_json, {MADE_BY},"
            f" {_tracking()} AS tracking"
            " FROM requests r JOIN games g ON g.igdb_id = r.igdb_id"
            # Soonest release first, undated last, so the list reads as what is coming next.
            " ORDER BY g.first_release_date IS NULL, g.first_release_date ASC,"
            " r.created_at DESC"
        ).fetchall()
    return [_shown(_request(row)) for row in rows]


def _shown(request: dict[str, Any]) -> dict[str, Any]:
    """The status the API reports, `tracking` for a notified game still searched for."""
    tracking = request.pop("tracking")
    return {**request, "status": "tracking"} if tracking else request


def notifiable_requests() -> list[dict[str, Any]]:
    """Monitored games, and only those.

    Notifications must never reach into the wider games table, which holds every game Discover
    has ever listed. The join to requests is what guarantees that, and there is no limit here
    on purpose: a cap would silently skip whatever fell off the end.
    """
    with conn() as c:
        rows = c.execute(
            "SELECT r.*, g.name AS game_name, g.first_release_date, g.release_label,"
            f" g.release_status, g.exclusive_json, {MADE_BY}"
            " FROM requests r JOIN games g ON g.igdb_id = r.igdb_id"
            f" WHERE r.status IN ({','.join('?' * len(LIVE_STATUSES))})"
            " ORDER BY g.first_release_date IS NULL, g.first_release_date ASC",
            LIVE_STATUSES,
        ).fetchall()
    return [dict(row) for row in rows]


def waiting_requests() -> list[dict[str, Any]]:
    """Monitored games on PC not grabbed yet, notified or not, with the name and PC date a grab
    is matched on. A game on consoles alone is notified and never grabbed."""
    with conn() as c:
        rows = c.execute(
            "SELECT r.*, g.name AS game_name, g.first_release_date"
            " FROM requests r JOIN games g ON g.igdb_id = r.igdb_id"
            f" WHERE r.status IN ('monitored', 'notified') AND {ON_PC}"
        ).fetchall()
    return [dict(row) for row in rows]


def get_request(request_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(
            "SELECT r.*, g.name AS game_name FROM requests r"
            " JOIN games g ON g.igdb_id = r.igdb_id WHERE r.id = ?",
            (request_id,),
        ).fetchone()
    return None if row is None else _request(row)


def claim_grab(request_id: int, release_name: str) -> bool:
    """Take a monitored game as found by this release. False when it was taken first."""
    with conn() as c:
        return (
            c.execute(
                "UPDATE requests SET status = 'matched', matched_release = ?, matched_at = ?,"
                " error = NULL, review_release = NULL, review_json = NULL, rejected_json = '[]',"
                " cleared_at = NULL, updated_at = ?"
                " WHERE id = ? AND status IN ('monitored', 'notified')",
                (release_name, now(), now(), request_id),
            ).rowcount
            == 1
        )


def release_grab(request_id: int, status: RequestStatus) -> None:
    """Hand a claimed game back to the `status` it had, its grab having failed."""
    with conn() as c:
        c.execute(
            "UPDATE requests SET status = ?, matched_release = NULL, matched_at = NULL,"
            " updated_at = ? WHERE id = ?",
            (status, now(), request_id),
        )


def put_in_review(request_id: int, release: dict[str, Any]) -> bool:
    """Hold a matched release for the user to confirm. False while another one waits, or once
    the game is found."""
    with conn() as c:
        return (
            c.execute(
                "UPDATE requests SET review_release = ?, review_json = ?, cleared_at = NULL,"
                " updated_at = ? WHERE id = ? AND status IN ('monitored', 'notified')"
                " AND review_json IS NULL",
                (release["title"], json.dumps(release), now(), request_id),
            ).rowcount
            == 1
        )


def review(request_id: int) -> dict[str, Any] | None:
    """The release held for the user to confirm, as Prowlarr returned it."""
    with conn() as c:
        row = c.execute(
            "SELECT review_json FROM requests WHERE id = ? AND status IN ('monitored', 'notified')",
            (request_id,),
        ).fetchone()
    return (
        None if row is None or row["review_json"] is None else dict(json.loads(row["review_json"]))
    )


def reject_review(request_id: int) -> None:
    """Never offer the release under review again, and leave the game waiting."""
    with conn() as c:
        c.execute(
            "UPDATE requests SET"
            " rejected_json = json_insert(rejected_json, '$[#]', review_release),"
            " review_release = NULL, review_json = NULL, updated_at = ?"
            " WHERE id = ? AND review_json IS NOT NULL",
            (now(), request_id),
        )


def rejected(request_id: int) -> set[str]:
    with conn() as c:
        row = c.execute("SELECT rejected_json FROM requests WHERE id = ?", (request_id,)).fetchone()
    return set() if row is None else set(json.loads(row["rejected_json"]))


def mark_downloaded(request_id: int) -> bool:
    """Record that a grab finished downloading. False when it already had."""
    with conn() as c:
        return (
            c.execute(
                "UPDATE requests SET downloaded_at = ?, updated_at = ?"
                " WHERE id = ? AND status = 'matched' AND downloaded_at IS NULL",
                (now(), now(), request_id),
            ).rowcount
            == 1
        )


def set_request_error(request_id: int, error: str) -> None:
    """Why the last grab for a game failed. A grab that goes through clears it."""
    with conn() as c:
        c.execute(
            "UPDATE requests SET error = ?, cleared_at = NULL, updated_at = ? WHERE id = ?",
            (redact.scrub(error), now(), request_id),
        )


def mark_release_notified(request_id: int, marker: str, *, done: bool) -> None:
    """Record the release notice sent, as `notices` marks it. `done`, the last of the schedule,
    makes a waiting game notified, and a notice for a date that moved makes it wait again."""
    with conn() as c:
        c.execute(
            "UPDATE requests SET notified_for = ?, updated_at = ?,"
            " status = CASE WHEN status = 'matched' THEN status"
            " WHEN ? THEN 'notified' ELSE 'monitored' END,"
            " cleared_at = CASE WHEN status = 'matched' OR ? THEN cleared_at END,"
            " notified_at = CASE WHEN ? THEN ? END WHERE id = ?",
            (marker, now(), done, done, done, now(), request_id),
        )


def live_request_for(igdb_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute(
            f"SELECT * FROM requests WHERE igdb_id = ?"
            f" AND status IN ({','.join('?' * len(LIVE_STATUSES))})"
            " ORDER BY created_at DESC LIMIT 1",
            (igdb_id, *LIVE_STATUSES),
        ).fetchone()
    return None if row is None else dict(row)


def request_status_map(igdb_ids: list[int]) -> dict[int, str]:
    if not igdb_ids:
        return {}
    placeholders = ",".join("?" * len(igdb_ids))
    with conn() as c:
        rows = c.execute(
            f"SELECT r.igdb_id, r.status, {_tracking()} AS tracking FROM requests r"
            f" WHERE r.igdb_id IN ({placeholders}) ORDER BY r.created_at ASC",
            igdb_ids,
        ).fetchall()
    return {row["igdb_id"]: "tracking" if row["tracking"] else row["status"] for row in rows}


# ---------------------------------------------------------------- what Robin tracks

# One table per category, each holding what is tracked there.
Table = Literal["requests", "comics", "reminders", "book_reminders"]

# The stored status of a row still waiting, and of one found.
WAITING: dict[Table, str] = {
    "requests": "monitored",
    "comics": "monitored",
    "reminders": "waiting",
    "book_reminders": "waiting",
}
FOUND: dict[Table, tuple[str, ...]] = {
    "requests": ("notified", "matched"),
    "comics": ("added",),
    "reminders": ("sent",),
    "book_reminders": ("sent",),
}


def rows(table: Table) -> list[dict[str, Any]]:
    """Every row, newest first."""
    with conn() as c:
        found = c.execute(f"SELECT * FROM {table} ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in found]


def waiting(table: Table) -> list[dict[str, Any]]:
    with conn() as c:
        found = c.execute(f"SELECT * FROM {table} WHERE status = ?", (WAITING[table],)).fetchall()
    return [dict(row) for row in found]


def row(table: Table, row_id: int) -> dict[str, Any] | None:
    with conn() as c:
        found = c.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return None if found is None else dict(found)


def delete_row(table: Table, row_id: int) -> None:
    with conn() as c:
        c.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def clear_found(table: Table) -> int:
    """Take found rows off the Monitored page. Returns how many.

    Only Monitored hides them: the row stays, so the item still reads as found everywhere else
    and cannot be monitored a second time. A game comes back once it needs the user again: it
    waits on a moved date, is grabbed, holds a release for review, or a grab fails. A game still
    tracked is not cleared.
    """
    tracked = f" AND NOT {_tracking()}" if table == "requests" else ""
    with conn() as c:
        return c.execute(
            f"UPDATE {table} AS r SET cleared_at = ?"
            f" WHERE status IN ({','.join('?' * len(FOUND[table]))}) AND cleared_at IS NULL"
            + tracked,
            (now(), *FOUND[table]),
        ).rowcount


def mark_notified(
    table: Literal["reminders", "book_reminders"], row_id: int, notified_for: str, *, done: bool
) -> None:
    """Record the notice sent. `done` ends a reminder for one release, one following a show or
    a series stays waiting for the next."""
    with conn() as c:
        c.execute(
            f"UPDATE {table} SET notified_for = ?, sent_at = ?,"
            " status = CASE WHEN ? THEN 'sent' ELSE status END WHERE id = ?",
            (notified_for, now(), done, row_id),
        )


# ---------------------------------------------------------------- comics


def monitor_comic(
    *,
    issue_id: str,
    title: str,
    series: str,
    year: int,
    publisher: str,
    url: str,
    cover: str | None,
    volume_id: int | None = None,
) -> dict[str, Any]:
    """Monitoring a series already monitored, from this issue or any other, returns the
    existing row."""
    with conn() as c:
        if volume_id is not None:
            row = c.execute("SELECT * FROM comics WHERE volume_id = ?", (volume_id,)).fetchone()
            if row is not None:
                return dict(row)
        c.execute(
            "INSERT INTO comics (issue_id, volume_id, title, series, year, publisher, url, cover,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'monitored', ?)"
            " ON CONFLICT (issue_id) DO NOTHING",
            (issue_id, volume_id, title, series, year, publisher, url, cover, now()),
        )
        row = c.execute("SELECT * FROM comics WHERE issue_id = ?", (issue_id,)).fetchone()
    return dict(row)


def mark_comic_added(comic_id: int, suwayomi_id: int, issues: int) -> None:
    """`issues` is how many the source had when the series was added, never updated after."""
    with conn() as c:
        c.execute(
            "UPDATE comics SET status = 'added', suwayomi_id = ?, issues = ?, added_at = ?"
            " WHERE id = ?",
            (suwayomi_id, issues, now(), comic_id),
        )


# ---------------------------------------------------------------- reminders


def add_reminder(
    *,
    kind: str,
    tmdb_id: int,
    release_type: str,
    title: str,
    poster: str | None,
    date: str | None,
    platform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Setting a reminder already set returns the existing row."""
    with conn() as c:
        c.execute(
            "INSERT INTO reminders (kind, tmdb_id, release_type, title, poster, date, platform,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting', ?)"
            " ON CONFLICT (kind, tmdb_id, release_type) DO NOTHING",
            (
                kind,
                tmdb_id,
                release_type,
                title,
                poster,
                date,
                (platform or {}).get("name"),
                now(),
            ),
        )
        row = c.execute(
            "SELECT * FROM reminders WHERE kind = ? AND tmdb_id = ? AND release_type = ?",
            (kind, tmdb_id, release_type),
        ).fetchone()
    return dict(row)


def update_reminder(
    reminder_id: int,
    date: str | None,
    platform: dict[str, Any] | None,
    title: str,
    poster: str | None,
) -> None:
    """A reminder as its title now reads, so Home and Monitored follow the source."""
    with conn() as c:
        c.execute(
            "UPDATE reminders SET date = ?, platform = ?, title = ?, poster = ? WHERE id = ?",
            (date, (platform or {}).get("name"), title, poster, reminder_id),
        )


def set_dated_as(table: Table, row_id: int, dated_as: str) -> None:
    """What a monitored item's date was last read as, for `notices.date_change`."""
    with conn() as c:
        c.execute(f"UPDATE {table} SET dated_as = ? WHERE id = ?", (dated_as, row_id))


# ---------------------------------------------------------------- book reminders


def add_book_reminder(
    *,
    kind: str,
    hardcover_id: int,
    book_id: int,
    title: str,
    cover: str | None,
    date: str | None,
    next_title: str | None = None,
) -> dict[str, Any]:
    """Setting a reminder already set returns the existing row."""
    with conn() as c:
        c.execute(
            "INSERT INTO book_reminders (kind, hardcover_id, book_id, title, cover, date,"
            " next_title, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting', ?)"
            " ON CONFLICT (kind, hardcover_id) DO NOTHING",
            (kind, hardcover_id, book_id, title, cover, date, next_title, now()),
        )
        row = c.execute(
            "SELECT * FROM book_reminders WHERE kind = ? AND hardcover_id = ?",
            (kind, hardcover_id),
        ).fetchone()
    return dict(row)


def update_book_reminder(
    reminder_id: int, date: str | None, next_title: str | None, title: str, cover: str | None
) -> None:
    """A book reminder as its book now reads, so Home and Monitored follow the source."""
    with conn() as c:
        c.execute(
            "UPDATE book_reminders SET date = ?, next_title = ?, title = ?, cover = ? WHERE id = ?",
            (date, next_title, title, cover, reminder_id),
        )


# ---------------------------------------------------------------- favourites

FavouriteCategory = Literal["games", "comics", "screens", "books"]


def _favourite(row: sqlite3.Row) -> dict[str, Any]:
    """A favourite with `ids`, every source id it covers, its own first."""
    found = dict(row)
    found["ids"] = json.loads(found.pop("source_ids_json") or "[]") or [found["source_id"]]
    return found


def favourites(category: FavouriteCategory | None = None) -> list[dict[str, Any]]:
    """Every favourite, or one category's, newest first."""
    with conn() as c:
        found = c.execute(
            "SELECT * FROM favourites WHERE ? IS NULL OR category = ? ORDER BY created_at DESC",
            (category, category),
        ).fetchall()
    return [_favourite(row) for row in found]


def add_favourite(
    category: FavouriteCategory,
    kind: str,
    source_id: int,
    name: str,
    image: str | None,
    ids: list[int] | None = None,
) -> dict[str, Any]:
    """Favouriting one already a favourite returns the existing row. `ids` is every source id
    it covers, for studios TMDB lists more than once under one name."""
    with conn() as c:
        c.execute(
            "INSERT INTO favourites"
            " (category, kind, source_id, source_ids_json, name, image, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (category, kind, source_id) DO NOTHING",
            (category, kind, source_id, json.dumps(ids or [source_id]), name, image, now()),
        )
        row = c.execute(
            "SELECT * FROM favourites WHERE category = ? AND kind = ? AND source_id = ?",
            (category, kind, source_id),
        ).fetchone()
    return _favourite(row)


def maker_filters(category: FavouriteCategory | None = None) -> list[dict[str, Any]]:
    """Every maker always hidden or shown, or one category's, newest first, each with `ids`."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM maker_filters WHERE ? IS NULL OR category = ? ORDER BY created_at DESC",
            (category, category),
        ).fetchall()
    return [_favourite(row) for row in rows]


MakerMode = Literal["hide", "show"]


def filter_maker(
    mode: MakerMode,
    category: FavouriteCategory,
    kind: str,
    source_id: int,
    name: str,
    ids: list[int],
) -> dict[str, Any]:
    """Always hide or always show a maker, in place of whichever it was. Hidden, it stops being
    a favourite, the two cannot both hold."""
    with conn() as c:
        c.execute(
            "INSERT INTO maker_filters"
            " (mode, category, kind, source_id, source_ids_json, name, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (category, kind, source_id)"
            " DO UPDATE SET mode = excluded.mode",
            (mode, category, kind, source_id, json.dumps(ids or [source_id]), name, now()),
        )
        if mode == "hide":
            c.execute(
                "DELETE FROM favourites WHERE category = ? AND kind = ? AND source_id = ?",
                (category, kind, source_id),
            )
        row = c.execute(
            "SELECT * FROM maker_filters WHERE category = ? AND kind = ? AND source_id = ?",
            (category, kind, source_id),
        ).fetchone()
    return _favourite(row)


def unfilter_maker(maker_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM maker_filters WHERE id = ?", (maker_id,))


def delete_favourite(favourite_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM favourites WHERE id = ?", (favourite_id,))


def hold_notice(
    category: Category,
    title: str,
    message: str,
    tags: str,
    click: str | None,
    attach: str | None,
) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO held_notices (category, title, message, tags, click, attach, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (category, title, message, tags, click, attach, now()),
        )


def held_notices() -> dict[Category, list[dict[str, Any]]]:
    """Every notice quiet hours kept, by category, oldest first."""
    found: dict[Category, list[dict[str, Any]]] = {}
    with conn() as c:
        for row in c.execute("SELECT * FROM held_notices ORDER BY id"):
            found.setdefault(row["category"], []).append(dict(row))
    return found


def drop_held(ids: list[int]) -> None:
    with conn() as c:
        c.executemany("DELETE FROM held_notices WHERE id = ?", [(i,) for i in ids])


def favourite_noticed(category: FavouriteCategory) -> dict[str, str]:
    """The notice last sent for each release of a favourite in the category, by its key. One
    kept from when a release was announced once reads as every notice sent."""
    with conn() as c:
        found = c.execute(
            "SELECT title, notified_for FROM favourite_notices WHERE category = ?", (category,)
        ).fetchall()
    return {row["title"]: row["notified_for"] or f"*|{SENT_ALL}" for row in found}


def mark_favourite_noticed(category: FavouriteCategory, title: str, marker: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO favourite_notices (category, title, notified_for, sent_at)"
            " VALUES (?, ?, ?, ?) ON CONFLICT (category, title)"
            " DO UPDATE SET notified_for = excluded.notified_for, sent_at = excluded.sent_at",
            (category, title, marker, now()),
        )


def favourite_monitored(category: FavouriteCategory) -> set[str]:
    """The releases of a favourite in the category Robin has monitored on its own."""
    with conn() as c:
        found = c.execute(
            "SELECT title FROM favourite_monitored WHERE category = ?", (category,)
        ).fetchall()
    return {row["title"] for row in found}


def library_monitored() -> set[str]:
    """The titles Robin has monitored on its own because Radarr or Sonarr holds them."""
    with conn() as c:
        found = c.execute("SELECT title FROM library_monitored").fetchall()
    return {row["title"] for row in found}


def drop_undated_library_shows() -> int:
    """Forget the shows Robin monitored because Sonarr holds them that have no season premiere
    dated, so each is monitored again once one is. Returns how many."""
    with conn() as c:
        keys = [
            row["title"]
            for row in c.execute(
                "SELECT l.title FROM library_monitored l JOIN reminders r"
                " ON l.title = 'tv-' || r.tmdb_id"
                " WHERE r.kind = 'tv' AND r.status = 'waiting' AND r.date IS NULL"
            ).fetchall()
        ]
        for key in keys:
            c.execute("DELETE FROM library_monitored WHERE title = ?", (key,))
            c.execute(
                "DELETE FROM reminders WHERE kind = 'tv' AND tmdb_id = ?",
                (int(key.removeprefix("tv-")),),
            )
    return len(keys)


def mark_library_monitored(title: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO library_monitored (title, created_at) VALUES (?, ?)",
            (title, now()),
        )


def mark_favourite_monitored(category: FavouriteCategory, title: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO favourite_monitored (category, title, created_at)"
            " VALUES (?, ?, ?)",
            (category, title, now()),
        )


# ---------------------------------------------------------------- countdowns


def countdowns() -> list[dict[str, Any]]:
    """Every countdown, soonest first."""
    with conn() as c:
        rows = c.execute("SELECT * FROM countdowns ORDER BY date, created_at").fetchall()
    return [dict(row) for row in rows]


def add_countdown(
    category: str, target: str, title: str, image: str | None, tag: str | None, date: str
) -> dict[str, Any]:
    """Count down to an item. One already counted down to takes what is given."""
    with conn() as c:
        c.execute(
            "INSERT INTO countdowns (category, target, title, image, tag, date, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (target)"
            " DO UPDATE SET date = excluded.date, tag = excluded.tag, title = excluded.title,"
            " image = excluded.image",
            (category, target, title, image, tag, date, now()),
        )
        row = c.execute("SELECT * FROM countdowns WHERE target = ?", (target,)).fetchone()
    return dict(row)


def delete_countdown(countdown_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM countdowns WHERE id = ?", (countdown_id,))
