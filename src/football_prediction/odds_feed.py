# -*- coding: utf-8 -*-
"""ESPN scoreboard adapter: upcoming fixtures + pre-match odds capture.

Scope and time safety (mirrors DATA-004/005 conventions):
  * only events whose state is still pre-match are eligible for capture;
  * odds are stamped retrieved_at = capture time (now, UTC), so the
    predictor's time-safety gate (retrieved_at < kickoff_utc) holds whenever
    the state check passed;
  * over/under legs are extracted ONLY when the book's total line is exactly
    2.5 — the predictor's O/U model is defined on the 2.5 line, and mapping
    another line onto ">2.5"/"<2.5" would fabricate data.

The fixtures feed file (data/lineups/prospective/fixtures_feed.json) is the
same file scripts/lineup_capture/fixtures_feed.py writes; this module reads
and writes a field superset so the DATA-006 supervisor keeps working.

Network access uses urllib (stdlib) with a browser User-Agent, identical to
the repo's existing ESPN adapters.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0 Safari/537.36")}

# same league set as scripts/lineup_capture/fixtures_feed.py
LEAGUES = ["esp.1", "eng.1", "fra.1", "ita.1", "ned.1", "bund.1"]
LEAGUE_LABELS = {"esp.1": "西甲", "eng.1": "英超", "fra.1": "法甲",
                 "ita.1": "意甲", "ned.1": "荷甲", "bund.1": "德甲"}

ROOT = Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "data" / "lineups" / "prospective" / "fixtures_feed.json"

_PROVIDER_CODES = {
    "draftkings": "DK", "fanduel": "FD", "espn bet": "EB", "caesars": "CAE",
    "bet 365": "B365", "bet365": "B365", "betfair": "BFD", "bwin": "BV",
    "william hill": "WH", "pinnacle": "PS", "ladbrokes": "LB",
    "interwetten": "IW", "betmgm": "BMGM", "1xbet": "1XB", "betway": "BW",
    "vcbet": "VC", "tipico": "TIP", "unibet": "UNI", "pointsbet": "PB",
}


class OddsFeedError(RuntimeError):
    """Network/parse failure with a user-presentable message."""


# ------------------------------------------------------------------- basics
def get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def american_to_decimal(v) -> Optional[float]:
    """Convert ESPN odds value (American string/number, or bare decimal) to
    decimal odds. Returns None when unparseable or not a valid odd (>1)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        signed, num = False, float(v)
    else:
        s = str(v).strip().replace(",", "")
        if not s:
            return None
        signed = s[0] in "+-"
        try:
            num = float(s)
        except ValueError:
            return None
    if num == 0.0:
        return None
    # signed strings and |v|>=100 are American odds; a small bare number is
    # already decimal
    if signed or abs(num) >= 100.0:
        dec = 1.0 + (num / 100.0 if num > 0 else 100.0 / abs(num))
    elif 1.01 <= abs(num) <= 60.0:
        dec = abs(num)
    else:
        return None
    dec = round(dec, 6)
    return dec if dec > 1.0 else None


def provider_to_code(name: str) -> str:
    key = (name or "").strip().lower()
    if key in _PROVIDER_CODES:
        return _PROVIDER_CODES[key]
    cleaned = "".join(ch for ch in key.upper() if ch.isalnum())
    return cleaned[:4] or "UNKN"


def parse_espn_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------- fixtures
def parse_event(ev: dict, league: str) -> Optional[dict]:
    """Normalize an ESPN scoreboard event into a fixture record."""
    kickoff = parse_espn_date(ev.get("date") or "")
    comps = ev.get("competitions") or [{}]
    comp = comps[0] if comps else {}
    home = away = home_abbr = away_abbr = None
    for c in comp.get("competitors") or []:
        team = c.get("team") or {}
        if c.get("homeAway") == "home":
            home, home_abbr = team.get("displayName"), team.get("abbreviation")
        elif c.get("homeAway") == "away":
            away, away_abbr = team.get("displayName"), team.get("abbreviation")
    if not (kickoff and home and away):
        return None
    league_info = ((ev.get("leagues") or [{}])[0] or {})
    return {
        "event_id": str(ev.get("id") or ""),
        "league": league,
        "league_label": LEAGUE_LABELS.get(league, league),
        "league_name": league_info.get("name") or league,
        "kickoff_utc": kickoff.isoformat(),
        "home": home,
        "away": away,
        "home_abbr": home_abbr or "",
        "away_abbr": away_abbr or "",
        "state": ((ev.get("status") or {}).get("type") or {}).get("state") or "",
    }


def fetch_day(league: str, day: date) -> list[dict]:
    url = f"{BASE}/{league}/scoreboard?dates={day.strftime('%Y%m%d')}"
    sb = get_json(url)
    out = []
    for ev in sb.get("events") or []:
        rec = parse_event(ev, league)
        if rec and rec["event_id"]:
            out.append(rec)
    return out


