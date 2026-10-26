PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS games (
    igdb_id            INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL,
    slug               TEXT,
    summary            TEXT,
    first_release_date INTEGER,
    release_label      TEXT,
    release_status     TEXT,
    cover_image_id     TEXT,
    artwork_image_id   TEXT,
    platforms_json     TEXT    NOT NULL DEFAULT '[]',
    -- The platform families, igdb.PLATFORMS keys, a game is only on, when two or fewer.
    exclusive_json     TEXT    NOT NULL DEFAULT '[]',
    genres_json        TEXT    NOT NULL DEFAULT '[]',
    rating             REAL,
    popularity         INTEGER NOT NULL DEFAULT 0,
    url                TEXT,
    extra_json         TEXT    NOT NULL DEFAULT '{}',
    -- Every company involved, developer or publisher, by IGDB id. Favourites match on it.
    companies_json     TEXT    NOT NULL DEFAULT '[]',
    -- Its franchises and series (IGDB collections), by id, matched by favourites the same way.
    franchises_json    TEXT    NOT NULL DEFAULT '[]',
    collections_json   TEXT    NOT NULL DEFAULT '[]',
    cached_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    igdb_id         INTEGER NOT NULL REFERENCES games (igdb_id),
    -- 'notified' once the last notice of the games schedule went out for its date, 'matched'
    -- once a release was grabbed, which happens once ever. A notified game is still grabbed.
    status          TEXT    NOT NULL CHECK (status IN ('monitored', 'notified', 'matched')),
    matched_release TEXT,
    matched_at      TEXT,
    -- Set once qBittorrent has the grab complete, so it still reads as downloaded once the
    -- torrent is gone from it.
    downloaded_at   TEXT,
    -- A matched release PreDB could not vouch for, waiting for the user to confirm it: its
    -- name, and the release as Prowlarr returned it, which carries Prowlarr's key and never
    -- leaves Robin. Rejected release names are never offered again. Both go once it is found.
    review_release  TEXT,
    review_json     TEXT,
    rejected_json   TEXT    NOT NULL DEFAULT '[]',
    -- The release notice last sent, as `notices` marks it, and when the last one went out.
    notified_for    TEXT,
    notified_at     TEXT,
    -- The date it was last read as, a full day, a game's partial date or empty while undated,
    -- for `notices.date_change`. NULL until it is first read.
    dated_as        TEXT,
    -- Why the last grab failed, cleared by one that goes through.
    error           TEXT,
    -- Set when the Notified panel on Monitored is cleared. Hides the row there and nowhere else.
    cleared_at      TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS requests_igdb_id ON requests (igdb_id);
CREATE INDEX IF NOT EXISTS requests_created_at ON requests (created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    twitch_client_id         TEXT NOT NULL DEFAULT '',
    twitch_client_secret     TEXT NOT NULL DEFAULT '',
    prowlarr_url             TEXT NOT NULL DEFAULT '',
    prowlarr_api_key         TEXT NOT NULL DEFAULT '',
    prowlarr_indexer_ids_json TEXT NOT NULL DEFAULT '[]',
    -- Release groups outside the scene, which PreDB never lists, so a release from one is
    -- grabbed without asking it.
    p2p_groups_json          TEXT NOT NULL DEFAULT '["GOG","voices38"]',
    -- The Home panels in order, each with whether it is hidden. Empty means the default.
    home_layout_json         TEXT NOT NULL DEFAULT '[]',
    -- What each page shows when its address names nothing, by page and then control.
    page_defaults_json       TEXT NOT NULL DEFAULT '{}',
    -- The robin Robin is coloured as, and whether it is dark, light or follows the system.
    theme                    TEXT NOT NULL DEFAULT 'european',
    scheme                   TEXT NOT NULL DEFAULT 'dark',
    -- Comics, from Metron.
    metron_token             TEXT NOT NULL DEFAULT '',
    suwayomi_url             TEXT NOT NULL DEFAULT '',
    suwayomi_source_id       TEXT NOT NULL DEFAULT '',
    qbittorrent_url          TEXT NOT NULL DEFAULT '',
    qbittorrent_api_key      TEXT NOT NULL DEFAULT '',
    qbittorrent_category     TEXT NOT NULL DEFAULT 'games',
    -- Whether a monitored game grabs only a release its tracker marks freeleech.
    freeleech_only           INTEGER NOT NULL DEFAULT 1,
    tmdb_token               TEXT NOT NULL DEFAULT '',
    tmdb_region              TEXT NOT NULL DEFAULT 'US',
    tmdb_language            TEXT NOT NULL DEFAULT 'en-US',
    -- What Screens hides: original languages, genre ids per kind and release types. A title
    -- carrying a hidden value is left out unless it carries a genre of its kind always shown.
    tmdb_hidden_languages_json     TEXT NOT NULL DEFAULT '[]',
    tmdb_hidden_movie_genres_json  TEXT NOT NULL DEFAULT '[]',
    tmdb_hidden_tv_genres_json     TEXT NOT NULL DEFAULT '[]',
    tmdb_hidden_release_types_json TEXT NOT NULL DEFAULT '[]',
    tmdb_shown_movie_genres_json   TEXT NOT NULL DEFAULT '[]',
    tmdb_shown_tv_genres_json      TEXT NOT NULL DEFAULT '[]',
    -- Radarr and Sonarr. A profile of 0 and an empty root are the first the app lists.
    radarr_url               TEXT NOT NULL DEFAULT '',
    radarr_api_key           TEXT NOT NULL DEFAULT '',
    radarr_profile_id        INTEGER NOT NULL DEFAULT 0,
    radarr_root              TEXT NOT NULL DEFAULT '',
    radarr_add               INTEGER NOT NULL DEFAULT 0,
    sonarr_url               TEXT NOT NULL DEFAULT '',
    sonarr_api_key           TEXT NOT NULL DEFAULT '',
    sonarr_profile_id        INTEGER NOT NULL DEFAULT 0,
    sonarr_root              TEXT NOT NULL DEFAULT '',
    sonarr_add               INTEGER NOT NULL DEFAULT 0,
    -- Books, from Hardcover. What is hidden: literary types, categories, every one but Book
    -- (1) on a fresh install, and genre tag slugs, then the genres always shown.
    hardcover_token          TEXT NOT NULL DEFAULT '',
    books_hidden_literary_types_json TEXT NOT NULL DEFAULT '[]',
    books_hidden_categories_json     TEXT NOT NULL DEFAULT '[2,3,4,5,6,7,8,9,10]',
    books_hidden_genres_json         TEXT NOT NULL DEFAULT '[]',
    books_shown_genres_json          TEXT NOT NULL DEFAULT '[]',
    -- Games. The platform families hidden: a game on none other is left out.
    games_hidden_platforms_json TEXT NOT NULL DEFAULT '[]',
    -- When each category's dated notices go out, each {"days": before, "hour": local}. One
    -- the day before is always among them.
    games_schedule_json      TEXT NOT NULL DEFAULT '[{"days":1,"hour":9}]',
    comics_schedule_json     TEXT NOT NULL DEFAULT '[{"days":1,"hour":9}]',
    screen_schedule_json     TEXT NOT NULL DEFAULT '[{"days":1,"hour":9}]',
    books_schedule_json      TEXT NOT NULL DEFAULT '[{"days":1,"hour":9}]',
    -- Quiet hours per category, [start, end] in local hours, empty for none.
    games_quiet_json         TEXT NOT NULL DEFAULT '[]',
    comics_quiet_json        TEXT NOT NULL DEFAULT '[]',
    comics_digest_publishers_json TEXT NOT NULL DEFAULT '[]',
    screen_quiet_json        TEXT NOT NULL DEFAULT '[]',
    books_quiet_json         TEXT NOT NULL DEFAULT '[]',
    -- Where notifications go, each {"id", "service", "values", "places"}.
    notify_destinations_json TEXT NOT NULL DEFAULT '[]',
    -- Whether each category sends notifications.
    games_notify             INTEGER NOT NULL DEFAULT 1,
    comics_notify            INTEGER NOT NULL DEFAULT 1,
    screen_notify            INTEGER NOT NULL DEFAULT 1,
    books_notify             INTEGER NOT NULL DEFAULT 1,
    -- Whether a favourite's new releases are announced.
    games_favourites         INTEGER NOT NULL DEFAULT 1,
    screen_favourites        INTEGER NOT NULL DEFAULT 1,
    books_favourites         INTEGER NOT NULL DEFAULT 1,
    comics_favourites        INTEGER NOT NULL DEFAULT 1,
    -- Whether a favourite's new releases are monitored on their own.
    games_favourites_monitor INTEGER NOT NULL DEFAULT 0,
    screen_favourites_monitor INTEGER NOT NULL DEFAULT 0,
    books_favourites_monitor INTEGER NOT NULL DEFAULT 0,
    comics_favourites_monitor INTEGER NOT NULL DEFAULT 0,
    -- Backups, sealed with the passphrase, written daily at a local hour while on.
    backup_passphrase        TEXT NOT NULL DEFAULT '',
    backups                  INTEGER NOT NULL DEFAULT 1,
    backup_hour              INTEGER NOT NULL DEFAULT 3,
    backup_keep              INTEGER NOT NULL DEFAULT 7,
    updated_at               TEXT NOT NULL
);

-- A comic series monitored from its #1. `year` is the week of that #1, and a source series
-- started earlier is another run of the same name.
CREATE TABLE IF NOT EXISTS comics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    TEXT    NOT NULL UNIQUE,
    -- Its series on Metron, null for one monitored from LOCG. One row per series.
    series_id   INTEGER,
    title       TEXT    NOT NULL,
    series      TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    publisher   TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL,
    cover       TEXT,
    status      TEXT    NOT NULL CHECK (status IN ('monitored', 'added')),
    suwayomi_id INTEGER,
    -- Issues on the source when the series was added. Zero means it was found before its first.
    issues      INTEGER,
    added_at    TEXT,
    -- Set when the Found panel on Monitored is cleared. Hides the row there and nowhere else.
    cleared_at  TEXT,
    created_at  TEXT    NOT NULL
);

