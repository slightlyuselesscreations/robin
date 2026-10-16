"""What Discover shows and in what order.

Robin lists PC and PlayStation, Xbox and Nintendo releases, and only things still to come, so
the rules that decide membership and order are worth pinning.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from robin import db, igdb


def game(**overrides: Any) -> dict[str, Any]:
    """A normalised game. A date passed here is an exact day unless stated otherwise."""
    base: dict[str, Any] = {
        "id": 1,
        "name": "A Game",
        "platforms": [{"id": 6, "abbreviation": "PC"}],
    }
    raw = {**base, **overrides}
    if raw.get("first_release_date") and "release_dates" not in raw:
        raw["release_dates"] = [
            {
                "date": raw["first_release_date"],
                "date_format": 0,
                "platform": 6,
                "human": "Jun 01, 2026",
            }
        ]
    return igdb.normalise(raw)


def ts(year: int, month: int = 6, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp())


THIS_YEAR = datetime.now(UTC).year
SINCE = igdb._tomorrow()
DAY = 86400


def test_a_game_on_consoles_alone_is_shown() -> None:
    console_only = game(platforms=[{"id": 167, "abbreviation": "PS5"}, {"id": 130}])
    assert igdb._is_shown(console_only, SINCE) is True


def test_a_game_on_no_shown_platform_is_not() -> None:
    mobile = game(platforms=[{"id": 34, "abbreviation": "Android"}])
    assert igdb._is_shown(mobile, SINCE) is False
    n64 = game(platforms=[{"id": 4, "abbreviation": "N64"}])
    assert igdb._is_shown(n64, SINCE) is False, "cancelled on an old console, TBA forever"


def test_a_port_is_listed_once_keeping_the_pc_one() -> None:
    switch = game(id=1, name="A Game", platforms=[{"id": 130, "abbreviation": "Switch"}])
    pc = game(id=2, name="A game!", platforms=[{"id": 6, "abbreviation": "PC"}])
    other = game(id=3, name="Another Game")
    assert [g["igdb_id"] for g in igdb._once([switch, other, pc])] == [3, 2]


def test_a_multiplatform_game_with_pc_is_shown() -> None:
    multi = game(platforms=[{"id": 167}, {"id": 6}, {"id": 130}], first_release_date=SINCE)
    assert igdb._is_shown(multi, SINCE) is True


def test_a_game_with_no_platform_data_is_not_shown() -> None:
    assert igdb._is_shown(game(platforms=[]), SINCE) is False


@pytest.mark.parametrize(
    ("released", "shown", "why"),
    [
        (None, True, "TBA"),
        (SINCE, True, "tomorrow"),
        (SINCE + 30 * DAY, True, "next month"),
        (ts(THIS_YEAR + 2), True, "future"),
        (SINCE - DAY, False, "today"),
        (SINCE - 60 * DAY, False, "earlier this year"),
        (ts(2015), False, "long past"),
    ],
)
def test_only_from_tomorrow_on_or_undated(released: int | None, shown: bool, why: str) -> None:
    assert igdb._is_shown(game(first_release_date=released), SINCE) is shown, why


@pytest.mark.parametrize(
    ("platforms", "families"),
    [
        ([6], ["pc"]),
        ([508], ["nintendo"]),
        ([48, 167], ["playstation"]),
        ([167, 6], ["pc", "playstation"]),
        ([6, 167, 169], []),
        ([6, 167, 169, 130], []),
        ([34], []),
    ],
)
def test_a_game_on_two_families_or_fewer_is_tagged_with_them(
    platforms: list[int], families: list[str]
) -> None:
    assert game(platforms=[{"id": p} for p in platforms])["exclusive"] == families


def test_release_order_is_soonest_first_with_undated_last() -> None:
    games = [
        game(first_release_date=None),
        game(first_release_date=ts(THIS_YEAR + 1)),
        game(first_release_date=ts(THIS_YEAR)),
        game(first_release_date=None),
    ]
    ordered = sorted(games, key=igdb._sort_key)
    assert [g["first_release_date"] for g in ordered] == [
        ts(THIS_YEAR),
        ts(THIS_YEAR + 1),
        None,
        None,
    ]


def test_stale_metadata_is_refetched_rather_than_shown_with_gaps() -> None:
    """A row stored before a metadata field existed must miss, not serve a half filled game."""
    db.upsert_games([{"igdb_id": 55, "name": "Old Row", "extra": {"developers": ["Someone"]}}])
    assert db.get_detailed_game(55) is None

    db.upsert_games([{"igdb_id": 55, "name": "Old Row", "extra": {"v": db.EXTRA_VERSION}}])
    assert db.get_detailed_game(55) is not None


def test_a_trailer_is_picked_from_the_videos() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "game_modes": [{"name": "Single player"}],
        "videos": [
            {"name": "Teaser", "video_id": "aaa"},
            {"name": "Gameplay Trailer", "video_id": "bbb"},
        ],
    }
    trailer = igdb.normalise(raw, detailed=True)["extra"]["trailer"]
    assert trailer == {
        "name": "Gameplay Trailer",
        "url": "https://www.youtube.com/watch?v=bbb",
    }, "a video naming itself a trailer wins over a teaser"


def test_the_only_video_is_used_when_none_says_trailer() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "game_modes": [],
        "videos": [{"name": "Teaser", "video_id": "z"}],
    }
    assert igdb.normalise(raw, detailed=True)["extra"]["trailer"]["name"] == "Teaser"


def test_a_list_row_never_passes_for_a_detailed_one() -> None:
    """LIST_FIELDS asks for the companies too, for favourites. A Discover row tagged detailed
    would overwrite the stored metadata and serve a dialog with none of it."""
    raw = {"id": 1, "name": "A Game", "involved_companies": [{"company": 70}]}
    assert igdb.normalise(raw)["extra"] == {}
    db.upsert_games([igdb.normalise(raw)])
    assert db.get_detailed_game(1) is None


def test_no_videos_means_no_trailer() -> None:
    raw = {"id": 1, "name": "A Game", "game_modes": [{"name": "Single player"}]}
    assert igdb.normalise(raw, detailed=True)["extra"]["trailer"] is None


@pytest.mark.parametrize(
    ("date_format", "kept", "why"),
    [
        (0, True, "an actual day"),
        (1, False, "month only, IGDB stores the first of it"),
        (2, False, "year only, IGDB stores 31 December"),
        (3, False, "Q1"),
        (4, False, "Q2, IGDB stores 30 June"),
        (6, False, "Q4"),
        (7, False, "TBD"),
        (None, False, "no format to judge it by"),
    ],
)
def test_only_an_exact_day_counts_as_a_release_date(
    date_format: int | None, kept: bool, why: str
) -> None:
    raw: dict[str, Any] = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1782777600,
        "release_dates": (
            [{"date": 1782777600, "date_format": date_format, "platform": 6}]
            if date_format is not None
            else []
        ),
    }
    got = igdb.normalise(raw)["first_release_date"]
    assert (got is not None) is kept, why
    if kept:
        assert got == 1782777600


def test_the_pc_entry_decides_when_platforms_disagree() -> None:
    """A vague console date must not discard a firm PC one."""
    raw = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1782777600,
        "release_dates": [
            {"date": 1782777600, "date_format": 2, "platform": 48},
            {"date": 1782777600, "date_format": 0, "platform": 6},
        ],
    }
    assert igdb.normalise(raw)["first_release_date"] == 1782777600


def test_a_vague_date_is_kept_as_wording_even_though_it_is_undated() -> None:
    """The card can say Q2 2026 while the game still sorts and notifies as undated."""
    raw = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1782777600,
        "release_dates": [
            {"date": 1782777600, "date_format": 4, "platform": 6, "human": "Q2 2026"}
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] is None
    assert game["release_label"] == "Q2 2026"


def test_a_game_with_no_date_at_all_has_no_wording() -> None:
    assert igdb.normalise({"id": 1, "name": "A Game"})["release_label"] is None


def test_a_vague_game_is_shown_as_tba_rather_than_hidden() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "platforms": [{"id": 6}],
        "first_release_date": 1782777600,
        "release_dates": [{"date": 1782777600, "date_format": 4, "platform": 6}],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] is None
    assert igdb._is_shown(game, SINCE) is True


def test_the_pc_date_wins_over_an_earlier_console_one() -> None:
    """first_release_date is the earliest across platforms, which is not Robin's business."""
    raw = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1830211200,
        "release_dates": [
            {"date": 1830211200, "date_format": 0, "platform": 508, "human": "Dec 31, 2027"},
            {"date_format": 7, "platform": 6, "human": "TBD"},
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] is None, "the PC version has no date"
    assert game["release_label"] is None, "TBD is not worth showing"