def fetch_fixtures(leagues: list[str] | None = None, days: int = 3) -> list[dict]:
    """Upcoming pre-match fixtures across leagues (skips fetch errors)."""
    leagues = leagues or LEAGUES
    today = datetime.now(timezone.utc).date()
    fixtures: dict[str, dict] = {}
    for league in leagues:
        for offset in range(days):
            try:
                for rec in fetch_day(league, today + timedelta(days=offset)):
                    if rec["state"] in ("pre", "scheduled"):
                        fixtures[rec["event_id"]] = rec
            except Exception as exc:  # noqa: BLE001 - one league/day failing
                print(f"odds_feed: {league} day+{offset} error: {str(exc)[:80]}",
                      flush=True)
                time.sleep(0.4)
    return sorted(fixtures.values(), key=lambda r: r["kickoff_utc"])


def write_feed(fixtures: list[dict], fetched_at: datetime | None = None,
               path: Path | None = None) -> Path:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    payload = {
        "fetched_at": fetched_at.isoformat(),
        "count": len(fixtures),
        "source": "espn scoreboard via football_prediction.odds_feed",
        "fixtures": fixtures,
    }
    target = Path(path) if path else FEED_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return target


def load_feed(path: Path | None = None) -> tuple[list[dict], Optional[str]]:
    """Return (fixtures, fetched_at_iso); ([], None) when no feed exists."""
    p = Path(path) if path else FEED_PATH
    if not p.exists():
        return [], None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], None
    return data.get("fixtures") or [], data.get("fetched_at")


def feed_age_hours(fetched_at: Optional[str]) -> Optional[float]:
    ts = parse_espn_date(fetched_at or "")
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


# -------------------------------------------------------------------- odds
def _side_decimal(side) -> Optional[float]:
    """side like {"open": {"odds": "+350"}, "close": {"odds": "+400"}}."""
    if not isinstance(side, dict):
        return None
    for key in ("close", "open"):
        dec = american_to_decimal((side.get(key) or {}).get("odds"))
        if dec is not None:
            return dec
    return None


def extract_books(comp: dict) -> tuple[dict[str, dict[str, float]], list[dict]]:
    """Extract book -> legs mapping from an ESPN competition.

    Legs follow football-data.co.uk naming so the values feed
    football_prediction.market directly: H/D/A and (only on a 2.5 line)
    ">2.5"/"<2.5". Returns (books, provider_meta).
    """
    books: dict[str, dict[str, float]] = {}
    providers: list[dict] = []
    for o in comp.get("odds") or []:
        name = (o.get("provider") or {}).get("name") or "unknown"
        code = provider_to_code(name)
        legs: dict[str, float] = {}
        ml = o.get("moneyline") or {}
        h = _side_decimal(ml.get("home"))
        d = _side_decimal(ml.get("draw"))
        a = _side_decimal(ml.get("away"))
        if d is None:
            d = american_to_decimal((o.get("drawOdds") or {}).get("moneyLine"))
        if h is not None and d is not None and a is not None:
            legs.update({"H": h, "D": d, "A": a})
        ou_line = o.get("overUnder")
        over = _side_decimal((o.get("total") or {}).get("over"))
        under = _side_decimal((o.get("total") or {}).get("under"))
        ou_ok = False
        if ou_line is not None:
            try:
                ou_ok = abs(float(ou_line) - 2.5) < 1e-9
            except (TypeError, ValueError):
                ou_ok = False
        if over is not None and under is not None and ou_ok:
            legs[">2.5"] = over
            legs["<2.5"] = under
        while code in books:
            code += "X"
        if legs:
            books[code] = legs
        providers.append({
            "provider": name, "book_code": code,
            "legs": sorted(legs),
            "ou_line": ou_line,
            "ou_used": ">2.5" in legs,
            "note": None if ou_ok or ou_line is None else
                    "total line is not 2.5 — O/U legs skipped (model is 2.5-defined)",
        })
    return books, providers


def get_event(league: str, event_id: str, day: date) -> tuple[dict, dict]:
    """Fetch one event (with fresh state/odds) by id from its kickoff day.

    Looks at `day` and `day + 1` so kickoff-midnight edges still resolve.
    Returns (fixture_record, raw_competition). Raises OddsFeedError when the
    event cannot be found or the network fails.
    """
    last_exc: Exception | None = None
    for d in (day, day + timedelta(days=1)):
        try:
            sb = get_json(f"{BASE}/{league}/scoreboard?dates={d.strftime('%Y%m%d')}")
            for ev in sb.get("events") or []:
                if str(ev.get("id")) != str(event_id):
                    continue
                rec = parse_event(ev, league)
                comp = (ev.get("competitions") or [{}])[0]
                if rec and rec["event_id"]:
                    return rec, comp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise OddsFeedError(f"event {event_id} not found in {league} "
                        f"({day}..{day + timedelta(days=1)}): {last_exc}")
