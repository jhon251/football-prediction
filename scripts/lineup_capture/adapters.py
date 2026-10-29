"""DATA-004: source adapters.

ESPNAdapter: live source (accessible in this environment).  ESPN's summary
endpoint exposes rosters but NO native publication timestamp, so every record
is time_trust='capture_proxy' - the capture time is OUR evidence of
availability, never presented as the source's publication time.

MockAdapter: scripted adapter for unit tests and the dry run.  Mock records
are always labeled mock=True and are NEVER treated as real validation
samples.

Adapter interface:
  get_event(event_id) -> dict(kickoff_utc, home_team, away_team, season,
                              score_home, score_away, postponed)
  get_lineup(event_id) -> LineupState or None (None = no lineup yet / error)
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from lineup_capture.models import LineupState

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0 Safari/537.36")}

TEAM_MAP = {
    "AFC Bournemouth": "Bournemouth", "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa", "Brentford": "Brentford",
    "Brighton & Hove Albion": "Brighton", "Burnley": "Burnley",
    "Chelsea": "Chelsea", "Crystal Palace": "Crystal Palace",
    "Everton": "Everton", "Fulham": "Fulham", "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds", "Leicester City": "Leicester",
    "Liverpool": "Liverpool", "Manchester City": "Man City",
    "Manchester United": "Man United", "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest", "Southampton": "Southampton",
    "Sunderland": "Sunderland", "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham", "Wolverhampton Wanderers": "Wolves",
}


def _to_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


class ESPNAdapter:
    name = "espn"

    def __init__(self, league: str = "eng.1",
                 headers: Optional[Dict[str, str]] = None):
        self.league = league
        self.base = f"{BASE}/{league}"
        self.headers = headers or HEADERS

    def _get(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_event(self, event_id: str) -> Dict[str, Any]:
        summary = self._get(f"{self.base}/summary?event={event_id}")
        header = summary.get("header", {})
        comps = header.get("competitions") or [{}]
        comp = comps[0]
        comps2 = comp.get("competitors", [])
        sides = {}
        for t in comps2:
            side = t.get("homeAway")
            name = (t.get("team") or {}).get("displayName", "")
            sides[side] = TEAM_MAP.get(name, name)
        kickoff_raw = comp.get("date") or ""
        kickoff = _to_utc(kickoff_raw) if kickoff_raw else None
        season_year = str((header.get("season") or {}).get("year", ""))
        return {
            "event_id": event_id,
            "league": self.league,
            "season": season_year,
            "kickoff_utc": kickoff,
            "home_team": sides.get("home", ""),
            "away_team": sides.get("away", ""),
            "postponed": False,
        }

    def get_lineup(self, event_id: str) -> Optional[LineupState]:
        """Returns the CURRENT observed lineup state (capture-proxy timing).
        ESPN provides no native publication timestamp -> source_event_time=None,
        time_trust='capture_proxy'.  If rosters are empty (not yet published or
        only populated post-match), returns None (outcome: no_lineup_yet or
        post_kickoff is decided by the pipeline using capture time)."""
        ev = self.get_event(event_id)
        summary = self._get(f"{self.base}/summary?event={event_id}")
        rosters = summary.get("rosters") or []
        if not rosters:
            return None
        home_xi: List[str] = []
        away_xi: List[str] = []
        home_formation = away_formation = None
        for team in rosters:
            is_home = team.get("homeAway") == "home"
            xi = home_xi if is_home else away_xi
            if is_home:
                home_formation = team.get("formation")
            else:
                away_formation = team.get("formation")
            for p in team.get("roster", []):
                if p.get("starter"):
                    xi.append(p["athlete"]["displayName"])
        # P0-1: a roster STRUCTURE without any published starters is NOT a
        # lineup.  Treat starters==0 as no_lineup_yet/UNKNOWN - never emit an
        # empty-XI state (which the runner would otherwise record as a
        # lineup_captured/time_safe capture).
        if not home_xi or not away_xi:
            return None
        league_tag = self.league.replace(".", "-")
        return LineupState(
            event_id=event_id, match_id=f"{league_tag}-{ev['season']}-{event_id}",
            season=ev["season"], league=self.league, kickoff_utc=ev["kickoff_utc"],
            home_team=ev["home_team"], away_team=ev["away_team"],
            home_xi=home_xi, away_xi=away_xi,
            home_formation=home_formation, away_formation=away_formation,
            source=self.name, source_event_time=None,
            time_trust="capture_proxy", mock=False,
        )


class MockAdapter:
    """Scripted adapter for tests/dry-run.  mock=True on every record."""

    name = "mock"

    def __init__(self, script: Dict[str, Any]):
        self.script = script  # {event_id: {kickoff, home, away, states:[...],
        #                                  errors:[{after_seconds, message}]}}

    def get_event(self, event_id: str) -> Dict[str, Any]:
        spec = self.script[event_id]
        elapsed = (datetime.now(timezone.utc) - spec.get("started_at"))
        elapsed_s = elapsed.total_seconds()
        kickoff = spec["kickoff"]
        for upd in spec.get("kickoff_updates", []):
            if upd["after_seconds"] <= elapsed_s:
                kickoff = upd["kickoff"]
        postponed = bool(spec.get("postponed", False))
        for upd in spec.get("postponed_updates", []):
            if upd["after_seconds"] <= elapsed_s:
                postponed = bool(upd["postponed"])
        return {
            "event_id": event_id,
            "season": spec.get("season", "2026-27"),
            "kickoff_utc": kickoff,
            "home_team": spec["home"],
            "away_team": spec["away"],
            "postponed": postponed,
        }

    def get_lineup(self, event_id: str) -> Optional[LineupState]:
        spec = self.script[event_id]
        ev = self.get_event(event_id)
        elapsed = (datetime.now(timezone.utc) - spec.get("started_at"))
        elapsed_s = elapsed.total_seconds()
        for err in spec.get("errors", []):
            active = err["after_seconds"] <= elapsed_s
            if "until_seconds" in err:
                active = active and elapsed_s < err["until_seconds"]
            if active:
                raise RuntimeError(err["message"])
        state = None
        for candidate in spec.get("states", []):
            if candidate["at_seconds"] <= elapsed_s:
                state = candidate
        if state is None:
            return None
        return LineupState(
            event_id=event_id, match_id=spec.get("match_id", f"epl-{event_id}"),
            season=ev["season"], kickoff_utc=ev["kickoff_utc"],
            home_team=ev["home_team"], away_team=ev["away_team"],
            home_xi=state["home_xi"], away_xi=state["away_xi"],
            home_formation=state.get("home_formation"),
            away_formation=state.get("away_formation"),
            source=self.name, source_event_time=state.get("source_event_time"),
            time_trust=state.get("time_trust", "capture_proxy"), mock=True,
        )


def build_mock_script(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """specs: list of {event_id, kickoff, home, away, states, errors}."""
    script: Dict[str, Any] = {}
    started = datetime.now(timezone.utc)
    for spec in specs:
        item = dict(spec)
        item["started_at"] = started
        script[item["event_id"]] = item
    return script
