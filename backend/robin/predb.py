"""PreDB.net, which logs every scene release as it is pre'd, and whether it was nuked. No key.

`q` matches from the start of a release name and treats spaces, dots and underscores alike, so
one query for a game's title and a group returns every release of it by that group, whatever
separators a tracker uses. The group keeps a game with dozens of updates from pushing its
release off the one page asked for. A release counts as the full game only in the `GAMES`
section, `GAMES-DOX` being its updates, DLC and language packs.
"""

from __future__ import annotations

from typing import Any, Literal

from robin import filters, upstream

BASE = "https://api.predb.net/"
TIMEOUT = 15.0

FULL_GAME = "GAMES"

# PreDB's status: 0 ok, 1 nuked, 2 unnuked, 3 deleted pre, 4 restored pre.
CLEAN = {0, 2, 4}

# Clean is the full game and not nuked. Bad is listed as anything else, nuked or an update.
Verdict = Literal["clean", "bad", "unknown"]


# A release name with case and separators gone, the form both sides are compared in.
key = filters.comparable


async def pres(term: str, group: str) -> dict[str, tuple[str, int]]:
    """Every release a group pre'd under a title, by `key`, with its section and status."""
    resp = await upstream.request(
        upstream.UpstreamError,
        "PreDB",
        "GET",
        BASE,
        timeout=TIMEOUT,
        source="predb",
        params={"q": term, "group": group, "limit": 100},
    )
    payload: dict[str, Any] = resp.json()
    if payload.get("status") != "success":
        raise upstream.UpstreamError(
            f"PreDB answered {payload.get('message') or payload.get('status')}"
        )
    return {
        key(str(row.get("release", ""))): (str(row.get("section", "")), int(row.get("status") or 0))
        for row in payload.get("data") or []
    }


def verdict(release: str, known: dict[str, tuple[str, int]]) -> Verdict:
    found = known.get(key(release))
    if found is None:
        return "unknown"
    section, status = found
    return "clean" if section == FULL_GAME and status in CLEAN else "bad"
