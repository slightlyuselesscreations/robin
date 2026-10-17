"""Interactive search against Prowlarr.

Prowlarr is not running in tests, so the wire format is pinned instead: the request Robin
sends, and what it makes of the answer. Those are the two halves that break silently.
"""

from collections.abc import Callable

import httpx
import pytest

from robin import db, prowlarr, upstream

Stub = Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]


def configured() -> None:
    db.save_settings({"prowlarr_url": "http://prowlarr.test", "prowlarr_api_key": "secret"})


RELEASES = [
    {
        "guid": "a",
        "title": "Cyberpunk.2077-CODEX",
        "indexerId": 3,
        "indexer": "TorrentLeech",
        "size": 60_000_000_000,
        "seeders": 12,
        "leechers": 2,
        "age": 40,
        "protocol": "torrent",
        "infoUrl": "http://tl/1",
        "indexerFlags": ["FreeLeech", "Internal"],
        "categories": [{"id": 4050, "name": "PC/Games"}],
    },
    {
        "guid": "b",
        "title": "Cyberpunk.2077.REPACK-RUNE",
        "indexerId": 3,
        "indexer": "TorrentLeech",
        "size": 40_000_000_000,
        "seeders": 90,
        "leechers": 1,
        "age": 5,
        "protocol": "torrent",
        "categories": [],
    },
    {
        "guid": "c",
        "title": "Cyberpunk.2077.Usenet",
        "indexerId": 4,
        "indexer": "Newz",
        "size": 50_000_000_000,
        "seeders": None,
        "leechers": None,
        "age": 1,
        "protocol": "usenet",
    },
]


async def test_the_search_request_is_what_prowlarr_expects(
    prowlarr_stub: Stub,
) -> None:
    configured()
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=RELEASES))

    await prowlarr.raw("Cyberpunk 2077")

    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith("http://prowlarr.test/api/v1/search")
    assert request.headers["X-Api-Key"] == "secret"

    params = request.url.params
    assert params["query"] == "Cyberpunk 2077"
    assert params["type"] == "search"
    assert params.get_list("categories") == ["4050"], "PC games, not the whole PC parent"


async def test_nothing_is_sent_until_prowlarr_is_configured(
    prowlarr_stub: Stub,
) -> None:
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=[]))

    with pytest.raises(upstream.NotConfigured, match="not configured"):
        await prowlarr.raw("Cyberpunk 2077")
    assert seen == []


async def test_a_rejected_key_says_so(prowlarr_stub: Stub) -> None:
    configured()
    prowlarr_stub(lambda _: httpx.Response(401))

    with pytest.raises(upstream.UpstreamError, match="rejected the API key"):
        await prowlarr.raw("Cyberpunk 2077")


async def test_every_indexer_is_searched_when_none_are_chosen(prowlarr_stub: Stub) -> None:
    configured()
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=RELEASES))

    await prowlarr.raw("Cyberpunk 2077")

    assert "indexerIds" not in seen[0].url.params


async def test_only_the_chosen_indexers_are_searched(prowlarr_stub: Stub) -> None:
    """Scoped at Prowlarr rather than filtered afterwards, so a tracker with no games is
    never asked in the first place."""
    configured()
    db.save_settings({"prowlarr_indexer_ids_json": "[3, 9]"})
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=RELEASES))

    await prowlarr.raw("Cyberpunk 2077")

    assert seen[0].url.params.get_list("indexerIds") == ["3", "9"]


async def test_the_sync_is_scoped_the_same_way(prowlarr_stub: Stub) -> None:
    configured()
    db.save_settings({"prowlarr_indexer_ids_json": "[5]"})
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=RELEASES))

    await prowlarr.raw("")

    assert seen[0].url.params.get_list("indexerIds") == ["5"]
    assert seen[0].url.params["query"] == ""


async def test_the_indexer_list_is_shaped_for_the_settings_page(prowlarr_stub: Stub) -> None:
    configured()
    prowlarr_stub(
        lambda _: httpx.Response(
            200,
            json=[
                {"id": 3, "name": "TorrentLeech", "enable": True},
                {"id": 9, "name": "Anime Only", "enable": False},
            ],
        )
    )

    assert await prowlarr.indexers() == [
        {"id": 3, "name": "TorrentLeech", "enabled": True},
        {"id": 9, "name": "Anime Only", "enabled": False},
    ]


async def test_the_pc_parent_category_is_never_asked_for(prowlarr_stub: Stub) -> None:
    """4000 also carries 4010 PC/0day, 4020 PC/ISO and 4030 PC/Mac, so asking for it returns
    application software. Both paths are scoped to games alone."""
    configured()
    seen = prowlarr_stub(lambda _: httpx.Response(200, json=RELEASES))

    await prowlarr.raw("Cyberpunk 2077")

    for request in seen:
        assert request.url.params.get_list("categories") == ["4050"]


async def test_a_grab_hands_the_release_to_prowlarrs_download_client(prowlarr_stub: Stub) -> None:
    configured()
    seen = prowlarr_stub(lambda _: httpx.Response(200, json={}))
    await prowlarr.grab(RELEASES[0])
    assert (seen[0].method, seen[0].url.path) == ("POST", "/api/v1/search")
    assert seen[0].headers["X-Api-Key"] == "secret"
    assert httpx.Response(200, content=seen[0].content).json() == {"guid": "a", "indexerId": 3}
