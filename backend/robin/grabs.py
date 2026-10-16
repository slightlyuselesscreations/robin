"""A monitored game from waiting to found, and its download after.

Robin syncs as Sonarr and Radarr do. Every RSS_INTERVAL it reads what the indexers listed lately,
one Prowlarr call, and matches it against every game still waiting. A game already out is also
searched for by name, as it is monitored and once each time Robin starts, so a release listed
while Robin was off is not missed.

Of the releases a game takes, the first listed is grabbed once it comes from a group outside the
scene set in Settings, or PreDB has it pre'd as the full game and not nuked. One PreDB lists as
anything else, nuked or an update, is passed over. One PreDB cannot vouch for, because it does
not list it or did not answer, is held for the user to confirm, and the user is told. Every grab
goes to qBittorrent under the category set in Settings, tagged so its download is followed, and
the user is told once it is done.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from robin import db, filters, notify, predb, prowlarr, qbittorrent, upstream

log = logging.getLogger(__name__)

# Sonarr's and Radarr's default RSS sync interval.
RSS_INTERVAL = 15 * 60

# A release published more than this before a dated game is out belongs to another game of the
# same name, an earlier one or the one remade.
EARLY = timedelta(days=1)


def refusal(release: dict[str, Any], request: dict[str, Any], freeleech: bool) -> str | None:
    """Why a monitored game turns down a release leading with its title, None when it takes
    it: excluded by `filters`, not freeleech when Settings asks for it, published before the
    game could be out, rejected by the user or already under review."""
    title = str(release.get("title", ""))
    if filters.excluded(title):
        return "excluded release"
    if title == request["review_release"]:
        return "awaiting confirmation"
    if title in db.rejected(int(request["id"])):
        return "rejected"
    flags = {str(f).lower() for f in release.get("indexerFlags") or []}
    if freeleech and "freeleech" not in flags:
        return "not freeleech"
    released, published = request["first_release_date"], release.get("publishDate")
    if released and published:
        # Prowlarr writes UTC, with or without saying so.
        when = datetime.fromisoformat(published)
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        day = datetime.fromtimestamp(released, UTC)
        if when < day - EARLY:
            return f"published {when:%Y-%m-%d}, before release {day:%Y-%m-%d}"
    return None


async def rss_sync() -> int:
    """Match what the indexers listed lately against every game still waiting. Returns grabs."""
    if not db.get_settings().prowlarr_ready:
        return 0
    waiting = db.waiting_requests()
    if not waiting:
        return 0
    releases = await prowlarr.raw("")
    log.info("grabs: sync, %d releases, %d waiting", len(releases), len(waiting))
    grabbed = 0
    for request in waiting:
        grabbed += await _consider(releases, request)
    return grabbed


async def search_waiting(igdb_id: int | None = None) -> int:
    """Search the indexers by name for every waiting game that is out, or only `igdb_id`.

    An undated game, or one not out by tomorrow, has nothing on the indexers yet. The sync
    catches it when it lands.
    """
    if not db.get_settings().prowlarr_ready:
        return 0
    tomorrow = (datetime.now(UTC) + EARLY).timestamp()
    grabbed = 0
    for request in db.waiting_requests():
        released = request["first_release_date"]
        if igdb_id not in (None, request["igdb_id"]) or not released or released > tomorrow:
            continue
        term = filters.search_term_for(request["game_name"])
        try:
            releases = await prowlarr.raw(term)
        except upstream.UpstreamError as exc:
            log.warning("grabs: could not search for %s: %s", request["game_name"], exc)
            db.set_request_error(int(request["id"]), str(exc))
            continue
        log.info("grabs: search %r, %d releases", term, len(releases))
        grabbed += await _consider(releases, request)
    return grabbed


async def _consider(releases: list[dict[str, Any]], request: dict[str, Any]) -> int:
    """Grab the first release the game takes that is clean, or hold the first PreDB cannot
    vouch for. PreDB is asked once per group in the running, and only for scene releases."""
    request_id = int(request["id"])
    name = request["game_name"]
    settings = db.get_settings()
    candidates = []
    for release in releases:
        if not filters.leads(str(release.get("title", "")), name):
            continue
        why = refusal(release, request, settings.freeleech_only)
        if why is None:
            candidates.append(release)
        else:
            log.info("grabs: skipped %s: %s", release.get("title"), why)
    candidates.sort(key=lambda r: str(r.get("publishDate") or ""))
    if not candidates:
        return 0
    outside = {g.lower() for g in settings.p2p_groups}
    known: dict[str, dict[str, tuple[str, int]]] = {}
    unsure: dict[str, Any] | None = None
    for release in candidates:
        title = str(release["title"])
        group = filters.release_group(title) or ""
        if group.lower() in outside:
            return await _grab(release, request)
        if group.lower() not in known:
            try:
                known[group.lower()] = await predb.pres(
                    filters.search_term_for(request["game_name"]), group
                )
            except upstream.UpstreamError as exc:
                log.warning("grabs: PreDB could not be asked about %s: %s", title, exc)
                known[group.lower()] = {}
        verdict = predb.verdict(title, known[group.lower()])
        if verdict == "clean":
            return await _grab(release, request)
        if verdict == "bad":
            section, status = known[group.lower()][predb.key(title)]
            log.info("grabs: skipped %s: PreDB %s, status %d", title, section, status)
        elif unsure is None:
            log.info("grabs: not on PreDB: %s", title)
            unsure = release
    if unsure is not None and db.put_in_review(request_id, unsure):
        log.info("grabs: holding %s for %s to be confirmed", unsure["title"], request["game_name"])
        await _tell(
            settings,
            title=f"Confirm a release for {request['game_name']}",
            message=f"PreDB could not vouch for {unsure['title']}. Open the game in Robin to "
            "grab it or reject it.",
            tags="question",
        )
    return 0


async def _grab(release: dict[str, Any], request: dict[str, Any]) -> int:
    """Grab once ever. A failed grab hands the game back to waiting with its error."""
    request_id = int(request["id"])
    # Claimed before it is sent, in the statement that checks it is still waiting, so the sync
    # and a search cannot both grab it.
    if not db.claim_grab(request_id, str(release["title"])):
        return 0
    try:
        await _send(release, request)
    except upstream.UpstreamError as exc:
        log.warning("grabs: could not grab %s: %s", release["title"], exc)
        db.release_grab(request_id, request["status"])
        db.set_request_error(request_id, str(exc))
        return 0
    log.info("grabs: grabbed %s for %s", release["title"], request["game_name"])
    await _tell(
        db.get_settings(),
        title=f"{request['game_name']} is downloading",
        message=f"Sent {release['title']} to qBittorrent.",
        tags="inbox_tray",
    )
    return 1


async def _send(release: dict[str, Any], request: dict[str, Any]) -> None:
    settings = db.get_settings()
    torrent = await prowlarr.torrent(release)
    await qbittorrent.add(
        settings, torrent, category=settings.qbittorrent_category, request_id=int(request["id"])
    )


async def confirm(request_id: int) -> bool:
    """Grab the release the user confirmed. False when nothing is held, the game found first.

    A grab that fails puts the release back under review and raises.
    """
    release, request = db.review(request_id), db.get_request(request_id)
    if release is None or request is None or not db.claim_grab(request_id, release["title"]):
        return False
    try:
        await _send(release, request)
    except upstream.UpstreamError:
        db.release_grab(request_id, request["status"])
        db.put_in_review(request_id, release)
        raise
    log.info("grabs: grabbed %s for %s, confirmed", release["title"], request["game_name"])
    return True


async def track_downloads() -> int:
    """Mark the grabs qBittorrent has finished and tell the user, once each. Returns how many."""
    settings = db.get_settings()
    if not settings.prowlarr_ready:
        return 0
    held = await qbittorrent.grabs(settings)
    done = 0
    for request_id, torrent in held.items():
        if torrent["progress"] < 1 or not db.mark_downloaded(request_id):
            continue
        done += 1
        request = db.get_request(request_id)
        if request is not None:
            await _tell(
                settings,
                title=f"{request['game_name']} is downloaded",
                message=str(request["matched_release"]),
                tags="white_check_mark",
            )
    return done


async def with_downloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each grabbed game's download as qBittorrent has it now, None when it holds none or
    cannot be reached."""
    settings = db.get_settings()
    held: dict[int, dict[str, Any]] = {}
    pending = any(r["status"] == "matched" and not r["downloaded_at"] for r in rows)
    if settings.prowlarr_ready and pending:
        try:
            held = await qbittorrent.grabs(settings)
        except upstream.UpstreamError as exc:
            log.warning("grabs: could not read qBittorrent: %s", exc)
    return [{**r, "download": held.get(r["id"])} for r in rows]


async def _tell(settings: db.Settings, *, title: str, message: str, tags: str) -> None:
    """A notice on the games topic, while it is on. A failed one is logged, never retried."""
    channel = settings.notices("games")
    if channel is None:
        return
    try:
        await notify.send(settings, channel, title=title, message=message, tags=tags)
    except notify.NotifyError as exc:
        log.warning("grabs: could not send %r: %s", title, exc)
