"""Monitored comic series, added to the Suwayomi library once a source carries them.

Robin tracks series, not issues. A series is monitored from its #1 on the Comics page and
looked for on the configured Suwayomi source at once, then on every hourly pass while it is
still waiting. The moment the source lists it, it is added to the library and announced on the
comics topic, whether or not an issue is up yet. From there Suwayomi owns it, fetching and
downloading issues as they come out, and Robin asks nothing more about it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from robin import db, notify, upstream

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


def _key(title: str) -> str:
    """Punctuation differs between Comic Vine and a source, "..." against "…" for one."""
    return re.sub(r"[^0-9a-z]+", "", title.casefold())


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
        if _key(result["title"][: dated.start()]) == _key(series):
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
    """Add a series found by searching. Suwayomi owns it from here, Robin keeps no record."""
    await gql(settings, ADD, {"id": manga_id})
    await download_all(settings, manga_id)
    return await series(settings, manga_id)


async def source_name(settings: db.Settings) -> str:
    data = await gql(settings, SOURCE, {"id": settings.suwayomi_source_id})
    return str(data["source"]["displayName"])


async def find(settings: db.Settings, series: str, year: int) -> dict[str, Any] | None:
    for query in queries(series):
        data = await gql(settings, SEARCH, {"source": settings.suwayomi_source_id, "query": query})
        match = pick(data["fetchSourceManga"]["mangas"], series, year)
        if match:
            return match
    return None


async def add_found_series() -> int:
    """Add each waiting series the source now carries. Returns how many were added.

    Runs on the hourly loop. Only series still waiting are looked for.
    """
    settings = db.get_settings()
    if not settings.suwayomi_ready:
        return 0
    added = 0
    for comic in db.waiting("comics"):
        try:
            if await add_if_found(settings, comic):
                added += 1
        except SuwayomiError as exc:
            log.warning("suwayomi: %s failed: %s", comic["series"], exc)
    return added


async def add_if_found(settings: db.Settings, comic: dict[str, Any]) -> bool:
    match = await find(settings, comic["series"], int(comic["year"]))
    if not match:
        return False
    if not match["inLibrary"]:
        await gql(settings, ADD, {"id": match["id"]})
    # Loads whatever issues the source has now, so the count says whether the series was
    # found before its first issue. Suwayomi keeps the list current from here.
    count = await download_all(settings, int(match["id"]))
    db.mark_comic_added(int(comic["id"]), int(match["id"]), count)
    log.info("suwayomi: added %s as %s with %s issues", comic["series"], match["title"], count)

    channel = settings.notices("comics")
    if channel is not None:
        issues = (
            f"{count} issue{'' if count == 1 else 's'} to read"
            if count
            else "no issue is out yet, Suwayomi fetches them as they come"
        )
        try:
            await notify.send(
                settings,
                channel,
                title=f"{comic['series']} is in your library",
                message=f"{match['title']}, {issues}.",
                tags="books",
                click=f"{settings.suwayomi_url}/manga/{match['id']}",
                attach=comic["cover"],
            )
        except notify.NotifyError as exc:
            log.warning("suwayomi: notice for %s failed: %s", comic["series"], exc)
    return True
