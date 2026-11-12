"""Favourites: what releases come from, starred, and the notice for each new one.

A favourite is a game company, franchise or series on IGDB, a series, person or publisher on
Metron, a person, studio or network on TMDB, or an author or series on Hardcover. Each
category's search finds them beside its titles.
A favourite's new releases are announced on the category's topic, at each notice of its
schedule, when its notices and its favourites switch are on, and never for a title the user
already monitors, which has its own notices. With the category's Monitor switch on, each new
release is monitored instead, once: one the user stops monitoring stays stopped.

What a favourite has coming is kept six hours under `COMING_PREFIX`. Its dialog, Home and the
hourly notices all read it from there, so a source is asked about each favourite at most four
times a day.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any, Literal

from robin import (
    arr,
    comics,
    db,
    hardcover,
    hidden,
    igdb,
    notices,
    notify,
    reminders,
    suwayomi,
    tmdb,
    upstream,
)
from robin.routes.common import decorate

log = logging.getLogger(__name__)

Category = Literal["games", "comics", "screens", "books"]

KINDS: dict[Category, tuple[str, ...]] = {
    "games": ("company", "franchise", "collection"),
    # A series is what Comics titles search finds, so it is not searched as a kind of its own.
    "comics": ("series", "person", "publisher", "character", "universe"),
    "screens": ("person", "studio", "network"),
    "books": ("author", "series"),
}

COMING_PREFIX = "favourite:coming:v4:"
# As a category's page, but for comics, whose publisher and creator lists run months ahead.
COMING_TTL = 3600
COMICS_COMING_TTL = 6 * 3600


async def search(
    settings: db.Settings,
    category: Category,
    query: str,
    everything: bool = False,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """What can be favourited in the category, matching `query`, each with `ids`. A maker
    hidden is left out, unless `everything` is asked for, as Settings picking filters does.
    `kind` narrows comics to one kind, a call to Metron each."""
    if category == "games":
        found = await igdb.search_favourites(query)
    elif category == "comics":
        found = await comics.search_favourites(query, kind)
    elif category == "screens":
        found = await tmdb.search_favourites(settings, query)
    else:
        found = await hardcover.search_favourites(settings, query)
    for entity in found:
        entity.setdefault("ids", [entity["id"]])
    if everything:
        return found
    hidden_ids = settings.hidden_makers.get(category, {})
    return [e for e in found if hidden_ids.get(e["kind"], frozenset()).isdisjoint(e["ids"])]


async def entity(
    settings: db.Settings, category: Category, kind: str, source_id: int
) -> dict[str, Any] | None:
    """One favourite as its source has it, with `ids`, every source id it covers."""
    if category == "games":
        found = await igdb.favourite(kind, source_id)
    elif category == "comics":
        found = await comics.favourite(kind, source_id)
    elif category == "screens":
        found = await tmdb.favourite(settings, kind, source_id)
    else:
        found = await hardcover.favourite(settings, kind, source_id)
    if found is not None:
        found.setdefault("ids", [found["id"]])
    return found


async def coming(
    settings: db.Settings, category: Category, kind: str, ids: list[int]
) -> list[dict[str, Any]]:
    """What one favourite has coming, in the category's own title shape, unstarred, but what
    Settings hides. The cache keeps all of it, so a change in Settings applies at once."""
    shown = igdb.platforms(settings.games_hidden_platforms)

    async def fetch() -> list[dict[str, Any]]:
        if category == "games":
            return await igdb.favourite_releases(kind, ids, shown)
        if category == "comics":
            return await comics.favourite_releases(kind, ids)
        if category == "screens":
            return await tmdb.favourite_releases(settings, kind, ids)
        return await hardcover.favourite_releases(settings, kind, ids)

    key = f"{COMING_PREFIX}{category}:{kind}:" + ",".join(map(str, sorted(ids)))
    if category == "games":
        # The platforms Settings keeps make a list of their own.
        key += ":" + ",".join(map(str, sorted(shown)))
    ttl = COMICS_COMING_TTL if category == "comics" else COMING_TTL
    found: list[dict[str, Any]] = await db.remember(key, ttl, fetch)
    if category == "comics":
        suwayomi.link(found)
    if category == "screens":
        return await tmdb.unhidden(settings, found)
    if category == "books":
        return [b for b in found if hidden.book(settings, b)]
    if category == "comics":
        await comics.credit(settings, found)
        return [c for c in found if hidden.comic(settings, comics.made(c))]
    return [g for g in found if hidden.game(settings, g)]


async def releases(
    settings: db.Settings, category: Category, kind: str, ids: list[int]
) -> list[dict[str, Any]]:
    """What one favourite has coming, starred."""
    titles = await coming(settings, category, kind, ids)
    if category == "games":
        return decorate(titles)
    if category == "comics":
        return comics.star(titles, db.favourites("comics"))
    if category == "screens":
        await tmdb.star(settings, titles, db.favourites("screens"))
        return titles
    hardcover.star(titles, db.favourites("books"))
    return titles


PLATFORM_TAGS = {"pc": "PC", "playstation": "PS", "xbox": "X", "nintendo": "N"}


def tag(category: Category, release: dict[str, Any]) -> str | None:
    """What a card tags a release with, for the list that has no room for more: the platform
    families a game is only on and EA, Cinema, Digital or Series, a #1 and its publisher, a
    book in a series."""
    parts: list[str | None]
    if category == "games":
        parts = [PLATFORM_TAGS[f] for f in release.get("exclusive") or []]
        parts.append("EA" if release.get("release_status") == "Early Access" else None)
    elif category == "comics":
        return comics.tag(release)
    elif category == "screens":
        parts = ["Series" if release["kind"] == "tv" else release.get("release")]
    else:
        parts = ["Series" if release.get("series") else None]
    return " · ".join(p for p in parts if p) or None


def _brief(category: Category, release: dict[str, Any]) -> dict[str, Any]:
    """One release in a shape every category shares: its key, title, day, art, and where it
    opens in Robin as a dialog parameter."""
    if category == "games":
        stamp = release["first_release_date"]
        cover = release["cover_image_id"]
        return {
            "key": str(release["igdb_id"]),
            "title": release["name"],
            "date": datetime.fromtimestamp(stamp, tz=UTC).date() if stamp else None,
            "art": igdb.image_url(cover) if cover else None,
            "image": f"/img/cover_big/{cover}.jpg" if cover else None,
            "to": f"game={release['igdb_id']}",
        }
    if category == "comics":
        return {
            "key": release["id"],
            "title": release["title"],
            "date": date.fromisoformat(release["date"]) if release["date"] else None,
            "art": release["cover"],
            "image": release["cover"],
            "to": f"comic={release['id']}",
        }
    if category == "screens":
        return {
            "key": f"{release['kind']}-{release['id']}",
            "title": release["title"],
            "date": date.fromisoformat(release["date"][:10]) if release["date"] else None,
            "art": release["poster"],
            "image": release["poster"],
            "to": f"title={release['kind']}-{release['id']}",
        }
    return {
        "key": str(release["id"]),
        "title": release["title"],
        "date": date.fromisoformat(release["date"]) if release["date"] else None,
        "art": release["cover"],
        "image": release["cover"],
        "to": f"book={release['id']}",
    }


async def dated(settings: db.Settings) -> list[dict[str, Any]]:
    """Every favourite's dated releases, for Home, each once. A category whose source is
    unset, or that cannot be read just now, is left out rather than failing the rest."""

    async def releases(favourite: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            kind, ids = favourite["kind"], favourite["ids"]
            return await coming(settings, favourite["category"], kind, ids)
        except upstream.UpstreamError as exc:
            log.info("favourites: no releases for %s: %s", favourite["name"], exc)
            return []

    favourites = db.favourites()
    # Asked together, each source paced by its own limit, so the slowest decides the wait.
    every = await asyncio.gather(*map(releases, favourites))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for favourite, titles in zip(favourites, every, strict=True):
        category = favourite["category"]
        for release in titles:
            brief = _brief(category, release)
            if brief["date"] is None:
                continue
            found.setdefault(
                (category, brief["key"]),
                {
                    "category": category,
                    "key": brief["key"],
                    "title": brief["title"],
                    "image": brief["image"],
                    "date": brief["date"].isoformat(),
                    "to": brief["to"],
                    "tag": tag(category, release),
                    "favourite": favourite["name"],
                },
            )
    return sorted(found.values(), key=lambda r: (r["date"], r["title"]))


# ---------------------------------------------------------------- notices


def _row_key(category: Category, row: dict[str, Any]) -> str | None:
    """A monitored row by `_monitor_key`, None for a comic series no Metron series names."""
    if category == "games":
        return str(row["igdb_id"])
    if category == "comics":
        return f"series-{row['series_id']}" if row["series_id"] else None
    if category == "screens":
        return f"{row['kind']}-{row['tmdb_id']}"
    return str(row["hardcover_id"])


def _monitored(category: Category) -> set[str]:
    """The titles the user monitors, by `_monitor_key`."""
    keys = (_row_key(category, r) for r in db.rows(db.ORIGIN_ROWS[category][0]))
    return {key for key in keys if key}


def _row_title(category: Category, row: dict[str, Any]) -> str:
    names = {"games": "game_name", "comics": "series", "screens": "title", "books": "title"}
    return str(row[names[category]])


async def reach(
    settings: db.Settings, favourite: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Everything a favourite put anywhere, each with its `rows` in Robin and the integration
    `held` by it: what was monitored from it, and what it has coming that a library holds. What
    the user monitored, or another favourite did, is not its own. Beside it, the libraries that
    could not be read, whose titles it cannot name."""
    held: dict[str, str] = {}
    unread: list[str] = []
    if settings.radarr_ready or settings.sonarr_ready:
        try:
            held = dict(await arr.library(settings))
        except upstream.UpstreamError as exc:
            log.warning("favourites: could not read the libraries: %s", exc)
            unread = [name for app, name in arr.NAMES.items() if arr.ready(settings, app)]
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def take(category: Category, key: str, title: str, rows: list[dict[str, Any]]) -> None:
        entry = {"category": category, "key": key, "title": title, "rows": []}
        kept = found.setdefault((category, key), entry)["rows"]
        kept += [r for r in rows if r["id"] not in {k["id"] for k in kept}]

    for category, (table, _) in db.ORIGIN_ROWS.items():
        for row in db.rows(table):
            if (row["origin"] or {}).get("id") == favourite["id"]:
                key = _row_key(category, row) or f"row-{row['id']}"
                take(category, key, _row_title(category, row), [row])

    mine: Category = favourite["category"]
    by_key: dict[str | None, list[dict[str, Any]]] = {}
    for row in db.rows(db.ORIGIN_ROWS[mine][0]):
        by_key.setdefault(_row_key(mine, row), []).append(row)
    titles: list[dict[str, Any]] = []
    try:
        titles = await coming(settings, mine, favourite["kind"], favourite["ids"])
    except Exception as exc:  # noqa: BLE001
        log.warning("favourites: could not read %s: %s", favourite["name"], exc)
    for release in titles:
        key = _monitor_key(mine, release)
        rows = by_key.get(key, [])
        others = any(not r["origin"] or r["origin"].get("id") for r in rows)
        wanted = new_series(mine, favourite["kind"], release)
        if wanted and not others and (rows or (mine == "screens" and key in held)):
            take(mine, key, _brief(mine, release)["title"], rows)

    for entry in found.values():
        in_suwayomi = any(r.get("suwayomi_id") for r in entry["rows"])
        comic = entry["category"] == "comics" and in_suwayomi and settings.suwayomi_ready
        entry["held"] = "suwayomi" if comic else held.get(entry["key"])
    return list(found.values()), unread