def test_a_dated_pc_release_is_used_even_when_a_console_shipped_first() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1700000000,
        "release_dates": [
            {"date": 1700000000, "date_format": 0, "platform": 48, "human": "Nov 14, 2023"},
            {"date": 1830211200, "date_format": 0, "platform": 6, "human": "Dec 31, 2027"},
        ],
    }
    assert igdb.normalise(raw)["first_release_date"] == 1830211200


def test_a_console_date_is_used_when_igdb_lists_no_pc_entry() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "first_release_date": 1700000000,
        "release_dates": [
            {"date": 1700000000, "date_format": 0, "platform": 48, "human": "Nov 14, 2023"}
        ],
    }
    assert igdb.normalise(raw)["first_release_date"] == 1700000000


@pytest.mark.parametrize("fields", [igdb.LIST_FIELDS, igdb.GAME_FIELDS])
def test_both_field_sets_ask_for_what_the_release_rule_reads(fields: str) -> None:
    """Without the platform the PC entry cannot be found, and a console date slips through."""
    for needed in (
        "release_dates.date",
        "release_dates.date_format",
        "release_dates.platform",
        "release_dates.status.name",
    ):
        assert needed in fields


def pc(when: int | None, status: str | None, date_format: int = 0) -> dict[str, Any]:
    entry: dict[str, Any] = {"date": when, "date_format": date_format, "platform": 6}
    if status is not None:
        entry["status"] = {"name": status}
    return entry


