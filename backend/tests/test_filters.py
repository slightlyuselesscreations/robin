"""The regex is the product. If it is wrong, Robin grabs the wrong thing or nothing at all.

A monitored game takes a release that leads with its title and is not excluded, pinned here
against real scene and repack names. Whether it is clean is PreDB's to say, in test_requests.
"""

import re

import pytest

from robin.filters import (
    EXCEPT_RELEASES,
    match_releases_for,
    release_group,
    search_term_for,
    wanted,
)

TITLES = [
    "Cyberpunk 2077",
    "Baldur's Gate 3",
    "Grand Theft Auto VI",
    "Deus Ex: Human Revolution",
    "S.T.A.L.K.E.R. 2: Heart of Chornobyl",
    "Ori and the Will of the Wisps",
    "Tom Clancy's The Division 2",
    "Pokémon Legends: Z-A",
    "Marvel's Spider-Man 2",
    "Half-Life: Alyx",
    "Vampire: The Masquerade - Bloodlines 2",
    "Command & Conquer: Red Alert 3",
    "Assassin's Creed Shadows",
    "The First Berserker: Khazan",
    "007 First Light",
]


@pytest.mark.parametrize("title", TITLES)
def test_generated_patterns_compile(title: str) -> None:
    re.compile(match_releases_for(title))


def test_the_exclusions_compile() -> None:
    re.compile(EXCEPT_RELEASES)


@pytest.mark.parametrize(
    ("title", "release"),
    [
        ("Cyberpunk 2077", "Cyberpunk.2077.v2.1.MULTi18-RUNE"),
        ("Cyberpunk 2077", "Cyberpunk 2077 [MULTI] [DL] [Steam]"),
        # Space separated names, which is how TorrentLeech actually announces games.
        ("Cyberpunk 2077", "Cyberpunk 2077-voices38"),
        ("Assassin's Creed Shadows", "Assassin's Creed Shadows-voices38"),
        ("Assassin's Creed Shadows", "Assassins Creed Shadows-voices38"),
        ("The First Berserker: Khazan", "The First Berserker Khazan-voices38"),
        ("007 First Light", "007 First Light-voices38"),
        ("Baldur's Gate 3", "Baldurs.Gate.3.Digital.Deluxe.Edition.MULTi12-RUNE"),
        ("Vampire: The Masquerade - Bloodlines 2", "Vampire.The.Masquerade.Bloodlines.2-RUNE"),
        ("Command & Conquer: Red Alert 3", "Command.and.Conquer.Red.Alert.3-FLT"),
        ("Command & Conquer: Red Alert 3", "Command.&.Conquer.Red.Alert.3-FLT"),
        ("Baldur's Gate 3", "Baldur's.Gate.3-RUNE"),
        ("Grand Theft Auto VI", "Grand.Theft.Auto.VI-EMPRESS"),
        ("Deus Ex: Human Revolution", "Deus.Ex.Human.Revolution.Directors.Cut-PLAZA"),
        ("Half-Life: Alyx", "Half-Life.Alyx.Build.16063700-TENOKE"),
        ("Half-Life: Alyx", "Half.Life.Alyx-CODEX"),
        ("Marvel's Spider-Man 2", "Marvels.Spider-Man.2.v1.0.3-RUNE"),
        ("Pokémon Legends: Z-A", "Pokemon.Legends.Z-A.NSW-VENOM"),
        ("S.T.A.L.K.E.R. 2: Heart of Chornobyl", "S.T.A.L.K.E.R.2.Heart.of.Chornobyl-RUNE"),
        ("Ori and the Will of the Wisps", "Ori_and_the_Will_of_the_Wisps-CODEX"),
        ("Warhammer 40,000: Boltgun 2", "Warhammer 40000 Boltgun 2-RUNE"),
        ("Warhammer 40,000: Boltgun 2", "Warhammer.40000.Boltgun.2-RUNE"),
        ("Warhammer 40,000: Boltgun 2", "Warhammer.40.000.Boltgun.2-RUNE"),
    ],
)
def test_original_releases_are_accepted(title: str, release: str) -> None:
    assert wanted(release, title)


