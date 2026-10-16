"""Countdowns to a release, kept for Home and dated again as the release moves."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from robin import db

AHEAD = (datetime.now(UTC) + timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)


async def test_a_countdown_follows_its_release_and_goes_when_removed(client: AsyncClient) -> None:
    db.upsert_games([{"igdb_id": 7, "name": "Game", "first_release_date": int(AHEAD.timestamp())}])
    body = {
        "category": "games",
        "target": "game=7",
        "title": "Game",
        "date": AHEAD.date().isoformat(),
    }
    assert (await client.post("/api/countdowns", json=body)).status_code == 200

    # The release moves a week, and the countdown with it.
    later = AHEAD + timedelta(days=7)
    db.upsert_games([{"igdb_id": 7, "name": "Game", "first_release_date": int(later.timestamp())}])
    [countdown] = (await client.get("/api/countdowns")).json()
    assert countdown["date"] == later.date().isoformat()

    assert (await client.delete(f"/api/countdowns/{countdown['id']}")).status_code == 204
    assert (await client.get("/api/countdowns")).json() == []


async def test_nothing_out_already_is_counted_down_to(client: AsyncClient) -> None:
    body = {"category": "books", "target": "book=1", "title": "Old", "date": "2019-11-27"}
    assert (await client.post("/api/countdowns", json=body)).status_code == 409
    assert db.countdowns() == []
