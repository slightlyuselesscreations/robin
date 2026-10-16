"""Notifications, through Apprise, to every destination set in Settings.

Anything Robin announces goes through `send` with the category's channel, and lands on each
destination, at the category's own place there when one is set: an ntfy topic, a Telegram
chat, a Matrix room. A notice inside the category's quiet hours is kept, and `send_held`
sends what was kept once they end, a digest when there is more than one.

The games checks live here too: one at each notice of the games schedule before a game is
due out, and one when a game IGDB listed as TBA finally gets a date. The checks run on a loop
inside the app rather than from a cron entry, so a single container is still the whole
deployment.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import apprise

from robin import db, hidden, igdb, notices, upstream

log = logging.getLogger(__name__)

# How often the watcher wakes. Release dates move by days, so hourly is plenty and keeps the
# log quiet.
CHECK_INTERVAL_SECONDS = 3600

# How long a destination's last failure is kept for Health.
ERROR_TTL = 7 * 24 * 3600


class NotifyError(upstream.UpstreamError):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    example: str
    secret: bool = False
    optional: bool = False


Values = dict[str, str]


@dataclass(frozen=True)
class Service:
    label: str
    fields: tuple[Field, ...]
    url: Callable[[Values], str]
    # The field naming where on the service a notice lands, which a category can change.
    place: str | None = None
    # ntfy takes a link, an image and tags as options of its address. Any other service gets
    # the link in the body and the image as an attachment.
    options: bool = False


def _q(value: str) -> str:
    return quote(value.strip(), safe="")


def _server(value: str, plain: str, secure: str) -> str:
    """`https://host:port/path` as an Apprise address, its schema the secure one over HTTPS."""
    raw = value.strip()
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    schema = secure if parts.scheme == "https" else plain
    return f"{schema}://{parts.netloc}{parts.path.rstrip('/')}"


def _ntfy(v: Values) -> str:
    schema, _, rest = _server(v["server"], "ntfy", "ntfys").partition("://")
    token = f"{_q(v['token'])}@" if v.get("token") else ""
    return f"{schema}://{token}{rest}/{_q(v['topic'])}"


SERVER = "Server"

# What the picker offers, each a service set by a URL, a token or two, and a place. Every
# other Apprise service goes in as its own address, `apprise`.
SERVICES: dict[str, Service] = {
    "ntfy": Service(
        "ntfy",
        (
            Field("server", SERVER, "https://ntfy.sh"),
            Field("topic", "Topic", "robin"),
            Field("token", "Token", "tk_AgQdq7mVBoFD37zQVN29RhuMzNIz2", secret=True, optional=True),
        ),
        _ntfy,
        place="topic",
        options=True,
    ),
    "discord": Service(
        "Discord",
        (
            Field(
                "webhook",
                "Webhook",
                "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOp",
                secret=True,
            ),
        ),
        lambda v: v["webhook"].strip(),
        place="webhook",
    ),
    "slack": Service(
        "Slack",
        (
            Field(
                "webhook",
                "Webhook",
                "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
                secret=True,
            ),
        ),
        lambda v: v["webhook"].strip(),
        place="webhook",
    ),
    "telegram": Service(
        "Telegram",
        (
            Field("token", "Bot token", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ", secret=True),
            Field("chat", "Chat ID", "-1001234567890"),
        ),
        lambda v: f"tgram://{_q(v['token'])}/{_q(v['chat'])}",
        place="chat",
    ),
    "matrix": Service(
        "Matrix",
        (
            Field("server", SERVER, "https://matrix.org"),
            Field("token", "Access token", "syt_cm9iaW4_AbCdEfGhIjKlMnOpQrSt", secret=True),
            Field("room", "Room", "#robin:matrix.org"),
        ),
        lambda v: (
            f"{_server(v['server'], 'matrix', 'matrixs')}/{_q(v['room'])}"
            f"?{urlencode({'token': v['token'].strip()})}"
        ),
        place="room",
    ),
    "gotify": Service(
        "Gotify",
        (
            Field("server", SERVER, "https://gotify.example.com"),
            Field("token", "App token", "AbCdEf.GhIjKl", secret=True),
        ),
        lambda v: f"{_server(v['server'], 'gotify', 'gotifys')}/{_q(v['token'])}",
    ),
    "pushover": Service(
        "Pushover",
        (
            Field("user", "User key", "uQiRzpo4DXghDmr9QzzfQu27cmVRsG", secret=True),
            Field("token", "App token", "azGDORePK8gMaC0QOYAMyEEuzJnyUi", secret=True),
            Field("device", "Device", "phone", optional=True),
        ),
        lambda v: f"pover://{_q(v['user'])}@{_q(v['token'])}/{_q(v.get('device', ''))}",
        place="device",
    ),
    "pushbullet": Service(
        "Pushbullet",
        (
            Field("token", "Access token", "o.AbCdEfGhIjKlMnOpQrStUvWxYz012345", secret=True),
            Field("target", "Device or #channel", "#robin", optional=True),
        ),
        lambda v: f"pbul://{_q(v['token'])}/{_q(v.get('target', ''))}",
        place="target",
    ),
    "homeassistant": Service(
        "Home Assistant",
        (
            Field("server", SERVER, "https://homeassistant.local:8123"),
            Field("token", "Long-lived token", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", secret=True),
        ),
        lambda v: f"{_server(v['server'], 'hassio', 'hassios')}/{_q(v['token'])}",
    ),
    "signal": Service(
        "Signal",
        (
            Field("server", SERVER, "http://signal-cli-rest-api:8080"),
            Field("sender", "From", "+15551234567"),
            Field("to", "To", "+15557654321"),
        ),
        lambda v: f"{_server(v['server'], 'signal', 'signals')}/{_q(v['sender'])}/{_q(v['to'])}",
        place="to",
    ),
    "prowl": Service(
        "Prowl",
        (Field("key", "API key", "f00d4a1c0ffee5b2d8e7a6c3b9f1e0d2c4a6b8e0", secret=True),),
        lambda v: f"prowl://{_q(v['key'])}",
    ),
    "apprise": Service(
        "Other",
        (Field("url", "Apprise URL", "schema://credentials/target", secret=True),),
        lambda v: v["url"].strip(),
    ),
}

CATEGORIES: tuple[db.Category, ...] = ("games", "comics", "screens", "books")

Destination = dict[str, Any]


def values(destination: Destination, category: db.Category | None = None) -> Values:
    """A destination's fields, its place the category's own when it has one there."""
    found = {k: str(v) for k, v in destination["values"].items()}
    service = SERVICES[destination["service"]]
    place = (destination.get("places") or {}).get(category) if category else None
    if service.place and place:
        found[service.place] = place
    return found


def address(destination: Destination, category: db.Category | None = None) -> str:
    return SERVICES[destination["service"]].url(values(destination, category))


def check(destination: Destination) -> None:
    """Raise ValueError unless every required field is set and Apprise reads the address, at
    the destination's own place and at each category's."""
    service = SERVICES.get(destination.get("service", ""))
    if service is None:
        raise ValueError("Unknown service")
    given = values(destination)
    for f in service.fields:
        if not f.optional and not given.get(f.key, "").strip():
            raise ValueError(f"{service.label}: {f.label} is required")
    for category in (None, *CATEGORIES):
        if apprise.Apprise.instantiate(address(destination, category)) is None:
            raise ValueError(f"{service.label}: not a valid address")


def secrets(destinations: list[Destination]) -> list[str]:
    """Every secret the destinations hold, a place that is one included, for log redaction."""
    found = []
    for destination in destinations:
        service = SERVICES.get(destination.get("service", ""))
        if service is None:
            continue
        for f in service.fields:
            if f.secret:
                found.append(str(destination["values"].get(f.key, "")))
                if f.key == service.place:
                    found.extend(str(p) for p in (destination.get("places") or {}).values())
    return [s for s in found if s]


def masked(destinations: list[Destination]) -> list[Destination]:
    """As the API reports them: each secret blank and named in `saved` while one is kept, and
    a place that is a secret named by its category in `saved_places`."""
    out = []
    for destination in destinations:
        service = SERVICES[destination["service"]]
        secret = {f.key for f in service.fields if f.secret}
        places = dict(destination.get("places") or {})
        hide = service.place in secret
        out.append(
            {
                "id": destination["id"],
                "service": destination["service"],
                "values": {k: "" if k in secret else v for k, v in destination["values"].items()},
                "saved": sorted(k for k in secret if destination["values"].get(k)),
                "places": {c: "" if hide else p for c, p in places.items()},
                "saved_places": sorted(places) if hide else [],
            }
        )
    return out


def merged(sent: list[Destination], stored: list[Destination]) -> list[Destination]:
    """The destinations as sent, a blank secret keeping the one stored for the same
    destination. One whose address moved keeps none, so a key never goes on to a host it was
    not given for."""
    before = {d["id"]: d for d in stored}
    out = []
    for destination in sent:
        service = SERVICES[destination["service"]]
        secret = {f.key for f in service.fields if f.secret}
        kept = before.get(destination["id"])
        vals = {k: str(v).strip() for k, v in destination["values"].items()}
        places = {c: str(p).strip() for c, p in (destination.get("places") or {}).items()}
        if kept and kept["service"] == destination["service"]:
            moved = any(
                vals.get(f.key, "") != kept["values"].get(f.key, "")
                for f in service.fields
                if not f.secret and f.key != service.place
            )
            if not moved:
                for key in secret:
                    vals[key] = vals.get(key) or kept["values"].get(key, "")
                if service.place in secret:
                    old = kept.get("places") or {}
                    places = {c: p or old.get(c, "") for c, p in places.items()}
        out.append(
            {
                "id": destination["id"],
                "service": destination["service"],
                "values": {k: v for k, v in vals.items() if v},
                "places": {c: p for c, p in places.items() if p},
            }
        )
    return out


# ---------------------------------------------------------------- sending


async def send(
    settings: db.Settings,
    channel: db.Channel,
    *,
    title: str,
    message: str,
    tags: str = "video_game",
    click: str | None = None,
    attach: str | None = None,
) -> None:
    """Send one notice on a category's channel to every destination, or keep it while the
    category's quiet hours last. Raises NotifyError when no destination took it."""
    if not settings.notify_destinations:
        raise NotifyError("No notification destination. Add one in Settings.")
    if held_until(channel.quiet, notices.local_now()) is not None:
        db.hold_notice(channel.category, title, message, tags, click, attach)
        log.info("notify: %r kept until quiet hours end", title)
        return
    await deliver(
        settings.notify_destinations,
        channel.category,
        title=title,
        message=message,
        tags=tags,
        click=click,
        attach=attach,
    )


