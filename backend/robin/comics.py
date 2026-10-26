"""Comics from Metron: each week's issues, their details, and the #1s sent as Comics
notifications.

A week's listing is one call per hundred issues and names each issue's series, not its
publisher, which only a series or an issue's detail names. Each series' publisher is kept on its
own, read from every detail and every series Robin sees, so a list draws it from what is kept
and the hourly pass reads what it lacks. The current week's details are read by that pass and
kept until the week ends.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from robin import __version__, db, hidden, notices, notify, updates, upstream

log = logging.getLogger(__name__)

API = "https://metron.cloud/api"
SITE = "https://metron.cloud"

# Metron publisher ids, in the order the #1 digest and a list ordered by publisher take them
# first. The name is for a publisher with nothing in a week.
PUBLISHERS = {
    "1": "Marvel",
    "2": "DC Comics",
    "4": "Image Comics",
    "20": "Boom! Studios",
}

# How long a week other than the current one, or an issue from it, is kept once asked for.
ON_DEMAND_TTL = 4 * 3600

# How long a week ahead, and the current week's listing at most, is kept. Metron adds to a
# week as it comes closer.
AHEAD_TTL = 24 * 3600

# How long an issue read at a `modified` is kept. It stays right until Metron edits it, which a
# listing then names a newer `modified` for, read again under its own key.
DETAIL_TTL = 30 * 24 * 3600

# How long a week's listing that came back empty is kept.
EMPTY_TTL = 3600

# Most services cut a notification body shorter than this.
MAX_BODY_BYTES = 3800

# Long enough that a week's issues never come back as new.
SEEN_SECONDS = 90 * 24 * 3600

# How long a search, and a series, creator or publisher, is kept, and a series' publisher.
SEARCH_TTL = 3600
ENTITY_TTL = 24 * 3600
PUBLISHER_OF_SECONDS = 90 * 24 * 3600

# How far ahead a publisher's issues are listed for its favourite, a big one has hundreds.
PUBLISHER_REACH = timedelta(days=90)
# The weeks after the current one the hourly loop lists, so their grids open at once.
PREFETCH_WEEKS = 2

# Metron names itself what Robin is, in the User-Agent.
USER_AGENT = f"Robin/{__version__} (self-hosted; +https://github.com/{updates.REPOSITORY})"

# Metron's most per page.
PAGE = 100

# Where each kind of favourite is read and searched.
_PATHS = {"series": "/series/", "person": "/creator/", "publisher": "/publisher/"}

# Metron's roles as the dialog names them. Writer covers whoever wrote the issue.
_ROLES = {
    "Script": "Writer",
    "Story": "Writer",
    "Plot": "Writer",
    "Cover": "Cover Artist",
}
_TAG = re.compile(r"<[^>]+>")


def week_of(today: date) -> date:
    """The Wednesday new comics ship on, today included."""
    return today - timedelta(days=(today.weekday() - 2) % 7)


def first_week() -> date:
    """The earliest week listed, the one the first of this month falls in."""
    return week_of(db.month_start())


def week_ttl(week: date, now: datetime) -> int:
    """Until the next week starts for the current week, a day for one ahead, a few hours for
    any before."""
    current = week_of(now.date())
    if week > current:
        return AHEAD_TTL
    if week != current:
        return ON_DEMAND_TTL
    ends = datetime.combine(week + timedelta(days=7), datetime.min.time(), tzinfo=UTC)
    return max(60, int((ends - now).total_seconds()))


def listing_ttl(week: date, found: Any) -> int:
    """How long a week's listing is kept: an hour while it is empty, at most a day for the
    current week, since Metron adds to a week as it goes, and as `week_ttl` otherwise."""
    if not (any(found.values()) if isinstance(found, dict) else found):
        return EMPTY_TTL
    return min(week_ttl(week, datetime.now(UTC)), AHEAD_TTL)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def digest(by_publisher: dict[str, list[dict[str, Any]]]) -> str:
    """Each publisher as a heading with its count, its #1s under it, a blank line between
    publishers, cut short to fit a notification."""
    total = sum(len(c) for c in by_publisher.values())
    lines: list[str] = []
    used = told = 0
    for publisher, comics in by_publisher.items():
        block = [f"{publisher.upper()} ({len(comics)})"]
        block += [f"• {c['title'].removesuffix(' #1')}" for c in comics]
        if lines:
            block.insert(0, "")
        for line in block:
            cost = len(line.encode("utf-8")) + 1
            if used + cost > MAX_BODY_BYTES:
                lines.append(f"…and {total - told} more")
                return "\n".join(lines)
            lines.append(line)
            used += cost
            told += line.startswith("•")
    return "\n".join(lines)


def _seen_key(comic: dict[str, Any]) -> str:
    return f"comics:seen:v2:{comic['id']}"


def seen(comic: dict[str, Any]) -> str | None:
    """The notice last sent for an issue, as `notices` marks it."""
    found = db.cache_get(_seen_key(comic))
    return found if isinstance(found, str) else None


def mark_seen(comic: dict[str, Any], marker: str) -> None:
    db.cache_put(_seen_key(comic), marker, SEEN_SECONDS)


def _dated_key(comic: dict[str, Any]) -> str:
    return f"comics:dated:v2:{comic['id']}"


def dated_as(comic: dict[str, Any]) -> str | None:
    """The date an issue of a monitored series was last read as, for `notices.date_change`.
    None until it is first read."""
    found = db.cache_get(_dated_key(comic))
    return found if isinstance(found, str) else None


def mark_dated_as(comic: dict[str, Any], value: str) -> None:
    db.cache_put(_dated_key(comic), value, SEEN_SECONDS)


def client() -> httpx.AsyncClient:
    """The only way anything reaches Metron. Every request then goes through `_get`."""
    settings = db.get_settings()
    if not settings.comics_ready:
        raise upstream.NotConfigured("Comics needs a Metron API key. Add it in Settings.")
    return httpx.AsyncClient(
        base_url=API,
        headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {settings.metron_key}"},
        timeout=20,
    )


# Metron calls a page is waiting on. Every other call, the hourly loop's and what is read behind
# a page, waits while there are any, takes `_behind` first, so at most one of them is in Metron's
# queue, and starts no sooner than `_behind_next`, at half of Metron's pace, so the rest of it is
# always there for a page.
_pages_waiting = 0
_behind = asyncio.Lock()
_behind_next = 0.0


async def _get(http: httpx.AsyncClient, path: str, **params: str | int) -> dict[str, Any] | None:
    """One call to Metron, in its turn, a page's ahead of the hourly loop's. A refusal pauses it
    and raises RateLimited. What Metron does not have, a 404, is None."""
    global _pages_waiting, _behind_next
    if db.STALE.get() is not None:
        _pages_waiting += 1
        try:
            async with upstream.slot("metron"):
                resp = await http.get(path, params=params)
        finally:
            _pages_waiting -= 1
    else:
        async with _behind:
            while _pages_waiting or time.monotonic() < _behind_next:
                await asyncio.sleep(0.5)
            limit = upstream.LIMITS["metron"]
            _behind_next = time.monotonic() + 2 * limit.per / limit.rate
            async with upstream.slot("metron"):
                resp = await http.get(path, params=params)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        upstream.observe("metron", resp.status_code, resp.headers.get("retry-after"))
    resp.raise_for_status()
    body: dict[str, Any] = resp.json()
    return body


async def ping() -> None:
    """One live call, for Health: the publisher list, one row of it."""
    async with client() as http:
        await _get(http, "/publisher/", page_size=1)


async def _paged(http: httpx.AsyncClient, path: str, **params: str | int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        body = await _get(http, path, page_size=PAGE, page=page, **params) or {}
        found += body.get("results") or []
        if not body.get("next"):
            return found
        page += 1


def _publisher_key(series_id: int) -> str:
    return f"comics:publisher-of:v1:{series_id}"


def _keep_publisher(series_id: int | None, publisher: dict[str, Any] | None) -> None:
    if series_id and publisher and publisher.get("id"):
        db.cache_put(
            _publisher_key(series_id),
            {"id": publisher["id"], "name": publisher.get("name") or ""},
            PUBLISHER_OF_SECONDS,
        )


def publisher_of(series_id: int) -> dict[str, Any] | None:
    """A series' publisher, `{"id", "name"}`, as kept. None until a detail or the series names
    it."""
    found: dict[str, Any] | None = db.cache_get(_publisher_key(series_id))
    return found


async def read_publishers(series_ids: set[int]) -> None:
    """Read the publisher of each series not kept yet, from the series itself."""
    for series_id in sorted(series_ids):
        if publisher_of(series_id) is None:
            try:
                await favourite("series", series_id)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("comics: series %s failed: %s", series_id, exc)


async def read_publishers_behind(series_ids: set[int]) -> None:
    """`read_publishers` for a page's week, behind its answer, giving way to pages as the hourly
    loop does. A pause ends it, and the page asking again starts it over."""
    db.STALE.set(None)
    try:
        await read_publishers(series_ids)
    except upstream.UpstreamError as exc:
        log.warning("comics: reading publishers stopped: %s", exc)


def lacking_publishers(comics: list[dict[str, Any]]) -> set[int]:
    """The series of the issues whose publisher is not kept yet."""
    return {c["series_id"] for c in comics if c["series_id"] and not c["publisher_id"]}


def with_publishers(comics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each issue with its series' publisher, as far as one is kept."""
    kept = db.cache_lookup_many(
        [_publisher_key(c["series_id"]) for c in comics if c["series_id"] and not c["publisher_id"]]
    )
    for comic in comics:
        if not comic.get("publisher_id"):
            publisher = kept.get(_publisher_key(comic["series_id"])) or {}
            comic["publisher"] = publisher.get("name") or ""
            comic["publisher_id"] = publisher.get("id")
    return comics