def test_the_release_status_is_carried_through() -> None:
    raw = {"id": 1, "name": "A Game", "release_dates": [pc(ts(THIS_YEAR + 1), "Early Access")]}
    assert igdb.normalise(raw)["release_status"] == "Early Access"


def test_a_game_igdb_says_nothing_about_has_no_status() -> None:
    assert igdb.normalise({"id": 1, "name": "A Game"})["release_status"] is None


def test_early_access_is_used_while_the_full_release_has_no_date() -> None:
    """The full release is the one that counts, but a TBD entry gives the user nothing."""
    raw = {
        "id": 1,
        "name": "A Game",
        "release_dates": [
            pc(None, "Full Release", date_format=7),
            pc(ts(THIS_YEAR + 1), "Early Access"),
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] == ts(THIS_YEAR + 1)
    assert game["release_status"] == "Early Access"


def test_a_passed_early_access_gives_way_to_the_full_release_still_ahead() -> None:
    """A game already in Early Access is worth showing for the 1.0 that is still to come."""
    raw = {
        "id": 1,
        "name": "A Game",
        "release_dates": [
            pc(ts(THIS_YEAR - 2), "Early Access"),
            pc(ts(THIS_YEAR + 1), "Full Release"),
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] == ts(THIS_YEAR + 1)
    assert game["release_status"] == "Full Release"


def test_a_full_release_wins_over_an_earlier_early_access() -> None:
    """Early Access gives way the moment IGDB carries a full date, however much later it is."""
    raw = {
        "id": 1,
        "name": "A Game",
        "release_dates": [
            pc(ts(THIS_YEAR + 2), "Full Release"),
            pc(ts(THIS_YEAR + 1), "Early Access"),
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] == ts(THIS_YEAR + 2)
    assert game["release_status"] == "Full Release"


def test_paid_advanced_access_is_not_a_release() -> None:
    """An edition that unlocks days early is not the date the world gets the game."""
    raw = {
        "id": 1,
        "name": "A Game",
        "release_dates": [
            pc(ts(THIS_YEAR + 1, 2, 18), "Advanced Access"),
            pc(ts(THIS_YEAR + 1, 2, 23), "Full Release"),
        ],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] == ts(THIS_YEAR + 1, 2, 23)
    assert game["release_status"] == "Full Release"


@pytest.mark.parametrize("status", ["Advanced Access", "Alpha", "Beta", "Cancelled"])
def test_a_game_with_nothing_but_an_unusable_release_is_undated(status: str) -> None:
    raw = {"id": 1, "name": "A Game", "release_dates": [pc(ts(THIS_YEAR + 1), status)]}
    game = igdb.normalise(raw)
    assert game["first_release_date"] is None
    assert game["release_status"] is None


def test_an_entry_igdb_gave_no_status_counts_as_a_plain_release() -> None:
    raw = {"id": 1, "name": "A Game", "release_dates": [pc(ts(THIS_YEAR + 1), None)]}
    assert igdb.normalise(raw)["first_release_date"] == ts(THIS_YEAR + 1)


def test_a_status_survives_a_date_too_vague_to_use() -> None:
    raw = {
        "id": 1,
        "name": "A Game",
        "release_dates": [pc(ts(THIS_YEAR + 1), "Early Access", date_format=4)],
    }
    game = igdb.normalise(raw)
    assert game["first_release_date"] is None
    assert game["release_status"] == "Early Access"


@pytest.mark.parametrize("fields", [igdb.LIST_FIELDS, igdb.GAME_FIELDS])
def test_both_field_sets_ask_for_what_popularity_is_built_from(fields: str) -> None:
    """Popularity ranks the Hot page. Drop either field and a game silently ranks at zero."""
    assert "total_rating_count" in fields
    assert "hypes" in fields


def test_popularity_survives_a_round_trip_through_the_games_table() -> None:
    raw = {"id": 7, "name": "A Game", "total_rating_count": 120, "hypes": 30}
    game = igdb.normalise(raw)
    assert game["popularity"] == 150

    db.upsert_games([game])
    stored = db.get_game(7)
    assert stored is not None
    assert stored["popularity"] == 150


def test_a_game_igdb_has_no_counts_for_ranks_at_zero() -> None:
    db.upsert_games([igdb.normalise({"id": 8, "name": "Obscure"})])
    stored = db.get_game(8)
    assert stored is not None
    assert stored["popularity"] == 0


def test_the_page_picks_a_platform_among_what_settings_shows() -> None:
    assert igdb.platforms([]) == igdb.SHOWN_PLATFORMS, "hiding none shows all"
    assert igdb.platforms(["playstation", "nintendo"]) == {6, 49, 169}
    assert igdb.platforms(["playstation", "xbox", "nintendo"], "nintendo") == {130, 508}
    switch = game(platforms=[{"id": 130}])
    assert (
        igdb._is_shown(switch, SINCE, igdb.platforms(["playstation", "xbox", "nintendo"])) is False
    )


async def test_a_game_not_on_steam_joins_the_pool_by_its_hype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most Wishlisted Upcoming is Steam's, so a console game only comes in through hype."""
    soon = ts(THIS_YEAR + 1)
    steam = {"id": 1, "name": "On Steam", "platforms": [{"id": 6}], "first_release_date": soon}
    console = {
        "id": 2,
        "name": "Not on Steam",
        "platforms": [{"id": 167}],
        "first_release_date": soon,
    }

    async def popularity_type() -> int:
        return 10

    async def query(endpoint: str, body: str) -> list[dict[str, Any]]:
        if endpoint == "popularity_primitives":
            return [{"game_id": 1, "value": 1.0}]
        return [steam] if "where id = (1)" in body else [console, steam]

    monkeypatch.setattr(igdb, "discover_popularity_type", popularity_type)
    monkeypatch.setattr(igdb, "query", query)
    assert await igdb._discover_pool(igdb.SHOWN_PLATFORMS) == [1, 2]
    assert await igdb._discover_pool(igdb.platforms(["playstation", "xbox", "nintendo"])) == [1]
