"""New #1 comics from Comic Vine, sent as Comics notifications.

A week is two calls: every #1 with a store date in it, then their volumes in one call, which is
where the publisher is. An issue's credits and synopsis are one more call each. The current
week is read once, its listing and then each issue, all kept until the week is over. A week
ahead is kept a day, read when the comics schedule reaches it. Any other week is read when the
Comics page asks for it, an issue only when it is opened, each kept a few hours.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from robin import __version__, db, hidden, notices, notify, upstream

log = logging.getLogger(__name__)

API = "https://comicvine.gamespot.com/api"

# Comic Vine publisher ids, in the order the Comics page shows them. The name is for a box
# with nothing in it, a notice takes the publisher Comic Vine names on the volume.
PUBLISHERS = {
    "31": "Marvel",
    "10": "DC Comics",
    "513": "Image",
    "1868": "Boom! Studios",
}

# How long a week other than the current one, or an issue from it, is kept once asked for.
ON_DEMAND_TTL = 4 * 3600

# How long a week ahead is kept. Comic Vine fills a week in as it comes closer.
AHEAD_TTL = 24 * 3600

# ntfy turns a body over 4096 bytes into an attachment, and most services cut one shorter.
MAX_BODY_BYTES = 3800

# Long enough that a week's issues never come back as new.
SEEN_SECONDS = 90 * 24 * 3600

# Comic Vine refuses a client that does not name itself.
USER_AGENT = (
    f"Robin/{__version__} (self-hosted; +https://github.com/slightlyuselesscreations/robin)"
)

# Comic Vine's most per page, for the issue list and for volumes asked for by id.
PAGE = 100

# How long a search, and a series, person or publisher, is kept.
SEARCH_TTL = 3600
ENTITY_TTL = 24 * 3600

# What Comic Vine calls each kind of favourite, and where one of each is read.
RESOURCES = {"volume": "series", "person": "person", "publisher": "publisher"}
_ENTITY_PATH = {
    "series": "/volume/4050-{}/",
    "person": "/person/4040-{}/",
    "publisher": "/publisher/4010-{}/",
}
_ENTITY_FIELDS = "id,name,image,publisher,start_year,count_of_issues,site_detail_url,deck"

# Comic Vine writes roles in lower case, two of them under names of its own.
_ROLES = {"penciler": "Penciller", "cover": "Cover Artist"}
_TAG = re.compile(r"<[^>]+>")


def week_of(today: date) -> date:
    """The Wednesday new comics ship on, today included."""
    return today - timedelta(days=(today.weekday() - 2) % 7)


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
    return f"comics:seen:{comic['id']}"


def seen(comic: dict[str, Any]) -> str | None:
    """The notice last sent for an issue, as `notices` marks it. One announced when each had a
    single notice reads as every notice sent."""
    found = db.cache_get(_seen_key(comic))
    if found is None:
        return None
    return found if isinstance(found, str) else f"*|{db.SENT_ALL}"


def mark_seen(comic: dict[str, Any], marker: str) -> None:
    db.cache_put(_seen_key(comic), marker, SEEN_SECONDS)


def client() -> httpx.AsyncClient:
    """The only way anything reaches Comic Vine. Every request then goes through `_get`."""
    settings = db.get_settings()
    if not settings.comics_ready:
        raise upstream.NotConfigured("Comics needs a Comic Vine API key. Add it in Settings.")
    return httpx.AsyncClient(
        base_url=API,
        headers={"User-Agent": USER_AGENT},
        params={"api_key": settings.comicvine_key, "format": "json"},
        timeout=20,
    )


async def _get(http: httpx.AsyncClient, path: str, **params: str | int) -> dict[str, Any]:
    """One call to Comic Vine, in its turn. A refusal pauses it and raises RateLimited.

    Comic Vine also answers errors in the body, a `status_code` other than 1, raised as
    ValueError. An object it does not have, 101, is answered with no results.
    """
    async with upstream.slot("comicvine"):
        resp = await http.get(path, params=params)
    if resp.status_code >= 400:
        upstream.observe("comicvine", resp.status_code, resp.headers.get("retry-after"))
    resp.raise_for_status()
    body: dict[str, Any] = resp.json()
    if body.get("status_code") == 101:
        return {**body, "results": None}
    if body.get("status_code") != 1:
        raise ValueError(f"Comic Vine: {body.get('error') or 'no answer'}")
    return body


async def ping() -> None:
    """One live call, for Health: the publisher list, one row of it."""
    async with client() as http:
        await _get(http, "/publishers/", limit=1, field_list="id")


async def _paged(http: httpx.AsyncClient, path: str, **params: str | int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    while True:
        body = await _get(http, path, limit=PAGE, offset=len(found), **params)
        found += body["results"]
        if not body["results"] or len(found) >= body["number_of_total_results"]:
            return found


def _comic(issue: dict[str, Any], volume: dict[str, Any]) -> dict[str, Any]:
    """An issue as every list carries it, with the series and publisher ids it is made by."""
    image = issue.get("image") or {}
    publisher = volume.get("publisher") or {}
    return {
        "id": str(issue["id"]),
        "title": f"{volume['name']} #{issue['issue_number']}",
        "number": issue["issue_number"],
        "url": issue["site_detail_url"],
        "publisher": publisher.get("name") or "",
        "publisher_id": publisher.get("id"),
        "volume_id": volume["id"],
        "date": issue.get("store_date"),
        "cover": image.get("super_url"),
        "series_url": volume.get("site_detail_url"),
    }


async def _issues(
    http: httpx.AsyncClient, filter: str, sort: str = "id:asc"
) -> list[dict[str, Any]]:
    """The issues `filter` names, each with its volume, which is where the publisher is. Two
    calls for up to a hundred of each."""
    issues = await _paged(
        http,
        "/issues/",
        filter=filter,
        field_list="id,issue_number,image,site_detail_url,volume,store_date",
        sort=sort,
    )
    ids = sorted({str(i["volume"]["id"]) for i in issues})
    volumes: dict[int, dict[str, Any]] = {}
    for start in range(0, len(ids), PAGE):
        for volume in await _paged(
            http,
            "/volumes/",
            filter=f"id:{'|'.join(ids[start : start + PAGE])}",
            field_list="id,name,publisher,site_detail_url",
        ):
            volumes[volume["id"]] = volume
    return [
        _comic(issue, volumes[issue["volume"]["id"]])
        for issue in issues
        if issue["volume"]["id"] in volumes
    ]


def _days(week: date) -> str:
    return f"store_date:{week.isoformat()}|{(week + timedelta(days=6)).isoformat()}"


async def _firsts(http: httpx.AsyncClient, week: date) -> dict[str, list[dict[str, Any]]]:
    """The week's #1s by publisher id, of every publisher, those in `PUBLISHERS` always there
    and first."""
    found: dict[str, list[dict[str, Any]]] = {publisher: [] for publisher in PUBLISHERS}
    for comic in await _issues(http, f"{_days(week)},issue_number:1"):
        found.setdefault(str(comic["publisher_id"]), []).append(comic)
    return found


def _names(credits: Any) -> list[str]:
    """The names in a list of credits. Comic Vine leaves an empty one null."""
    return [c["name"] for c in credits] if isinstance(credits, list) else []


def parse_detail(issue: dict[str, Any] | None) -> dict[str, Any] | None:
    """What an issue says beyond the listing. None when Comic Vine has no such issue."""
    if not issue:
        return None
    # One person in two jobs is one entry under each, "penciler, inker".
    creators: dict[str, list[str]] = {}
    people: dict[str, list[dict[str, Any]]] = {}
    for person in issue.get("person_credits") or []:
        for role in (person.get("role") or "").split(","):
            role = _ROLES.get(role.strip(), role.strip().title())
            if role and person["name"] not in creators.setdefault(role, []):
                creators[role].append(person["name"])
                people.setdefault(role, []).append({"id": person["id"], "name": person["name"]})
    volume = issue.get("volume") or {}
    image = issue.get("image") or {}
    return {
        "name": issue.get("name"),
        "creators": creators,
        # The same by role with the ids each opens as a favourite by.
        "people": people,
        "person_ids": sorted({p["id"] for p in issue.get("person_credits") or []}),
        "volume_id": volume.get("id"),
        "series": volume.get("name"),
        "number": issue.get("issue_number"),
        "date": issue.get("store_date"),
        "cover": image.get("super_url"),
        "url": issue.get("site_detail_url"),
        "synopsis": _text(issue.get("description") or issue.get("deck") or ""),
        "cover_date": issue.get("cover_date"),
        "story_arcs": _names(issue.get("story_arc_credits")),
        "characters": _names(issue.get("character_credits")),
        "teams": _names(issue.get("team_credits")),
        "first_appearances": _names(issue.get("first_appearance_characters")),
        "variants": len(issue.get("associated_images") or []),
    }


def _detail_key(comic_id: str) -> str:
    return f"comics:detail:v4:{comic_id}"


def cached_detail(comic_id: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = db.cache_get(_detail_key(comic_id))
    return found


async def detail(comic_id: str, ttl: int) -> dict[str, Any] | None:
    """The issue, kept `ttl` seconds. One Comic Vine does not have is kept as nothing, so it is
    not asked for again every hour."""

    async def read() -> dict[str, Any] | None:
        # Its own client, since a refresh outlives the request that started it.
        async with client() as http:
            body = await _get(
                http,
                f"/issue/4000-{comic_id}/",
                field_list="name,description,deck,cover_date,person_credits,story_arc_credits,"
                "character_credits,team_credits,first_appearance_characters,associated_images,"
                "volume,issue_number,store_date,image,site_detail_url",
            )
        return parse_detail(body["results"])

    found: dict[str, Any] | None = await db.remember(_detail_key(comic_id), ttl, read)
    return found


async def prefetch_week() -> int:
    """Read every issue of the current week not read before. Returns how many were read.

    Runs on the hourly loop, so the week is in the cache before anyone opens it, with the
    credits that star a favourite writer or artist on every card. Once it is, a pass asks
    Comic Vine nothing until the next week starts.
    """
    if not db.get_settings().comics_ready:
        return 0
    now = datetime.now(UTC)
    week = week_of(now.date())
    read = 0
    firsts = [c for comics in (await week_listing(week)).values() for c in comics]
    try:
        every = await week_issues(week)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("comics: listing every issue of %s failed: %s", week, exc)
        every = []
    for comic in {c["id"]: c for c in [*firsts, *every]}.values():
        if db.cache_lookup(_detail_key(comic["id"]))[0]:
            continue
        try:
            await detail(comic["id"], week_ttl(week, now))
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("comics: %s failed: %s", comic["title"], exc)
            continue
        read += 1
    return read


async def week_listing(week: date) -> dict[str, list[dict[str, Any]]]:
    """The week's new #1s by publisher id, empty when Comic Vine failed to answer and nothing
    was kept.

    A failure is not kept, so the next pass asks again.
    """

    async def read() -> dict[str, list[dict[str, Any]]]:
        # Its own client, since a refresh outlives the request that started it.
        async with client() as http:
            return await _firsts(http, week)

    key = f"comics:week:v4:{week.isoformat()}"
    try:
        found: dict[str, list[dict[str, Any]]] = await db.remember(
            key, week_ttl(week, datetime.now(UTC)), read
        )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("comics: listing %s failed: %s", week, exc)
        return {}
    return found


async def week_issues(week: date) -> list[dict[str, Any]]:
    """Every issue of the week, of every publisher, kept as the week's #1s are."""

    async def read() -> list[dict[str, Any]]:
        async with client() as http:
            return await _issues(http, _days(week))

    found: list[dict[str, Any]] = await db.remember(
        f"comics:issues:v1:{week.isoformat()}", week_ttl(week, datetime.now(UTC)), read
    )
    return found


