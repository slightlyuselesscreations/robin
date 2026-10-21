"""Remind me notices for Screens, on the Screens topic.

A movie's reminder is for one release type in the region, Cinema or Digital, and ends once
its last notice is sent. A show's covers every season premiere until it is removed. Each pass
reads the title's cached TMDB detail, so a date that moves is followed, and sends each notice
of the Screens schedule as `notices.Window` says it is due.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from robin import db, hidden, notices, notify, tmdb, upstream

log = logging.getLogger(__name__)


def premiere(show: dict[str, Any]) -> dict[str, Any] | None:
    """The show's next episode when it opens a season, the only kind a reminder announces."""
    upcoming = show.get("next_episode_to_air") or {}
    if upcoming.get("episode_number") == 1 and upcoming.get("air_date"):
        return dict(upcoming)
    return None


def premiere_date(detail: dict[str, Any]) -> str | None:
    """The day a show's next season opens, from its shaped detail. A show's reminder is dated
    by it, never by an episode inside a season, and is undated while none is set."""
    upcoming = detail.get("next_episode") or {}
    return upcoming.get("date") if upcoming.get("episode") == 1 else None


async def shown(settings: db.Settings, kind: str, tmdb_id: int) -> bool:
    """Whether Settings leaves a title shown, read from its cached detail. One TMDB cannot be
    asked about just now stays."""
    try:
        raw = await (tmdb.movie if kind == "movie" else tmdb.show)(settings, tmdb_id)
    except upstream.UpstreamError:
        return True
    return hidden.detail(settings, kind, raw)


def _where(release_type: str, platform: str | None) -> str:
    """How a notice names a film's release."""
    if release_type == "theatrical":
        return "in cinemas"
    return f"on {platform}" if platform else "out digitally"


async def notify_reminders(now: datetime | None = None) -> int:
    """Send each reminder that is due. Returns how many were sent."""
    settings = db.get_settings()
    window = notices.window(settings, "screens", now)
    if window is None:
        return 0
    sent = 0
    for row in db.waiting("reminders"):
        if not await shown(settings, row["kind"], int(row["tmdb_id"])):
            continue
        try:
            if row["kind"] == "movie":
                sent += await _movie(settings, row, window)
            else:
                sent += await _show(settings, row, window)
        except tmdb.TmdbError as exc:
            log.warning("reminders: could not read %s: %s", row["title"], exc)
        except notify.NotifyError as exc:
            # Nothing is marked, so the next pass tries again.
            log.warning("reminders: could not notify for %s: %s", row["title"], exc)
    return sent


async def _movie(settings: db.Settings, row: dict[str, Any], window: notices.Window) -> int:
    film = await tmdb.movie(settings, int(row["tmdb_id"]))
    catalogue = await tmdb.platforms(settings)
    [found] = tmdb.regional_releases(
        film, settings.tmdb_region, window.today.isoformat(), [row["release_type"]], catalogue
    ) or [{"date": None, "platform": None}]
    when, platform = found["date"], found["platform"]
    title, poster = film.get("title") or row["title"], tmdb.image(film.get("poster_path"), "w342")
    if (when, (platform or {}).get("name"), title, poster) != (
        row["date"],
        row["platform"],
        row["title"],
        row["poster"],
    ):
        db.update_reminder(int(row["id"]), when, platform, title, poster)
    word = _where(row["release_type"], (platform or {}).get("name"))
    told = await _told(settings, row, f"{title} {word}", when, window.today)
    due = window.pending(date.fromisoformat(when), row["notified_for"]) if when else None
    if due is None:
        return told
    await _send(
        settings,
        row,
        title=f"{title} is {word} {window.relative(date.fromisoformat(when))}",
        message=f"Releases {when} in {settings.tmdb_region}.",
        tags="clapper",
    )
    db.mark_notified("reminders", int(row["id"]), due.marker, done=due.last)
    return told + 1


async def _show(settings: db.Settings, row: dict[str, Any], window: notices.Window) -> int:
    show = await tmdb.show(settings, int(row["tmdb_id"]))
    episode = premiere(show)
    upcoming = episode["air_date"] if episode else None
    title, poster = show.get("name") or row["title"], tmdb.image(show.get("poster_path"), "w342")
    if (upcoming, title, poster) != (row["date"], row["title"], row["poster"]):
        db.update_reminder(int(row["id"]), upcoming, tmdb.network(show), title, poster)
    told = await _told(settings, row, title, upcoming, window.today)
    if episode is None:
        return told
    when = date.fromisoformat(episode["air_date"])
    due = window.pending(when, row["notified_for"])
    if due is None:
        return told
    season = episode.get("season_number")
    await _send(
        settings,
        row,
        title=f"{title} season {season} premieres {window.relative(when)}",
        message=f"Season {season} starts {episode['air_date']}.",
        tags="tv",
    )
    db.mark_notified("reminders", int(row["id"]), due.marker, done=False)
    return told + 1


async def _told(
    settings: db.Settings, row: dict[str, Any], name: str, when: str | None, today: date
) -> int:
    """Tell of a reminder's date changing, `notices.tell_change`. Returns how many were sent."""

    async def tell(change: notices.Change) -> None:
        await _send(settings, row, title=change.title, message=change.message, tags="calendar")

    return await notices.tell_change(
        name,
        row["dated_as"],
        when or "",
        today,
        tell,
        lambda value: db.set_dated_as("reminders", int(row["id"]), value),
    )


async def _send(
    settings: db.Settings, row: dict[str, Any], *, title: str, message: str, tags: str
) -> None:
    await notify.send(
        settings,
        settings.channel("screens"),
        title=title,
        message=message,
        tags=tags,
        click=f"https://www.themoviedb.org/{row['kind']}/{row['tmdb_id']}",
        attach=row["poster"],
    )
    log.info("reminders: %s", title)


async def monitor_title(settings: db.Settings, kind: tmdb.Kind, tmdb_id: int) -> bool:
    """Monitor a title as its dialog's Monitor would, every variant it allows: each release
    type a film can be monitored for, dated or still awaited, a show's season premieres. False
    when there is nothing to monitor, a title out already."""
    detail = await tmdb.title(settings, kind, tmdb_id)
    if not detail["monitorable"]:
        return False
    dated = {r["type"]: r for r in detail["releases"]}
    variants = (
        [
            (name, (dated.get(name) or {}).get("date"), (dated.get(name) or {}).get("platform"))
            for name in detail["open_releases"]
        ]
        if kind == "movie"
        else [("", premiere_date(detail), detail["platform"])]
    )
    for release_type, when, platform in variants:
        db.add_reminder(
            kind=kind,
            tmdb_id=tmdb_id,
            release_type=release_type,
            title=detail["title"],
            poster=detail["poster"],
            date=when,
            platform=platform,
        )
    return bool(variants)
