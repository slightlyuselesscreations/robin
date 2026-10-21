"""Radarr and Sonarr: their calendars on Home, what their libraries hold, and adding to them.

What either library holds that still has a release ahead is monitored in Robin on its own, once,
so a title the user stops monitoring stays stopped.

Both answer the same `/api/v3` with an `X-Api-Key` header, so one client serves them. Sonarr
must be v4, the first to carry a series' TMDB id. A title is known to Robin by its TMDB id,
`movie-<id>` or `tv-<id>` as the Screens dialog is addressed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Literal

import httpx

from robin import db, reminders, tmdb, upstream

log = logging.getLogger(__name__)

App = Literal["radarr", "sonarr"]
APPS: tuple[App, ...] = ("radarr", "sonarr")
NAMES: dict[App, str] = {"radarr": "Radarr", "sonarr": "Sonarr"}
KIND: dict[App, tmdb.Kind] = {"radarr": "movie", "sonarr": "tv"}

TIMEOUT = 30.0
TTL = 3600
LIBRARY_KEY = "arr:library:v3"
CALENDAR_KEY = "arr:calendar:v2"
# A fixed window, widen it if the Calendar panel is paged further.
CALENDAR_AHEAD = timedelta(days=120)


def ready(settings: db.Settings, app: App) -> bool:
    return settings.radarr_ready if app == "radarr" else settings.sonarr_ready


def app_for(kind: str) -> App:
    return "radarr" if kind == "movie" else "sonarr"


async def _request(
    settings: db.Settings, app: App, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    if not ready(settings, app):
        raise upstream.NotConfigured(
            f"{NAMES[app]} is not configured. Add its URL and API key, and TMDB, in Settings,"
            " Screens."
        )
    url, key = (
        (settings.radarr_url, settings.radarr_api_key)
        if app == "radarr"
        else (settings.sonarr_url, settings.sonarr_api_key)
    )
    return await upstream.request(
        upstream.UpstreamError,
        NAMES[app],
        method,
        f"{url}/api/v3{path}",
        timeout=TIMEOUT,
        rejected=f"{NAMES[app]} rejected the API key",
        headers={"X-Api-Key": key},
        **kwargs,
    )


async def _get(settings: db.Settings, app: App, path: str, **params: Any) -> Any:
    return (await _request(settings, app, "GET", path, params=params or None)).json()


async def status(settings: db.Settings, app: App) -> str:
    return str((await _get(settings, app, "/system/status")).get("version", ""))


async def profiles(settings: db.Settings, app: App) -> list[dict[str, Any]]:
    return [
        {"id": int(p["id"]), "name": str(p["name"])}
        for p in await _get(settings, app, "/qualityprofile")
    ]


async def folders(settings: db.Settings, app: App) -> list[str]:
    return [str(f["path"]) for f in await _get(settings, app, "/rootfolder")]


def _ahead(app: App, item: dict[str, Any]) -> bool:
    """Whether a title still has a release to come: a film Radarr has not marked released, a
    show Sonarr has as continuing or upcoming. An ended show has no premiere left."""
    if app == "radarr":
        return item.get("status") != "released"
    return item.get("status") in ("continuing", "upcoming")


async def holdings(settings: db.Settings) -> list[dict[str, Any]]:
    """Every title either library holds: its `movie-<id>` or `tv-<id>` key, the app holding it,
    its id there and whether it has a release ahead. An app that cannot be read is left out."""

    async def held(app: App) -> list[dict[str, Any]]:
        if not ready(settings, app):
            return []
        try:
            items = await _get(settings, app, "/movie" if app == "radarr" else "/series")
        except upstream.UpstreamError as exc:
            log.info("arr: no library from %s: %s", NAMES[app], exc)
            return []
        return [
            {
                "key": f"{KIND[app]}-{i['tmdbId']}",
                "app": app,
                "id": int(i["id"]),
                "ahead": _ahead(app, i),
            }
            for i in items
            if i.get("tmdbId")
        ]

    async def fetch() -> list[dict[str, Any]]:
        return [h for found in await asyncio.gather(*map(held, APPS)) for h in found]

    if not (settings.radarr_ready or settings.sonarr_ready):
        return []
    kept: list[dict[str, Any]] = await db.remember(LIBRARY_KEY, TTL, fetch)
    return kept


async def library(settings: db.Settings) -> dict[str, App]:
    """Every title either library holds, as `movie-<id>` or `tv-<id>`, and which one."""
    return {h["key"]: h["app"] for h in await holdings(settings)}


async def monitor_library() -> int:
    """Monitor what either library holds with a release dated ahead, once. Returns how many.

    A show is monitored only while its next season premiere is dated, so a running show waits
    for its next season to be announced. A show monitored here that has no premiere dated any
    more is let go, and taken up again once one is.
    """
    settings = db.get_settings()
    db.drop_undated_library_shows()
    done = db.library_monitored() | {f"{r['kind']}-{r['tmdb_id']}" for r in db.rows("reminders")}
    added = 0
    for held in await holdings(settings):
        if not held["ahead"] or held["key"] in done:
            continue
        kind, tmdb_id = KIND[held["app"]], int(held["key"].split("-")[1])
        if not await reminders.shown(settings, kind, tmdb_id):
            continue
        try:
            # Only what is dated: the libraries hold far more than anyone asked Robin to wait
            # for, and an undated title is taken up once it has a date.
            detail = await tmdb.title(settings, kind, tmdb_id)
            if not (reminders.premiere_date(detail) if kind == "tv" else detail["releases"]):
                continue
            made = await reminders.monitor_title(settings, kind, tmdb_id)
        except upstream.UpstreamError as exc:
            log.warning("arr: could not monitor %s: %s", held["key"], exc)
            continue
        if not made:
            continue
        db.mark_library_monitored(held["key"])
        log.info("arr: monitoring %s, held by %s", held["key"], NAMES[held["app"]])
        added += 1
    return added


def _poster(item: dict[str, Any]) -> str | None:
    """The poster's remote address, at the size Robin shows TMDB's posters."""
    url = next(
        (i.get("remoteUrl") for i in item.get("images") or [] if i.get("coverType") == "poster"),
        None,
    )
    return str(url).replace("/t/p/original/", "/t/p/w342/") if url else None


def _entry(
    app: App, tmdb_id: int, title: str, image: str | None, day: str, tag: str
) -> dict[str, Any]:
    to = f"title={KIND[app]}-{tmdb_id}"
    return {
        "category": "screens",
        "key": f"{app}:{to}:{day}",
        "title": title,
        "image": image,
        "date": day,
        "to": to,
        "tag": tag,
        "library": app,
    }


def movie_entries(movies: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    """A film's cinema and digital releases in [start, end]. Discs are not tracked."""
    found = []
    for movie in movies:
        if not movie.get("tmdbId"):
            continue
        for field, tag in (("inCinemas", "Cinema"), ("digitalRelease", "Digital")):
            day = str(movie.get(field) or "")[:10]
            if day and start <= day <= end:
                found.append(
                    _entry("radarr", movie["tmdbId"], movie["title"], _poster(movie), day, tag)
                )
    return found


