"""TMDB, the data source for upcoming movies and TV.

Discovery only. Robin lists what is coming and shows it, and leaves fetching anything to the
arr stack. TMDB's discover endpoints filter and sort server side and page natively, so unlike
IGDB nothing is pooled here: each filtered page is asked for and cached as it is.

TMDB issues two credentials and either works. The v4 API Read Access Token is a JWT, sent as
a bearer token. The v3 API key is 32 hex characters and only works as an `api_key` query
parameter, so it shows in request URLs, which is why `db.get_settings` registers it for log
redaction. TMDB asks for attribution, which the page carries.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from robin import db, hidden, upstream

API = "https://api.themoviedb.org/3"
# TMDB's daily exports, no key needed. TMDB has no network search, so its list of every
# network is read from here and searched in Robin.
EXPORTS = "https://files.tmdb.org/p/exports"
IMAGES = "https://image.tmdb.org/t/p"
TIMEOUT = 20.0

Kind = Literal["movie", "tv"]

# A filtered page moves slowly, an hour of it is not stale. A title's detail even less so.
PAGE_TTL = 3600
DETAIL_TTL = 12 * 3600
# Genres and languages change a few times a year.
REFERENCE_TTL = 7 * 24 * 3600

# TMDB's release types as Settings names them: 2 limited and 3 theatrical, 4 digital. Type 1,
# a festival premiere, is no date anyone can see the film on, 5 is a disc and 6 a television
# airing.
RELEASE_TYPES = {"theatrical": (2, 3), "digital": (4,)}

Release = Literal["theatrical", "digital"]

# What a card says beside the date, the way a game says EA. A digital release names its
# platform instead when one is known.
RELEASE_TAGS = {2: "Cinema", 3: "Cinema", 4: "Digital"}

# TMDB's show types: 2 miniseries and 4 scripted. The rest, news, talk, reality, documentary
# and video, fill every day of the calendar and bury what was asked for.
SCRIPTED = "2|4"


class TmdbError(upstream.UpstreamError):
    pass


def image(path: str | None, size: str) -> str | None:
    return f"{IMAGES}/{size}{path}" if path else None


async def _get(settings: db.Settings, path: str, params: dict[str, Any] | None = None) -> Any:
    if not settings.tmdb_ready:
        raise upstream.NotConfigured("Screens is off. Add a TMDB key in Settings, Screens.")
    query = {"language": settings.tmdb_language, **(params or {})}
    headers = {}
    if settings.tmdb_token.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.tmdb_token}"
    else:
        query["api_key"] = settings.tmdb_token
    resp = await upstream.request(
        TmdbError,
        "TMDB",
        "GET",
        f"{API}{path}",
        timeout=TIMEOUT,
        rejected="TMDB rejected the API key",
        missing="TMDB has no such title",
        source="tmdb",
        params={k: v for k, v in query.items() if v not in (None, "")},
        headers=headers,
    )
    return resp.json()


def _key(settings: db.Settings, key: str) -> str:
    return f"tmdb:v1:{settings.tmdb_language}:{key}"


async def _cached(
    settings: db.Settings,
    key: str,
    ttl: db.Lifetime,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    return await db.remember(_key(settings, key), ttl, lambda: _get(settings, path, params))


def _check(settings: db.Settings, title: dict[str, Any], raw: dict[str, Any]) -> None:
    """Expire a title's kept detail when the list just read says otherwise, its poster or its
    date, so the detail and its dialog follow the list."""
    said = (
        image(raw.get("poster_path"), "w342"),
        raw.get("release_date") or raw.get("first_air_date") or None,
    )
    db.expire_if(
        _key(settings, f"detail:v2:{title['kind']}:{title['id']}"),
        lambda _: said != (title["poster"], title["date"]),
    )


async def ping(settings: db.Settings) -> None:
    await _get(settings, "/configuration")


async def genres(settings: db.Settings, kind: Kind) -> list[dict[str, Any]]:
    data = await _cached(settings, f"genres:{kind}", REFERENCE_TTL, f"/genre/{kind}/list")
    return [{"id": g["id"], "name": g["name"]} for g in data.get("genres", [])]


async def languages(settings: db.Settings) -> list[dict[str, Any]]:
    data = await _cached(settings, "languages", REFERENCE_TTL, "/configuration/languages")
    return sorted(
        ({"code": lang["iso_639_1"], "name": lang["english_name"]} for lang in data),
        key=lambda lang: str(lang["name"]),
    )


def kept_releases(settings: db.Settings) -> list[str]:
    """The release types Settings does not hide, every one of them while it hides them all."""
    return [n for n in RELEASE_TYPES if n not in settings.tmdb_hidden_release_types] or list(
        RELEASE_TYPES
    )


def release_types(settings: db.Settings, release: str = "") -> tuple[int, ...]:
    """TMDB's types for the page's pick, or for what Settings shows when it picks none."""
    chosen = [release] if release else kept_releases(settings)
    return tuple(t for name in chosen for t in RELEASE_TYPES.get(name, ()))


def original_languages(language: str, shown: list[str]) -> str:
    """The page's choice: empty for the languages Settings shows, `shown`, `any` for every one,
    else one code."""
    if language == "any":
        return ""
    return language or "|".join(shown)


def _rescues(settings: db.Settings, kind: str) -> bool:
    """Whether a genre or a maker always shown can bring back what Settings hides, which TMDB's
    own query cannot say, so the page is filtered here instead."""
    genres = settings.tmdb_shown_movie_genres if kind == "movie" else settings.tmdb_shown_tv_genres
    return bool(genres or settings.shown_makers.get("screens"))


def window(days: int, today: date | None = None) -> tuple[str, str]:
    start = today or datetime.now(UTC).date()
    return start.isoformat(), (start + timedelta(days=days)).isoformat()


def discover_params(
    settings: db.Settings,
    kind: Kind,
    *,
    days: int,
    page: int,
    language: str,
    release: str,
    languages: tuple[str, ...] | list[str] = (),
    sort: str = "popularity",
    today: date | None = None,
) -> dict[str, Any]:
    """The TMDB query for one filtered page. Kept apart from the call so a test can read it.

    What Settings hides is asked of TMDB where it can say it, so a page comes back full: the
    genres hidden, and every language of `languages` but those hidden, a pipe being TMDB's OR.
    A genre always shown can bring back what those would drop, so with one set they are left to
    `hidden.screen` on the answer. `release` is one type instead of those Settings shows. A list
    is ranked by popularity, most anticipated first, or by `sort` "date", soonest first.
    """
    start, end = window(days, today)
    rescued = _rescues(settings, kind)
    hidden_genres = (
        settings.tmdb_hidden_movie_genres if kind == "movie" else settings.tmdb_hidden_tv_genres
    )
    shown = [code for code in languages if code not in settings.tmdb_hidden_languages]
    params: dict[str, Any] = {
        "page": page,
        "without_genres": "" if rescued else "|".join(map(str, hidden_genres)),
        "with_original_language": original_languages(
            language, [] if rescued or not settings.tmdb_hidden_languages else shown
        ),
        "include_adult": "false",
        "sort_by": "popularity.desc"
        if sort != "date"
        else ("release_date.asc" if kind == "movie" else "first_air_date.asc"),
    }
    if kind == "movie":
        # Release dates are per region, so a film is upcoming where you are, not anywhere.
        params.update(
            {
                "region": settings.tmdb_region,
                # Out nowhere yet, by date. A film already in cinemas would otherwise come back
                # for its digital release in the window. TMDB's own Released status
                # cannot say this, contributors set it on films still weeks away.
                "primary_release_date.gte": (
                    date.fromisoformat(start) + timedelta(days=1)
                ).isoformat(),
                "release_date.gte": start,
                "release_date.lte": end,
                "with_release_type": "|".join(map(str, release_types(settings, release))),
            }
        )
    else:
        params.update(
            {
                "with_type": SCRIPTED,
                "first_air_date.gte": start,
                "first_air_date.lte": end,
            }
        )
    return params


def _title(raw: dict[str, Any], kind: Kind) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "kind": kind,
        "title": raw.get("title") or raw.get("name") or "",
        "original_title": raw.get("original_title") or raw.get("original_name") or "",
        "date": raw.get("release_date") or raw.get("first_air_date") or None,
        "poster": image(raw.get("poster_path"), "w342"),
        "backdrop": image(raw.get("backdrop_path"), "w1280"),
        "overview": raw.get("overview") or "",
        "genre_ids": raw.get("genre_ids", []),
        "language": raw.get("original_language") or "",
        "rating": raw.get("vote_average") or 0,
        "votes": raw.get("vote_count") or 0,
        "popularity": raw.get("popularity") or 0,
        "next_episode": None,
        # Cinema or Digital, for a film dated by its release in the region, and the platform a
        # digital release or a show is on, {name}.
        "release": None,
        "platform": None,
        # The favourite it comes from, by name, set by `star`.
        "favourite": None,
    }


async def discover(settings: db.Settings, kind: Kind, **filters: Any) -> dict[str, Any]:
    codes = (
        [lang["code"] for lang in await languages(settings)]
        if settings.tmdb_hidden_languages
        else []
    )
    params = discover_params(settings, kind, languages=codes, **filters)
    key = "discover:" + kind + ":" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    data = await _cached(settings, key, PAGE_TTL, f"/discover/{kind}", params)
    titles = [_title(raw, kind) for raw in data.get("results", [])]
    # A language the page picks, or any, stands in for those Settings hides.
    judged = replace(settings, tmdb_hidden_languages=[]) if filters.get("language") else settings
    titles = await unhidden(judged, titles)
    if kind == "movie":
        await _date_by_region(
            settings, titles, params["release_date.gte"], filters.get("release", "")
        )
    else:
        await _networks(settings, titles)
        # A show no network airs is one anyone added to TMDB, a fan film or a school project,
        # and never what the list is for.
        titles = [t for t in titles if t["platform"]]
    if filters.get("sort") == "date":
        titles.sort(key=lambda t: t["date"] or "9999")
    return {
        "titles": titles,
        "page": data.get("page", 1),
        "total_pages": min(int(data.get("total_pages", 1)), 500),
    }


async def search(settings: db.Settings, query: str) -> list[dict[str, Any]]:
    """Movies and shows matching `query`, as TMDB ranks them, people left out and what Settings
    hides too. A title out before this month is found, to be favourited by who made it, and is
    never monitored."""
    data = await _cached(
        settings,
        f"search:{query.casefold()}",
        PAGE_TTL,
        "/search/multi",
        {"query": query, "include_adult": "false"},
    )
    titles = [
        _title(raw, raw["media_type"])
        for raw in data.get("results", [])
        if raw.get("media_type") in ("movie", "tv")
    ]
    return await unhidden(settings, titles)


def network(show: dict[str, Any]) -> dict[str, Any] | None:
    """The network a show airs on, its first when it has several."""
    first = next(iter(show.get("networks") or []), None)
    if not first:
        return None
    return {"name": first["name"]}


async def _networks(settings: db.Settings, titles: list[dict[str, Any]]) -> None:
    """Each show's network, which the list leaves out, from the show's cached detail."""

    async def one(title: dict[str, Any]) -> None:
        try:
            raw = await show(settings, title["id"])
        except TmdbError:
            return
        _check(settings, title, raw)
        title["platform"] = network(raw)

    await asyncio.gather(*(one(t) for t in titles))


async def discover_all(settings: db.Settings, **filters: Any) -> dict[str, Any]:
    """Movies and shows on one page: the same page of each, most anticipated first, or soonest
    first for `sort` "date". Each kind is ordered across its own pages, so the two interleave
    only within a page."""
    films, shows = await asyncio.gather(
        discover(settings, "movie", **filters), discover(settings, "tv", **filters)
    )
    both = films["titles"] + shows["titles"]
    if filters.get("sort") == "date":
        titles = sorted(both, key=lambda t: t["date"] or "9999")
    else:
        titles = sorted(both, key=lambda t: -float(t["popularity"]))
    return {
        "titles": titles,
        "page": filters["page"],
        "total_pages": max(films["total_pages"], shows["total_pages"]),
    }


def _episode(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "season": raw.get("season_number"),
        "episode": raw.get("episode_number"),
        "name": raw.get("name") or "",
        "date": raw.get("air_date"),
    }


async def _date_by_region(
    settings: db.Settings, titles: list[dict[str, Any]], since: str, release: str
) -> None:
    """Each film dated and tagged by its release in the region.

    A film's own date is its first release anywhere, and where you are it can come months
    later. The one shown is the region's first release of a kept type from `since` on, the one
    that put the film in the window, so a limited run before it does not date it ahead.
    """
    types = release_types(settings, release)
    catalogue = await platforms(settings)

    async def one(title: dict[str, Any]) -> None:
        try:
            film = await movie(settings, title["id"])
        except TmdbError:
            return
        _check(settings, title, film)
        entry, _ = _regional_release(film, settings.tmdb_region, since, types)
        if entry:
            found = _release(entry, film, settings.tmdb_region, catalogue)
            title["date"] = found["date"]
            title["release"] = found["tag"]
            title["platform"] = found["platform"]

    await asyncio.gather(*(one(t) for t in titles))


def _regional_release(
    film: dict[str, Any], region: str, since: str, types: tuple[int, ...]
) -> tuple[dict[str, Any] | None, str]:
    """The region's earliest release of one of `types` from `since` on, falling back to the
    earliest of them at all, and the age rating the region gives the film.
    """
    dates = _in_region(film.get("release_dates", {}).get("results", []), region)
    local = dates.get("release_dates", [])
    rating = next((d["certification"] for d in local if d.get("certification")), "")
    kept = sorted(
        (d for d in local if d.get("release_date") and d.get("type") in types),
        key=lambda d: str(d["release_date"]),
    )
    later = [d for d in kept if d["release_date"][:10] >= since]
    return (later or kept or [None])[0], rating


def _release(
    entry: dict[str, Any], film: dict[str, Any], region: str, catalogue: list[dict[str, Any]]
) -> dict[str, Any]:
    """One release as a card tags it: its day, Cinema or Digital, and a digital one's platform."""
    digital = entry.get("type") in RELEASE_TYPES["digital"]
    return {
        "date": entry["release_date"][:10],
        "tag": RELEASE_TAGS.get(entry.get("type", 0)),
        "platform": _platform(film, region, entry.get("note") or "", catalogue)
        if digital
        else None,
    }


