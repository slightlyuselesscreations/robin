"""Monitored comic series, added to the Suwayomi library once a source carries them, and the
library followed from then on.

Robin tracks series, not issues. A series is monitored from its #1 on the Comics page and
looked for on the configured Suwayomi source at once, then on every hourly pass while it is
still waiting. The moment the source lists it, it is added to the library and announced on the
comics topic, whether or not an issue is up yet. From there Suwayomi fetches and downloads its
issues as they come out, and `sync_library` reads the library from the configured source on
every sync: each series in it is monitored in Robin, each issue Suwayomi lists past the count
kept is announced, and a series gone from it is forgotten.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from robin import db, filters, notify, upstream

log = logging.getLogger(__name__)

TIMEOUT = 60.0

SEARCH = """
mutation($source: LongString!, $query: String) {
  fetchSourceManga(input: {source: $source, type: SEARCH, page: 1, query: $query}) {
    mangas { id title inLibrary }
  }
}"""

# Loads the chapter list from the source. Both flags are required by the schema.
CHAPTERS = """
mutation($id: Int!) {
  fetchMangaAndChapters(input: {id: $id, fetchManga: true, fetchChapters: true}) {
    chapters { id }
  }
}"""

# Queues the chapters, then starts the queue in case Suwayomi has it stopped. Mutations run in
# order. A chapter already downloaded is skipped by Suwayomi.
DOWNLOAD = """
mutation($ids: [Int!]!) {
  enqueueChapterDownloads(input: {ids: $ids}) { clientMutationId }
  startDownloader(input: {}) { clientMutationId }
}"""

ADD = """
mutation($id: Int!) {
  updateManga(input: {id: $id, patch: {inLibrary: true}}) { manga { id inLibrary } }
}"""

REMOVE = """
mutation($id: Int!) {
  updateManga(input: {id: $id, patch: {inLibrary: false}}) { manga { id inLibrary } }
}"""

# Series of one source Suwayomi already has in its own database, from any search or browse
# before, by a part of their title. Answered at once, unlike a search of the source.
KNOWN = """
query($source: LongString!, $title: String!) {
  mangas(condition: {sourceId: $source}, filter: {title: {includesInsensitive: $title}}) {
    nodes { id title inLibrary thumbnailUrl }
  }
}"""

# The library from one source, with how many issues Suwayomi lists for each, read from its own
# database. Suwayomi's library updates keep that current, the source is not asked.
LIBRARY = """
query($source: LongString!) {
  mangas(condition: {inLibrary: true, sourceId: $source}) {
    nodes { id title thumbnailUrl chapters { totalCount } latestUploadedChapter { name } }
  }
}"""

SOURCE = """
query($id: LongString!) { source(id: $id) { displayName } }"""

# What the Comics page and search show, a search or the source's latest updates, with covers.
BROWSE = """
mutation($source: LongString!, $type: FetchSourceMangaType!, $query: String) {
  fetchSourceManga(input: {source: $source, type: $type, page: 1, query: $query}) {
    mangas { id title inLibrary thumbnailUrl }
  }
}"""

# One series with its details. A search stores only titles, so the source page is read.
SERIES = """
mutation($id: Int!) {
  fetchManga(input: {id: $id}) {
    manga { id title inLibrary thumbnailUrl description author artist genre status realUrl }
  }
}"""

# Read Comics Online names a series "Midnight X-Men (2026-)", or "(2020)" for a one shot.
_YEAR = re.compile(r"\s*\((\d{4})(?:-\d{4}|-)?\)\s*$")
_WORDS = re.compile(r"[^A-Za-z0-9 ]+")


class SuwayomiError(upstream.UpstreamError):
    pass


def series_title(issue_title: str) -> str:
    """ "Midnight X-Men #1" is the series "Midnight X-Men"."""
    title = issue_title.strip()
    head, _, last = title.rpartition(" ")
    return head.strip() if head and re.fullmatch(r"#\d\S*", last) else title


def run_of(title: str) -> tuple[str, int]:
    """ "Corpse Knight (2026-)" is the series "Corpse Knight" started in 2026, 0 when undated."""
    dated = _YEAR.search(title)
    return (title[: dated.start()].strip(), int(dated.group(1))) if dated else (title.strip(), 0)


def queries(series: str) -> list[str]:
    """The title, then its longest stretch free of punctuation.

    The source matches the query literally, so "DC's Quoth the Raven... Whatever" finds nothing
    while "Quoth the Raven" finds it.
    """
    stretches = [" ".join(w for w in part.split() if len(w) > 1) for part in _WORDS.split(series)]
    longest = max(stretches, key=len, default="")
    return [series] + ([longest] if longest and longest != series else [])


def pick(results: list[dict[str, Any]], series: str, year: int) -> dict[str, Any] | None:
    """The result named exactly as the series, started the year of its #1 or later.

    The year keeps an older run of the same name from being taken for the new one. The
    earliest qualifying year wins, since a later one is a relaunch after this.
    """
    found = []
    for result in results:
        dated = _YEAR.search(result["title"])
        if not dated or int(dated.group(1)) < year:
            continue
        if filters.comparable(result["title"][: dated.start()]) == filters.comparable(series):
            found.append((int(dated.group(1)), result))
    return min(found, key=lambda pair: pair[0])[1] if found else None


async def gql(settings: db.Settings, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Run one operation. A partial answer carries `errors` beside its data and is returned."""
    if not settings.suwayomi_ready:
        raise upstream.NotConfigured("Add a Suwayomi instance and source in Settings, Comics.")
    return await upstream.graphql(
        SuwayomiError,
        "Suwayomi",
        f"{settings.suwayomi_url}/api/graphql",
        query,
        variables,
        timeout=TIMEOUT,
        partial=True,
    )


