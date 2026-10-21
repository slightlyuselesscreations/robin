import asyncio
import logging
import math
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from robin import (
    __version__,
    arr,
    auth,
    backups,
    book_reminders,
    comics,
    db,
    favourites,
    grabs,
    hardcover,
    igdb,
    logs,
    notify,
    redact,
    reminders,
    spa,
    suwayomi,
    updates,
    upstream,
)
from robin.config import env
from robin.routes import arr as arr_routes
from robin.routes import auth as auth_routes
from robin.routes import backups as backups_routes
from robin.routes import books as books_routes
from robin.routes import comics as comics_routes
from robin.routes import common
from robin.routes import countdowns as countdowns_routes
from robin.routes import favourites as favourites_routes
from robin.routes import games as games_routes
from robin.routes import images as images_routes
from robin.routes import logs as logs_routes
from robin.routes import monitored as monitored_routes
from robin.routes import prowlarr as prowlarr_routes
from robin.routes import qbittorrent as qbittorrent_routes
from robin.routes import screen as screen_routes
from robin.routes import settings as settings_routes
from robin.upstream import NotConfigured, RateLimited, UpstreamError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")
logs.install()
redact.install()


async def purge_expired() -> int:
    """Expired cache rows and sessions, and images not served in a while. A read already ignores
    them, this reclaims the space."""
    db.cache_purge()
    await asyncio.to_thread(images_routes.prune)
    return 0


async def warm_pages() -> int:
    """Ask again for what each page opens with, as its saved defaults set it, so a visit after a
    while away is answered with data under about an hour old. Returns how many were asked.

    The controls are read as the pages read them in the UI, a value they do not offer taking the
    page's own default.
    """
    settings = db.get_settings()

    def control(page: str, name: str) -> str:
        return settings.page_defaults.get(page, {}).get(name, "")

    def pick[T: str](page: str, name: str, offered: tuple[T, ...], fallback: T) -> T:
        return next((o for o in offered if o == control(page, name)), fallback)

    def sort(page: str, fallback: db.Sort) -> db.Sort:
        return pick(page, "order", get_args(db.Sort), fallback)

    def genre(page: str) -> str:
        return control(page, "genre")[:60]

    pages: list[Awaitable[object]] = []
    if settings.igdb_ready:
        game_types: tuple[igdb.GameType, ...] = get_args(igdb.GameType)
        platforms = get_args(igdb.Platform)
        pages.append(
            games_routes.discover(
                limit=36,
                offset=0,
                platform=next((p for p in platforms if p == control("games", "platform")), None),
                type=pick("games", "type", game_types, "upcoming"),
                genre=genre("games"),
                sort=sort("games", "date"),
            )
        )
    if settings.tmdb_ready:
        types: tuple[Literal["movie", "tv", "all"], ...] = ("movie", "tv", "all")
        releases: tuple[Literal["theatrical", "digital", ""], ...] = ("theatrical", "digital")
        language = control("screens", "language")
        pages.append(
            screen_routes.discover(
                kind=pick("screens", "type", types, "all"),
                page=1,
                language=language if re.fullmatch(r"[a-z]{2}", language) else "",
                release=pick("screens", "release", releases, ""),
                genre=genre("screens"),
                sort=sort("screens", "popularity"),
            )
        )
    if settings.hardcover_ready:
        book_types: tuple[hardcover.Kind, ...] = ("fiction", "nonfiction")
        book_genre = genre("books")
        pages.append(
            books_routes.discover(
                page=1,
                kind=pick("books", "type", book_types, ""),
                genre=book_genre if re.fullmatch(r"[a-z0-9-]{1,60}", book_genre) else "",
                sort=sort("books", "popularity"),
            )
        )
    if settings.suwayomi_ready:
        pages.append(suwayomi.latest(settings))
    if settings.radarr_ready or settings.sonarr_ready:
        pages.append(arr.calendar(settings))
    if db.favourites():
        pages.append(favourites.dated(settings))
    for failed in await asyncio.gather(*pages, return_exceptions=True):
        if isinstance(failed, BaseException):
            logging.getLogger(__name__).info("warm: %s", failed)
    return len(pages)