def weeks_ahead(today: date, slots: list[tuple[int, int]]) -> list[date]:
    """The weeks a pass reads: the current one, and each the schedule reaches ahead."""
    reach = max(days for days, _ in slots)
    return sorted({week_of(today + timedelta(days=d)) for d in range(reach + 1)})


async def notify_new_firsts(now: datetime | None = None) -> int:
    """Send each week's new #1s as one digest, at the first notice of the comics schedule due
    for its Wednesday. Returns how many digests were sent.

    Runs on the hourly loop. Each #1 is in one digest only, so a later notice of the schedule
    sends again only for #1s Comic Vine added since. An issue of the current week is still
    announced after its Wednesday, until the week ends. Issues are marked only once the digest
    went out, so a failure is retried on the next pass.
    """
    settings = db.get_settings()
    channel = settings.notices("comics")
    window = notices.window(settings, "comics", now)
    if channel is None or window is None:
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
        for comic in listed:
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


def _image(raw: dict[str, Any]) -> str | None:
    """A person's photo or a series' cover. Comic Vine stands a blank image in for none."""
    url = (raw.get("image") or {}).get("super_url")
    return None if not url or "blank" in url.rsplit("/", 1)[-1] else url


def _entity(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """A series, person or publisher as a favourite is shown. A publisher is a name, never a
    logo, as every organisation is."""
    publisher = raw.get("publisher") or {}
    if kind == "series":
        count = raw.get("count_of_issues")
        meta = " · ".join(
            str(part)
            for part in (
                publisher.get("name"),
                raw.get("start_year"),
                f"{count} issues" if count else None,
            )
            if part
        )
    else:
        meta = "Creator" if kind == "person" else "Publisher"
    return {
        "category": "comics",
        "kind": kind,
        "id": raw["id"],
        "name": raw["name"],
        "image": None if kind == "publisher" else _image(raw),
        "meta": meta or "Series",
        "url": raw.get("site_detail_url"),
        "ids": [raw["id"]],
        "publisher": publisher.get("name") or "",
        "publisher_id": publisher.get("id"),
    }


async def search_favourites(query: str) -> list[dict[str, Any]]:
    """Series, people and publishers matching `query`, as Comic Vine ranks them."""

    async def read() -> list[dict[str, Any]]:
        async with client() as http:
            body = await _get(
                http,
                "/search/",
                query=query,
                resources=",".join(RESOURCES),
                field_list=f"{_ENTITY_FIELDS},resource_type",
                limit=30,
            )
        return [
            _entity(RESOURCES[r["resource_type"]], r)
            for r in body["results"] or []
            if r.get("resource_type") in RESOURCES
        ]

    found: list[dict[str, Any]] = await db.remember(
        f"comics:search:v1:{query.casefold()}", SEARCH_TTL, read
    )
    return found


async def favourite(kind: str, source_id: int) -> dict[str, Any] | None:
    """One series, person or publisher, None when Comic Vine has no such one."""

    async def read() -> dict[str, Any] | None:
        async with client() as http:
            body = await _get(http, _ENTITY_PATH[kind].format(source_id), field_list=_ENTITY_FIELDS)
        return _entity(kind, body["results"]) if body["results"] else None

    found: dict[str, Any] | None = await db.remember(
        f"comics:entity:v1:{kind}:{source_id}", ENTITY_TTL, read
    )
    return found


async def favourite_releases(kind: str, ids: list[int]) -> list[dict[str, Any]]:
    """What a favourite has coming. A series' issues from the first of the month on, one call
    each. A publisher's or a person's are of the current week only, the one Comic Vine dates,
    a person's read from the credits the hourly pass keeps."""
    if kind == "series":
        start = db.month_start()
        days = f"store_date:{start.isoformat()}|{(start + timedelta(days=400)).isoformat()}"
        found: list[dict[str, Any]] = []
        async with client() as http:
            for source_id in ids:
                found += await _issues(http, f"volume:{source_id},{days}", "store_date:asc")
        return found
    week = await week_issues(week_of(datetime.now(UTC).date()))
    if kind == "publisher":
        return [c for c in week if c["publisher_id"] in ids]
    return [c for c in week if not set(made(c)["person"]).isdisjoint(ids)]


def made(comic: dict[str, Any]) -> dict[str, list[int]]:
    """Who and what made an issue, by kind of favourite. Its people once its details are read."""
    detail = comic.get("detail") or cached_detail(comic["id"]) or {}
    return {
        "series": [comic["volume_id"]] if comic.get("volume_id") else [],
        "publisher": [comic["publisher_id"]] if comic.get("publisher_id") else [],
        "person": list(detail.get("person_ids") or []),
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
    """One issue as every list carries it, read from its details and its series, for a dialog
    opened away from any list."""
    found = await detail(comic_id, ON_DEMAND_TTL)
    if not found or not found.get("volume_id"):
        return None
    series = await favourite("series", int(found["volume_id"]))
    return {
        "id": comic_id,
        "title": f"{found['series']} #{found['number']}",
        "url": found["url"],
        "publisher": (series or {}).get("publisher") or "",
        "publisher_id": (series or {}).get("publisher_id"),
        "volume_id": found["volume_id"],
        "number": found["number"],
        "date": found["date"],
        "cover": found["cover"],
        "series_url": (series or {}).get("url"),
        "detail": found,
    }