async def remove_everywhere(
    settings: db.Settings, entry: dict[str, Any], delete_files: bool
) -> None:
    """Take one of `reach` out of the integration holding it, then out of Robin."""
    if entry["held"] == "suwayomi":
        for row in entry["rows"]:
            if row.get("suwayomi_id"):
                await suwayomi.remove_from_library(settings, int(row["suwayomi_id"]))
    elif entry["held"]:
        kind, tmdb_id = entry["key"].split("-")
        await arr.remove(settings, kind, int(tmdb_id), delete_files)
    table = db.ORIGIN_ROWS[entry["category"]][0]
    for row in entry["rows"]:
        db.delete_row(table, int(row["id"]))


def _monitor_key(category: Category, release: dict[str, Any]) -> str:
    """What monitoring a release monitors: a comic's series, anything else the release itself."""
    if category == "comics":
        return f"series-{release['series_id']}"
    return str(_brief(category, release)["key"])


async def notify_favourites(now: datetime | None = None) -> int:
    """Notify each favourite's new release that is due. Returns how many were sent."""
    settings = db.get_settings()
    sent = 0
    for category in KINDS:
        channel = settings.favourite_notices(category)
        window = notices.window(settings, category, now)
        if channel is None or window is None:
            continue
        stars = db.favourites(category)
        if not stars:
            continue
        noticed = db.favourite_noticed(category)
        monitored = _monitored(category)
        for favourite in stars:
            try:
                titles = await coming(settings, category, favourite["kind"], favourite["ids"])
            except Exception as exc:  # noqa: BLE001
                log.warning("favourites: could not read %s: %s", favourite["name"], exc)
                continue
            for raw in titles:
                release = _brief(category, raw)
                when = release["date"]
                if _monitor_key(category, raw) in monitored or when is None:
                    continue
                if not new_series(category, favourite["kind"], raw):
                    continue
                due = window.pending(when, noticed.get(release["key"]))
                if due is None:
                    continue
                try:
                    await notify.send(
                        settings,
                        channel,
                        about=db.Notified(
                            release["title"],
                            release["to"],
                            release["image"],
                            tag(category, raw),
                            favourite["name"],
                        ),
                        title=f"{release['title']} is out {window.relative(when)}",
                        message=f"From {favourite['name']}. Releases {when.isoformat()}.",
                        attach=release["art"],
                    )
                except notify.NotifyError as exc:
                    # Nothing is marked, so the next pass tries again.
                    log.warning("favourites: could not notify for %s: %s", release["title"], exc)
                    continue
                db.mark_favourite_noticed(category, release["key"], due.marker)
                noticed[release["key"]] = due.marker
                log.info("favourites: %s, from %s", release["title"], favourite["name"])
                sent += 1
    return sent


