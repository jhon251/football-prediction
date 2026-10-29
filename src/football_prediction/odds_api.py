# -*- coding: utf-8 -*-
"""the-odds-api.com adapter: multi-book odds merged into the ESPN capture.

PURPOSE: ESPN carries exactly one bookmaker per match (DraftKings), which
pins the frozen predictor's confidence grade at LOW (single-book fallback
chains). This adapter fetches the same fixture from the-odds-api (which
aggregates bet365 / Pinnacle / William Hill / bwin / ...), maps each
bookmaker to its football-data.co.uk book code (B365 etc.), and lets the
service merge the legs into one multi-book `books` dict — the frozen
predictor then grades MEDIUM/HIGH on its own existing rules.

COSTS: one capture = 1 request x (regions=eu,uk) x (markets=h2h,totals)
= 4 credits. The free plan is 500 credits/month (~125 clicks). Nothing is
requested unless an API key is configured (env ODDS_API_KEY or
config/odds_api.key, gitignored).

MATCHING to ESPN events: kickoff within 15 minutes AND team-name fuzzy
match (normalized difflib ratio; accepted when average >= 0.62 and at
least one side >= 0.82 — handles e.g. ESPN "Internazionale" vs TOA
"Inter Milan" when the opponent matches exactly). A wrong pairing scores
far below the bar and is never merged.

Time safety is unchanged: retrieved_at is still the capture time, and the
service still refuses non-pre matches before any of this runs.
"""
from __future__ import annotations

import difflib
import json
import os
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from football_prediction.odds_feed import parse_espn_date

BASE = "https://api.the-odds-api.com/v4"
REGIONS = "eu,uk"
MARKETS = "h2h,totals"

ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = ROOT / "config" / "odds_api.key"

# ESPN league code -> the-odds-api sport key
SPORT_KEYS = {
    "esp.1": "soccer_spain_la_liga",
    "eng.1": "soccer_epl",
    "fra.1": "soccer_france_ligue_one",
    "ita.1": "soccer_italy_serie_a",
    "ned.1": "soccer_netherlands_eredivisie",
    "bund.1": "soccer_germany_bundesliga",
}

# the-odds-api bookmaker key -> book code. Keys below are the REAL v4 keys
# (verified 2026-10-25 across regions uk/eu/us/au); bet365/bwin entries are
# kept for other sources — the-odds-api itself does not carry bet365, which
# is why the frozen O2 baseline (defined on B365) stays on its fallback
# chain and confidence caps at LOW when only this source is merged.
BOOK_CODES = {
    "bet365": "B365", "bwin": "BV",
    "pinnacle": "PS", "williamhill": "WH", "betway": "BW", "betmgm": "BMGM",
    "onexbet": "1XB", "tipico_de": "TIP", "marathonbet": "MRB",
    "unibet": "UNI", "unibet_uk": "UNIU", "unibet_fr": "UNIF",
    "unibet_nl": "UNIN", "unibet_se": "UNIS",
    "betfair_ex_eu": "BFD", "betfair_ex_uk": "BFU", "betfair_ex_au": "BFA",
    "betfair_sb_uk": "BFS",
    "ladbrokes_uk": "LB", "ladbrokes_au": "LBA",
    "skybet": "SKY", "paddypower": "PP", "coral": "COR", "betfred_uk": "BFR",
    "sport888": "SPT8", "betvictor": "BVT", "boylesports": "BOY",
    "betclic_fr": "BCL", "pmu_fr": "PMU", "codere_it": "COD",
    "winamax_de": "WIND", "winamax_fr": "WINF", "leovegas": "LEO",
    "leovegas_se": "LEOS", "nordicbet": "NOR", "matchbook": "MBK",
    "smarkets": "SMK", "livescorebet": "LSB", "virginbet": "VBT",
    "betano_uk": "BAN", "coolbet": "CLB", "betsson": "BTS",
    "grosvenor": "GRO", "casumo": "CAS", "everygame": "EVG", "gtbets": "GTB",
    "mybookieag": "MYB", "betanysports": "BAS", "betonlineag": "BOL",
    "draftkings": "DK", "fanduel": "FD", "lowvig": "LVIG", "betus": "BUS",
    "bovada": "BVD", "betrivers": "BRR", "pointsbetau": "PBA",
    "neds": "NED", "sportsbet": "SBT", "tab": "TAB", "tabtouch": "TBT",
    "betr_au": "BER", "betright": "BRI", "picklebet_au": "PKB",
    "playup": "PLU",
}

_KICKOFF_TOLERANCE_SECONDS = 15 * 60
_MIN_AVG_RATIO = 0.62
_MIN_ONE_TEAM_RATIO = 0.82


class OddsApiError(RuntimeError):
    """the-odds-api request failed (bad key, quota exhausted, network)."""


def get_odds_api_key() -> Optional[str]:
    env = os.environ.get("ODDS_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    return None


def is_configured() -> bool:
    return get_odds_api_key() is not None


# ---------------------------------------------------------------- matching
def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.replace("&", " and ").lower()
    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)
    return " ".join(s.split())


def _ratio(a: str, b: str) -> float:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _pair_score(toa_home: str, toa_away: str, home: str, away: str) -> tuple[float, float]:
    direct = (_ratio(toa_home, home) + _ratio(toa_away, away)) / 2.0
    swapped = (_ratio(toa_home, away) + _ratio(toa_away, home)) / 2.0
    avg = max(direct, swapped)
    one_team = max(_ratio(toa_home, home), _ratio(toa_away, away),
                   _ratio(toa_home, away), _ratio(toa_away, home))
    return avg, one_team


