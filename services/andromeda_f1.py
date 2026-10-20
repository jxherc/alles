"""formula 1 for andromeda: the current season's standings, calendar and last result.

data comes from jolpica-f1 (api.jolpi.ca), the free community successor of the ergast api. the server
asks it, never the owner's browser, and keeps the answer for ten minutes (jolpica itself caches for ten).
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime

BASE = "https://api.jolpi.ca/ergast/f1/current"
SOURCE = "jolpica-f1"
_CACHE: dict = {"at": 0.0, "data": None}
_TTL = 600

_VIEWS = {
    "standings": "drivers",
    "drivers": "drivers",
    "driver standings": "drivers",
    "drivers standings": "drivers",
    "drivers championship": "drivers",
    "championship": "drivers",
    "constructors": "teams",
    "constructor standings": "teams",
    "constructors standings": "teams",
    "constructors championship": "teams",
    "teams": "teams",
    "team standings": "teams",
    "schedule": "schedule",
    "calendar": "schedule",
    "races": "schedule",
    "race calendar": "schedule",
    "results": "results",
    "result": "results",
    "race results": "results",
    "last race": "results",
    "winner": "results",
    "next race": "next",
    "race": "next",
    "next": "next",
}
_NAME = r"(?:f1|formula 1|formula one)"


def detect(low: str) -> dict | None:
    year = re.search(r"\b(20\d\d)\b", low)
    if year and int(year[1]) != datetime.now().year:
        # another season goes to the web: the card only knows the current one
        return None
    if re.fullmatch(rf"{_NAME}(?: 20\d\d)?(?: season)?", low):
        return {"kind": "f1", "view": "next"}
    found = re.fullmatch(rf"{_NAME}(?: 20\d\d)? (.+?)(?: 20\d\d)?", low) or re.fullmatch(
        rf"(?:the )?(.+?) {_NAME}(?: race)?", low
    )
    if found and found[1] in _VIEWS:
        return {"kind": "f1", "view": _VIEWS[found[1]]}
    if re.fullmatch(
        r"(?:when is )?(?:the )?next (?:f1 |formula 1 )?(?:race|grand prix|gp)|"
        r"who won the (?:last )?(?:f1 race|grand prix)|"
        r"(?:last|latest) (?:f1 race|grand prix)(?: results?)?",
        low,
    ):
        return {
            "kind": "f1",
            "view": "results" if "won" in low or "last" in low or "latest" in low else "next",
        }
    return None


def _driver(row: dict) -> dict:
    person = row.get("Driver") or {}
    team = (row.get("Constructors") or [row.get("Constructor") or {}])[0] or {}
    return {
        "name": f"{person.get('givenName', '')} {person.get('familyName', '')}".strip(),
        "code": person.get("code") or "",
        "team": team.get("name") or "",
        "team_id": team.get("constructorId") or "",
    }


def _standings(data: dict, key: str) -> tuple[list, str]:
    lists = (data.get("MRData") or {}).get("StandingsTable", {}).get("StandingsLists") or []
    if not lists:
        return [], ""
    rows = []
    for row in lists[0].get(key) or []:
        entry = {
            "position": row.get("positionText") or row.get("position"),
            "points": row.get("points"),
            "wins": row.get("wins"),
        }
        if key == "DriverStandings":
            entry.update(_driver(row))
        else:
            team = row.get("Constructor") or {}
            entry["name"] = team.get("name") or ""
            entry["team_id"] = team.get("constructorId") or ""
        rows.append(entry)
    return rows, str(lists[0].get("round") or "")


def _race(race: dict) -> dict:
    circuit = race.get("Circuit") or {}
    place = circuit.get("Location") or {}
    sessions = []
    for key, label in (
        ("FirstPractice", "practice 1"),
        ("SecondPractice", "practice 2"),
        ("ThirdPractice", "practice 3"),
        ("SprintQualifying", "sprint qualifying"),
        ("Sprint", "sprint"),
        ("Qualifying", "qualifying"),
    ):
        if race.get(key, {}).get("date"):
            sessions.append({"name": label, "start": _stamp(race[key])})
    sessions.sort(key=lambda s: s["start"])
    return {
        "round": int(race.get("round") or 0),
        "name": race.get("raceName") or "",
        "circuit": circuit.get("circuitName") or "",
        "place": ", ".join(p for p in (place.get("locality"), place.get("country")) if p),
        "start": _stamp(race),
        "sessions": sessions,
    }


def _stamp(part: dict) -> str:
    day = part.get("date") or ""
    clock = (part.get("time") or "").rstrip("Z") or "00:00:00"
    return f"{day}T{clock}Z" if day else ""


def _results(data: dict) -> dict:
    races = (data.get("MRData") or {}).get("RaceTable", {}).get("Races") or []
    if not races:
        return {}
    race = races[0]
    rows = []
    for row in race.get("Results") or []:
        rows.append(
            {
                "position": row.get("positionText") or row.get("position"),
                **_driver(row),
                "time": (row.get("Time") or {}).get("time") or row.get("status") or "",
                "points": row.get("points"),
            }
        )
    return {**_race(race), "results": rows}


async def _fetch(get_json) -> dict:
    parts = await asyncio.gather(
        get_json(f"{BASE}/driverstandings.json"),
        get_json(f"{BASE}/constructorstandings.json"),
        get_json(f"{BASE}/races.json?limit=40"),
        get_json(f"{BASE}/last/results.json"),
        return_exceptions=True,
    )
    drivers, teams, races, last = (None if isinstance(p, BaseException) else p for p in parts)
    if all(p is None for p in (drivers, teams, races, last)):
        return {}
    out: dict = {"season": "", "missing": []}
    if drivers:
        out["drivers"], out["after_round"] = _standings(drivers, "DriverStandings")
        out["season"] = (drivers.get("MRData") or {}).get("StandingsTable", {}).get("season", "")
    else:
        out["missing"].append("drivers")
    if teams:
        out["teams"], _ = _standings(teams, "ConstructorStandings")
    else:
        out["missing"].append("teams")
    if races:
        table = (races.get("MRData") or {}).get("RaceTable") or {}
        out["schedule"] = [_race(r) for r in table.get("Races") or []]
        out["season"] = out["season"] or table.get("season", "")
    else:
        out["missing"].append("schedule")
    if last:
        out["last"] = _results(last)
    else:
        out["missing"].append("results")
    return out


async def resolve(found: dict, get_json) -> dict:
    now = time.monotonic()
    data = _CACHE["data"]
    if not data or now - _CACHE["at"] > _TTL:
        try:
            data = await _fetch(get_json)
        except Exception:
            data = {}
        if data:
            _CACHE.update(at=now, data=data)
    if not data:
        return {
            "kind": "f1",
            "view": found.get("view", "next"),
            "status": "unavailable",
            "source": SOURCE,
        }
    return {
        "kind": "f1",
        "view": found.get("view", "next"),
        "status": "ok",
        "source": SOURCE,
        **data,
    }
