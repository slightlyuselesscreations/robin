import asyncio
import dataclasses
from collections.abc import Coroutine
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from robin import (
    arr,
    backups,
    comics,
    db,
    grabs,
    hardcover,
    igdb,
    notify,
    predb,
    prowlarr,
    qbittorrent,
    suwayomi,
    tmdb,
)
from robin.upstream import RateLimited, UpstreamError

router = APIRouter(prefix="/api/settings", tags=["settings"])


class HomePanel(BaseModel):
    """`beside` puts a panel in the row of the one before, `size` is its percent of that row.

    Both stay null on a layout saved before rows existed, and the frontend fills in its defaults.
    """

    id: str = Field(max_length=40)
    hidden: bool = False
    beside: bool | None = None
    size: float | None = Field(default=None, ge=0, le=100)


# A page, a control on it, or the value it starts at.
Name = Annotated[str, Field(max_length=40)]

Hour = Annotated[int, Field(ge=0, le=23)]


class Notice(BaseModel):
    """One notice of a schedule: this many days before the date, at this local hour."""

    days: int = Field(ge=0, le=30)
    hour: Hour


Schedule = Annotated[list[Notice], Field(max_length=10)]


class Publisher(BaseModel):
    """A Comic Vine publisher, by its id, named as Comic Vine names it."""

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)


# Quiet hours, [start, end], or empty for none.
Quiet = Annotated[list[Hour], Field(max_length=2)]

Value = Annotated[str, Field(max_length=2000)]


class Destination(BaseModel):
    """A notification destination as sent. A blank secret keeps the one stored for its id."""

    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
    service: str
    values: dict[Name, Value] = Field(max_length=10)
    places: dict[db.Category, Value] = {}


class DestinationOut(BaseModel):
    """Each secret blank, named in `saved` while one is kept."""

    id: str
    service: str
    values: dict[str, str]
    saved: list[str]
    places: dict[str, str]
    saved_places: list[str]


class SettingsOut(BaseModel):
    """Secrets are reported as a boolean, never as a value.

    The Twitch client id is an identifier rather than a credential, so it is returned as is.
    """

    twitch_client_id: str
    has_twitch_client_secret: bool
    prowlarr_url: str
    has_prowlarr_api_key: bool
    prowlarr_indexer_ids: list[int]
    p2p_groups: list[str]
    home_layout: list[HomePanel]
    page_defaults: dict[str, dict[str, str]]
    theme: db.Theme
    scheme: db.Scheme
    suwayomi_url: str
    suwayomi_source_id: str
    qbittorrent_url: str
    has_qbittorrent_api_key: bool
    qbittorrent_category: str
    freeleech_only: bool
    has_tmdb_token: bool
    tmdb_region: str
    tmdb_language: str
    tmdb_hidden_languages: list[str]
    tmdb_hidden_movie_genres: list[int]
    tmdb_hidden_tv_genres: list[int]
    tmdb_hidden_release_types: list[str]
    tmdb_shown_movie_genres: list[int]
    tmdb_shown_tv_genres: list[int]
    tmdb_ready: bool
    screen_notices_ready: bool
    radarr_url: str
    has_radarr_api_key: bool
    radarr_profile_id: int
    radarr_root: str
    radarr_add: bool
    sonarr_url: str
    has_sonarr_api_key: bool
    sonarr_profile_id: int
    sonarr_root: str
    sonarr_add: bool
    has_hardcover_token: bool
    has_comicvine_token: bool
    books_hidden_literary_types: list[int]
    books_hidden_categories: list[int]
    books_hidden_genres: list[str]
    books_shown_genres: list[str]
    hardcover_ready: bool
    books_notices_ready: bool
    games_hidden_platforms: list[str]
    games_schedule: list[Notice]
    comics_schedule: list[Notice]
    screen_schedule: list[Notice]
    books_schedule: list[Notice]
    comics_digest_publishers: list[Publisher]
    games_quiet: list[int]
    comics_quiet: list[int]
    screen_quiet: list[int]
    books_quiet: list[int]
    notify_destinations: list[DestinationOut]
    games_notify: bool
    comics_notify: bool
    screen_notify: bool
    books_notify: bool
    games_favourites: bool
    screen_favourites: bool
    books_favourites: bool
    comics_favourites: bool
    games_favourites_monitor: bool
    screen_favourites_monitor: bool
    books_favourites_monitor: bool
    comics_favourites_monitor: bool
    igdb_ready: bool
    comics_ready: bool
    prowlarr_ready: bool
    qbittorrent_ready: bool
    radarr_ready: bool
    sonarr_ready: bool
    suwayomi_ready: bool
    notify_ready: bool
    has_backup_passphrase: bool
    backups: bool
    backup_hour: int
    backup_keep: int
    backups_ready: bool


