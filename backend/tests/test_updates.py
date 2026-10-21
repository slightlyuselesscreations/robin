"""The newest release on GitHub, told only when it is newer than the Robin running."""

import httpx
import pytest
from httpx import AsyncClient

from robin import __version__, updates
from tests.conftest import stub_http


def answer(tag: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "tag_name": tag,
            "body": "Bug fixes\r\n- A fix",
            "html_url": f"https://github.com/{updates.REPOSITORY}/releases/tag/{tag}",
            "published_at": "2026-10-21T09:00:00Z",
        },
    )


async def test_a_newer_release_is_told_with_its_notes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return answer("v99.0.0")

    stub_http(monkeypatch, handler)
    found = (await client.get("/api/update")).json()
    assert found["version"] == "99.0.0"
    assert found["notes"] == "Bug fixes\n- A fix"
    assert str(asked[0].url).endswith(f"/repos/{updates.REPOSITORY}/releases/latest")

    await client.get("/api/update")
    assert len(asked) == 1, "kept, not asked again"


async def test_the_running_release_tells_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_http(monkeypatch, lambda _: answer(f"v{__version__}"))
    assert (await client.get("/api/update")).json() is None


def test_versions_compare_as_numbers() -> None:
    assert updates.release("0.0.10") > updates.release("v0.0.9")