# ---------------------------------------------------------------- monitoring


def new_series(category: Category, kind: str, release: dict[str, Any]) -> bool:
    """Whether a release is news of a favourite. A comic favourite but a series takes a new
    series, its #1, as a studio takes a new show, never the next issue of a run."""
    return category != "comics" or kind == "series" or release["number"] == "1"


async def monitor_favourites() -> int:
    """Monitor each favourite's new release, in a category whose Monitor switch is on, once,
    each kept as from that favourite and told. A row monitored from a favourite before Robin
    kept which is matched to the first that has it coming. Returns how many were monitored."""
    settings = db.get_settings()
    added = 0
    for category in KINDS:
        monitor = settings.favourites_monitor(category)
        unnamed = db.unnamed_favourite_origins(category)
        stars = db.favourites(category)
        if not stars or not (monitor or unnamed):
            continue
        done = db.favourite_monitored(category) | _monitored(category)
        told: list[tuple[dict[str, Any], str]] = []
        for favourite in stars:
            why = {"kind": "favourite", "id": favourite["id"], "name": favourite["name"]}
            try:
                titles = await coming(settings, category, favourite["kind"], favourite["ids"])
            except upstream.UpstreamError as exc:
                log.warning("favourites: could not read %s: %s", favourite["name"], exc)
                continue
            for release in titles:
                key = _monitor_key(category, release)
                if key in unnamed:
                    db.set_origin(category, key, why)
                    unnamed.discard(key)
                if not monitor or key in done:
                    continue
                if not new_series(category, favourite["kind"], release):
                    continue
                try:
                    made = await _monitor(settings, category, release)
                except upstream.UpstreamError as exc:
                    log.warning("favourites: could not monitor %s: %s", key, exc)
                    continue
                if not made:
                    continue
                db.mark_favourite_monitored(category, key)
                db.set_origin(category, key, why)
                done.add(key)
                brief = {**_brief(category, release), "tag": tag(category, release)}
                told.append((brief, favourite["name"]))
                log.info("favourites: monitoring %s %s, from %s", category, key, favourite["name"])
                added += 1
        await _tell_monitored(settings, category, told)
    return added