# A Hardcover genre tag slug.
GENRE_SLUG = r"^[a-z0-9-]{1,60}$"


class SettingsPatch(BaseModel):
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    prowlarr_url: str | None = None
    prowlarr_api_key: str | None = None
    prowlarr_indexer_ids: list[int] | None = None
    p2p_groups: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_.]{1,40}$")]] | None = Field(
        default=None, max_length=50
    )
    home_layout: list[HomePanel] | None = Field(default=None, max_length=40)
    page_defaults: dict[Name, dict[Name, Name]] | None = Field(default=None, max_length=20)
    theme: db.Theme | None = None
    scheme: db.Scheme | None = None
    suwayomi_url: str | None = None
    suwayomi_source_id: str | None = Field(default=None, pattern=r"^-?\d*$")
    qbittorrent_url: str | None = None
    qbittorrent_api_key: str | None = None
    qbittorrent_category: str | None = Field(default=None, min_length=1, max_length=200)
    freeleech_only: bool | None = None
    tmdb_token: str | None = None
    tmdb_region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    tmdb_language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    tmdb_hidden_languages: list[Annotated[str, Field(pattern=r"^[a-z]{2}$")]] | None = Field(
        default=None, max_length=300
    )
    tmdb_hidden_movie_genres: list[int] | None = Field(default=None, max_length=50)
    tmdb_hidden_tv_genres: list[int] | None = Field(default=None, max_length=50)
    tmdb_hidden_release_types: list[tmdb.Release] | None = None
    tmdb_shown_movie_genres: list[int] | None = Field(default=None, max_length=50)
    tmdb_shown_tv_genres: list[int] | None = Field(default=None, max_length=50)
    radarr_url: str | None = None
    radarr_api_key: str | None = None
    radarr_profile_id: int | None = Field(default=None, ge=0)
    radarr_root: str | None = Field(default=None, max_length=500)
    radarr_add: bool | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    sonarr_profile_id: int | None = Field(default=None, ge=0)
    sonarr_root: str | None = Field(default=None, max_length=500)
    sonarr_add: bool | None = None
    hardcover_token: str | None = None
    comicvine_token: str | None = None
    books_hidden_literary_types: list[Annotated[int, Field(ge=1, le=2)]] | None = None
    books_hidden_categories: list[Annotated[int, Field(ge=1, le=20)]] | None = Field(
        default=None, max_length=20
    )
    books_hidden_genres: list[Annotated[str, Field(pattern=GENRE_SLUG)]] | None = Field(
        default=None, max_length=200
    )
    books_shown_genres: list[Annotated[str, Field(pattern=GENRE_SLUG)]] | None = Field(
        default=None, max_length=200
    )
    games_hidden_platforms: list[igdb.Platform] | None = None
    games_schedule: Schedule | None = None
    comics_schedule: Schedule | None = None
    screen_schedule: Schedule | None = None
    books_schedule: Schedule | None = None
    comics_digest_publishers: list[Publisher] | None = Field(default=None, max_length=100)
    games_quiet: Quiet | None = None
    comics_quiet: Quiet | None = None
    screen_quiet: Quiet | None = None
    books_quiet: Quiet | None = None
    notify_destinations: list[Destination] | None = Field(default=None, max_length=20)
    games_notify: bool | None = None
    comics_notify: bool | None = None
    screen_notify: bool | None = None
    books_notify: bool | None = None
    games_favourites: bool | None = None
    screen_favourites: bool | None = None
    books_favourites: bool | None = None
    comics_favourites: bool | None = None
    games_favourites_monitor: bool | None = None
    screen_favourites_monitor: bool | None = None
    books_favourites_monitor: bool | None = None
    comics_favourites_monitor: bool | None = None
    # Blank keeps the one stored.
    backup_passphrase: str | None = Field(default=None, pattern=r"^(.{8,200})?$")
    backups: bool | None = None
    backup_hour: Hour | None = None
    backup_keep: int | None = Field(default=None, ge=1, le=100)


