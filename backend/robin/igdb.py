"""IGDB client. Auth is Twitch client credentials, queries are apicalypse over POST.

IGDB allows 4 requests per second and 8 in flight. Every call, the token's included, goes
through its `upstream` limit, which keeps inside that and stops asking once IGDB says slow down.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

from robin import db, upstream
from robin.filters import fold_to_ascii

log = logging.getLogger(__name__)

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_BASE = "https://api.igdb.com/v4"
IMAGE_BASE = "https://images.igdb.com/igdb/image/upload"

TOKEN_CACHE_KEY = "igdb:token"
POPULARITY_TYPES_CACHE_KEY = "igdb:popularity_types"
# The version is part of the key so a release that changes the stored shape rebuilds the
# pool instead of serving rows that predate the change.
DISCOVER_CACHE_PREFIX = "igdb:discover:v14:"

POPULARITY_TYPES_TTL = 24 * 3600
# As every category's page and detail.
DISCOVER_TTL = 3600
DETAIL_TTL = 12 * 3600

PREFERRED_POPULARITY_NAME = "wishlist"

# Enough to draw a poster. Discover pulls hundreds of these at a time.
LIST_FIELDS = (
    "fields name,slug,summary,first_release_date,total_rating,total_rating_count,hypes,url,"
    "cover.image_id,artworks.image_id,platforms.id,platforms.abbreviation,platforms.name,"
    "genres.name,release_dates.date,release_dates.date_format,release_dates.human,"
    "release_dates.platform,release_dates.status.name,involved_companies.company,franchises,"
    "collections;"
)

# Everything the detail view shows. Only ever fetched one game at a time.
GAME_FIELDS = (
    "fields name,slug,summary,storyline,first_release_date,total_rating,total_rating_count,"
    "aggregated_rating,aggregated_rating_count,hypes,url,cover.image_id,artworks.image_id,"
    "screenshots.image_id,platforms.id,platforms.abbreviation,platforms.name,genres.name,"
    "themes.name,game_modes.name,player_perspectives.name,game_engines.name,franchises.name,"
    "collections.name,involved_companies.company.name,involved_companies.developer,involved_companies.publisher,"
    "videos.video_id,videos.name,release_dates.date,release_dates.date_format,"
    "release_dates.human,release_dates.platform,release_dates.status.name;"
)

# Robin grabs PC releases only, and stores the PC as its abbreviation.
PC_PLATFORM_ID = 6
PC = "PC"

# What Discover and a favourite's releases list, by the family Settings and the page pick
# from: the PC, and PlayStation, Xbox and Nintendo's current consoles. IGDB keeps games
# cancelled on older ones as TBA forever.
PLATFORMS: dict[str, frozenset[int]] = {
    "pc": frozenset({PC_PLATFORM_ID}),
    "playstation": frozenset({48, 167}),  # PS4, PS5
    "xbox": frozenset({49, 169}),  # One, Series X|S
    "nintendo": frozenset({130, 508}),  # Switch 1 and 2
}
Platform = Literal["pc", "playstation", "xbox", "nintendo"]
SHOWN_PLATFORMS: frozenset[int] = frozenset().union(*PLATFORMS.values())

# A game on this many of the families or fewer is tagged with them.
EXCLUSIVE_FAMILIES = 2


def exclusive(platform_ids: list[int]) -> list[str]:
    """The families a game is only on, in `PLATFORMS` order, or none when it is on more than
    two of them or on none."""
    families = [f for f, ids in PLATFORMS.items() if not ids.isdisjoint(platform_ids)]
    return families if len(families) <= EXCLUSIVE_FAMILIES else []


def platforms(hidden: list[str], pick: str = "") -> frozenset[int]:
    """The platform ids listed: every family Settings does not hide, and every one while it
    hides them all. The page's pick narrows that to one, never to a family Settings hides."""
    shown = [f for f in PLATFORMS if f not in hidden]
    families = [pick] if pick in shown else shown
    return frozenset().union(*(PLATFORMS[f] for f in families)) or SHOWN_PLATFORMS