# More monitored from favourites at once than this go out as one notice.
TELL_APART = 3


async def _tell_monitored(
    settings: db.Settings, category: Category, told: list[tuple[dict[str, Any], str]]
) -> None:
    """Tell what a pass monitored from favourites, each on its own, or as one notice past
    `TELL_APART`. Nothing is retried: what was monitored stays monitored either way."""
    channel = settings.notices(category)
    if channel is None or not told:
        return
    label = notify.LABELS[category]

    def item(release: dict[str, Any], name: str) -> db.Notified:
        return db.Notified(release["title"], release["to"], release["image"], release["tag"], name)

    # Each as what it is about, title, message and its art.
    sends: list[tuple[db.Notified | list[db.Notified], str, str, str | None]] = (
        [
            (
                item(release, name),
                f"Now monitoring {release['title']} ({label})",
                f"You favourited {name}.",
                release["art"],
            )
            for release, name in told
        ]
        if len(told) <= TELL_APART
        else [
            (
                [item(release, name) for release, name in told],
                f"Now monitoring {len(told)} releases ({label})",
                "\n".join(f"{release['title']}. You favourited {name}." for release, name in told),
                None,
            )
        ]
    )
    for about, title, message, attach in sends:
        try:
            await notify.send(
                settings,
                channel,
                about=about,
                title=title,
                message=message,
                attach=attach,
            )
        except notify.NotifyError as exc:
            log.warning("favourites: could not tell %s: %s", title, exc)