def _to_out(s: db.Settings) -> SettingsOut:
    return SettingsOut(
        twitch_client_id=s.twitch_client_id,
        has_twitch_client_secret=bool(s.twitch_client_secret),
        prowlarr_url=s.prowlarr_url,
        has_prowlarr_api_key=bool(s.prowlarr_api_key),
        prowlarr_indexer_ids=s.prowlarr_indexer_ids,
        p2p_groups=s.p2p_groups,
        home_layout=[HomePanel(**panel) for panel in s.home_layout],
        page_defaults=s.page_defaults,
        theme=s.theme,
        scheme=s.scheme,
        suwayomi_url=s.suwayomi_url,
        suwayomi_source_id=s.suwayomi_source_id,
        qbittorrent_url=s.qbittorrent_url,
        has_qbittorrent_api_key=bool(s.qbittorrent_api_key),
        qbittorrent_category=s.qbittorrent_category,
        freeleech_only=s.freeleech_only,
        has_tmdb_token=bool(s.tmdb_token),
        tmdb_region=s.tmdb_region,
        tmdb_language=s.tmdb_language,
        tmdb_hidden_languages=s.tmdb_hidden_languages,
        tmdb_hidden_movie_genres=s.tmdb_hidden_movie_genres,
        tmdb_hidden_tv_genres=s.tmdb_hidden_tv_genres,
        tmdb_hidden_release_types=[
            t for t in s.tmdb_hidden_release_types if t in tmdb.RELEASE_TYPES
        ],
        tmdb_shown_movie_genres=s.tmdb_shown_movie_genres,
        tmdb_shown_tv_genres=s.tmdb_shown_tv_genres,
        tmdb_ready=s.tmdb_ready,
        screen_notices_ready=s.notices("screens") is not None,
        radarr_url=s.radarr_url,
        has_radarr_api_key=bool(s.radarr_api_key),
        radarr_profile_id=s.radarr_profile_id,
        radarr_root=s.radarr_root,
        radarr_add=s.radarr_add,
        sonarr_url=s.sonarr_url,
        has_sonarr_api_key=bool(s.sonarr_api_key),
        sonarr_profile_id=s.sonarr_profile_id,
        sonarr_root=s.sonarr_root,
        sonarr_add=s.sonarr_add,
        has_hardcover_token=bool(s.hardcover_token),
        has_comicvine_token=bool(s.comicvine_token),
        books_hidden_literary_types=s.books_hidden_literary_types,
        books_hidden_categories=s.books_hidden_categories,
        books_hidden_genres=s.books_hidden_genres,
        books_shown_genres=s.books_shown_genres,
        hardcover_ready=s.hardcover_ready,
        books_notices_ready=s.notices("books") is not None,
        games_hidden_platforms=[p for p in s.games_hidden_platforms if p in igdb.PLATFORMS],
        games_schedule=_schedule(s, "games"),
        comics_schedule=_schedule(s, "comics"),
        screen_schedule=_schedule(s, "screens"),
        books_schedule=_schedule(s, "books"),
        comics_digest_publishers=[Publisher(**p) for p in s.comics_digest_publishers],
        games_quiet=s.games_quiet,
        comics_quiet=s.comics_quiet,
        screen_quiet=s.screen_quiet,
        books_quiet=s.books_quiet,
        notify_destinations=[DestinationOut(**d) for d in notify.masked(s.notify_destinations)],
        games_notify=s.games_notify,
        comics_notify=s.comics_notify,
        screen_notify=s.screen_notify,
        books_notify=s.books_notify,
        games_favourites=s.games_favourites,
        screen_favourites=s.screen_favourites,
        books_favourites=s.books_favourites,
        comics_favourites=s.comics_favourites,
        games_favourites_monitor=s.games_favourites_monitor,
        screen_favourites_monitor=s.screen_favourites_monitor,
        books_favourites_monitor=s.books_favourites_monitor,
        comics_favourites_monitor=s.comics_favourites_monitor,
        igdb_ready=s.igdb_ready,
        comics_ready=s.comics_ready,
        prowlarr_ready=s.prowlarr_ready,
        qbittorrent_ready=s.qbittorrent_ready,
        radarr_ready=s.radarr_ready,
        sonarr_ready=s.sonarr_ready,
        suwayomi_ready=s.suwayomi_ready,
        notify_ready=s.notify_ready,
        has_backup_passphrase=bool(s.backup_passphrase),
        backups=s.backups,
        backup_hour=s.backup_hour,
        backup_keep=s.backup_keep,
        backups_ready=s.backups_ready,
    )


