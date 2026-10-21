"""The newest Robin released on GitHub, so the sidebar can say an update is out."""

from __future__ import annotations

import re
from typing import Any

from robin import __version__, db, upstream

REPOSITORY = "slightlyuselesscreations/robin"

# A release is looked for four times a day, well under GitHub's 60 an hour without a token.
TTL = 6 * 3600


def release(version: str) -> tuple[int, ...]:
    """A version as numbers, so 0.0.10 comes after 0.0.9."""
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


async def latest() -> dict[str, Any] | None:
    """The newest release when it is newer than the Robin running, else None."""

    async def fetch() -> dict[str, Any]:
        resp = await upstream.request(
            upstream.UpstreamError,
            "GitHub",
            "GET",
            f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
            timeout=15,
            source="github",
            headers={"Accept": "application/vnd.github+json"},
        )
        raw = resp.json()
        return {
            "version": str(raw["tag_name"]).removeprefix("v"),
            # GitHub keeps the line endings the notes were written with.
            "notes": str(raw.get("body") or "").replace("\r\n", "\n").strip(),
            "url": raw.get("html_url"),
            "published": raw.get("published_at"),
        }

    found: dict[str, Any] | None = await db.remember("github:release:v1", TTL, fetch)
    if found is None or release(found["version"]) <= release(__version__):
        return None
    return found
