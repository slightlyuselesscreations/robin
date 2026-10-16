import dataclasses
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from robin import auth, db, notify, upstream
from robin.config import env
from robin.main import app

PASSWORD = "correct horse battery"
# Hashed once, Argon2 is slow on purpose.
PASSWORD_HASH = auth.hash_password(PASSWORD)

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def quick_comicvine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comic Vine is asked a second apart, which no test needs to wait for."""
    monkeypatch.setitem(
        upstream.LIMITS, "comicvine", dataclasses.replace(upstream.LIMITS["comicvine"], per=0.0)
    )


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path) -> Iterator[None]:
    """Every test gets an empty database."""
    env.robin_data_dir = tmp_path
    db.init_db()
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Signed in, with the header every write carries."""
    db.update_account(password_hash=PASSWORD_HASH)
    token = "test-session"
    db.create_session(hashlib.sha256(token.encode()).hexdigest(), "9999-12-31T00:00:00+00:00")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://robin.test",
        cookies={auth.COOKIE: token},
        headers={auth.CSRF_HEADER: "1"},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def anon() -> AsyncIterator[AsyncClient]:
    """No session, but the write header, so a refusal is about the session and nothing else."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://robin.test",
        headers={auth.CSRF_HEADER: "1"},
    ) as c:
        yield c


# One ntfy destination, `topic` its place for every category without one of its own.
NTFY = {
    "id": "ntfy",
    "service": "ntfy",
    "values": {"server": "https://ntfy.test", "topic": "robin"},
}


def notify_to(**places: str) -> dict[str, Any]:
    """Settings that send notifications to `NTFY`, at a topic per category given."""
    return {"notify_destinations": [{**NTFY, "places": places}]}


@pytest.fixture(autouse=True)
def delivered(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every message handed to Apprise, its address included. Nothing leaves the test."""
    out: list[dict[str, Any]] = []

    async def capture(url: str, **kwargs: Any) -> str | None:
        out.append({"url": url, **kwargs})
        return None

    monkeypatch.setattr(notify, "_deliver", capture)
    return out


@pytest.fixture
def notified(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every notice Robin sends, as its keyword arguments plus the channel's category."""
    out: list[dict[str, Any]] = []

    async def capture(settings: db.Settings, channel: db.Channel, **kwargs: Any) -> None:
        out.append({**kwargs, "category": channel.category})

    monkeypatch.setattr(notify, "send", capture)
    return out


Answer = httpx.Response | Awaitable[httpx.Response]


def stub_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], Answer]
) -> list[httpx.Request]:
    """Answer every request Robin sends with `handler`, in process, and keep each one.

    Nothing leaves the test: every client Robin opens from here on is a mock.
    """
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> Any:
        seen.append(request)
        return handler(request)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(record), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


@pytest.fixture
def prowlarr_stub(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    """Answer Prowlarr's endpoints in process and keep every request Robin made.

    Returns the installer, so a test picks its own handler and then reads what was sent.
    """
    return lambda handler: stub_http(monkeypatch, handler)