# IGDB stores an imprecise release as the last day it could fall on, so a game slated for
# "Q2 2026" arrives as 30 June and one slated for "2026" as 31 December. Robin only recognises
# a date IGDB is certain of; anything vaguer is TBA, which keeps it out of the release order
# and out of the notifications that fire the day before a release.
DATE_EXACT_DAY = 0
DATE_TBD = 7

# IGDB names the status of every release, and only two of them are releases Robin can act on:
# the full one the whole world gets, and Early Access while no full date exists yet. Paid
# advanced access, alphas, betas and cancelled entries are dropped rather than ranked. An entry
# with no status at all is a plain release, which is the assumption everywhere else.
FULL_RELEASE_STATUS = "Full Release"
EARLY_ACCESS_STATUS = "Early Access"
RELEASE_RANKS = {FULL_RELEASE_STATUS: 0, EARLY_ACCESS_STATUS: 1}

# Main Game, Standalone Expansion, Remake, Remaster, Expanded Game, Port. Keeps mods, DLC,
# bundles and update entries out of search results, which is where the junk lives.
REAL_GAME_TYPES = "(0,4,8,9,10,11)"

# How much of the popularity ranking Discover considers. Built in four calls, cached, then
# paged from the stored games, so the release date order applies across the whole list.
DISCOVER_POOL = 300

# The most IGDB answers in one query. Dated upcoming games are asked for this many by hype, so a
# modestly followed game with a date is not crowded out by the TBA ones.
IGDB_MAX_LIMIT = 500

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _post(url: str, **kwargs: Any) -> httpx.Response:
    async with upstream.slot("igdb"):
        try:
            resp = await client().post(url, **kwargs)
        except httpx.HTTPError as exc:
            raise upstream.UpstreamError(f"Could not reach IGDB: {exc}") from exc
        if resp.status_code >= 400:
            upstream.observe("igdb", resp.status_code, resp.headers.get("retry-after"))
        return resp


async def _access_token(settings: db.Settings) -> str:
    if not settings.igdb_ready:
        raise upstream.NotConfigured(
            "Games is off. Add a Twitch client id and secret in Settings, Games."
        )
    cached = db.cache_get(TOKEN_CACHE_KEY)
    if isinstance(cached, str):
        return cached

    resp = await _post(
        TOKEN_URL,
        params={
            "client_id": settings.twitch_client_id,
            "client_secret": settings.twitch_client_secret,
            "grant_type": "client_credentials",
        },
    )
    if resp.status_code != 200:
        raise upstream.UpstreamError(
            f"Twitch rejected the credentials ({resp.status_code})", status=resp.status_code
        )

    payload = resp.json()
    token = str(payload["access_token"])
    # Refresh a minute early so an in-flight request never dies on an expired token.
    db.cache_put(TOKEN_CACHE_KEY, token, max(60, int(payload.get("expires_in", 3600)) - 60))
    log.info("igdb: obtained a new access token")
    return token


