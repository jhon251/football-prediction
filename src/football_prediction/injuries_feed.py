# -*- coding: utf-8 -*-
"""API-Football (api-sports.io v3) adapter: pre-match injury intel.

PURPOSE: surface each team's absentees (injuries + suspensions) for the
selected fixture as an EXTERNAL SIGNAL. Per the frozen pipeline's P3
invariant this can never modify probabilities: the signal enters
`external_signals`, gets gated by football_prediction.signals to
AVAILABLE_NOT_VALIDATED at best, and is displayed as intel only.

Source note (2026-10-25): football-data.org was tried first but its v4
API has no injuries endpoint on ANY tier (verified empirically: 404 on
both plausible routes — and the account's fixtures access works, so it
was not an auth issue). API-Football's free plan (100 requests/day,
x-apisports-key header) exposes a dedicated /injuries endpoint; each
capture costs 2 requests (fixture lookup + injuries).

Matched to ESPN fixtures by kickoff (+/-15 min) and fuzzy team names —
same normalization and scoring helpers as odds_api.

Nothing is requested unless a key is configured (env API_FOOTBALL_KEY or
config/api_football.key, gitignored).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from football_prediction.odds_api import _pair_score
from football_prediction.odds_feed import parse_espn_date

BASE = "https://v3.football.api-sports.io"

ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = ROOT / "config" / "api_football.key"

# ESPN league code -> API-Football league id (free-tier covered leagues)
LEAGUES = {
    "esp.1": 140,   # La Liga
    "eng.1": 39,    # Premier League
    "fra.1": 61,    # Ligue 1
    "ita.1": 135,   # Serie A
    "ned.1": 88,    # Eredivisie
    "bund.1": 78,   # Bundesliga
}

# Free-plan reality (verified 2026-10-25): /fixtures refuses the CURRENT
# season when filtered by league ("try from 2022 to 2024") and refuses the
# `last` parameter, but date-only queries across all leagues work fine
# (~1200 fixtures/day). So we query by date and filter by league id
# client-side instead of passing league+season to the API.
_LEAGUE_IDS = set(LEAGUES.values())

SIGNAL_SOURCE = "api-football:injuries"

_KICKOFF_TOLERANCE_SECONDS = 15 * 60
_MIN_AVG_RATIO = 0.62
_MIN_ONE_TEAM_RATIO = 0.82


class InjuriesApiError(RuntimeError):
    """API-Football request failed (bad key, quota exhausted, network)."""


def get_key() -> Optional[str]:
    env = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    return None


def is_configured() -> bool:
    return get_key() is not None


def _fetch(path: str, key: str, params: dict | None = None,
           timeout: int = 20) -> Any:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    # API-Football usually answers HTTP 200 with an `errors` object; a
    # short bounded retry covers transient transport failures
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            url, headers={"x-apisports-key": key,
                          "User-Agent": "football_prediction/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            last_err = InjuriesApiError(
                f"api-football HTTP {exc.code}: {detail}")
            if attempt < 2:
                time.sleep(1.5)
                continue
            raise last_err from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = InjuriesApiError(f"api-football request failed: {exc}")
            if attempt < 2:
                time.sleep(1.5)
                continue
            raise last_err from exc
        errors = data.get("errors")
        if errors:
            raise InjuriesApiError(f"api-football errors: {errors}")
        return data
    raise last_err or InjuriesApiError("api-football request failed")


def match_fixture(fixtures: list[dict], home: str, away: str,
                  kickoff: Optional[datetime]) -> Optional[dict]:
    """Pick the API-Football fixture for an ESPN event, else None."""
    if kickoff is None:
        return None
    best: tuple[float, float, dict] | None = None
    for fx in fixtures or []:
        ft = parse_espn_date((fx.get("fixture") or {}).get("date") or "")
        if ft is None or abs((ft - kickoff).total_seconds()) > _KICKOFF_TOLERANCE_SECONDS:
            continue
        teams = fx.get("teams") or {}
        avg, one_team = _pair_score(
            str((teams.get("home") or {}).get("name") or ""),
            str((teams.get("away") or {}).get("name") or ""),
            home, away)
        if best is None or avg > best[0]:
            best = (avg, one_team, fx)
    if best is None:
        return None
    avg, one_team, fx = best
    if avg >= _MIN_AVG_RATIO and one_team >= _MIN_ONE_TEAM_RATIO:
        return fx
    return None


def _team_side(item: dict, fx: dict) -> Optional[str]:
    team_name = str((item.get("team") or {}).get("name") or "")
    teams = fx.get("teams") or {}
    home_name = str((teams.get("home") or {}).get("name") or "")
    away_name = str((teams.get("away") or {}).get("name") or "")
    if team_name and team_name in (home_name, away_name):
        return "home" if team_name == home_name else "away"
    _, one_h = _pair_score(team_name, away_name, home_name, away_name)
    _, one_a = _pair_score(home_name, team_name, home_name, away_name)
    if one_h >= 0.85:
        return "home"
    if one_a >= 0.85:
        return "away"
    return None


def _normalize_injuries(raw_items: list[dict], fx: dict) -> dict:
    home, away, unassigned = [], [], []
    seen: set[tuple[str, str]] = set()
    for item in raw_items or []:
        entry = {
            "player": str((item.get("player") or {}).get("name") or "?"),
            # the API leaves type/reason null on many entries; render a
            # plain "absence" instead of a confusing pseudo-reason
            "reason": str(item.get("reason") or "").strip() or "原因未披露",
            "type": str(item.get("type") or "").strip() or "缺阵",
        }
        # the API repeats the same player per fixture entry — dedupe
        key = (entry["player"], entry["type"])
        if key in seen:
            continue
        seen.add(key)
        side = _team_side(item, fx)
        if side == "home":
            home.append(entry)
        elif side == "away":
            away.append(entry)
        else:
            unassigned.append(entry)
    return {"home": home, "away": away, "unassigned": unassigned,
            "count": len(home) + len(away) + len(unassigned)}


def _season_for(kickoff: datetime) -> int:
    """European seasons start in August: 2026-10 -> season 2026.

    Kept for reference/documentation only — the free plan rejects season-
    filtered queries for the current season, so capture_injuries uses
    date-only fixture queries and filters by league id client-side.
    """
    return kickoff.year if kickoff.month >= 8 else kickoff.year - 1


def capture_injuries(fixture: dict, key: Optional[str]
                     ) -> tuple[list[dict], dict]:
    """Capture absentees for one ESPN fixture record.

    Returns (external_signal_records, intel). With no key, no league
    mapping, or no matching fixture this is ([], intel) — prediction
    proceeds unchanged.
    """
    if not key:
        return [], {"configured": False}
    league_id = LEAGUES.get(fixture.get("league") or "")
    if not league_id:
        return [], {"configured": True,
                    "note": f"league {fixture.get('league')} not mapped to an "
                            f"API-Football league id"}
    kickoff = parse_espn_date(fixture.get("kickoff_utc") or "")
    if kickoff is None:
        return [], {"configured": True, "note": "kickoff unparseable"}

    # date-only query (free-plan safe); league filtering happens client-side
    data = _fetch("/fixtures", key, {"date": kickoff.date().isoformat()})
    candidates = [fx for fx in data.get("response") or []
                  if (fx.get("league") or {}).get("id") in _LEAGUE_IDS]
    fx = match_fixture(candidates,
                       fixture.get("home") or "", fixture.get("away") or "",
                       kickoff)
    intel: dict[str, Any] = {"configured": True, "league_id": league_id}
    if fx is None:
        intel["note"] = "no kickoff+name-matching fixture on API-Football"
        return [], intel

    fixture_id = (fx.get("fixture") or {}).get("id")
    intel["fixture_id"] = fixture_id
    inj = _fetch("/injuries", key, {"fixture": fixture_id})
    intel.update(_normalize_injuries(inj.get("response") or [], fx))
    if intel["count"] == 0:
        intel["note"] = "no recorded absences for either side"
        return [], intel

    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    signal = {
        "source": SIGNAL_SOURCE,
        "namespace": "forward",
        "dq_status": "time_safe",
        "retrieved_at": retrieved_at,
        "payload": {"fixture_id": fixture_id,
                    "home_count": len(intel["home"]),
                    "away_count": len(intel["away"]),
                    "count": intel["count"]},
    }
    return [signal], intel