def match_event(events: list[dict], home: str, away: str,
                kickoff: Optional[datetime]) -> Optional[dict]:
    """Pick the the-odds-api event matching an ESPN fixture, else None."""
    if kickoff is None:
        return None
    best: tuple[float, float, dict] | None = None
    for ev in events or []:
        ct = parse_espn_date(ev.get("commence_time") or "")
        if ct is None or abs((ct - kickoff).total_seconds()) > _KICKOFF_TOLERANCE_SECONDS:
            continue
        avg, one_team = _pair_score(str(ev.get("home_team") or ""),
                                    str(ev.get("away_team") or ""), home, away)
        if best is None or avg > best[0]:
            best = (avg, one_team, ev)
    if best is None:
        return None
    avg, one_team, ev = best
    if avg >= _MIN_AVG_RATIO and one_team >= _MIN_ONE_TEAM_RATIO:
        return ev
    return None


# ---------------------------------------------------------------- fetching
def fetch_league_odds(sport_key: str, key: str, days: int = 2,
                      timeout: int = 20) -> tuple[list[dict], dict]:
    """Return (events, meta) — meta carries quota headers when present."""
    url = (f"{BASE}/sports/{urllib.parse.quote(sport_key)}/odds/"
           f"?apiKey={urllib.parse.quote(key)}&regions={REGIONS}"
           f"&markets={MARKETS}&oddsFormat=decimal&daysFrom={days}")
    req = urllib.request.Request(url, headers={"User-Agent": "football_prediction/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = {
                "requests_remaining": resp.headers.get("x-requests-remaining"),
                "requests_used": resp.headers.get("x-requests-used"),
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise OddsApiError(f"the-odds-api HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OddsApiError(f"the-odds-api request failed: {exc}") from exc
    return data if isinstance(data, list) else [], meta


def _valid_price(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 1.0 else None


def extract_bookmaker(bm: dict, toa_home: str, toa_away: str
                      ) -> tuple[str, Optional[dict[str, float]], Optional[str]]:
    """One TOA bookmaker -> (book_code, legs | None, note | None)."""
    legs: dict[str, float] = {}
    ou_line = None
    for market in bm.get("markets") or []:
        if market.get("key") == "h2h":
            for o in market.get("outcomes") or []:
                name = str(o.get("name") or "")
                price = _valid_price(o.get("price"))
                if price is None:
                    continue
                if name == toa_home:
                    legs["H"] = price
                elif name == toa_away:
                    legs["A"] = price
                elif name.strip().lower() == "draw":
                    legs["D"] = price
        elif market.get("key") == "totals":
            over = under = None
            for o in market.get("outcomes") or []:
                point = o.get("point")
                try:
                    point_f = float(point)
                except (TypeError, ValueError):
                    continue
                if abs(point_f - 2.5) > 1e-9:
                    ou_line = point_f
                    continue
                ou_line = 2.5
                price = _valid_price(o.get("price"))
                side = str(o.get("name") or "").strip().lower()
                if price is None:
                    continue
                if side.startswith("over"):
                    over = price
                elif side.startswith("under"):
                    under = price
            if over is not None and under is not None:
                legs[">2.5"] = over
                legs["<2.5"] = under
    bm_key = str(bm.get("key") or "").strip().lower()
    code = BOOK_CODES.get(bm_key)
    if code is None:
        cleaned = "".join(ch for ch in bm_key.upper() if ch.isalnum())[:4]
        code = cleaned or "TOA"
    if not any(k in legs for k in ("H", "D", "A")) and ">2.5" not in legs:
        return code, None, None
    note = None
    if ou_line is not None and abs(ou_line - 2.5) > 1e-9 and ">2.5" not in legs:
        note = "total line is not 2.5 — O/U legs skipped (model is 2.5-defined)"
    return code, legs, note


def capture_for(fixture: dict, key: Optional[str]) -> tuple[dict, list[dict], dict]:
    """Multi-book odds for one ESPN fixture record.

    Returns (books, provider_meta, meta). With no key, no league mapping,
    or no matching event this is ({}, [], meta) — callers proceed with
    ESPN-only odds.
    """
    if not key:
        return {}, [], {"configured": False}
    sport_key = SPORT_KEYS.get(fixture.get("league") or "")
    if not sport_key:
        return {}, [], {"configured": True,
                        "note": f"league {fixture.get('league')} not on the-odds-api"}
    kickoff = parse_espn_date(fixture.get("kickoff_utc") or "")
    if kickoff is None:
        return {}, [], {"configured": True, "note": "kickoff unparseable"}
    # 2 days of window: fixtures feed looks 3 days ahead; commence-day filter
    # happens via the kickoff tolerance in match_event
    try:
        events, meta = fetch_league_odds(sport_key, key, days=3)
    except OddsApiError as exc:
        return {}, [], {"configured": True, "error": str(exc)}
    meta["configured"] = True
    ev = match_event(events, fixture.get("home") or "", fixture.get("away") or "",
                     kickoff)
    if ev is None:
        meta["note"] = "no kickoff+name-matching event in the-odds-api"
        return {}, [], meta
    meta["matched"] = True
    meta["toa_event_id"] = ev.get("id")
    toa_home, toa_away = str(ev.get("home_team") or ""), str(ev.get("away_team") or "")
    books: dict[str, dict[str, float]] = {}
    providers: list[dict] = []
    for bm in ev.get("bookmakers") or []:
        code, legs, note = extract_bookmaker(bm, toa_home, toa_away)
        if legs is None or code in books:
            continue
        books[code] = legs
        providers.append({
            "provider": bm.get("title") or bm.get("key") or code,
            "book_code": code,
            "source": "the-odds-api",
            "legs": sorted(legs),
            "ou_line": 2.5 if ">2.5" in legs else None,
            "ou_used": ">2.5" in legs,
            "note": note,
        })
    return books, providers, meta