def _platform(
    film: dict[str, Any], region: str, note: str, catalogue: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Where a digital release is out. Its note names the platform when a contributor wrote
    one, the longest name it contains winning so Apple TV+ is not read as Apple TV. Otherwise
    the first service the region already offers the film on.
    """
    said = note.casefold()
    named = [p for p in catalogue if said and p["name"].casefold() in said]
    if named:
        return max(named, key=lambda p: len(str(p["name"])))
    offers = film.get("watch/providers", {}).get("results", {}).get(region, {})
    for kind in ("flatrate", "rent", "buy"):
        for offer in offers.get(kind, []):
            return {"name": offer["provider_name"]}
    return None


async def platforms(settings: db.Settings) -> list[dict[str, Any]]:
    """The streaming and rental services TMDB knows in the region, by name."""
    try:
        data = await _cached(
            settings,
            f"platforms:{settings.tmdb_region}",
            REFERENCE_TTL,
            "/watch/providers/movie",
            {"watch_region": settings.tmdb_region},
        )
    except TmdbError:
        return []
    return [{"name": p["provider_name"]} for p in data.get("results", [])]


def regional_releases(
    film: dict[str, Any],
    region: str,
    since: str,
    kept: list[str],
    catalogue: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Each kept release type the region has a date for from `since` on, with its earliest."""
    found = []
    for name in kept:
        entry, _ = _regional_release(film, region, since, RELEASE_TYPES[name])
        if entry and entry["release_date"][:10] >= since:
            found.append({"type": name, **_release(entry, film, region, catalogue)})
    return found


async def movie(settings: db.Settings, tmdb_id: int) -> Any:
    """A film's detail with its release dates in every region, cached."""
    return await _cached(
        settings,
        f"detail:v2:movie:{tmdb_id}",
        _detail_ttl,
        f"/movie/{tmdb_id}",
        {"append_to_response": "videos,credits,watch/providers,release_dates"},
    )


def _detail_ttl(raw: Any) -> int:
    """A title TMDB has no poster for yet is a new one, asked again as often as a page."""
    return DETAIL_TTL if isinstance(raw, dict) and raw.get("poster_path") else PAGE_TTL


async def show(settings: db.Settings, tmdb_id: int) -> Any:
    """A show's detail with its next episode, cached."""
    return await _cached(
        settings,
        f"detail:v2:tv:{tmdb_id}",
        _detail_ttl,
        f"/tv/{tmdb_id}",
        {"append_to_response": "videos,credits,watch/providers,content_ratings,external_ids"},
    )


def _in_region(entries: list[dict[str, Any]], region: str) -> dict[str, Any]:
    return next((e for e in entries if e.get("iso_3166_1") == region), {})


def _ref(raw: dict[str, Any]) -> dict[str, Any]:
    """A person, studio or network a dialog names, with the id it opens as a favourite by."""
    return {"id": raw["id"], "name": raw.get("name") or ""}


async def title(settings: db.Settings, kind: Kind, tmdb_id: int) -> dict[str, Any]:
    """One title with what the dialog shows: people, trailer, where to watch, rating."""
    if kind == "tv":
        raw = await show(settings, tmdb_id)
    else:
        raw = await movie(settings, tmdb_id)
    region = settings.tmdb_region
    base = _title({**raw, "genre_ids": []}, kind)
    credits = raw.get("credits", {})
    watch = raw.get("watch/providers", {}).get("results", {}).get(region, {})
    trailer = next(
        (
            v
            for v in raw.get("videos", {}).get("results", [])
            if v.get("site") == "YouTube" and v.get("type") == "Trailer"
        ),
        None,
    )
    if kind == "movie":
        makers = [_ref(c) for c in credits.get("crew", []) if c.get("job") == "Director"]
        today = datetime.now(UTC).date().isoformat()
        catalogue = await platforms(settings)
        entry, rating = _regional_release(raw, region, today, release_types(settings))
        when = base["date"]
        if entry:
            found = _release(entry, raw, region, catalogue)
            when, base["release"], base["platform"] = found["date"], found["tag"], found["platform"]
        releases = regional_releases(raw, region, today, kept_releases(settings), catalogue)
        companies = [_ref(c) for c in raw.get("production_companies", [])]
        runtime = raw.get("runtime") or None
        imdb = raw.get("imdb_id") or None
    else:
        makers = [_ref(c) for c in raw.get("created_by", [])]
        rating = _in_region(raw.get("content_ratings", {}).get("results", []), region).get(
            "rating", ""
        )
        upcoming = raw.get("next_episode_to_air")
        releases = []
        when = (upcoming or {}).get("air_date") or base["date"]
        base["next_episode"] = _episode(upcoming) if upcoming else None
        base["platform"] = network(raw)
        companies = [_ref(n) for n in raw.get("networks", [])]
        runtime = (raw.get("episode_run_time") or [None])[0]
        imdb = raw.get("external_ids", {}).get("imdb_id") or None
    return {
        **base,
        "date": when,
        "tagline": raw.get("tagline") or "",
        "genres": [g["name"] for g in raw.get("genres", [])],
        "status": raw.get("status") or "",
        "runtime": runtime,
        "certification": rating or None,
        "makers": makers,
        "cast": [_ref(c) for c in credits.get("cast", [])[:8]],
        "companies": companies,
        "seasons": raw.get("number_of_seasons"),
        # A film's kept release types with a date in the region from today, each one a reminder.
        "releases": releases,
        "trailer": f"https://www.youtube.com/watch?v={trailer['key']}" if trailer else None,
        "watch": {
            "stream": [p["provider_name"] for p in watch.get("flatrate", [])],
            "rent": [p["provider_name"] for p in watch.get("rent", [])],
            "buy": [p["provider_name"] for p in watch.get("buy", [])],
            "link": watch.get("link"),
        },
        "imdb": f"https://www.imdb.com/title/{imdb}" if imdb else None,
        "tmdb": f"https://www.themoviedb.org/{kind}/{tmdb_id}",
        "homepage": raw.get("homepage") or None,
    }


# ---------------------------------------------------------------- favourites

# The people Screens finds: who acts and who directs.
DEPARTMENTS = {"Acting": "Actor", "Directing": "Director"}


def _person(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": "screens",
        "kind": "person",
        "id": raw["id"],
        "name": raw.get("name") or "",
        "image": image(raw.get("profile_path"), "w342"),
        "meta": DEPARTMENTS.get(raw.get("known_for_department") or "", "Person"),
        "url": f"https://www.themoviedb.org/person/{raw['id']}",
    }


def _organisation(
    raw: dict[str, Any], kind: Literal["studio", "network"], ids: list[int] | None = None
) -> dict[str, Any]:
    """A studio or a network, by name only, never by its logo. `ids` is every id it covers."""
    return {
        "category": "screens",
        "kind": kind,
        "id": raw["id"],
        "ids": ids or [raw["id"]],
        "name": raw.get("name") or "",
        "image": None,
        "meta": "Studio" if kind == "studio" else "Network",
        "url": f"https://www.themoviedb.org/{'company' if kind == 'studio' else kind}/{raw['id']}",
    }


async def networks(settings: db.Settings) -> list[dict[str, Any]]:
    """Every network TMDB knows, {id, name}, from yesterday's export, kept a week."""

    async def fetch() -> list[dict[str, Any]]:
        day = datetime.now(UTC).date() - timedelta(days=1)
        resp = await upstream.request(
            TmdbError,
            "TMDB",
            "GET",
            f"{EXPORTS}/tv_network_ids_{day:%m_%d_%Y}.json.gz",
            timeout=TIMEOUT,
            source="tmdb",
            follow_redirects=True,
        )
        lines = gzip.decompress(resp.content).decode().splitlines()
        rows = (json.loads(line) for line in lines if line.strip())
        return [{"id": r["id"], "name": r["name"]} for r in rows if r.get("name")]

    if not settings.tmdb_ready:
        raise upstream.NotConfigured("Screens is off. Add a TMDB key in Settings, Screens.")
    found: list[dict[str, Any]] = await db.remember("tmdb:v1:networks", REFERENCE_TTL, fetch)
    return found


def _match(name: str, needle: str) -> tuple[int, int, int] | None:
    """How well `name` answers `needle`, exact first, then a prefix, then shorter. None is no."""
    folded = name.casefold()
    if needle not in folded:
        return None
    return int(folded == needle), int(folded.startswith(needle)), -len(folded)


async def search_favourites(settings: db.Settings, query: str) -> list[dict[str, Any]]:
    """People who act or direct, studios and networks matching `query`."""
    people, studios, every = await asyncio.gather(
        _cached(
            settings,
            f"search:person:{query.casefold()}",
            PAGE_TTL,
            "/search/person",
            {"query": query, "include_adult": "false"},
        ),
        _cached(
            settings,
            f"search:company:{query.casefold()}",
            PAGE_TTL,
            "/search/company",
            {"query": query},
        ),
        networks(settings),
    )
    needle = query.casefold()
    ranked = sorted(
        ((score, n) for n in every if (score := _match(n["name"], needle)) is not None),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return (
        [
            _person(p)
            for p in people.get("results", [])
            if p.get("known_for_department") in DEPARTMENTS
        ][:12]
        + _studios(studios.get("results", []))[:12]
        + [_organisation(n, "network") for _, n in ranked[:12]]
    )


def _studios(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Studios, each name once. TMDB lists one studio under several ids, Netflix under a
    handful, each crediting a share of its titles, so one favourite covers all of them.

    An exact name merges studios, so two unrelated studios sharing one name merge
    too. Match on origin country as well if that ever bites.
    """
    named: dict[str, list[dict[str, Any]]] = {}
    for raw in results:
        named.setdefault((raw.get("name") or "").casefold(), []).append(raw)
    return [
        _organisation(
            min(group, key=lambda raw: int(raw["id"])),
            "studio",
            sorted(int(raw["id"]) for raw in group),
        )
        for group in named.values()
    ]


async def _studio(settings: db.Settings, studio_id: int) -> dict[str, Any] | None:
    """One studio with every id TMDB lists its name under."""
    raw = await _cached(settings, f"company:{studio_id}", REFERENCE_TTL, f"/company/{studio_id}")
    name = raw.get("name") or ""
    found = await _cached(
        settings,
        f"search:company:{name.casefold()}",
        PAGE_TTL,
        "/search/company",
        {"query": name},
    )
    same = [
        r for r in found.get("results", []) if (r.get("name") or "").casefold() == name.casefold()
    ]
    return next(
        (s for s in _studios([raw, *same]) if studio_id in s["ids"]),
        None,
    )


async def _person_detail(settings: db.Settings, person_id: int) -> Any:
    return await _cached(
        settings,
        f"person:{person_id}",
        # Their credits are a favourite's releases, so as fresh as a page.
        PAGE_TTL,
        f"/person/{person_id}",
        {"append_to_response": "combined_credits"},
    )


async def favourite(settings: db.Settings, kind: str, source_id: int) -> dict[str, Any] | None:
    """A person, studio or network as a favourite is shown. A studio is named by the lowest
    of its ids, whichever one it was opened by."""
    if kind == "person":
        return _person(await _person_detail(settings, source_id))
    if kind == "studio":
        return await _studio(settings, source_id)
    raw = await _cached(settings, f"network:{source_id}", REFERENCE_TTL, f"/network/{source_id}")
    return _organisation(raw, "network")


async def favourite_releases(
    settings: db.Settings, kind: str, source_ids: list[int]
) -> list[dict[str, Any]]:
    """What a favourite has coming: films dated by their release in the region, and new shows.

    A person's are their acting, directing and creator credits, as `hidden.credited` reads
    them. A studio's are its films and shows under any of its ids, a network's the shows it
    airs. Shows are scripted only, as on the Screens page.
    """
    today = datetime.now(UTC).date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    # TMDB reads a pipe as OR.
    source_id = "|".join(str(i) for i in sorted(source_ids))
    if kind == "person":
        raw = await _person_detail(settings, source_ids[0])
        credits = raw.get("combined_credits", {})
        found = credits.get("cast", []) + [
            c for c in credits.get("crew", []) if c.get("job") in hidden.MAKER_JOBS
        ]
        seen: dict[tuple[str, int], dict[str, Any]] = {}
        for credit in found:
            kind_of = credit.get("media_type")
            when = credit.get("release_date") or credit.get("first_air_date") or ""
            if kind_of in ("movie", "tv") and when >= tomorrow:
                seen.setdefault((kind_of, credit["id"]), _title(credit, kind_of))
        titles = list(seen.values())
    else:
        with_key = "with_companies" if kind == "studio" else "with_networks"
        asks = [
            _cached(
                settings,
                f"favourite:tv:{with_key}:{source_id}",
                PAGE_TTL,
                "/discover/tv",
                {
                    with_key: source_id,
                    "first_air_date.gte": tomorrow,
                    "with_type": SCRIPTED,
                    "sort_by": "popularity.desc",
                },
            )
        ]
        if kind == "studio":
            asks.append(
                _cached(
                    settings,
                    f"favourite:movie:{source_id}",
                    PAGE_TTL,
                    "/discover/movie",
                    {
                        "with_companies": source_id,
                        "primary_release_date.gte": tomorrow,
                        "include_adult": "false",
                        "sort_by": "popularity.desc",
                    },
                )
            )
        answers = await asyncio.gather(*asks)
        titles = [_title(r, "tv") for r in answers[0].get("results", [])]
        if kind == "studio":
            titles += [_title(r, "movie") for r in answers[1].get("results", [])]
    films = [t for t in titles if t["kind"] == "movie"]
    await asyncio.gather(
        _date_by_region(settings, films, today.isoformat(), ""),
        _networks(settings, [t for t in titles if t["kind"] == "tv"]),
    )
    return sorted(titles, key=lambda t: (t["date"] is None, t["date"] or ""))


async def unhidden(settings: db.Settings, titles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The titles Settings leaves shown. Who made each is read from its cached detail only while
    a maker is hidden or shown, and a title TMDB cannot be asked about just now is judged
    without it."""
    if not (settings.hidden_makers.get("screens") or settings.shown_makers.get("screens")):
        return [t for t in titles if hidden.screen(settings, t)]

    async def made(title: dict[str, Any]) -> dict[str, set[int]] | None:
        try:
            raw = await (show if title["kind"] == "tv" else movie)(settings, title["id"])
        except TmdbError:
            return None
        return hidden.credited(raw)

    makers = await asyncio.gather(*(made(t) for t in titles))
    return [t for t, m in zip(titles, makers, strict=True) if hidden.screen(settings, t, m)]


async def star(
    settings: db.Settings, titles: list[dict[str, Any]], favourites: list[dict[str, Any]]
) -> None:
    """Name on each title the favourite it comes from, read from its cached detail."""
    if not favourites:
        return

    async def one(title: dict[str, Any]) -> None:
        try:
            raw = await (show if title["kind"] == "tv" else movie)(settings, title["id"])
        except TmdbError:
            return
        made = hidden.credited(raw)
        title["favourite"] = next(
            (f["name"] for f in favourites if made.get(f["kind"], set()) & set(f["ids"])),
            None,
        )

    await asyncio.gather(*(one(t) for t in titles))