def _comic(issue: dict[str, Any]) -> dict[str, Any]:
    """An issue as every list carries it, with the series and publisher ids it is made by. A
    list names no publisher, which `with_publishers` adds."""
    series = issue.get("series") or {}
    return {
        "id": str(issue["id"]),
        "title": f"{series.get('name')} #{issue['number']}",
        "number": issue["number"],
        "url": f"{SITE}/issue/{issue['id']}/",
        "publisher": "",
        "publisher_id": None,
        "series_id": series.get("id"),
        "date": issue.get("store_date"),
        "cover": issue.get("image"),
        "series_url": f"{SITE}/series/{series['id']}/" if series.get("id") else None,
        # When Metron last edited it, which says whether a kept detail still holds.
        "modified": issue.get("modified"),
    }


def _days(week: date) -> dict[str, str]:
    return {
        "store_date_range_after": week.isoformat(),
        "store_date_range_before": (week + timedelta(days=6)).isoformat(),
    }


async def _issues(http: httpx.AsyncClient, **params: str | int) -> list[dict[str, Any]]:
    return [_comic(i) for i in await _paged(http, "/issue/", **params)]


def _names(rows: Any) -> list[str]:
    return [r["name"] for r in rows] if isinstance(rows, list) else []


def parse_detail(issue: dict[str, Any] | None) -> dict[str, Any] | None:
    """What an issue says beyond the listing. None when Metron has no such issue."""
    if not issue:
        return None
    # One person in two jobs is one entry under each.
    creators: dict[str, list[str]] = {}
    people: dict[str, list[dict[str, Any]]] = {}
    for credit in issue.get("credits") or []:
        for role in credit.get("role") or []:
            named = _ROLES.get(role["name"], role["name"])
            if credit["creator"] not in creators.setdefault(named, []):
                creators[named].append(credit["creator"])
                people.setdefault(named, []).append({"id": credit["id"], "name": credit["creator"]})
    series = issue.get("series") or {}
    stories = [n for n in issue.get("name") or [] if n]
    return {
        "name": issue.get("title") or (stories[0] if len(stories) == 1 else None),
        "creators": creators,
        # The same by role with the ids each opens as a favourite by.
        "people": people,
        "person_ids": sorted({c["id"] for c in issue.get("credits") or []}),
        "series_id": series.get("id"),
        "series": series.get("name"),
        "publisher": issue.get("publisher"),
        "imprint": (issue.get("imprint") or {}).get("name"),
        "number": issue.get("number"),
        "date": issue.get("store_date"),
        "cover": issue.get("image"),
        "url": f"{SITE}/issue/{issue['id']}/",
        "modified": issue.get("modified"),
        "synopsis": _text(issue.get("desc") or ""),
        "cover_date": issue.get("cover_date"),
        "story_arcs": _names(issue.get("arcs")),
        "characters": _names(issue.get("characters")),
        "teams": _names(issue.get("teams")),
        "universes": _names(issue.get("universes")),
        # Metron names no first appearance on an issue.
        "first_appearances": [],
        "variants": [
            {"name": v.get("name") or "", "image": v["image"]}
            for v in issue.get("variants") or []
            if v.get("image")
        ],
    }