def _series(settings: db.Settings, raw: dict[str, Any]) -> dict[str, Any]:
    """A series with its cover made absolute, since Suwayomi answers with its own paths."""
    thumbnail = raw.get("thumbnailUrl")
    return {
        **raw,
        "thumbnailUrl": f"{settings.suwayomi_url}{thumbnail}" if thumbnail else None,
        "url": f"{settings.suwayomi_url}/manga/{raw['id']}",
    }


async def _browse(settings: db.Settings, kind: str, query: str | None) -> list[dict[str, Any]]:
    variables = {"source": settings.suwayomi_source_id, "type": kind, "query": query}
    data = await gql(settings, BROWSE, variables)
    return [_series(settings, m) for m in data["fetchSourceManga"]["mangas"]]


async def search(settings: db.Settings, query: str) -> list[dict[str, Any]]:
    """The source's own search, as it answers it. Nothing is added to the library."""
    return await _browse(settings, "SEARCH", query)


# Asking for Latest makes Suwayomi read the source live, so a page waits on that source.
LATEST_TTL = 3600


# How long a series' issue count is kept, and how many are read from the source at once.
ISSUES_TTL = 6 * 3600
ISSUES_AT_ONCE = 4


async def latest(settings: db.Settings) -> list[dict[str, Any]]:
    """The first page of the source's latest updates, in the order it gives them, each with
    `issues`, how many the source has, None when it could not be read. Kept `LATEST_TTL`
    seconds, each count `ISSUES_TTL`."""
    if not settings.suwayomi_ready:
        raise upstream.NotConfigured("Add a Suwayomi instance and source in Settings, Comics.")
    turn = asyncio.Semaphore(ISSUES_AT_ONCE)

    async def counted(found: dict[str, Any]) -> dict[str, Any]:
        async def count() -> int:
            async with turn:
                return await issue_count(settings, int(found["id"]))

        try:
            issues: int | None = await db.remember(
                f"suwayomi:issues:v1:{settings.suwayomi_url}:{found['id']}", ISSUES_TTL, count
            )
        except SuwayomiError as exc:
            log.info("suwayomi: no issue count for %s: %s", found["title"], exc)
            issues = None
        return {**found, "issues": issues}

    async def read() -> list[dict[str, Any]]:
        return list(await asyncio.gather(*map(counted, await _browse(settings, "LATEST", None))))

    key = f"suwayomi:latest:v2:{settings.suwayomi_url}:{settings.suwayomi_source_id}"
    listed: list[dict[str, Any]] = await db.remember(key, LATEST_TTL, read)
    return listed


async def issue_count(settings: db.Settings, manga_id: int) -> int:
    """How many issues the source has for a series, read from it now."""
    chapters = await gql(settings, CHAPTERS, {"id": manga_id})
    return len((chapters.get("fetchMangaAndChapters") or {}).get("chapters") or [])


async def series(settings: db.Settings, manga_id: int) -> dict[str, Any]:
    """One series, with `issues`, how many the source has to download now."""
    data = await gql(settings, SERIES, {"id": manga_id})
    found = _series(settings, data["fetchManga"]["manga"])
    found["issues"] = await issue_count(settings, manga_id)
    return found


async def download_all(settings: db.Settings, manga_id: int) -> int:
    """Load the series' chapters from the source and download every one. Returns how many.

    Everything Robin adds to the library goes through here, so its chapters start at once.
    """
    data = await gql(settings, CHAPTERS, {"id": manga_id})
    ids = [c["id"] for c in (data.get("fetchMangaAndChapters") or {}).get("chapters") or []]
    if ids:
        await gql(settings, DOWNLOAD, {"ids": ids})
    return len(ids)