async def _monitor(settings: db.Settings, category: Category, release: dict[str, Any]) -> bool:
    """Monitor one release as its dialog's Monitor would, every variant it allows, reaching an
    integration only while `favourites_send` lets it. False when there is nothing to monitor
    yet, a film with no release in the region."""
    send = settings.favourites_send == "integrations"
    if category == "games":
        # A monitored game is grabbed, so one only notified stays the favourite's release.
        if settings.prowlarr_ready and not send:
            return False
        db.create_request(int(release["igdb_id"]))
        return True
    if category == "comics":
        await monitor_series(settings, release, auto_add=send)
        return True
    if category == "books":
        db.add_book_reminder(
            kind="book",
            hardcover_id=int(release["id"]),
            book_id=int(release["id"]),
            title=release["title"],
            cover=release["cover"],
            date=release["date"],
        )
        return True
    made = await reminders.monitor_title(settings, release["kind"], int(release["id"]))
    if made and send:
        await arr.follow(settings, release["kind"], int(release["id"]))
    return made


async def monitor_series(
    settings: db.Settings,
    issue: dict[str, Any],
    *,
    to_suwayomi: bool = False,
    auto_add: bool = True,
) -> dict[str, Any]:
    """Monitor the series an issue is of, each new issue announced from Metron. With
    `to_suwayomi`, or with `suwayomi_add` on and `auto_add`, it is added to Suwayomi instead,
    looked for at once and on every pass until the source lists it, and Suwayomi alone announces
    its issues. Either way, a series the library already holds is tracked from there, so its
    issues are never announced twice."""
    to_suwayomi = to_suwayomi or (auto_add and settings.suwayomi_add and settings.suwayomi_ready)
    series = suwayomi.series_title(issue["title"])
    comic = db.monitor_comic(
        issue_id=issue["id"],
        title=issue["title"],
        series=series,
        year=int(issue.get("year") or (issue.get("date") or db.month_start().isoformat())[:4]),
        publisher=issue.get("publisher") or "",
        url=issue["url"],
        cover=issue.get("cover"),
        series_id=issue.get("series_id"),
        suwayomi=to_suwayomi,
    )
    if comic["status"] == "monitored" and settings.suwayomi_ready:
        try:
            match = await suwayomi.find(
                settings, comic["series"], int(comic["year"]), live=to_suwayomi
            )
            if match and (to_suwayomi or match["inLibrary"]):
                await suwayomi.add_if_found(settings, comic, match)
        except suwayomi.SuwayomiError as exc:
            log.warning("suwayomi: %s failed: %s", comic["series"], exc)
    # A row already tracking its run in Suwayomi takes it in, by its issue.
    kept = next((r for r in db.rows("comics") if r["issue_id"] == comic["issue_id"]), None)
    return kept or comic


