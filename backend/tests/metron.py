"""A Metron answering from a few series, issues, creators and publishers, for every comics
test. It filters as Metron does: by week, number, series, creator, publisher and Comic Vine id."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from robin import comics
from tests.conftest import stub_http

KEY = "metron-key-1"

PUBLISHERS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "Marvel", "cv_id": 31},
    2: {"id": 2, "name": "DC Comics", "cv_id": 10},
    9999: {"id": 9999, "name": "Some Manga House", "cv_id": None},
}

CREATORS: dict[int, dict[str, Any]] = {
    41: {
        "id": 41,
        "name": "Phillip Kennedy Johnson",
        "image": "https://static.metron.test/41.jpg",
        "cv_id": 9041,
    },
    42: {"id": 42, "name": "ScieTronc", "image": None},
}


def series(series_id: int, name: str, publisher: int, cv_id: int | None = None) -> dict[str, Any]:
    return {
        "id": series_id,
        "name": name,
        "year_began": 2026,
        "issue_count": 2,
        "publisher": {k: PUBLISHERS[publisher][k] for k in ("id", "name")},
        "cv_id": cv_id,
    }


def issue(
    issue_id: int, series_id: int, number: str = "1", day: date | None = None, **extra: Any
) -> dict[str, Any]:
    """One issue, with what its detail says. `credits` is a list of (creator id, role)."""
    return {"id": issue_id, "series_id": series_id, "number": number, "day": day, **extra}


@dataclass
class Metron:
    series: dict[int, dict[str, Any]]
    issues: list[dict[str, Any]]
    asked: list[httpx.Request] = field(default_factory=list)
    refuse: int | None = None

    def _row(self, found: dict[str, Any]) -> dict[str, Any]:
        named = self.series[found["series_id"]]
        return {
            "id": found["id"],
            "series": {"id": named["id"], "name": named["name"], "volume": 1, "year_began": 2026},
            "number": found["number"],
            "issue": f"{named['name']} (2026) #{found['number']}",
            "cover_date": "2026-12-01",
            "store_date": found["day"].isoformat() if found["day"] else None,
            "image": f"https://static.metron.test/{found['id']}.jpg",
        }

    def _detail(self, found: dict[str, Any]) -> dict[str, Any]:
        named = self.series[found["series_id"]]
        credits = [
            {
                "id": creator,
                "creator": CREATORS[creator]["name"],
                "role": [{"id": 1, "name": role}],
            }
            for creator, role in found.get("credits", [])
        ]
        return {
            **self._row(found),
            "publisher": named["publisher"],
            "series": {"id": named["id"], "name": named["name"], "year_began": 2026},
            "title": "",
            "name": [found.get("story", "Into the Night")],
            "desc": "<p>A young Peter Parker is <em>transformed</em> &amp; more.</p>",
            "credits": credits,
            "arcs": [{"id": 1, "name": "Midnight"}],
            "characters": [{"id": 2, "name": "Spider-Man"}],
            "teams": [],
            "variants": [{"name": "A"}, {"name": "B"}],
            "cv_id": found.get("cv_id"),
        }

    def _issues(self, params: httpx.QueryParams) -> list[dict[str, Any]]:
        found = self.issues
        if "cv_id" in params:
            found = [i for i in found if i.get("cv_id") == int(params["cv_id"])]
        if "number" in params:
            found = [i for i in found if i["number"] == params["number"]]
        if "series_id" in params:
            found = [i for i in found if i["series_id"] == int(params["series_id"])]
        if "publisher_id" in params:
            pid = int(params["publisher_id"])
            found = [i for i in found if self.series[i["series_id"]]["publisher"]["id"] == pid]
        if "creator_id" in params:
            cid = int(params["creator_id"])
            found = [i for i in found if cid in [c for c, _ in i.get("credits", [])]]
        after = params.get("store_date_range_after")
        before = params.get("store_date_range_before")
        if after:
            found = [i for i in found if i["day"] and i["day"].isoformat() >= after]
        if before:
            found = [i for i in found if i["day"] and i["day"].isoformat() <= before]
        return [self._row(i) for i in found]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "metron.cloud":
            raise AssertionError(f"only Metron is asked: {request.url}")
        self.asked.append(request)
        if self.refuse:
            return httpx.Response(self.refuse)
        path, params = request.url.path, request.url.params
        parts = path.strip("/").split("/")
        if path == "/api/issue/":
            return page(self._issues(params))
        if parts[:2] == ["api", "issue"]:
            found = [i for i in self.issues if i["id"] == int(parts[2])]
            return httpx.Response(200, json=self._detail(found[0])) if found else missing()
        if path == "/api/series/":
            found = list(self.series.values())
            if "cv_id" in params:
                found = [s for s in found if s.get("cv_id") == int(params["cv_id"])]
            if "name" in params:
                found = [s for s in found if params["name"].casefold() in s["name"].casefold()]
            return page([{**s, "series": f"{s['name']} (2026)", "name": None} for s in found])
        if parts[:2] == ["api", "series"]:
            found_series = self.series.get(int(parts[2]))
            return httpx.Response(200, json=found_series) if found_series else missing()
        for kind, table in (("creator", CREATORS), ("publisher", PUBLISHERS)):
            if path == f"/api/{kind}/":
                rows = list(table.values())
                if "cv_id" in params:
                    rows = [r for r in rows if r.get("cv_id") == int(params["cv_id"])]
                if "name" in params:
                    rows = [r for r in rows if params["name"].casefold() in r["name"].casefold()]
                return page(rows)
            if parts[:2] == ["api", kind]:
                row = table.get(int(parts[2]))
                return httpx.Response(200, json=row) if row else missing()
        raise AssertionError(str(request.url))


def page(results: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(
        200, json={"count": len(results), "next": None, "previous": None, "results": results}
    )


def missing() -> httpx.Response:
    return httpx.Response(404, json={"detail": "Not found."})


def this_week() -> date:
    return comics.week_of(datetime.now(UTC).date())


def week_of_series() -> dict[int, dict[str, Any]]:
    return {
        100: series(100, "Midnight Spider-Man", 1, cv_id=5100),
        200: series(200, "The Demon", 2, cv_id=5200),
        300: series(300, "Chotto Kiiteyo! Miyazawa-san", 9999),
    }


def week_of_issues(week: date) -> list[dict[str, Any]]:
    """Three #1s this week, one writer credited, and the second issue of the first a week on."""
    return [
        issue(1, 100, day=week, credits=[(41, "Writer"), (42, "Artist")], cv_id=9001),
        issue(2, 200, day=week, credits=[(42, "Artist")], cv_id=9002),
        issue(3, 300, day=week, cv_id=9003),
        issue(4, 100, "2", day=week + timedelta(days=7), credits=[(41, "Writer")], cv_id=9004),
    ]


def stub(
    monkeypatch: pytest.MonkeyPatch,
    week: date | None = None,
    *,
    series_of: dict[int, dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
) -> Metron:
    """Metron answering a week of issues, by default this one, everything else refused."""
    week = week or this_week()
    metron = Metron(
        series_of or week_of_series(), week_of_issues(week) if issues is None else issues
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return metron.handler(request)

    stub_http(monkeypatch, handler)
    return metron
