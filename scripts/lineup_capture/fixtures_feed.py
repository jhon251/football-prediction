"""DATA-006: fixtures feed fetcher.

Polls ESPN scoreboards for the configured leagues over the next N days and
writes data/lineups/prospective/fixtures_feed.json with every SCHEDULED
(pre-game) fixture: {event_id, league, kickoff_utc, season, home, away}.

The supervisor reads this feed to plan per-match short-lifecycle capture
jobs.  Refresh is idempotent and never touches the capture store.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FEED_PATH = Path("data/lineups/prospective/fixtures_feed.json")
BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0 Safari/537.36")}

# La Liga first, EPL second, other big-5 leagues as engineering samples
LEAGUES = ["esp.1", "eng.1", "fra.1", "ita.1", "ned.1", "bund.1"]
LOOKAHEAD_DAYS = 7


def get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_fixtures(leagues: List[str] = LEAGUES,
                   days: int = LOOKAHEAD_DAYS) -> List[Dict[str, Any]]:
    fixtures: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for league in leagues:
        for offset in range(days):
            d = (today + timedelta(days=offset)).strftime("%Y%m%d")
            try:
                sb = get_json(f"{BASE}/{league}/scoreboard?dates={d}")
            except Exception as exc:  # noqa: BLE001
                print(f"feed: {league} {d} fetch error: {str(exc)[:80]}", flush=True)
                time.sleep(0.5)
                continue
            for ev in sb.get("events", []):
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                status = (comps[0].get("status") or {}).get("type", {}).get(
                    "description", "")
                if status not in ("Scheduled", "Pre-Game"):
                    continue
                sides = {c["homeAway"]: c for c in comps[0].get("competitors", [])}
                if "home" not in sides or "away" not in sides:
                    continue
                fixtures.append({
                    "event_id": ev["id"],
                    "league": league,
                    "kickoff_utc": ev.get("date"),
                    "season": str((ev.get("season") or {}).get("year", "")),
                    "home": sides["home"]["team"]["displayName"],
                    "away": sides["away"]["team"]["displayName"],
                })
            time.sleep(0.4)
    return fixtures


def write_feed(fixtures: List[Dict[str, Any]]) -> Path:
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(fixtures),
        "fixtures": sorted(fixtures, key=lambda f: f["kickoff_utc"]),
    }
    FEED_PATH.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return FEED_PATH


def load_feed(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    p = Path(path) if path is not None else FEED_PATH
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("fixtures", [])


if __name__ == "__main__":
    fixtures = fetch_fixtures()
    path = write_feed(fixtures)
    print(f"fixtures feed written -> {path} ({len(fixtures)} scheduled fixtures)")
    for f in fixtures[:10]:
        print(f"  {f['kickoff_utc']} | {f['league']} | {f['home']} vs {f['away']} "
              f"| {f['event_id']}")