-- A Remind me on a movie or show. A movie's is for one release type in the region and is done
-- once its last notice is sent. A show's covers every season premiere until removed.
-- `notified_for` is the notice last sent, as `notices` marks it.
CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK (kind IN ('movie', 'tv')),
    tmdb_id      INTEGER NOT NULL,
    release_type TEXT    NOT NULL DEFAULT '',
    title        TEXT    NOT NULL,
    poster       TEXT,
    date         TEXT,
    -- The platform a digital release is on, as last read.
    platform     TEXT,
    status       TEXT    NOT NULL CHECK (status IN ('waiting', 'sent')),
    notified_for TEXT,
    -- The date it was last read as, a full day, a game's partial date or empty while undated,
    -- for `notices.date_change`. NULL until it is first read.
    dated_as     TEXT,
    sent_at      TEXT,
    -- Set when the Found panel on Monitored is cleared. Hides the row there and nowhere else.
    cleared_at   TEXT,
    created_at   TEXT    NOT NULL,
    UNIQUE (kind, tmdb_id, release_type)
);

-- A Monitor on a book, done once its last notice is sent. `notified_for` is the notice last
-- sent, as `notices` marks it. A series is followed as a favourite.
CREATE TABLE IF NOT EXISTS book_reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK (kind IN ('book', 'series')),
    -- The book, or the series.
    hardcover_id INTEGER NOT NULL,
    -- The book it was set from, which the dialog opens.
    book_id      INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    cover        TEXT,
    date         TEXT,
    -- A series' next entry, as last read.
    next_title   TEXT,
    status       TEXT    NOT NULL CHECK (status IN ('waiting', 'sent')),
    notified_for TEXT,
    -- The date it was last read as, a full day, a game's partial date or empty while undated,
    -- for `notices.date_change`. NULL until it is first read.
    dated_as     TEXT,
    sent_at      TEXT,
    -- Set when the Found panel on Monitored is cleared. Hides the row there and nowhere else.
    cleared_at   TEXT,
    created_at   TEXT    NOT NULL,
    UNIQUE (kind, hardcover_id)
);