def premiere_entries(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Season premieres only, the first episode of a season past the specials."""
    found = []
    for episode in episodes:
        series = episode.get("series") or {}
        if (
            episode.get("episodeNumber") == 1
            and (episode.get("seasonNumber") or 0) >= 1
            and episode.get("airDate")
            and series.get("tmdbId")
        ):
            found.append(
                _entry(
                    "sonarr",
                    series["tmdbId"],
                    series["title"],
                    _poster(series),
                    episode["airDate"],
                    "Series",
                )
            )
    return found


async def calendar(settings: db.Settings, today: date | None = None) -> list[dict[str, Any]]:
    """What both calendars have dated from the first of this month on, each app left out while
    it cannot be read."""
    today = today or date.today()
    start, end = today.replace(day=1).isoformat(), (today + CALENDAR_AHEAD).isoformat()

    window = {"start": start, "end": end, "unmonitored": "false"}

    async def dated(app: App) -> list[dict[str, Any]]:
        if not ready(settings, app):
            return []
        try:
            if app == "radarr":
                return movie_entries(await _get(settings, app, "/calendar", **window), start, end)
            return premiere_entries(
                await _get(settings, app, "/calendar", includeSeries="true", **window)
            )
        except upstream.UpstreamError as exc:
            log.info("arr: no calendar from %s: %s", NAMES[app], exc)
            return []

    async def fetch() -> list[dict[str, Any]]:
        return [e for found in await asyncio.gather(*map(dated, APPS)) for e in found]

    if not (settings.radarr_ready or settings.sonarr_ready):
        return []
    kept: list[dict[str, Any]] = await db.remember(CALENDAR_KEY, TTL, fetch)
    # What Settings hides is left out on reading, so a change there applies at once.
    shown = await asyncio.gather(*(_shown(settings, entry) for entry in kept))
    return [entry for entry, show in zip(kept, shown, strict=True) if show]


async def _shown(settings: db.Settings, entry: dict[str, Any]) -> bool:
    kind, tmdb_id = entry["to"].removeprefix("title=").split("-")
    return await reminders.shown(settings, kind, int(tmdb_id))


async def add(settings: db.Settings, app: App, tmdb_id: int) -> None:
    """Add a film to Radarr or a show to Sonarr, monitored, and have it search at once."""
    profile_id = settings.radarr_profile_id if app == "radarr" else settings.sonarr_profile_id
    root = settings.radarr_root if app == "radarr" else settings.sonarr_root
    if not profile_id:
        [first, *_] = await profiles(settings, app) or [{"id": 0}]
        profile_id = int(first["id"])
    if not root:
        [root, *_] = await folders(settings, app) or [""]
    if not profile_id or not root:
        raise upstream.UpstreamError(
            f"{NAMES[app]} has no quality profile or root folder to add to."
        )
    if app == "radarr":
        found = await _get(settings, app, "/movie/lookup/tmdb", tmdbId=tmdb_id)
        body = {
            **found,
            "minimumAvailability": "released",
            "addOptions": {"searchForMovie": True},
        }
    else:
        tvdb_id = ((await tmdb.show(settings, tmdb_id)).get("external_ids") or {}).get("tvdb_id")
        if not tvdb_id:
            raise upstream.UpstreamError("TMDB has no TVDB id for this show, which Sonarr adds by.")
        [found, *_] = await _get(settings, app, "/series/lookup", term=f"tvdb:{tvdb_id}") or [None]
        if found is None:
            raise upstream.UpstreamError(f"Sonarr does not know TVDB id {tvdb_id}.")
        body = {
            **found,
            "seasonFolder": True,
            "addOptions": {"monitor": "all", "searchForMissingEpisodes": True},
        }
    body |= {"qualityProfileId": profile_id, "rootFolderPath": root, "monitored": True}
    await _request(settings, app, "POST", "/movie" if app == "radarr" else "/series", json=body)
    db.cache_drop(LIBRARY_KEY)
    db.cache_drop(CALENDAR_KEY)


async def remove(settings: db.Settings, kind: str, tmdb_id: int, delete_files: bool) -> bool:
    """Remove a title from the app holding it, its files on disk too with `delete_files`, and
    never excluded from a later add. False when the app does not hold it."""
    app = app_for(kind)
    if not ready(settings, app):
        raise upstream.NotConfigured(f"{NAMES[app]} is not configured.")
    key = f"{kind}-{tmdb_id}"
    held = next((h for h in await holdings(settings) if h["key"] == key), None)
    if held is None:
        return False
    path = f"/movie/{held['id']}" if app == "radarr" else f"/series/{held['id']}"
    files = "true" if delete_files else "false"
    await _request(
        settings,
        app,
        "DELETE",
        path,
        params={"deleteFiles": files, "addImportExclusion": "false"},
    )
    db.cache_drop(LIBRARY_KEY)
    db.cache_drop(CALENDAR_KEY)
    return True


async def follow(settings: db.Settings, kind: str, tmdb_id: int) -> None:
    """Add a title just monitored to its app, while that app's switch is on and it is not
    there yet. A failure is logged, never raised, so monitoring never fails on it."""
    app = app_for(kind)
    switch = settings.radarr_add if app == "radarr" else settings.sonarr_add
    if not (switch and ready(settings, app)):
        return
    try:
        if f"{kind}-{tmdb_id}" not in await library(settings):
            await add(settings, app, tmdb_id)
    except upstream.UpstreamError as exc:
        log.warning("arr: could not add %s-%s to %s: %s", kind, tmdb_id, NAMES[app], exc)