# What the hourly loop runs, in order. Each returns at once while what it needs is unset.
CHECKS = (
    purge_expired,
    warm_pages,
    # Before the notices, so a release it monitors gets its own and not a favourite's.
    favourites.monitor_favourites,
    arr.monitor_library,
    notify.notify_upcoming_releases,
    notify.notify_date_changes,
    comics.prefetch_week,
    comics.notify_new_firsts,
    favourites.notify_series,
    suwayomi.add_found_series,
    reminders.notify_reminders,
    book_reminders.notify_book_reminders,
    favourites.notify_favourites,
    backups.scheduled,
)

# What runs every RSS sync interval rather than hourly, the same guarantee as CHECKS. What
# quiet hours kept goes out within one of them ending.
FREQUENT = (grabs.rss_sync, grabs.track_downloads, notify.send_held)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    auth.first_boot()
    watchers = [
        asyncio.create_task(notify.watch(*CHECKS)),
        asyncio.create_task(notify.watch(*FREQUENT, every=grabs.RSS_INTERVAL)),
        # What was listed while Robin was off is older than the sync reads.
        asyncio.create_task(common.notify_now(grabs.search_waiting, "starting")),
    ]
    yield
    for watcher in watchers:
        watcher.cancel()
    await igdb.close()
    await upstream.close()


app = FastAPI(
    title="Robin",
    version=__version__,
    # The schema stays behind the guard for tooling. No docs page, it loads its script from a
    # CDN into Robin's own origin.
    docs_url=None,
    openapi_url="/api/openapi.json",
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
    lifespan=lifespan,
)

# The SPA bundle and the Discover payload are the only large responses. Starlette excludes
# already compressed types, so the cached covers are passed through untouched.
app.add_middleware(GZipMiddleware, minimum_size=1000)
# A page asking for its data is answered at once with what was kept, however old, while its
# source is asked again. The answer says so, and the page asks once more with FRESH_HEADER to
# wait for the new one, which it offers to show when it differs.
STALE_HEADER = "X-Robin-Stale"
FRESH_HEADER = "x-robin-fresh"


async def serve_stale(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method != "GET" or not request.url.path.startswith("/api/"):
        return await call_next(request)
    mark = db.Stale(wait=request.headers.get(FRESH_HEADER) == "1")
    token = db.STALE.set(mark)
    try:
        response = await call_next(request)
    finally:
        db.STALE.reset(token)
    if mark.served:
        response.headers[STALE_HEADER] = "1"
    return response


app.middleware("http")(serve_stale)
app.middleware("http")(auth.guard)


@app.exception_handler(UpstreamError)
async def upstream_failed(_: Request, exc: Exception) -> JSONResponse:
    """A source or integration said no, in its own words.

    Unset is a 409. A paused source is a 429 carrying when the pause ends, as Retry-After and
    as `paused_until`, so the page can say until when.
    """
    detail = redact.scrub(str(exc))
    if isinstance(exc, RateLimited):
        wait = max(1, math.ceil((exc.until - datetime.now(UTC)).total_seconds()))
        return JSONResponse(
            {"detail": detail, "source": exc.name, "paused_until": exc.until.isoformat()},
            status_code=429,
            headers={"Retry-After": str(wait)},
        )
    status = 409 if isinstance(exc, NotConfigured) else 502
    return JSONResponse({"detail": detail}, status_code=status)


app.include_router(auth_routes.router)

app.include_router(settings_routes.router)
app.include_router(backups_routes.router)
app.include_router(games_routes.router)
app.include_router(images_routes.router)
app.include_router(monitored_routes.router)
app.include_router(prowlarr_routes.router)
app.include_router(qbittorrent_routes.router)
app.include_router(arr_routes.router)
app.include_router(comics_routes.router)
app.include_router(screen_routes.router)
app.include_router(books_routes.router)
app.include_router(favourites_routes.router)
app.include_router(countdowns_routes.router)
app.include_router(logs_routes.router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    """Open to anyone, for the container's health check, so it says nothing else."""
    return {"status": "ok"}


@app.get("/api/update", tags=["update"])
async def update() -> dict[str, Any] | None:
    """The newest release on GitHub when it is newer than the Robin running, else null."""
    return await updates.latest()


# Mounted last so every API route is matched before the SPA catch all sees the request.
_static = env.robin_static_dir or spa.DEFAULT_STATIC
if spa.mount(app, _static):
    logging.getLogger(__name__).info("serving the frontend from %s", _static)