async def notify_series(now: datetime | None = None) -> int:
    """Send each notice of the comics schedule due for a new issue of a monitored series that
    Suwayomi does not hold, and tell of an issue whose date changes, `notices.date_change`.
    Returns how many were sent.
    An issue is marked as a new #1 is, so neither notice repeats the other."""
    settings = db.get_settings()
    channel = settings.notices("comics")
    window = notices.window(settings, "comics", now)
    if channel is None or window is None:
        return 0
    sent = 0
    for row in db.rows("comics"):
        # Suwayomi announces each issue of a series added to it once it lists it,
        # `sync_library`, and nothing announces one while the source does not list it yet.
        if not row["series_id"] or (row["suwayomi"] and settings.suwayomi_ready):
            continue
        try:
            issues = await coming(settings, "comics", "series", [int(row["series_id"])])
        except upstream.UpstreamError as exc:
            log.warning("comics: could not read %s: %s", row["series"], exc)
            continue
        for issue in issues:

            async def tell(
                change: notices.Change,
                issue: dict[str, Any] = issue,
                series: str = row["series"],
            ) -> None:
                await notify.send(
                    settings,
                    channel,
                    about=db.Notified(
                        series, f"comic={issue['id']}", issue["cover"], comics.tag(issue)
                    ),
                    title=change.title,
                    message=change.message,
                    attach=issue["cover"],
                )

            def store(value: str, issue: dict[str, Any] = issue) -> None:
                comics.mark_dated_as(issue, value)

            try:
                sent += await notices.tell_change(
                    issue["title"],
                    comics.dated_as(issue),
                    issue["date"] or "",
                    window.today,
                    tell,
                    store,
                )
            except notify.NotifyError as exc:
                log.warning("comics: date of %s failed: %s", issue["title"], exc)
                continue
            when = date.fromisoformat(issue["date"]) if issue["date"] else None
            due = when and window.pending(when, comics.seen(issue), grace=6)
            if not when or not due:
                continue
            out = "" if when <= window.today else f" is out {window.relative(when)}"
            try:
                await notify.send(
                    settings,
                    channel,
                    about=db.Notified(
                        row["series"], f"comic={issue['id']}", issue["cover"], comics.tag(issue)
                    ),
                    title=f"{issue['title']}{out}",
                    message=issue["publisher"] or row["series"],
                    attach=issue["cover"],
                )
            except notify.NotifyError as exc:
                log.warning("comics: %s failed: %s", issue["title"], exc)
                continue
            comics.mark_seen(issue, due.marker)
            sent += 1
    return sent