async def deliver(
    destinations: list[Destination],
    category: db.Category | None,
    *,
    title: str,
    message: str,
    tags: str = "",
    click: str | None = None,
    attach: str | None = None,
) -> None:
    """Send to each destination now. One that fails is logged and kept for Health, and only
    when every one failed is it raised, so a retry never repeats a notice to one it reached."""
    failures = []
    for destination in destinations:
        service = SERVICES[destination["service"]]
        url = address(destination, category)
        body = message
        image = attach
        if service.options:
            given = {k: v for k, v in {"click": click, "attach": attach, "tags": tags}.items() if v}
            if given:
                url += ("&" if "?" in url else "?") + urlencode(given)
            image = None
        elif click:
            body = f"{message}\n{click}"
        error = await _deliver(url, title=title, body=body, attach=image)
        if error and image:
            # An image that cannot be fetched never holds a notice back.
            error = await _deliver(url, title=title, body=body, attach=None)
        key = f"notify:error:{destination['id']}"
        if error:
            failures.append(f"{service.label}: {error}")
            db.cache_put(key, error, ERROR_TTL)
            log.warning("notify: %s did not take %r: %s", service.label, title, error)
        else:
            db.cache_drop(key)
    if failures and len(failures) == len(destinations):
        raise NotifyError("; ".join(failures))