async def add_to_library(settings: db.Settings, manga_id: int) -> dict[str, Any]:
    """Add a series found by searching, monitored in Robin as the library is."""
    await gql(settings, ADD, {"id": manga_id})
    await download_all(settings, manga_id)
    found = await series(settings, manga_id)
    take_in(found, found["issues"])
    return found


async def remove_from_library(settings: db.Settings, manga_id: int) -> None:
    await gql(settings, REMOVE, {"id": manga_id})


def take_in(found: dict[str, Any], chapters: int) -> None:
    """Monitor a library series Robin has no row for, a waiting one of the same run when there
    is one."""
    if any(r["suwayomi_id"] == int(found["id"]) for r in db.rows("comics")):
        return
    for row in db.waiting("comics"):
        if pick([found], row["series"], int(row["year"])):
            db.mark_comic_added(int(row["id"]), int(found["id"]), chapters)
            return
    name, year = run_of(found["title"])
    db.take_in_comic(
        suwayomi_id=int(found["id"]),
        title=found["title"],
        series=name,
        year=year,
        url=found["url"],
        cover=found["thumbnailUrl"],
        chapters=chapters,
    )


def link(comics: list[dict[str, Any]]) -> None:
    """Name the Metron series of each series taken in from Suwayomi that `comics`, a week's
    issues, are of, by its name and the year its run began."""
    unlinked = [r for r in db.rows("comics") if r["suwayomi_id"] and not r["series_id"]]
    if not unlinked:
        return
    runs = {(filters.comparable(r["series"]), int(r["year"])): r for r in unlinked}
    for comic in comics:
        row = runs.get((filters.comparable(comic.get("series") or ""), comic.get("year") or 0))
        if row and comic.get("series_id"):
            db.link_comic_series(int(row["id"]), int(comic["series_id"]), comic["publisher"])


# One library pass at a time, so a page and the sync loop never announce an issue twice.
_syncing = asyncio.Lock()
# When a page last had the library read, how often it may, and how long it waits for it.
_page_synced = 0.0
PAGE_SYNC = 60.0
PAGE_WAIT = 2.0
_behind: set[asyncio.Task[int]] = set()


async def sync_for_page(settings: db.Settings) -> None:
    """Read the library again before a page answers, at most once every `PAGE_SYNC` seconds and
    waiting `PAGE_WAIT` at most, so what changed in Suwayomi shows at once. A pass that takes
    longer goes on behind the answer."""
    global _page_synced
    if not settings.suwayomi_ready or time.monotonic() - _page_synced < PAGE_SYNC:
        return
    _page_synced = time.monotonic()
    task = asyncio.create_task(_quiet_sync())
    _behind.add(task)
    task.add_done_callback(_behind.discard)
    await asyncio.wait({task}, timeout=PAGE_WAIT)


async def _quiet_sync() -> int:
    try:
        return await sync_library()
    except upstream.UpstreamError as exc:
        log.warning("suwayomi: library pass failed: %s", exc)
        return 0


async def sync_library() -> int:
    """Follow the library from the configured source. Returns how many notices were sent.

    Each series in it Robin has no row for is monitored, and each one Robin tracks that is no
    longer in it is forgotten. An issue Suwayomi lists past the count kept is announced on the
    comics topic, once. A waiting series Suwayomi already knows is added at once, rather than at
    the hourly search of the source. Runs on every sync, and for a page, `sync_for_page`.
    """
    async with _syncing:
        return await _sync_library()


async def _sync_library() -> int:
    settings = db.get_settings()
    if not settings.suwayomi_ready:
        return 0
    for waiting in db.waiting("comics"):
        match = await find(settings, waiting["series"], int(waiting["year"]), live=False)
        if match and (waiting["suwayomi"] or match["inLibrary"]):
            await add_if_found(settings, waiting, match)
    data = await gql(settings, LIBRARY, {"source": settings.suwayomi_source_id})
    shelf = {int(m["id"]): _series(settings, m) for m in data["mangas"]["nodes"]}
    channel = settings.notices("comics")
    sent = 0
    for row in db.rows("comics"):
        held = shelf.pop(int(row["suwayomi_id"]), None) if row["suwayomi_id"] else None
        if held is None:
            if row["status"] == "added" and row["suwayomi_id"]:
                db.delete_row("comics", int(row["id"]))
                log.info("suwayomi: %s left the library", row["series"])
            continue
        count = int(held["chapters"]["totalCount"])
        if row["chapters"] is not None and count > row["chapters"] and channel is not None:
            latest = (held.get("latestUploadedChapter") or {}).get("name") or ""
            new = count - int(row["chapters"])
            try:
                await notify.send(
                    settings,
                    channel,
                    title=f"{row['series']} {latest}".strip()
                    if new == 1
                    else f"{new} new issues of {row['series']}",
                    message=held["title"],
                    tags="books",
                    click=held["url"],
                    attach=held["thumbnailUrl"],
                )
            except notify.NotifyError as exc:
                log.warning("suwayomi: notice for %s failed: %s", row["series"], exc)
                continue
            sent += 1
        if count != row["chapters"]:
            db.set_comic_chapters(int(row["id"]), count)
    for found in shelf.values():
        take_in(found, int(found["chapters"]["totalCount"]))
    return sent