async def query(endpoint: str, body: str) -> list[dict[str, Any]]:
    settings = db.get_settings()
    token = await _access_token(settings)

    resp = await _post(
        f"{API_BASE}/{endpoint}",
        content=body.encode(),
        headers={
            "Client-ID": settings.twitch_client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    status = resp.status_code
    if status == 401:
        # The token was revoked or rotated. Drop it and let the caller retry.
        db.cache_drop(TOKEN_CACHE_KEY)
        raise upstream.UpstreamError("IGDB rejected the access token, try again", status=status)
    if status != 200:
        raise upstream.UpstreamError(
            f"IGDB returned {status} for /{endpoint}: {resp.text[:200]}", status=status
        )

    result = resp.json()
    return list(result) if isinstance(result, list) else []


# ---------------------------------------------------------------- shaping


def image_url(image_id: str, size: str = "cover_big") -> str:
    return f"{IMAGE_BASE}/t_{size}/{image_id}.jpg"


def normalise(raw: dict[str, Any], detailed: bool = False) -> dict[str, Any]:
    """A game as Robin stores it. `detailed` when `raw` was asked for with GAME_FIELDS, the
    only field set the detail view's metadata comes from."""
    exact_date, label, status = _release(raw)
    cover = raw.get("cover") or {}
    backdrops = raw.get("artworks") or raw.get("screenshots") or []
    platforms = [
        p.get("abbreviation") or p.get("name")
        for p in raw.get("platforms", [])
        if isinstance(p, dict)
    ]
    platform_ids = [p["id"] for p in raw.get("platforms", []) if isinstance(p, dict)]
    return {
        "igdb_id": raw["id"],
        "name": raw.get("name", "Unknown"),
        "slug": raw.get("slug"),
        "summary": raw.get("summary"),
        "first_release_date": exact_date,
        "release_label": label,
        "release_status": status,
        "cover_image_id": cover.get("image_id"),
        "artwork_image_id": backdrops[0].get("image_id") if backdrops else None,
        "platforms": [p for p in platforms if p],
        "platform_ids": platform_ids,
        "exclusive": exclusive(platform_ids),
        "genres": [g["name"] for g in raw.get("genres", []) if isinstance(g, dict) and "name" in g],
        "rating": raw.get("total_rating"),
        "popularity": (raw.get("total_rating_count") or 0) + (raw.get("hypes") or 0),
        "url": raw.get("url"),
        "extra": _extra_metadata(raw) if detailed else {},
        "company_ids": _company_ids(raw),
        "franchise_ids": _ids(raw, "franchises"),
        "collection_ids": _ids(raw, "collections"),
    }


def _ids(raw: dict[str, Any], key: str) -> list[int]:
    """The ids under `key`. The lean field set gives bare ids, the detail one objects."""
    found = [item.get("id") if isinstance(item, dict) else item for item in raw.get(key) or []]
    return sorted({i for i in found if isinstance(i, int)})


def _company_ids(raw: dict[str, Any]) -> list[int]:
    """Every company involved. The lean field set gives an id, the detail one an object."""
    found = []
    for involved in raw.get("involved_companies") or []:
        company = involved.get("company") if isinstance(involved, dict) else None
        if isinstance(company, dict):
            company = company.get("id")
        if isinstance(company, int):
            found.append(company)
    return sorted(set(found))


def _release(raw: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    """The PC release: its date if IGDB names an actual day, IGDB's own wording for it either
    way, and whether it is a full release or something like Early Access.

    first_release_date is the earliest across every platform, so a console launch can put a
    date on a game whose PC version is still TBD. The PC entry is the one that matters here.

    The timestamp drives ordering and the day before notice, so a vague date must not fill it.
    The wording is display only, which is how an undated game can still read "Q2 2026".
    """
    dated = [
        d
        for d in raw.get("release_dates", [])
        if isinstance(d, dict) and d.get("date_format") is not None
    ]
    if not dated:
        return None, None, None

    entries = [d for d in dated if d.get("platform") == PC_PLATFORM_ID]
    if not entries:
        target = raw.get("first_release_date")
        entries = [d for d in dated if d.get("date") == target]
    entry = _pick_release(entries)
    if entry is None:
        return None, None, None

    status = (entry.get("status") or {}).get("name")
    date_format = int(entry["date_format"])
    if date_format == DATE_TBD:
        return None, None, status

    date = entry.get("date")
    if date_format == DATE_EXACT_DAY and date is not None:
        return int(date), entry.get("human"), status
    return None, entry.get("human"), status


def _rank(entry: dict[str, Any]) -> int | None:
    """How much a release counts, lowest first. None means it is not one Robin acts on."""
    status = (entry.get("status") or {}).get("name")
    return 0 if status is None else RELEASE_RANKS.get(status)


def _pick_release(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The entry a game is dated by.

    A game holds one entry per release it has had on a platform, in no order IGDB promises:
    an Early Access date beside a 1.0 date, or a firm date beside a TBD one. The full release
    is the only one that matters, so Early Access is used only while no full release carries a
    date, and gives way to one the moment IGDB has it.
    """
    ranked = [(rank, d) for d in entries if (rank := _rank(d)) is not None]
    if not ranked:
        return None
    dated = [pair for pair in ranked if pair[1].get("date")]
    return min(dated or ranked, key=lambda pair: (pair[0], int(pair[1].get("date") or 0)))[1]


def _names(raw: dict[str, Any], key: str) -> list[str]:
    return [item["name"] for item in raw.get(key, []) if isinstance(item, dict) and "name" in item]


def _refs(items: list[Any]) -> list[dict[str, Any]]:
    """`{id, name}` of each expanded object by name, so a dialog can open it as a favourite."""
    found = {
        item["id"]: item["name"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), int) and item.get("name")
    }
    return [{"id": i, "name": n} for i, n in sorted(found.items(), key=lambda pair: pair[1])]


def _extra_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """The detail view fields, from a GAME_FIELDS answer. IGDB leaves out what a game lacks, and
    LIST_FIELDS asks for some of these too, so what came back cannot say which set was used."""
    companies = raw.get("involved_companies") or []

    videos = [v for v in raw.get("videos", []) if isinstance(v, dict) and v.get("video_id")]
    # A game lists teasers, gameplay overviews and several trailers. Prefer one that says
    # trailer, otherwise take whatever it has.
    trailer = next(
        (v for v in videos if "trailer" in (v.get("name") or "").lower()),
        videos[0] if videos else None,
    )

    return {
        "v": db.EXTRA_VERSION,
        "storyline": raw.get("storyline"),
        "developers": _refs([c.get("company") for c in companies if c.get("developer")]),
        "publishers": _refs([c.get("company") for c in companies if c.get("publisher")]),
        "themes": _names(raw, "themes"),
        "game_modes": _names(raw, "game_modes"),
        "player_perspectives": _names(raw, "player_perspectives"),
        "engines": _names(raw, "game_engines"),
        "franchises": _refs(raw.get("franchises") or []),
        "collections": _refs(raw.get("collections") or []),
        "critic_rating": raw.get("aggregated_rating"),
        "critic_rating_count": raw.get("aggregated_rating_count"),
        "rating_count": raw.get("total_rating_count"),
        "screenshots": [
            shot["image_id"]
            for shot in raw.get("screenshots", [])
            if isinstance(shot, dict) and shot.get("image_id")
        ][:8],
        "trailer": (
            {
                "name": trailer.get("name") or "Trailer",
                "url": f"https://www.youtube.com/watch?v={trailer['video_id']}",
            }
            if trailer
            else None
        ),
    }


def _comparable(text: str) -> str:
    """Lowercase alphanumerics only, so baldurs gate lines up with Baldur's Gate."""
    return "".join(ch for ch in fold_to_ascii(text).lower() if ch.isalnum())


def _relevance(game: dict[str, Any], term: str) -> tuple[int, int, int, float]:
    name = _comparable(game["name"])
    needle = _comparable(term)
    return (
        int(name == needle),
        int(name.startswith(needle)),
        int(needle in name),
        float(game.get("popularity") or 0),
    )


# Kept out of API responses: they exist to drive filtering, and the games table does not
# carry them, so leaving them in would make a cache hit and a cache miss look different.
INTERNAL_FIELDS = ("platform_ids",)


def _store(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    db.upsert_games(games)
    return [{k: v for k, v in g.items() if k not in INTERNAL_FIELDS} for g in games]


# ---------------------------------------------------------------- endpoints


async def search(
    term: str, limit: int = 24, shown: frozenset[int] = SHOWN_PLATFORMS
) -> list[dict[str, Any]]:
    """Search by title.

    IGDB's search relevance is poor: cyberpunk does not return Cyberpunk 2077, it returns
    asset packs. A name substring query sorted by vote count does return it but misses loose
    spellings such as baldurs gate against Baldur's Gate. Both run and are merged, then
    ranked on a punctuation insensitive title comparison with popularity as the tiebreak.

    version_parent = null drops collector and deluxe edition duplicates. A game out before this
    month is found too, to be favourited by its makers and series, and is never monitored. A
    game on none of the `shown` platforms is left out, one IGDB names no platform for kept.
    """
    safe = term.replace('"', "").replace("\\", "").strip()
    if not safe:
        return []

    # The platforms are asked for, not filtered after, or a long series fills both limits with
    # its old console games and a new one with no votes yet never comes back.
    platforms = ",".join(map(str, sorted(shown)))
    scope = (
        f"version_parent = null & game_type = {REAL_GAME_TYPES}"
        f" & (platforms = ({platforms}) | platforms = null)"
    )
    fuzzy = f'{LIST_FIELDS} search "{safe}"; where {scope}; limit 30;'
    by_name = (
        f'{LIST_FIELDS} where name ~ *"{safe}"* & {scope}; sort total_rating_count desc; limit 50;'
    )

    results = await asyncio.gather(
        query("games", fuzzy), query("games", by_name), return_exceptions=True
    )
    merged: dict[int, dict[str, Any]] = {}
    errors = [r for r in results if isinstance(r, BaseException)]
    for result in results:
        if isinstance(result, BaseException):
            continue
        for raw in result:
            merged.setdefault(int(raw["id"]), normalise(raw))

    if not merged and errors:
        # Both calls failed. The first failure is raised as it is, so an unset or paused IGDB
        # still reads as one.
        if isinstance(errors[0], upstream.UpstreamError):
            raise errors[0]
        raise upstream.UpstreamError(str(errors[0]))

    found = [
        g
        for g in merged.values()
        if not g.get("platform_ids") or not shown.isdisjoint(g["platform_ids"])
    ]
    games = sorted(found, key=lambda g: _relevance(g, safe), reverse=True)
    return _store(games[:limit])


# One release name resolves to at most a handful of candidates, and the caller throws away
# everything its own matching does not claim.
async def game(igdb_id: int) -> dict[str, Any] | None:
    rows = await query("games", f"{GAME_FIELDS} where id = {igdb_id};")
    if not rows:
        return None
    return _store([normalise(rows[0], detailed=True)])[0]


async def refresh_games(igdb_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Refetch a set of games and store them, for spotting metadata that has since changed."""
    if not igdb_ids:
        return {}
    ids = ",".join(str(i) for i in igdb_ids)
    raw = await query("games", f"{LIST_FIELDS} where id = ({ids}); limit {len(igdb_ids)};")
    stored = _store([normalise(r) for r in raw])
    return {g["igdb_id"]: g for g in stored}


async def popularity_types() -> list[dict[str, Any]]:
    async def fetch() -> list[dict[str, Any]]:
        rows = await query(
            "popularity_types", "fields id,name,popularity_source; sort id asc; limit 50;"
        )
        return [{"id": r["id"], "name": r.get("name", f"Type {r['id']}")} for r in rows]

    types: list[dict[str, Any]] = await db.remember(
        POPULARITY_TYPES_CACHE_KEY, POPULARITY_TYPES_TTL, fetch
    )
    return types


async def detail(igdb_id: int) -> dict[str, Any] | None:
    """A game with its full metadata, asked again every `DETAIL_TTL`, within the hour while
    IGDB has no cover for it. The row Discover keeps fresh is what is answered, so a moved date
    or a new cover shows before the detail is asked again."""
    try:
        await db.remember(
            f"igdb:detail:v{db.EXTRA_VERSION}:{igdb_id}",
            lambda g: DETAIL_TTL if g and g.get("cover_image_id") else DISCOVER_TTL,
            lambda: game(igdb_id),
        )
    except upstream.UpstreamError:
        # IGDB cannot be asked just now. A detail stored before still answers.
        if db.get_detailed_game(igdb_id) is None:
            raise
    return db.get_detailed_game(igdb_id)


async def discover_popularity_type() -> int:
    """Most Wishlisted Upcoming when IGDB offers it, otherwise the first type available."""
    types = await popularity_types()
    for entry in types:
        if PREFERRED_POPULARITY_NAME in entry["name"].lower():
            return int(entry["id"])
    return int(types[0]["id"]) if types else 1


def _tomorrow() -> int:
    """Midnight UTC starting tomorrow, where Discover begins, as Screens and Books do."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((today + timedelta(days=1)).timestamp())


def _month_start() -> int:
    start = db.month_start()
    return int(datetime(start.year, start.month, 1, tzinfo=UTC).timestamp())


def out(game: dict[str, Any]) -> bool:
    """Out before this month: found by search to be favourited."""
    return not _current(game, _month_start())


def monitorable(settings: db.Settings, game: dict[str, Any]) -> bool:
    """Coming, or out and on PC with Prowlarr set, the only reason to monitor one out: to grab
    it once a clean release is listed."""
    return not out(game) or (settings.prowlarr_ready and PC in (game.get("platforms") or []))


def _current(game: dict[str, Any], since: int) -> bool:
    """Undated, or out from `since` on."""
    released = game.get("first_release_date")
    return released is None or released >= since


def _is_shown(game: dict[str, Any], since: int, shown: frozenset[int] = SHOWN_PLATFORMS) -> bool:
    """On a shown platform, and coming from `since` on, or not dated yet."""
    if shown.isdisjoint(game.get("platform_ids") or []):
        return False
    return _current(game, since)


def _once(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each game once. IGDB files a port as a game of its own, so a game coming to several
    platforms can be listed twice under one name. The PC one is kept, then the first.

    Only for lists of what is coming, where one name is one game. A search spans remakes.
    """
    kept: dict[str, dict[str, Any]] = {}
    for game in games:
        key = _comparable(game["name"])
        if key not in kept or (PC in game["platforms"] and PC not in kept[key]["platforms"]):
            kept[key] = game
    chosen = {id(g) for g in kept.values()}
    return [g for g in games if id(g) in chosen]


def _sort_key(game: dict[str, Any]) -> tuple[int, int]:
    """Soonest first, with undated games after everything that has a date."""
    released = game.get("first_release_date")
    return (1, 0) if released is None else (0, int(released))


def _year_start() -> int:
    """Midnight UTC on the first of January, where Discover begins with released games."""
    return int(datetime(datetime.now(UTC).year, 1, 1, tzinfo=UTC).timestamp())


async def _discover_pool(shown: frozenset[int], released: bool = False) -> list[int]:
    """The ids Discover pages through, in popularity order, built in four IGDB calls, five
    with `released`.

    Most Wishlisted Upcoming is Steam's wishlist, so a game not on Steam is never in it. IGDB's
    own hype, its follows before release, ranks the `shown` platforms beside it, dated and TBA
    games asked apart, since hundreds of TBA games outrank a dated one followed by a few. `released`
    adds the games out since the first of January, by the same hype, and starts the list
    there instead of tomorrow. The ranking only decides which games are listed. They are
    served in release order.
    """
    type_id = await discover_popularity_type()
    platforms = ",".join(map(str, sorted(shown)))
    cache_key = f"{DISCOVER_CACHE_PREFIX}{type_id}:{'year' if released else 'next'}:{platforms}"
    games_where = (
        f"{LIST_FIELDS} where platforms = ({platforms})"
        f" & version_parent = null & game_type = {REAL_GAME_TYPES} & hypes > 0"
    )

    async def build() -> list[int]:
        now = int(datetime.now(UTC).timestamp())
        asked = [
            query(
                "popularity_primitives",
                f"fields game_id,value; sort value desc; limit {DISCOVER_POOL};"
                f" where popularity_type = {type_id};",
            ),
            query(
                "games",
                f"{games_where} & first_release_date > {now};"
                f" sort hypes desc; limit {IGDB_MAX_LIMIT};",
            ),
            query(
                "games",
                f"{games_where} & first_release_date = null;"
                f" sort hypes desc; limit {DISCOVER_POOL};",
            ),
        ]
        if released:
            asked.append(
                query(
                    "games",
                    f"{games_where} & first_release_date >= {_year_start()}"
                    f" & first_release_date <= {now}; sort hypes desc; limit {DISCOVER_POOL};",
                )
            )
        primitives, *lists = await asyncio.gather(*asked)
        hyped = [g for part in lists for g in part]
        wishlisted = [int(p["game_id"]) for p in primitives]
        raw = []
        if wishlisted:
            ids = ",".join(map(str, wishlisted))
            raw = await query(
                "games", f"{LIST_FIELDS} where id = ({ids}); limit {len(wishlisted)};"
            )
        by_id = {g["igdb_id"]: g for g in (normalise(r) for r in [*hyped, *raw])}
        game_ids = list(dict.fromkeys([*wishlisted, *(int(r["id"]) for r in hyped)]))

        since = _year_start() if released else _tomorrow()
        ranked = [by_id[i] for i in game_ids if i in by_id]
        kept = _once([g for g in ranked if _is_shown(g, since, shown)])

        _store(kept)
        log.info("discover: %s games from a pool of %s", len(kept), len(game_ids))
        return [g["igdb_id"] for g in kept]

    # Pages arrive together as the grid fills, and `remember` builds the pool once for all of
    # them rather than each queueing behind the rate limiter.
    ordered = await db.remember(cache_key, DISCOVER_TTL, build)
    return [int(i) for i in ordered]


GameType = Literal["upcoming", "out"]


async def discover(
    limit: int = 36,
    offset: int = 0,
    shown: frozenset[int] = SHOWN_PLATFORMS,
    game_type: GameType = "upcoming",
    genre: str = "",
    sort: db.Sort = "date",
) -> dict[str, Any]:
    """One page of the Discover list on the `shown` platforms.

    `game_type` is upcoming, dated from tomorrow on or undated, or out, dated from the first of
    January to today, read from the pool with the year's released games. `genre` keeps the
    games of one genre, by name. A list is soonest release first, or with `sort` "popularity"
    most anticipated first, filtered before it is paged so a page is never cut short by a filter.
    """
    pool = await _discover_pool(shown, released=game_type == "out")
    stored = db.get_games(pool)
    games = [stored[i] for i in pool if i in stored]
    if game_type == "out":
        tomorrow = _tomorrow()
        games = [g for g in games if g["first_release_date"] and g["first_release_date"] < tomorrow]
    if genre:
        games = [g for g in games if genre in g["genres"]]
    ordered = (
        sorted(games, key=lambda g: -float(g["popularity"] or 0))
        if sort == "popularity"
        else sorted(games, key=_sort_key)
    )

    window = ordered[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(ordered) else None
    return {"games": window, "next_offset": next_offset}


GENRES_KEY = "igdb:genres:v1"
GENRES_TTL = 7 * 86_400


async def genres() -> list[str]:
    """Every genre IGDB files games under, by name, as a game carries them."""

    async def fetch() -> list[str]:
        found = await query("genres", "fields name; sort name asc; limit 100;")
        return [str(g["name"]) for g in found if g.get("name")]

    names: list[str] = await db.remember(GENRES_KEY, GENRES_TTL, fetch)
    return names


# ---------------------------------------------------------------- companies

COMPANY_FIELDS = "fields name,developed,published,url;"


def _company(raw: dict[str, Any]) -> dict[str, Any]:
    """A company as a favourite is shown: by name, with what it does, never by its logo.
    `roles` lets a search ask for developers or publishers alone."""
    roles = [
        role
        for role, key in (("Developer", "developed"), ("Publisher", "published"))
        if raw.get(key)
    ]
    return {
        "category": "games",
        "kind": "company",
        "id": raw["id"],
        "name": raw.get("name") or "",
        "image": None,
        "meta": " and ".join(roles) or "Company",
        "roles": [role.lower() for role in roles],
        "url": raw.get("url"),
    }


GROUP_FIELDS = "fields name,games,url;"


def _group(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    """A franchise or a series, by name, with how many games IGDB files under it."""
    count = len(raw.get("games") or [])
    label = "Franchise" if kind == "franchise" else "Series"
    return {
        "category": "games",
        "kind": kind,
        "id": raw["id"],
        "name": raw.get("name") or "",
        "image": None,
        "meta": f"{label}, {count} games" if count else label,
        "url": raw.get("url"),
    }


# What each kind of game favourite is: its endpoint, its fields, how a game names it, its shape.
KINDS: dict[str, tuple[str, str, str, Any]] = {
    "company": ("companies", COMPANY_FIELDS, "involved_companies.company", _company),
    "franchise": ("franchises", GROUP_FIELDS, "franchises", lambda r: _group(r, "franchise")),
    "collection": ("collections", GROUP_FIELDS, "collections", lambda r: _group(r, "collection")),
}

# A company that made nothing, or a group with no games, is never worth starring.
MADE_SOMETHING = {
    "company": " & (developed != null | published != null)",
    "franchise": " & games != null",
    "collection": " & games != null",
}


async def search_favourites(term: str) -> list[dict[str, Any]]:
    """Developers and publishers, franchises and series by name, twelve of each at most."""
    safe = term.replace('"', "").replace("\\", "").strip()
    if not safe:
        return []
    needle = _comparable(safe)

    def rank(raw: dict[str, Any]) -> tuple[int, int, int]:
        name = _comparable(raw.get("name") or "")
        made = sum(len(raw.get(k) or []) for k in ("developed", "published", "games"))
        return int(name == needle), int(name.startswith(needle)), made

    async def one(kind: str) -> list[dict[str, Any]]:
        endpoint, fields, _, shape = KINDS[kind]
        rows = await query(
            endpoint, f'{fields} where name ~ *"{safe}"*{MADE_SOMETHING[kind]}; limit 50;'
        )
        return [shape(raw) for raw in sorted(rows, key=rank, reverse=True)[:12]]

    found = await asyncio.gather(*(one(kind) for kind in KINDS))
    return [entity for kind in found for entity in kind]


async def favourite(kind: str, source_id: int) -> dict[str, Any] | None:
    endpoint, fields, _, shape = KINDS[kind]
    rows = await query(endpoint, f"{fields} where id = {source_id};")
    found: dict[str, Any] | None = shape(rows[0]) if rows else None
    return found


async def favourite_releases(
    kind: str, source_ids: list[int], shown: frozenset[int] = SHOWN_PLATFORMS
) -> list[dict[str, Any]]:
    """The games on the `shown` platforms any of these companies, franchises or series has
    coming, dated or not yet, soonest first."""
    if not source_ids:
        return []
    field = KINDS[kind][2]
    ids = ",".join(str(i) for i in source_ids)
    today = int(datetime.now(UTC).timestamp())
    rows = await query(
        "games",
        f"{LIST_FIELDS} where {field} = ({ids})"
        f" & platforms = ({','.join(str(p) for p in sorted(shown))})"
        " & version_parent = null"
        f" & game_type = {REAL_GAME_TYPES}"
        f" & (first_release_date > {today} | first_release_date = null);"
        " sort first_release_date asc; limit 100;",
    )
    return _store(_once([normalise(raw) for raw in rows]))