async def _deliver(url: str, *, title: str, body: str, attach: str | None) -> str | None:
    """One message to one Apprise address. None once sent, else why not."""

    def run() -> str | None:
        notifier = apprise.Apprise()
        if not notifier.add(url):
            return "not a valid address"
        said: list[str] = []
        sent = notifier.notify(
            body=body,
            title=title,
            attach=attach,
            log_callback=lambda entry, _plugin: said.append(entry.message),
            log_level=logging.WARNING,
        )
        return None if sent else (said[-1] if said else "not delivered")

    return await asyncio.to_thread(run)


LABELS: dict[db.Category, str] = {
    "games": "Games",
    "comics": "Comics",
    "screens": "Screens",
    "books": "Books",
}


def digest(rows: list[dict[str, Any]]) -> str:
    """Every notice kept, oldest first: its title, its text and its link."""
    parts = []
    for row in rows:
        lines = [f"• {row['title']}", f"  {row['message']}"]
        if row["click"]:
            lines.append(f"  {row['click']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def send_held(now: datetime | None = None) -> int:
    """Send what quiet hours kept, per category once they are over: a notice alone as it was,
    several as one While you were away digest. Returns how many were sent."""
    held = db.held_notices()
    if not held:
        return 0
    settings = db.get_settings()
    now = now or notices.local_now()
    sent = 0
    for category, rows in held.items():
        channel = settings.notices(category)
        if channel is None or held_until(channel.quiet, now) is not None:
            continue
        one = rows[0]
        alone = len(rows) == 1
        try:
            await deliver(
                settings.notify_destinations,
                category,
                title=(
                    one["title"]
                    if alone
                    else f"While you were away: {len(rows)} {LABELS[category]} notifications"
                ),
                message=one["message"] if alone else digest(rows),
                tags=one["tags"] if alone else "zzz",
                click=one["click"] if alone else None,
                attach=one["attach"] if alone else None,
            )
        except NotifyError as exc:
            log.warning("notify: %s kept notices wait: %s", category, exc)
            continue
        db.drop_held([int(r["id"]) for r in rows])
        sent += 1
    return sent


async def health(settings: db.Settings) -> None:
    """Raise with why while a destination is not a valid address or failed its last notice.
    It never sends one, so healthy means the last notice was taken."""
    errors = []
    for destination in settings.notify_destinations:
        check(destination)
        error = db.cache_get(f"notify:error:{destination['id']}")
        if error:
            errors.append(f"{SERVICES[destination['service']].label}: {error}")
    if errors:
        raise ValueError("; ".join(errors))


def held_until(quiet: tuple[int, int] | None, now: datetime) -> datetime | None:
    """When the quiet hours `now` falls in end, or None outside them. They may span midnight."""
    if quiet is None:
        return None
    start, end = quiet
    inside = start <= now.hour < end if start < end else now.hour >= start or now.hour < end
    if not inside:
        return None
    ends = now.replace(hour=end, minute=0, second=0, microsecond=0)
    return ends if ends > now else ends + timedelta(days=1)


def _release_date(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, tz=UTC).date()


def due_for_notice(
    rows: list[dict[str, Any]], window: notices.Window
) -> list[tuple[dict[str, Any], notices.Due]]:
    """Monitored games with a notice of the schedule due. The marker holds the release it was
    sent for, so a date that moves is announced again: an Early Access date replaced by the
    full one, or a plain delay."""
    found = []
    for row in rows:
        if not row["first_release_date"]:
            continue
        due = window.pending(_release_date(row["first_release_date"]), row["notified_for"])
        if due is not None:
            found.append((row, due))
    return found


def undated(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ones IGDB still lists as TBA."""
    return [row for row in rows if row["first_release_date"] is None]


def _shown(settings: db.Settings) -> list[dict[str, Any]]:
    """Monitored games, but those Settings hides."""
    return [row for row in db.notifiable_requests() if hidden.game(settings, row)]


async def notify_upcoming_releases(now: datetime | None = None) -> int:
    """Send each notice due for a monitored game. Returns how many were sent."""
    settings = db.get_settings()
    channel = settings.notices("games")
    window = notices.window(settings, "games", now)
    if channel is None or window is None:
        return 0

    sent = 0
    for row, due in due_for_notice(_shown(settings), window):
        release = _release_date(row["first_release_date"])
        try:
            await send(
                settings,
                channel,
                title=f"{row['game_name']} is out {window.relative(release)}",
                message=f"Releases {release.isoformat()}.{_kind(row['release_status'])}",
                click=f"https://www.igdb.com/games/{row['igdb_id']}",
            )
        except NotifyError as exc:
            # Leave the marker unset so the next pass tries again.
            log.warning("notify: could not notify for %s: %s", row["game_name"], exc)
            continue

        db.mark_release_notified(int(row["id"]), due.marker, done=due.last)
        log.info("notify: notified that %s releases %s", row["game_name"], release)
        sent += 1

    return sent


def _kind(status: str | None) -> str:
    """Names the release only when it is not a full one, which is what a game is taken to be.

    A grab that turns out to be an Early Access build is the surprise worth warning about.
    """
    return "" if not status or status == igdb.FULL_RELEASE_STATUS else f" {status}."


async def notify_new_release_dates() -> int:
    """Tell the user when a game that was TBA finally gets a date on IGDB.

    No marker is needed to avoid repeats: once IGDB has a date the game is no longer TBA, so
    it drops out of this set by itself.
    """
    settings = db.get_settings()
    channel = settings.notices("games")
    if channel is None:
        return 0

    waiting = undated(_shown(settings))
    if not waiting:
        return 0

    fresh = await igdb.refresh_games([int(row["igdb_id"]) for row in waiting])

    sent = 0
    for row in waiting:
        game = fresh.get(int(row["igdb_id"]))
        if not game or not game.get("first_release_date"):
            continue

        release = _release_date(int(game["first_release_date"]))
        try:
            await send(
                settings,
                channel,
                title=f"{row['game_name']} has a release date",
                message=(
                    f"IGDB now lists it for {release.isoformat()}."
                    f"{_kind(game.get('release_status'))}"
                ),
                tags="calendar",
                click=f"https://www.igdb.com/games/{row['igdb_id']}",
            )
        except NotifyError as exc:
            log.warning("notify: could not announce a date for %s: %s", row["game_name"], exc)
            continue

        log.info("notify: %s is now dated %s", row["game_name"], release)
        sent += 1

    return sent


async def watch(*checks: Callable[[], Awaitable[int]], every: int = CHECK_INTERVAL_SECONDS) -> None:
    """Background loop over `checks`. Cancelled on shutdown by the lifespan handler."""
    while True:
        for check in checks:
            try:
                await check()
            except upstream.RateLimited as exc:
                # The pause was logged when it began. The check runs again on the next pass.
                log.info("notify: %s waits, %s until %s", check.__name__, exc, exc.until)
            except Exception:  # noqa: BLE001
                # A loop that dies takes every future notification with it.
                log.exception("notify: %s failed", check.__name__)
        await asyncio.sleep(every)
