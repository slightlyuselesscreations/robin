"""One request to a service Robin talks to, failing with a message that names the service.

The data sources Robin borrows from, IGDB, TMDB, Hardcover, Metron and PreDB, are
asked through a `Limit` each: a pace under what the owner publishes, a cap on requests in
flight, and a pause once the source says slow down, during which Robin does not ask it at all.
The pause is kept in the cache table, so a restart does not cut it short. Integrations are the
user's own services and pass no `source`, so they are never paced or paused.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

from robin import db

log = logging.getLogger(__name__)


class UpstreamError(RuntimeError):
    """A service failed. `status` is the HTTP status it answered with, None when it never did.

    `retry_after` is its Retry-After header, when it sent one.
    """

    def __init__(
        self, message: str, *, status: int | None = None, retry_after: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class NotConfigured(UpstreamError):
    """A source or integration Settings leaves unset. Answered as 409, never retried."""


class RateLimited(UpstreamError):
    """A data source asked Robin to slow down, and Robin is not asking it until `until`."""

    def __init__(self, name: str, until: datetime) -> None:
        super().__init__(f"{name} asked Robin to slow down", status=429)
        self.name = name
        self.until = until


# ---------------------------------------------------------------- source limits

Source = Literal["igdb", "tmdb", "hardcover", "metron", "predb", "github"]


@dataclass(frozen=True)
class Limit:
    name: str
    # At most `rate` requests start in any `per` seconds.
    rate: int
    per: float
    in_flight: int
    # Statuses that mean slow down. A 503 counts too, only when it names a time.
    refused: frozenset[int]
    # The pause when a refusal names no time, doubling on each refusal in a row up to `longest`.
    first_pause: float
    longest: float


LIMITS: dict[Source, Limit] = {
    # IGDB publishes 4 a second and 8 in flight.
    "igdb": Limit("IGDB", 4, 1.0, 4, frozenset({429}), 60, 3600),
    # TMDB holds a soft cap around 40 a second, half of it is plenty.
    "tmdb": Limit("TMDB", 20, 1.0, 8, frozenset({429}), 60, 3600),
    # Hardcover publishes 60 a minute.
    "hardcover": Limit("Hardcover", 50, 60.0, 2, frozenset({429}), 60, 3600),
    # Metron publishes 20 a minute and 5000 a day. One every four seconds, evenly, so a page
    # never waits out a minute behind a burst of the hourly loop.
    "metron": Limit("Metron", 1, 4.0, 1, frozenset({429}), 60, 3600),
    # PreDB.net publishes 30 a minute and blocks an address that overloads it.
    "predb": Limit("PreDB", 20, 60.0, 1, frozenset({429}), 60, 3600),
    # GitHub publishes 60 an hour for an address without a token, refused with 403 or 429.
    "github": Limit("GitHub", 30, 3600.0, 1, frozenset({403, 429}), 3600, 86400),
}

# Never wait longer than this on a Retry-After, whatever the source says.
LONGEST_RETRY_AFTER = 86400.0


@dataclass
class _Pace:
    """One source's pace in one event loop. asyncio primitives belong to the loop they wait in."""

    loop: asyncio.AbstractEventLoop
    flight: asyncio.Semaphore
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: deque[float] = field(default_factory=deque)


_paces: dict[Source, _Pace] = {}


def _pace(source: Source) -> _Pace:
    loop = asyncio.get_running_loop()
    pace = _paces.get(source)
    if pace is None or pace.loop is not loop:
        pace = _Pace(loop=loop, flight=asyncio.Semaphore(LIMITS[source].in_flight))
        _paces[source] = pace
    return pace


def _key(source: Source) -> str:
    return f"limit:v1:{source}"


def paused_until(source: Source) -> datetime | None:
    """When a pause on the source ends, or None while there is none."""
    held = db.cache_get(_key(source))
    if not isinstance(held, dict):
        return None
    until = datetime.fromisoformat(held["until"])
    return until if until > datetime.now(UTC) else None


@asynccontextmanager
async def slot(source: Source) -> AsyncIterator[None]:
    """Wait for the source's turn, or fail at once while it is paused."""
    until = paused_until(source)
    if until is not None:
        raise RateLimited(LIMITS[source].name, until)
    limit = LIMITS[source]
    pace = _pace(source)
    async with pace.flight:
        async with pace.lock:
            while True:
                now = time.monotonic()
                while pace.started and now - pace.started[0] >= limit.per:
                    pace.started.popleft()
                if len(pace.started) < limit.rate:
                    break
                await asyncio.sleep(limit.per - (now - pace.started[0]))
            pace.started.append(time.monotonic())
        yield