def _schedule(s: db.Settings, category: db.Category) -> list[Notice]:
    """The schedule as it is followed, the day before first."""
    slots = s.schedule(category)
    first = next(slot for slot in slots if slot[0] == db.DAY_BEFORE[0])
    ordered = [first, *(slot for slot in slots if slot != first)]
    return [Notice(days=days, hour=hour) for days, hour in ordered]


@router.get("")
def read_settings() -> SettingsOut:
    return _to_out(db.get_settings())


# What decides which release a game takes, so a change to one searches again for every waiting
# game that is out, in case a release passed over before is taken now.
GRAB_FIELDS = ("freeleech_only", "prowlarr_indexer_ids", "p2p_groups", "prowlarr_url")


@router.put("")
async def write_settings(patch: SettingsPatch, background: BackgroundTasks) -> SettingsOut:
    fields: dict[str, Any] = patch.model_dump(exclude_unset=True)
    # A key goes only to the address it was saved for. A different address takes a key sent
    # with it, or none, so a stored key is never sent on to a host it was not given for. A key
    # saved before any address was has gone nowhere yet, and stays.
    stored = db.get_settings()
    moved = tuple(
        key
        for url, key in db.KEYED_URLS.items()
        if fields.get(url) is not None
        and getattr(stored, url)
        and str(fields[url]).rstrip("/") != getattr(stored, url)
        and not fields.get(key)
    )
    if patch.notify_destinations is not None:
        if not patch.notify_destinations and stored.notify_destinations:
            raise HTTPException(status_code=409, detail="Keep one notification destination")
        fields["notify_destinations"] = _destinations(patch.notify_destinations, stored)
    db.save_settings(fields, clear=moved)
    saved = db.get_settings()
    if any(getattr(saved, name) != getattr(stored, name) for name in GRAB_FIELDS):
        background.add_task(grabs.search_waiting)
    return _to_out(saved)


class ConnectionCheck(BaseModel):
    ok: bool
    detail: str


class ServiceHealth(BaseModel):
    """One service, in the same three words for every one of them."""

    state: Literal["healthy", "faulty", "unset"]
    # Why it is faulty, as the service or the network put it. Empty otherwise.
    error: str = ""
    # When a data source Robin paused is asked again, while it is paused.
    until: str | None = None


class Health(BaseModel):
    igdb: ServiceHealth
    tmdb: ServiceHealth
    hardcover: ServiceHealth
    comicvine: ServiceHealth
    prowlarr: ServiceHealth
    predb: ServiceHealth
    suwayomi: ServiceHealth
    qbittorrent: ServiceHealth
    radarr: ServiceHealth
    sonarr: ServiceHealth
    notify: ServiceHealth
    backups: ServiceHealth


HEALTH_CACHE_KEY = "health:v12"
# Home reads it on every visit. A minute keeps it current without asking five servers each time.
HEALTH_TTL = 60


def _missing(own: dict[str, object], needs: dict[str, bool] | None = None) -> str:
    """What a service partly set still lacks, its own fields by name and then the services it
    needs. Empty while none of its own is set."""
    if not any(own.values()):
        return ""
    gaps = [name for name, value in own.items() if not value]
    gaps += [name for name, ok in (needs or {}).items() if not ok]
    return f"Needs {' and '.join(gaps)}" if gaps else ""


async def _check(
    ready: bool, probe: Coroutine[Any, Any, object], missing: str = ""
) -> ServiceHealth:
    """Run one probe against the service's own server. One never started is closed instead,
    saying what it still needs when it is partly set."""
    if not ready:
        probe.close()
        return ServiceHealth(state="unset", error=missing)
    try:
        await probe
    except RateLimited as exc:
        # A paused source is not asked, the probe fails before it leaves.
        return ServiceHealth(state="faulty", error=str(exc), until=exc.until.isoformat())
    except (UpstreamError, httpx.HTTPError, ValueError) as exc:
        return ServiceHealth(state="faulty", error=str(exc) or type(exc).__name__)
    return ServiceHealth(state="healthy")


@router.get("/health")
async def health(refresh: bool = False) -> Health:
    """Every upstream, asked directly. `refresh` skips the one minute cache."""
    if refresh:
        report = await _probe()
        db.cache_put(HEALTH_CACHE_KEY, report, HEALTH_TTL)
    else:
        report = await db.remember(HEALTH_CACHE_KEY, HEALTH_TTL, _probe)
    return Health(**report)


