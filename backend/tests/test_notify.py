"""Notifications: who gets told, where, when, and only once.

A container that was off overnight still announces a game on release day rather than skipping
it silently.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from robin import db, igdb, notices, notify
from tests.conftest import NTFY, notify_to

TODAY = date(2026, 9, 10)
# 10:00, past the day before's default hour of 9.
WINDOW = notices.Window(now=datetime(2026, 9, 10, 10), slots=[db.DAY_BEFORE])

# Game notices go out only while the Games category is shown, which needs IGDB.
IGDB = {"twitch_client_id": "client", "twitch_client_secret": "secret"}
NTFY_TOKEN = {
    **NTFY,
    "values": {"server": "https://ntfy.example.com/", "topic": "robin", "token": "tk_secret_value"},
}


def ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "igdb_id": 7,
        "game_name": "A Game",
        "status": "monitored",
        "first_release_date": ts(TODAY + timedelta(days=1)),
        "notified_for": None,
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("release", "expected", "why"),
    [
        (TODAY + timedelta(days=1), True, "out tomorrow"),
        (TODAY, True, "out today and never announced, so catch up"),
        (TODAY + timedelta(days=2), False, "still two days out"),
        (TODAY + timedelta(days=30), False, "far off"),
        (TODAY - timedelta(days=1), False, "already out, the moment has passed"),
    ],
)
def test_the_notice_window(release: date, expected: bool, why: str) -> None:
    candidates = notify.due_for_notice([row(first_release_date=ts(release))], WINDOW)
    assert bool(candidates) is expected, why


def test_a_release_is_announced_once() -> None:
    [(_, due)] = notify.due_for_notice([row()], WINDOW)
    assert notify.due_for_notice([row(notified_for=due.marker)], WINDOW) == []


def test_a_date_that_moved_is_announced_again() -> None:
    """An Early Access date already announced cannot silence the full release replacing it."""
    stale = row(notified_for="2025-05-14|2025-05-13T09")
    assert notify.due_for_notice([stale], WINDOW) != []


def test_a_game_with_no_date_is_never_announced() -> None:
    assert notify.due_for_notice([row(first_release_date=None)], WINDOW) == []


@pytest.mark.parametrize(
    ("hour", "until"),
    [
        (23, datetime(2026, 9, 11, 7)),
        (3, datetime(2026, 9, 10, 7)),
        (7, None),
        (12, None),
    ],
)
def test_quiet_hours_across_midnight(hour: int, until: datetime | None) -> None:
    assert notify.held_until((22, 7), datetime(2026, 9, 10, hour)) == until


def test_quiet_hours_within_a_day() -> None:
    assert notify.held_until((13, 15), datetime(2026, 9, 10, 14, 30)) == datetime(2026, 9, 10, 15)
    assert notify.held_until((13, 15), datetime(2026, 9, 10, 15)) is None
    assert notify.held_until(None, datetime(2026, 9, 10, 14)) is None


def test_undated_picks_out_the_tba_games() -> None:
    rows = [row(id=1, first_release_date=None), row(id=2)]
    assert [r["id"] for r in notify.undated(rows)] == [1]


def test_nothing_is_sent_until_a_destination_is_set() -> None:
    assert db.get_settings().notices("games") is None


def test_game_notices_need_a_destination_their_switch_and_igdb() -> None:
    db.save_settings(notify_to())
    assert db.get_settings().notices("games") is None
    db.save_settings(IGDB)
    assert db.get_settings().notices("games") == db.Channel(category="games")
    db.save_settings({"games_notify": False})
    assert db.get_settings().notices("games") is None


def test_quiet_hours_are_kept_per_category() -> None:
    db.save_settings({"games_quiet": [22, 7], "books_quiet": [5, 5]})
    settings = db.get_settings()
    assert settings.channel("games").quiet == (22, 7)
    # The same hour twice is no quiet hours at all.
    assert settings.channel("books").quiet is None
    assert settings.channel("comics").quiet is None


@pytest.mark.parametrize("key", list(notify.SERVICES))
def test_every_service_example_is_an_address_apprise_reads(key: str) -> None:
    service = notify.SERVICES[key]
    values = {f.key: f.example for f in service.fields}
    if key == "apprise":
        values["url"] = "ntfys://ntfy.sh/robin"
    destination = {"id": key, "service": key, "values": values, "places": {}}
    notify.check(destination)


def test_a_required_field_left_blank_is_refused() -> None:
    with pytest.raises(ValueError, match="Topic is required"):
        notify.check({"id": "n", "service": "ntfy", "values": {"server": "https://ntfy.sh"}})


async def test_a_notice_reaches_every_destination_at_the_categorys_place(
    delivered: list[dict[str, Any]],
) -> None:
    telegram = {
        "id": "tg",
        "service": "telegram",
        "values": {"token": "123:abc", "chat": "-100"},
        "places": {"books": "-200"},
    }
    games = {**NTFY_TOKEN, "places": {"games": "games"}}
    db.save_settings({**IGDB, "notify_destinations": [games, telegram]})
    settings = db.get_settings()

    await notify.send(
        settings,
        settings.channel("games"),
        title="Hello",
        message="Body",
        click="https://igdb.test",
    )

    ntfy, tgram = delivered
    # The trailing slash on the server must not become a double slash.
    assert ntfy["url"].startswith("ntfys://tk_secret_value@ntfy.example.com/games?")
    assert "click=https%3A%2F%2Figdb.test" in ntfy["url"]
    assert (ntfy["title"], ntfy["body"]) == ("Hello", "Body")
    # A service with no link of its own carries it in the body, at its default place.
    assert tgram["url"] == "tgram://123%3Aabc/-100"
    assert tgram["body"] == "Body\nhttps://igdb.test"


async def test_one_destination_failing_is_logged_and_the_rest_still_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gotify = {"id": "g", "service": "gotify", "values": {"server": "g.test", "token": "t"}}
    db.save_settings({"notify_destinations": [NTFY_TOKEN, gotify]})

    async def deliver(url: str, **_: Any) -> str | None:
        return "refused" if url.startswith("gotify") else None

    monkeypatch.setattr(notify, "_deliver", deliver)
    settings = db.get_settings()
    await notify.send(settings, settings.channel("games"), title="Hi", message="Body")
    health = await notify_health(settings)
    assert health == "Gotify: refused"

    monkeypatch.setattr(notify, "_deliver", lambda url, **_: _answer("down"))
    with pytest.raises(notify.NotifyError):
        await notify.send(settings, settings.channel("games"), title="Hi", message="Body")


async def _answer(value: str | None) -> str | None:
    return value


async def notify_health(settings: db.Settings) -> str:
    try:
        await notify.health(settings)
    except ValueError as exc:
        return str(exc)
    return "healthy"


async def test_quiet_hours_keep_notices_and_send_one_digest_when_they_end(
    monkeypatch: pytest.MonkeyPatch, delivered: list[dict[str, Any]]
) -> None:
    db.save_settings({**notify_to(), **IGDB, "games_quiet": [22, 7]})
    settings = db.get_settings()
    night = datetime(2026, 9, 10, 23, tzinfo=UTC)
    monkeypatch.setattr(notices, "local_now", lambda: night)

    for n in (1, 2):
        await notify.send(
            settings,
            settings.channel("games"),
            title=f"Game {n} is out tomorrow",
            message=f"Releases 2026-09-1{n}.",
            click=f"https://igdb.test/{n}",
        )
    assert delivered == []
    assert await notify.send_held(night) == 0

    assert await notify.send_held(datetime(2026, 9, 11, 7, tzinfo=UTC)) == 1
    [sent] = delivered
    assert sent["title"] == "While you were away: 2 Games notifications"
    assert (
        "• Game 1 is out tomorrow\n  Releases 2026-09-11.\n  https://igdb.test/1" in (sent["body"])
    )
    assert "Game 2" in sent["body"]
    assert db.held_notices() == {}


async def test_a_secret_is_never_returned_and_a_blank_one_keeps_it(client: AsyncClient) -> None:
    resp = await client.put("/api/settings", json={"notify_destinations": [NTFY_TOKEN]})
    assert resp.status_code == 200, resp.text
    assert "tk_secret_value" not in resp.text
    [out] = resp.json()["notify_destinations"]
    assert out["saved"] == ["token"] and out["values"]["token"] == ""

    await client.put("/api/settings", json={"notify_destinations": [out]})
    assert db.get_settings().notify_destinations[0]["values"]["token"] == "tk_secret_value"

    # A new server takes no stored token with it.
    moved = {**out, "values": {**out["values"], "server": "https://elsewhere.test"}}
    await client.put("/api/settings", json={"notify_destinations": [moved]})
    assert "token" not in db.get_settings().notify_destinations[0]["values"]


async def test_the_last_destination_cannot_be_removed(client: AsyncClient) -> None:
    await client.put("/api/settings", json=notify_to())
    resp = await client.put("/api/settings", json={"notify_destinations": []})
    assert resp.status_code == 409


async def test_a_destination_apprise_cannot_read_is_refused(client: AsyncClient) -> None:
    bad = {"id": "x", "service": "apprise", "values": {"url": "nothing://at/all"}}
    resp = await client.put("/api/settings", json={"notify_destinations": [bad]})
    assert resp.status_code == 422


async def test_a_test_sends_to_each_destination_as_the_form_holds_it(
    client: AsyncClient, delivered: list[dict[str, Any]]
) -> None:
    resp = await client.post(
        "/api/settings/notify-test",
        json={"destinations": [{**NTFY_TOKEN, "places": {"books": "shelf"}}], "category": "books"},
    )
    assert resp.json() == {"ok": True, "detail": "Sent to ntfy"}
    assert delivered[0]["url"].startswith("ntfys://tk_secret_value@ntfy.example.com/shelf?")


async def test_setup_waits_on_notifications(client: AsyncClient) -> None:
    db.update_account(setup_step="")
    refused = await client.put("/api/auth/setup", json={"step": "games"})
    assert refused.status_code == 409
    assert (await client.put("/api/auth/setup", json={"step": "notifications"})).status_code == 204
    db.save_settings(notify_to())
    assert (await client.put("/api/auth/setup", json={"step": "games"})).status_code == 204


def test_ntfy_and_its_topics_become_a_destination() -> None:
    with db.conn() as c:
        for column in (
            "ntfy_url",
            "ntfy_topic",
            "ntfy_token",
            "comics_topic",
            "screen_topic",
            "books_topic",
        ):
            c.execute(f"ALTER TABLE settings ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        c.execute(
            "UPDATE settings SET ntfy_url = 'https://ntfy.test', ntfy_topic = 'robin',"
            " ntfy_token = 'tk_x', comics_topic = 'comics'"
        )
    db.init_db()

    settings = db.get_settings()
    [ntfy] = settings.notify_destinations
    assert ntfy["values"] == {"server": "https://ntfy.test", "topic": "robin", "token": "tk_x"}
    assert ntfy["places"] == {"comics": "comics"}
    assert (settings.games_notify, settings.comics_notify, settings.books_notify) == (
        True,
        True,
        False,
    )
    with db.conn() as c:
        assert "ntfy_url" not in db._columns(c, "settings")


def test_an_install_without_ntfy_opens_setup_at_notifications() -> None:
    db.update_account(password_hash="x")
    with db.conn() as c:
        c.execute("ALTER TABLE settings ADD COLUMN ntfy_url TEXT NOT NULL DEFAULT ''")
    db.init_db()
    assert db.get_account()["setup_step"] == db.SETUP_NOTIFICATIONS


async def test_a_tba_game_that_gains_a_date_is_announced(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB},
    )
    db.upsert_games([{"igdb_id": 55, "name": "Someday", "first_release_date": None}])
    db.create_request(55)

    dated = ts(TODAY + timedelta(days=200))

    async def fake_refresh(igdb_ids: list[int]) -> dict[int, Any]:
        return {55: {"igdb_id": 55, "name": "Someday", "first_release_date": dated}}

    notices: list[dict[str, Any]] = []

    async def fake_send(settings: Any, channel: Any, **kwargs: Any) -> None:
        notices.append(kwargs)

    monkeypatch.setattr(igdb, "refresh_games", fake_refresh)
    monkeypatch.setattr(notify, "send", fake_send)

    assert await notify.notify_new_release_dates() == 1
    assert "has a release date" in notices[0]["title"]
    assert "2027-03-29" in notices[0]["message"]


async def test_a_game_still_tba_says_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB},
    )
    db.upsert_games([{"igdb_id": 55, "name": "Someday", "first_release_date": None}])
    db.create_request(55)

    async def still_tba(igdb_ids: list[int]) -> dict[int, Any]:
        return {55: {"igdb_id": 55, "name": "Someday", "first_release_date": None}}

    monkeypatch.setattr(igdb, "refresh_games", still_tba)
    monkeypatch.setattr(notify, "send", lambda *a, **k: pytest.fail("should not notify"))

    assert await notify.notify_new_release_dates() == 0


async def test_nothing_is_sent_while_notifications_are_off(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB, "games_notify": False},
    )
    monkeypatch.setattr(notify, "send", lambda *a, **k: pytest.fail("should not notify"))

    assert await notify.notify_upcoming_releases() == 0
    assert await notify.notify_new_release_dates() == 0


async def test_only_monitored_games_are_ever_notified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The games table holds everything Discover ever listed. None of it may be notified.

    Both checks read through the requests join, so a game nobody monitors is invisible to them
    however close its release is.
    """
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB},
    )
    tomorrow = ts(TODAY + timedelta(days=1))

    # Three games in the cache. Only the first is monitored.
    db.upsert_games([{"igdb_id": 1, "name": "Monitored", "first_release_date": tomorrow}])
    db.upsert_games([{"igdb_id": 2, "name": "Just Browsing", "first_release_date": tomorrow}])
    db.upsert_games([{"igdb_id": 3, "name": "Also Browsing", "first_release_date": None}])
    db.create_request(1)

    notified: list[str] = []

    async def capture(settings: Any, channel: Any, **kwargs: Any) -> None:
        notified.append(kwargs["title"])

    monkeypatch.setattr(notify, "send", capture)

    assert await notify.notify_upcoming_releases(WINDOW.now) == 1
    assert len(notified) == 1
    assert notified[0].startswith("Monitored")
    assert not any("Browsing" in title for title in notified)