def _detail_key(comic_id: str, modified: str | None) -> str:
    return f"comics:detail:v7:{comic_id}:{modified or ''}"


def details(comics: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """The issues already read at the `modified` each is listed with, by id, one Metron does
    not have as None, in one query."""
    keys = {c["id"]: _detail_key(c["id"], c.get("modified")) for c in comics}
    kept = db.cache_lookup_many(list(keys.values()))
    return {i: kept[key] for i, key in keys.items() if key in kept}


def cached_detail(comic: dict[str, Any]) -> dict[str, Any] | None:
    found: dict[str, Any] | None = db.cache_get(_detail_key(comic["id"], comic.get("modified")))
    return found


async def read_issue(comic_id: str) -> dict[str, Any] | None:
    """One issue as Metron answers it, its series' publisher kept on the way."""
    async with client() as http:
        raw = await _get(http, f"/issue/{comic_id}/")
    if raw:
        _keep_publisher((raw.get("series") or {}).get("id"), raw.get("publisher"))
    return raw


async def detail(comic_id: str, modified: str | None = None) -> dict[str, Any] | None:
    """The issue, read only when it is opened. Read at its listed `modified`, it is kept until
    Metron edits it, and without one `ON_DEMAND_TTL`. One Metron does not have is kept as
    nothing, so it is not asked for again."""

    async def read() -> dict[str, Any] | None:
        return parse_detail(await read_issue(comic_id))

    ttl = DETAIL_TTL if modified else ON_DEMAND_TTL
    found: dict[str, Any] | None = await db.remember(_detail_key(comic_id, modified), ttl, read)
    return found


async def prefetch_weeks() -> int:
    """List the current week and the `PREFETCH_WEEKS` after it, and read the publisher of each
    series Robin has not met, so their grids open at once. Returns how many series were read.
    No issue is read, its details wait until it is opened. Each creator `credit` matches by
    is listed too, so a page never waits on one."""
    settings = db.get_settings()
    if not settings.comics_ready:
        return 0
    await credit(settings, [])
    current = week_of(datetime.now(UTC).date())
    lacking: set[int] = set()
    for week in (current + timedelta(weeks=n) for n in range(PREFETCH_WEEKS + 1)):
        try:
            lacking |= lacking_publishers(await week_issues(week))
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("comics: listing every issue of %s failed: %s", week, exc)
    await read_publishers(lacking)
    return len(lacking)


async def week_listing(week: date) -> dict[str, list[dict[str, Any]]]:
    """The week's new #1s by publisher id, those in `PUBLISHERS` first, empty when Metron
    failed to answer and nothing was kept. Each series' publisher is read when it is not kept,
    so this waits on Metron, as the hourly loop can.

    A failure is not kept, so the next pass asks again.
    """

    async def read() -> list[dict[str, Any]]:
        # Its own client, since a refresh outlives the request that started it.
        async with client() as http:
            return await _issues(http, number="1", **_days(week))

    try:
        listed: list[dict[str, Any]] = await db.remember(
            f"comics:firsts:v2:{week.isoformat()}", lambda found: listing_ttl(week, found), read
        )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("comics: listing %s failed: %s", week, exc)
        return {}
    await read_publishers({c["series_id"] for c in listed if c["series_id"]})
    found: dict[str, list[dict[str, Any]]] = {publisher: [] for publisher in PUBLISHERS}
    for comic in with_publishers([dict(c) for c in listed]):
        found.setdefault(str(comic["publisher_id"]), []).append(comic)
    return found


async def week_issues(week: date) -> list[dict[str, Any]]:
    """Every issue of the week, of every publisher, kept as the week's #1s are. Each carries
    its publisher only as far as one is kept, the rest read on the hourly pass."""

    async def read() -> list[dict[str, Any]]:
        async with client() as http:
            return await _issues(http, **_days(week))

    found: list[dict[str, Any]] = await db.remember(
        f"comics:issues:v4:{week.isoformat()}", lambda listed: listing_ttl(week, listed), read
    )
    return with_publishers([dict(c) for c in found])


def weeks_ahead(today: date, slots: list[tuple[int, int]]) -> list[date]:
    """The weeks a pass reads: the current one, and each the schedule reaches ahead."""
    reach = max(days for days, _ in slots)
    return sorted({week_of(today + timedelta(days=d)) for d in range(reach + 1)})


async def notify_new_firsts(now: datetime | None = None) -> int:
    """Send each week's new #1s as one digest, at the first notice of the comics schedule due
    for its Wednesday. Returns how many digests were sent.

    Runs on the hourly loop. Each #1 is in one digest only, so a later notice of the schedule
    sends again only for #1s Metron added since. An issue of the current week is still
    announced after its Wednesday, until the week ends. Issues are marked only once the digest
    went out, so a failure is retried on the next pass. Nothing is sent while the carry-over
    from Comic Vine is still to run.
    """
    settings = db.get_settings()
    channel = settings.notices("comics")
    window = notices.window(settings, "comics", now)
    if channel is None or window is None or db.comicvine_pending():
        return 0

    sent = 0
    for week in weeks_ahead(window.today, window.slots):
        sent += await _announce_week(settings, channel, window, week)
    return sent


async def _announce_week(
    settings: db.Settings,
    channel: db.Channel,
    window: notices.Window,
    week: date,
) -> int:
    picked = {str(p["id"]) for p in settings.comics_digest_publishers}
    fresh: dict[str, list[dict[str, Any]]] = {}
    for publisher_id, listed in (await week_listing(week)).items():
        if picked and publisher_id not in picked:
            continue
        for comic in await credit(settings, listed):
            if hidden.comic(settings, made(comic)) and window.pending(week, seen(comic), grace=6):
                fresh.setdefault(comic["publisher"], []).append(comic)
    if not fresh:
        return 0

    count = sum(len(c) for c in fresh.values())
    firsts = f"{count} new #1s" if count > 1 else "1 new #1"
    when = "this week" if week <= window.today else f"out {window.relative(week)}"
    try:
        await notify.send(
            settings,
            channel,
            title=f"{firsts} {when}",
            message=digest(fresh),
            tags="comic_book",
        )
    except notify.NotifyError as exc:
        log.warning("comics: digest for %s failed: %s", week, exc)
        return 0
    for comics in fresh.values():
        for comic in comics:
            mark_seen(comic, f"*|{db.SENT_ALL}")
    return 1


# ---------------------------------------------------------------- favourites


def _entity(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """A series, creator or publisher as a favourite is shown. A publisher is a name, never a
    logo, as every organisation is, and a series has no image of its own."""
    publisher = raw.get("publisher") or {}
    if kind == "series":
        _keep_publisher(raw["id"], publisher)
        count = raw.get("issue_count")
        meta = " · ".join(
            str(part)
            for part in (
                publisher.get("name"),
                raw.get("year_began"),
                f"{count} issue{'' if count == 1 else 's'}" if count else None,
            )
            if part
        )
    else:
        meta = "Creator" if kind == "person" else "Publisher"
    # A series is named with its first year in a list, "Batman (2016)", and without in detail.
    name = raw.get("name") or raw.get("series") or ""
    if kind == "series" and raw.get("year_began") and not name.endswith(")"):
        name = f"{name} ({raw['year_began']})"
    return {
        "category": "comics",
        "kind": kind,
        "id": raw["id"],
        "name": name,
        "image": raw.get("image") if kind == "person" else None,
        "meta": meta or "Series",
        "url": f"{SITE}{_PATHS[kind]}{raw['id']}/",
        "ids": [raw["id"]],
        "publisher": publisher.get("name") or "",
        "publisher_id": publisher.get("id"),
    }


async def search_favourites(query: str, kind: str | None = None) -> list[dict[str, Any]]:
    """Series, creators and publishers whose name holds `query`, one call each, or only those
    of `kind`."""
    kinds = [kind] if kind in _PATHS else list(_PATHS)

    async def read() -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        async with client() as http:
            for each in kinds:
                body = await _get(http, _PATHS[each], name=query, page_size=20) or {}
                found += [_entity(each, row) for row in body.get("results") or []]
        return found

    found: list[dict[str, Any]] = await db.remember(
        f"comics:search:v4:{','.join(kinds)}:{query.casefold()}", SEARCH_TTL, read
    )
    return found


async def favourite(kind: str, source_id: int) -> dict[str, Any] | None:
    """One series, creator or publisher, None when Metron has no such one."""

    async def read() -> dict[str, Any] | None:
        async with client() as http:
            raw = await _get(http, f"{_PATHS[kind]}{source_id}/")
        return _entity(kind, raw) if raw else None

    found: dict[str, Any] | None = await db.remember(
        f"comics:entity:v2:{kind}:{source_id}", ENTITY_TTL, read
    )
    return found


async def favourite_releases(kind: str, ids: list[int]) -> list[dict[str, Any]]:
    """What a favourite has coming from the first of the month on, one call each: a series' and
    a creator's issues, a publisher's up to `PUBLISHER_REACH` ahead."""
    start = db.month_start()
    after = {"store_date_range_after": start.isoformat()}
    found: list[dict[str, Any]] = []
    async with client() as http:
        for source_id in ids:
            if kind == "series":
                found += await _issues(http, series_id=source_id, **after)
            elif kind == "person":
                found += await _issues(http, creator_id=source_id, **after)
            else:
                before = (start + PUBLISHER_REACH).isoformat()
                listed = await _issues(
                    http, publisher_id=source_id, store_date_range_before=before, **after
                )
                # Its publisher is the favourite itself, so no series is asked for it.
                named = await favourite("publisher", source_id) or {}
                for comic in listed:
                    comic["publisher"] = named.get("name") or ""
                    comic["publisher_id"] = source_id
                found += listed
    await read_publishers({c["series_id"] for c in found if not c["publisher_id"]})
    return sorted(with_publishers(found), key=lambda c: (c["date"] or "", c["title"]))


async def credit(settings: db.Settings, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set on each issue, as `person_ids`, the creators it credits that are a favourite, or
    hidden or shown in Settings, from each one's issues from the first of the month, one call a
    creator kept a day, so no issue is read for its credits. A creator Metron fails for is left
    out until it answers."""
    people = {i for f in db.favourites("comics") if f["kind"] == "person" for i in f["ids"]}
    for makers in (settings.hidden_makers, settings.shown_makers):
        people |= makers.get("comics", {}).get("person", frozenset())
    for person in sorted(people):

        async def read(person: int = person) -> list[str]:
            after = db.month_start().isoformat()
            async with client() as http:
                listed = await _paged(
                    http, "/issue/", creator_id=person, store_date_range_after=after
                )
            return [str(i["id"]) for i in listed]

        try:
            ids = set(await db.remember(f"comics:credited:v1:{person}", AHEAD_TTL, read))
        except (httpx.HTTPError, ValueError, upstream.UpstreamError) as exc:
            log.warning("comics: creator %s failed: %s", person, exc)
            continue
        for comic in found:
            if comic["id"] in ids:
                comic.setdefault("person_ids", []).append(person)
    return found


def made(comic: dict[str, Any]) -> dict[str, list[int]]:
    """Who and what made an issue, by kind of favourite: its people as `credit` set them, and
    any its details name once it was opened."""
    detail = (comic["detail"] if "detail" in comic else cached_detail(comic)) or {}
    return {
        "series": [comic["series_id"]] if comic.get("series_id") else [],
        "publisher": [comic["publisher_id"]] if comic.get("publisher_id") else [],
        "person": sorted({*comic.get("person_ids", []), *(detail.get("person_ids") or [])}),
    }


def star(comics: list[dict[str, Any]], favourites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name on each issue the favourite it comes from: its series, publisher or a creator."""
    by = {(f["kind"], i): f["name"] for f in favourites for i in f["ids"]}
    for comic in comics:
        comic["favourite"] = next(
            (by[(kind, i)] for kind, ids in made(comic).items() for i in ids if (kind, i) in by),
            None,
        )
    return comics


async def issue(comic_id: str) -> dict[str, Any] | None:
    """One issue as every list carries it, read from its details, for a dialog opened away from
    any list."""
    found = await detail(comic_id)
    if not found or not found.get("series_id"):
        return None
    publisher = found.get("publisher") or publisher_of(int(found["series_id"])) or {}
    return {
        "id": comic_id,
        "title": f"{found['series']} #{found['number']}",
        "url": found["url"],
        "publisher": publisher.get("name") or "",
        "publisher_id": publisher.get("id"),
        "series_id": found["series_id"],
        "number": found["number"],
        "date": found["date"],
        "cover": found["cover"],
        "series_url": f"{SITE}/series/{found['series_id']}/",
        "modified": None,
        "detail": found,
    }