-- What a release can come from, starred: a game company, franchise or series on IGDB, a series,
-- person or publisher on Metron, a person, studio or network on TMDB, an author or series on
-- Hardcover. `source_id` is the id the source
-- gives it. A changed kind CHECK is applied by `db._rebuild`.
CREATE TABLE IF NOT EXISTS favourites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL CHECK (category IN ('games', 'comics', 'screens', 'books')),
    kind       TEXT    NOT NULL
               CHECK (kind IN ('company', 'franchise', 'collection', 'person', 'studio', 'network', 'author', 'series', 'publisher')),
    source_id  INTEGER NOT NULL,
    -- Every id it covers, `source_id` among them: TMDB lists one studio under several ids.
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    name       TEXT    NOT NULL,
    image      TEXT,
    created_at TEXT    NOT NULL,
    UNIQUE (category, kind, source_id)
);

-- What releases come from, filtered as a genre is: `hide` leaves out everything it made
-- wherever Settings hides, `show` brings back what it made that something else hides. One mode
-- at a time. Kinds as in `favourites`.
CREATE TABLE IF NOT EXISTS maker_filters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mode       TEXT    NOT NULL CHECK (mode IN ('hide', 'show')),
    category   TEXT    NOT NULL CHECK (category IN ('games', 'comics', 'screens', 'books')),
    kind       TEXT    NOT NULL
               CHECK (kind IN ('company', 'franchise', 'collection', 'person', 'studio', 'network', 'author', 'series', 'publisher')),
    source_id  INTEGER NOT NULL,
    -- Every id it covers, `source_id` among them, as for a favourite.
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    UNIQUE (category, kind, source_id)
);