async def test_the_last_notice_makes_a_game_notified_and_still_grabbed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB},
    )
    db.upsert_games(
        [
            {
                "igdb_id": 1,
                "name": "A Game",
                "first_release_date": ts(TODAY + timedelta(days=1)),
                "platforms": ["PC"],
            }
        ]
    )
    request_id = db.create_request(1)

    async def sent(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(notify, "send", sent)
    assert await notify.notify_upcoming_releases(WINDOW.now) == 1
    stored = db.get_request(request_id)
    assert stored is not None
    assert (stored["status"], bool(stored["notified_at"])) == ("notified", True)
    assert [r["id"] for r in db.waiting_requests()] == [request_id], "a grab may still follow"

    db.mark_release_notified(request_id, "2026-12-01|2026-11-30T09", done=False)
    stored = db.get_request(request_id)
    assert stored is not None
    assert (stored["status"], stored["notified_at"]) == ("monitored", None), "the date moved"


async def test_an_unmonitored_tba_game_is_never_looked_up(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The TBA sweep must not spend IGDB calls on games nobody asked about."""
    await client.put(
        "/api/settings",
        json={**notify_to(), **IGDB},
    )
    db.upsert_games([{"igdb_id": 1, "name": "Monitored TBA", "first_release_date": None}])
    db.upsert_games([{"igdb_id": 2, "name": "Unmonitored TBA", "first_release_date": None}])
    db.create_request(1)

    asked: list[list[int]] = []

    async def record(igdb_ids: list[int]) -> dict[int, Any]:
        asked.append(sorted(igdb_ids))
        return {}

    monkeypatch.setattr(igdb, "refresh_games", record)

    await notify.notify_new_release_dates()
    assert asked == [[1]], "only the monitored game should be refetched"