@pytest.mark.parametrize(
    ("title", "release", "why"),
    [
        ("Cyberpunk 2077", "Cyberpunk.2077.v2.1-FitGirl.Repack", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk 2077 [FitGirl Repack]", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077-DODI.Repack", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077.MULTi18.ElAmigos", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Repack.by.Xatab", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077.RePack.by.KaOsKrew", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077-R.G.Mechanics", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Update.v2.11-RUNE", "update pack"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Patch.v2.02-TENOKE", "patch"),
        ("Cyberpunk 2077", "Cyberpunk.2077.v2.0.to.v2.1.Update-RUNE", "delta update"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Hotfix.2.12-RUNE", "hotfix"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Incl.Update.4-CODEX", "update bundle"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Trainer.v2.1-FLiNG", "trainer"),
        ("Cyberpunk 2077", "Cyberpunk.2077.DLC.Unlocker-Goldberg", "unlocker"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Language.Pack.RUS-RUNE", "language pack"),
        ("Cyberpunk 2077", "Cyberpunk.2077.Crackfix-RUNE", "crackfix"),
        # Space separated names, which is how TorrentLeech actually announces games.
        ("Assassin's Creed Shadows", "Assassins Creed Shadows CRACKFIX-voices38", "crackfix"),
        ("Cyberpunk 2077", "Cyberpunk 2077 Update v2.11-voices38", "update pack"),
        ("Cyberpunk 2077", "Cyberpunk 2077 FitGirl Repack-voices38", "repacker"),
        ("Cyberpunk 2077", "Cyberpunk 2077 Repack-voices38", "repack"),
        ("Cyberpunk 2077", "Cyberpunk 2077 Language Pack RUS-voices38", "language pack"),
        ("Cyberpunk 2077", "Cyberpunk.2077.PORTABLE-RUNE", "portable build"),
        ("Baldur's Gate 3", "Some.Other.Game-RUNE", "different game"),
        ("Half-Life: Alyx", "Half-Life.2.Remastered-CODEX", "different game"),
    ],
)
def test_repacks_updates_and_strangers_are_rejected(title: str, release: str, why: str) -> None:
    assert not wanted(release, title), why


def test_title_must_be_at_the_start_of_the_release_name() -> None:
    assert not wanted("Quantum.Break.Control.Edition-CODEX", "Control")


def test_empty_title_is_refused() -> None:
    with pytest.raises(ValueError):
        match_releases_for("   ")


@pytest.mark.parametrize(
    ("release", "group"),
    [
        ("Cyberpunk.2077-RUNE", "RUNE"),
        ("Cyberpunk 2077-voices38", "voices38"),
        ("Static_Dread_The_Submarine-Razor1911", "Razor1911"),
        ("Baldurs.Gate.3.v4.1.1.4922238-GOG", "GOG"),
        ("Cyberpunk 2077 [FitGirl Repack]", None),
    ],
)
def test_the_group_is_read_off_the_end_of_the_name(release: str, group: str | None) -> None:
    """What decides whether PreDB is asked, or a group outside the scene is trusted."""
    assert release_group(release) == group


@pytest.mark.parametrize(
    ("release", "grabbed", "why"),
    [
        ("Cyberpunk.2077-RUNE", True, "its title, a chosen group"),
        ("Cyberpunk 2077-voices38", True, "space separated, a chosen group"),
        ("Cyberpunk.2077-CODEX", True, "any group"),
        ("Cyberpunk.2077.Update.v2.11-RUNE", False, "excluded"),
        ("Starfield-RUNE", False, "another game"),
    ],
)
def test_a_monitored_game_wants_its_title_and_nothing_excluded(
    release: str, grabbed: bool, why: str
) -> None:
    assert wanted(release, "Cyberpunk 2077") is grabbed, why


@pytest.mark.parametrize(
    ("title", "term"),
    [
        ("Warhammer 40,000: Boltgun 2", "Warhammer 40000 Boltgun 2"),
        ("Castlevania: Belmont's Curse", "Castlevania Belmonts Curse"),
        # Not three digits after it, so not a thousands separator.
        ("Half-Life 2: Episode 1.5", "Half Life 2 Episode 1 5"),
    ],
)
def test_the_search_term_is_typed_as_releases_are_named(title: str, term: str) -> None:
    assert search_term_for(title) == term