def _seconds(retry_after: str | None) -> float | None:
    """A Retry-After as seconds from now, in either of its two forms."""
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(retry_after)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def observe(source: Source, status: int, retry_after: str | None) -> None:
    """Read one refused answer. Slow down starts or lengthens a pause and raises RateLimited."""
    limit = LIMITS[source]
    named = _seconds(retry_after)
    if status not in limit.refused and not (status == 503 and named is not None):
        return
    held = db.cache_get(_key(source))
    last = float(held["pause"]) if isinstance(held, dict) else 0.0
    pause = (
        min(named, LONGEST_RETRY_AFTER)
        if named is not None
        else min(max(limit.first_pause, last * 2), limit.longest)
    )
    until = datetime.now(UTC) + timedelta(seconds=pause)
    # Kept past the pause, so a refusal soon after it ends doubles the pause rather than
    # starting over.
    db.cache_put(_key(source), {"until": until.isoformat(), "pause": pause}, int(pause * 2) + 60)
    log.warning("%s refused a request (%s), not asking it until %s", limit.name, status, until)
    raise RateLimited(limit.name, until)


# ---------------------------------------------------------------- requests


async def request(
    error: type[UpstreamError],
    name: str,
    method: str,
    url: str,
    *,
    timeout: float,
    rejected: str = "",
    missing: str = "",
    source: Source | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """`rejected` answers a 401 or 403 and `missing` a 404, anything else 400 up is generic.

    A `source` is paced and paused by its `Limit`.
    """
    if source is None:
        return await _request(error, name, method, url, timeout, rejected, missing, **kwargs)
    async with slot(source):
        try:
            return await _request(error, name, method, url, timeout, rejected, missing, **kwargs)
        except UpstreamError as exc:
            if exc.status is not None:
                observe(source, exc.status, exc.retry_after)
            raise


_shared: tuple[type[httpx.AsyncClient], httpx.AsyncClient] | None = None


def _client() -> httpx.AsyncClient:
    """One client for every source and integration, so a connection is kept between requests.

    Made again when `httpx.AsyncClient` is no longer the class it was made from, which is how
    the tests swap in their own transport.
    """
    global _shared
    factory = httpx.AsyncClient
    if _shared is None or _shared[0] is not factory or _shared[1].is_closed:
        _shared = (factory, factory())
    return _shared[1]


async def close() -> None:
    global _shared
    if _shared is not None:
        await _shared[1].aclose()
        _shared = None


async def _request(
    error: type[UpstreamError],
    name: str,
    method: str,
    url: str,
    timeout: float,
    rejected: str,
    missing: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        resp = await _client().request(method, url, timeout=timeout, **kwargs)
    except httpx.HTTPError as exc:
        raise error(f"Could not reach {name}: {exc}") from exc
    status = resp.status_code
    retry_after = resp.headers.get("retry-after")
    if rejected and status in (401, 403):
        raise error(rejected, status=status, retry_after=retry_after)
    if missing and status == 404:
        raise error(missing, status=status)
    if status >= 400:
        path = resp.request.url.path
        raise error(
            f"{name} returned {status} for {path}: {resp.text[:300]}",
            status=status,
            retry_after=retry_after,
        )
    return resp


async def graphql(
    error: type[UpstreamError],
    name: str,
    url: str,
    query: str,
    variables: dict[str, Any],
    *,
    timeout: float,
    partial: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run one GraphQL operation and return its `data`.

    An answer carrying `errors` fails, unless `partial` and some field still came back, which
    is how Suwayomi reports a fetch that half worked.
    """
    resp = await request(
        error,
        name,
        "POST",
        url,
        timeout=timeout,
        json={"query": query, "variables": variables},
        **kwargs,
    )
    body = resp.json()
    data: dict[str, Any] | None = body.get("data")
    errors = body.get("errors")
    answered = data is not None and any(data.values())
    if errors and not (partial and answered):
        first = errors[0]
        raise error(f"{name}: {first.get('message', first) if isinstance(first, dict) else first}")
    if not data or (partial and not answered):
        raise error(f"{name}: empty answer")
    return data