async def _probe() -> dict[str, Any]:
    # Every probe makes a live request, never one answered from Robin's own cache, so healthy
    # means the server answered just now with the credentials in Settings.
    settings = db.get_settings()
    (
        igdb_h,
        tmdb_h,
        hardcover_h,
        comicvine_h,
        prowlarr_h,
        predb_h,
        suwayomi_h,
        qbittorrent_h,
        radarr_h,
        sonarr_h,
        notify_h,
        backups_h,
    ) = await asyncio.gather(
        _check(settings.igdb_ready, igdb.query("games", "fields id; limit 1;")),
        _check(settings.tmdb_ready, tmdb.ping(settings)),
        _check(settings.hardcover_ready, hardcover.ping(settings)),
        _check(settings.comics_ready, comics.ping()),
        _check(
            settings.prowlarr_ready,
            prowlarr.ping(),
            _missing(
                {"an address": settings.prowlarr_url, "an API key": settings.prowlarr_api_key}
            ),
        ),
        # PreDB is only asked once Prowlarr finds something to grab.
        _check(settings.prowlarr_ready, predb.pres("Robin", "RUNE")),
        _check(
            settings.suwayomi_ready,
            suwayomi.source_name(settings),
            _missing(
                {"an address": settings.suwayomi_url, "a source ID": settings.suwayomi_source_id},
                {"Comic Vine": settings.comics_ready},
            ),
        ),
        _check(settings.qbittorrent_ready, qbittorrent.version(settings)),
        _check(
            settings.radarr_ready,
            arr.status(settings, "radarr"),
            _missing(
                {"an address": settings.radarr_url, "an API key": settings.radarr_api_key},
                {"TMDB": settings.tmdb_ready},
            ),
        ),
        _check(
            settings.sonarr_ready,
            arr.status(settings, "sonarr"),
            _missing(
                {"an address": settings.sonarr_url, "an API key": settings.sonarr_api_key},
                {"TMDB": settings.tmdb_ready},
            ),
        ),
        _check(settings.notify_ready, notify.health(settings)),
        _check(settings.backups_ready, backups.health()),
    )
    report = Health(
        igdb=igdb_h,
        tmdb=tmdb_h,
        hardcover=hardcover_h,
        comicvine=comicvine_h,
        prowlarr=prowlarr_h,
        predb=predb_h,
        suwayomi=suwayomi_h,
        qbittorrent=qbittorrent_h,
        radarr=radarr_h,
        sonarr=sonarr_h,
        notify=notify_h,
        backups=backups_h,
    )
    return report.model_dump()


class FieldOut(BaseModel):
    key: str
    label: str
    example: str
    secret: bool
    optional: bool


class ServiceOut(BaseModel):
    key: str
    label: str
    fields: list[FieldOut]
    # The field a category can change, null for a service with one place.
    place: str | None


@router.get("/notify-services")
def notify_services() -> list[ServiceOut]:
    """What a destination can be, in the order the picker offers them."""
    return [
        ServiceOut(
            key=key,
            label=service.label,
            fields=[FieldOut(**dataclasses.asdict(f)) for f in service.fields],
            place=service.place,
        )
        for key, service in notify.SERVICES.items()
    ]


class NotifyTest(BaseModel):
    """Destinations as the form holds them, and the category whose places they are sent to."""

    destinations: list[Destination] = Field(min_length=1, max_length=20)
    category: db.Category | None = None


@router.post("/notify-test")
async def send_test_notification(body: NotifyTest) -> ConnectionCheck:
    """Send a real notification to each destination, at once, quiet hours or not."""
    settings = db.get_settings()
    destinations = _destinations(body.destinations, settings)
    where = f"{notify.LABELS[body.category]} notifications" if body.category else "Notifications"
    failed = []
    for destination in destinations:
        try:
            await notify.deliver(
                [destination],
                body.category,
                title="Robin is connected",
                message=f"{where} reach you here.",
                tags="bell",
            )
        except notify.NotifyError as exc:
            failed.append(str(exc))
    if failed:
        return ConnectionCheck(ok=False, detail="; ".join(failed))
    names = ", ".join(notify.SERVICES[d["service"]].label for d in destinations)
    return ConnectionCheck(ok=True, detail=f"Sent to {names}")


def _destinations(sent: list[Destination], settings: db.Settings) -> list[dict[str, Any]]:
    """The destinations as sent, with what is stored for each blank secret, each checked."""
    for d in sent:
        if d.service not in notify.SERVICES:
            raise HTTPException(status_code=422, detail=f"Unknown service {d.service}")
    destinations = notify.merged([d.model_dump() for d in sent], settings.notify_destinations)
    for destination in destinations:
        try:
            notify.check(destination)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return destinations