-- A countdown on Home to an item's release, by the dialog parameter that opens it, `game=12`.
-- `date` is the release as it was last read, YYYY-MM-DD.
CREATE TABLE IF NOT EXISTS countdowns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL,
    target     TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    image      TEXT,
    tag        TEXT,
    date       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

-- A release announced for a favourite. `title` is the category's own key for it: an IGDB id,
-- `movie-<id>` or `tv-<id>`, a Hardcover book id. `notified_for` is the notice last sent, as
-- `notices` marks it, and NULL on a row kept from when a release was announced once.
CREATE TABLE IF NOT EXISTS favourite_notices (
    category     TEXT NOT NULL,
    title        TEXT NOT NULL,
    notified_for TEXT,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (category, title)
);

-- A title Robin monitored on its own because Radarr or Sonarr holds it, `movie-<id>` or
-- `tv-<id>`, so one the user stops monitoring stays stopped.
CREATE TABLE IF NOT EXISTS library_monitored (
    title      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

-- A favourite's release Robin monitored on its own, keyed as in `favourite_notices`, so one the
-- user stops monitoring stays stopped.
CREATE TABLE IF NOT EXISTS favourite_monitored (
    category   TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (category, title)
);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- The one account. Its first password is printed at start and only signs in to set another.
CREATE TABLE IF NOT EXISTS account (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    username       TEXT    NOT NULL DEFAULT 'admin',
    password_hash  TEXT,
    -- 1 while the password is the one printed at start.
    one_time       INTEGER NOT NULL DEFAULT 0,
    -- The setup step to open at, '' for the first. NULL once setup is done, or never shown.
    setup_step     TEXT,
    -- Base32 TOTP secret, NULL while two factor is off.
    totp_secret    TEXT,
    -- The last time step a code was accepted for, so a code cannot be used twice.
    totp_last_step INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT    NOT NULL
);

-- Only a SHA-256 of each session token is kept.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- A WebAuthn credential. `rp_id` is the host it was created on, and it only signs in there.
CREATE TABLE IF NOT EXISTS passkeys (
    id           TEXT    PRIMARY KEY,
    public_key   BLOB    NOT NULL,
    sign_count   INTEGER NOT NULL DEFAULT 0,
    rp_id        TEXT    NOT NULL,
    transports   TEXT    NOT NULL DEFAULT '[]',
    label        TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    last_used_at TEXT
);

-- A notice its category's quiet hours kept, sent once they end.
CREATE TABLE IF NOT EXISTS held_notices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '',
    click      TEXT,
    attach     TEXT,
    created_at TEXT NOT NULL
);
