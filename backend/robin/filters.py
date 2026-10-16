"""From a game title to the release names that are its own.

Pure functions, no I/O. `match_releases_for` builds the pattern a monitored game's releases are
matched with, and `wanted` decides whether a release is one. Both rest on the same fact: a
release leads with the title. Patterns are matched case insensitively.
"""

from __future__ import annotations

import re
import unicodedata

# Scene names use any of these between words. Underscore is in the class, so is space.
SEP = "[._ -]"

# What is never a game's own release: repackers, update packs, portable builds, trainers. A
# monitored game is never grabbed as one. Separators are [._ -] and not [._-]: scene names are
# dot separated, but many trackers announce space separated titles such as "Assassins Creed
# Shadows CRACKFIX-uploader", and a class without the space lets every one of those through.
EXCEPT_RELEASES = (
    r"FitGirl|DODI|ElAmigos|Xatab|KaOsKrew|Chovka|R\.G\.[._ -]?Mechanics"
    r"|Selective[._ -]Download"
    r"|[._ -](?:Update|Patch|Hotfix|Crackfix|Dirfix|Nfofix|Rerip|Repack|PORTABLE)(?:[._ -]|$)"
    r"|Incl[._ -]Update|v?\d+(?:\.\d+)*[._ -]to[._ -]v?\d+"
    r"|Trainer|DLC[._ -]?Unlocker|Language[._ -]Pack"
)


def fold_to_ascii(text: str) -> str:
    """Pokemon, not Pokemon with an accent. Release names are ASCII."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def match_releases_for(title: str) -> str:
    """Build the match_releases pattern for a game title.

    Words are joined by a required separator and the whole thing is anchored to the start of
    the release name, because a scene release always leads with the title.

    A title that is a prefix of another game still matches it, for example ^Doom
    also matches Doom.Eternal. Telling them apart needs every other game's name.
    """
    words: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            words.append("".join(buf))
            buf.clear()

    folded = fold_to_ascii(title)
    for i, ch in enumerate(folded):
        if ch.isalnum():
            buf.append(re.escape(ch))
        elif _THOUSANDS.match(folded, i):
            # Warhammer 40,000 ships as 40000, now and then as 40.000.
            buf.append("[.,]?")
        elif ch in "'’" and buf:
            # Baldur's Gate ships as both Baldurs and Baldur's.
            buf.append("'?")
        elif ch == "&":
            flush()
            words.append("(?:&|and)")
        else:
            flush()
    flush()

    if not words:
        raise ValueError("title has no usable characters")

    return "^" + f"{SEP}+".join(words) + f"(?:{SEP}|$)"


# A comma or dot between digits, with three after it, groups thousands, as in 40,000.
_THOUSANDS = re.compile(r"(?<=\d)[,.](?=\d{3}(?!\d))")


def search_term_for(title: str) -> str:
    """A title as an indexer wants it typed: no punctuation, no accents.

    Indexers match on words, and a colon or an apostrophe in the query throws results away
    that the release itself does not have either.
    """
    folded = _THOUSANDS.sub("", fold_to_ascii(title))
    # An apostrophe is dropped rather than spaced, because releases write Baldurs, not Baldur s.
    kept = "".join(ch if ch.isalnum() else "" if ch in "'’" else " " for ch in folded)
    return " ".join(kept.split())


# A release name ends with the group that put it out, after the last dash.
_GROUP = re.compile(r"-([A-Za-z0-9_.]+)\s*$")


def release_group(release: str) -> str | None:
    """Who put a release out, as the name spells it.

    None for anything that does not end in a group, which is most repacker builds: they name
    themselves in brackets in the middle instead.
    """
    found = _GROUP.search(release)
    return found.group(1) if found else None


def excluded(release: str) -> bool:
    """Whether EXCEPT_RELEASES throws this release out."""
    return re.search(EXCEPT_RELEASES, release, re.IGNORECASE) is not None


def leads(release: str, title: str) -> bool:
    """Whether a release leads with a game's title."""
    return re.search(match_releases_for(title), release, re.IGNORECASE) is not None


def wanted(release: str, title: str) -> bool:
    """Whether a release is a game's own: it leads with the title, and is not excluded."""
    return leads(release, title) and not excluded(release)