async def source_name(settings: db.Settings) -> str:
    data = await gql(settings, SOURCE, {"id": settings.suwayomi_source_id})
    return str(data["source"]["displayName"])


async def find(
    settings: db.Settings, series: str, year: int, *, live: bool = True
) -> dict[str, Any] | None:
    """The run on the source, from what Suwayomi already knows of it, then, while `live`, from a
    search of the source itself, which takes seconds."""
    source = settings.suwayomi_source_id
    for query in queries(series):
        data = await gql(settings, KNOWN, {"source": source, "title": query})
        match = pick(data["mangas"]["nodes"], series, year)
        if match:
            return match
    if not live:
        return None
    for query in queries(series):
        data = await gql(settings, SEARCH, {"source": source, "query": query})
        match = pick(data["fetchSourceManga"]["mangas"], series, year)
        if match:
            return match
    return None


# How long whether the source carries a run is kept: a find a day, a miss an hour, since the
# source lists a series before its first issue is up.
ON_SOURCE_TTL = 24 * 3600
OFF_SOURCE_TTL = 3600


async def on_source(settings: db.Settings, series: str, year: int) -> dict[str, Any] | None:
    """The series on the source, by name and the year its run began, for any issue to open in
    Suwayomi, None when the source does not carry it. Nothing is added to the library. What
    Suwayomi already knows answers at once, and only a search of the source is kept."""
    known = await find(settings, series, year, live=False)
    if known:
        return _series(settings, known)

    async def read() -> dict[str, Any] | None:
        found = await find(settings, series, year)
        return _series(settings, found) if found else None

    key = f"suwayomi:on-source:v1:{settings.suwayomi_source_id}:{filters.comparable(series)}:{year}"
    kept: dict[str, Any] | None = await db.remember(
        key, lambda found: ON_SOURCE_TTL if found else OFF_SOURCE_TTL, read
    )
    return kept


async def add_found_series() -> int:
    """Add each series waiting for Suwayomi the source now carries. Returns how many were
    added.

    Runs on the hourly loop. Only series added to Suwayomi and still waiting are looked for, a
    series monitored in Robin alone never is.
    """
    settings = db.get_settings()
    if not settings.suwayomi_ready:
        return 0
    added = 0
    for comic in [c for c in db.waiting("comics") if c["suwayomi"]]:
        try:
            if await add_if_found(settings, comic):
                added += 1
        except SuwayomiError as exc:
            log.warning("suwayomi: %s failed: %s", comic["series"], exc)
    return added


async def add_if_found(
    settings: db.Settings, comic: dict[str, Any], match: dict[str, Any] | None = None
) -> bool:
    """Add a waiting series to the library once the source lists it, and announce it. One the
    library already holds is only linked: a row already tracking it takes this one in, and
    nothing is announced, since the user put it there."""
    match = match or await find(settings, comic["series"], int(comic["year"]))
    if not match:
        return False
    held = next(
        (
            r
            for r in db.rows("comics")
            if r["suwayomi_id"] == int(match["id"]) and r["id"] != comic["id"]
        ),
        None,
    )
    if held is not None:
        db.merge_comic(int(held["id"]), comic)
        return True
    if match["inLibrary"]:
        db.mark_comic_added(int(comic["id"]), int(match["id"]), None)
        return True
    await gql(settings, ADD, {"id": match["id"]})
    # Loads whatever issues the source has now, so the count says whether the series was
    # found before its first issue. Suwayomi keeps the list current from here.
    count = await download_all(settings, int(match["id"]))
    db.mark_comic_added(int(comic["id"]), int(match["id"]), count)
    log.info("suwayomi: added %s as %s with %s issues", comic["series"], match["title"], count)

    channel = settings.notices("comics")
    if channel is not None:
        try:
            await notify.send(
                settings,
                channel,
                title=f"{comic['series']} is in your library",
                message=f"{count} issue{'' if count == 1 else 's'}" if count else "No issue yet",
                tags="books",
                click=f"{settings.suwayomi_url}/manga/{match['id']}",
                attach=comic["cover"],
            )
        except notify.NotifyError as exc:
            log.warning("suwayomi: notice for %s failed: %s", comic["series"], exc)
    return True
