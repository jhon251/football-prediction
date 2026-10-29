"""DATA-003: Lineup data acquisition & freeze (ESPN summary API).

Source decision vs DATA-001 audit (MUST be recorded, not silently swapped):
  DATA-001 recommended official/Sportmonks structured APIs.  In this
  environment: Sportmonks/API-Football need credentials (unavailable),
  FBref -> 403 (anti-bot), worldfootball.net -> 403, TheSportsDB free test
  key returns only 5 events/season, Wikipedia API timed out.  The ESPN public
  JSON API (site.web.api.espn.com) is reachable and provides structured
  historical lineups (rosters with starter flags + formations) for BOTH
  seasons, so it is used as the actual source.

CRITICAL time-safety verdict (recorded, not worked around):
  ESPN lineups are FINAL XIs assembled from post-match summaries - they carry
  NO lineup_published_at and NO lineage of pre-kickoff versions.  Late
  changes (warm-up injuries etc.) cannot be recovered retroactively.  Per
  DIAG-007, every record is therefore flagged time_safe=false and
  unstable_lineup=true, and NO match is enterable into a time-safe main
  probe.  The frozen dataset is a FINAL-XI archive + pipeline for the
  forward-capture (75-minute rule) build-out, NOT a pre-match input.

Usage:
  python scripts/data_003_lineup_freeze.py --fetch-season 2024
  python scripts/data_003_lineup_freeze.py --fetch-season 2025
  python scripts/data_003_lineup_freeze.py --build
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.data.historical.etl import HistoricalDataset

RAW_DIR = Path("data/lineups/espn/raw")
NORM_DIR = Path("data/lineups/espn/normalized")
MANIFEST_PATH = Path("data/lineups/espn/MANIFEST.json")
AUDIT_DIR = Path("backtest_output/data_003_lineup")
LOCAL_DATASET = Path("data/historical/epl_2025_26.json")
UNDERSTAT_MATCHES = Path("data/xg/understat/normalized/matches_2024.csv")

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/eng.1"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0 Safari/537.36")}
DELAY = 0.3  # polite rate limit between ESPN calls

SEASONS = {"2024": "2024-25", "2025": "2025-26"}

# ESPN displayName -> canonical local name
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


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_season(year: str, skip_schedule: bool = False,
                 offset: int = 0, limit: Optional[int] = None,
                 workers: int = 4) -> None:
    from concurrent.futures import ThreadPoolExecutor

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ev_file = AUDIT_DIR / f"events_{year}.json"
    if skip_schedule and ev_file.exists():
        events = {e["id"]: e for e in json.loads(ev_file.read_text(encoding="utf-8"))["events"]}
        log(f"loaded cached event list {year}: {len(events)}")
    else:
        teams = get_json(f"{BASE}/teams")["sports"][0]["leagues"][0]["teams"]
        team_ids = [t["team"]["id"] for t in teams]
        log(f"teams: {len(team_ids)}")

        def fetch_schedule(tid: str) -> List[Dict[str, Any]]:
            url = f"{BASE}/teams/{tid}/schedule?season={year}"
            out = []
            try:
                sched = get_json(url)
            except Exception as exc:  # noqa: BLE001
                log(f"schedule fail team {tid}: {exc}")
                return out
            for ev in sched.get("events", []):
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                comp = comps[0]
                sides = {c["homeAway"]: c for c in comp.get("competitors", [])}
                if "home" not in sides or "away" not in sides:
                    continue
                out.append({
                    "id": ev["id"], "date": ev.get("date"), "name": ev.get("name"),
                    "season": year,
                    "home": sides["home"]["team"]["displayName"],
                    "away": sides["away"]["team"]["displayName"],
                    "home_score": sides["home"].get("score"),
                    "away_score": sides["away"].get("score"),
                })
            return out

        events: Dict[str, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for item_list in pool.map(fetch_schedule, team_ids):
                for item in item_list:
                    events[item["id"]] = item
        log(f"unique events {year}: {len(events)}")
        (AUDIT_DIR / f"events_{year}.json").write_text(
            json.dumps({"events": list(events.values()), "summary_ok": 0,
                        "summary_fail": []}, indent=1), encoding="utf-8")

    ev_ids = sorted(events, key=lambda i: events[i]["date"])
    if offset:
        ev_ids = ev_ids[offset:]
    if limit:
        ev_ids = ev_ids[:limit]
    log(f"summary slice: {len(ev_ids)} events (offset={offset}, limit={limit})")

    def fetch_one(eid: str) -> Tuple[str, Optional[str]]:
        raw_path = RAW_DIR / f"{eid}.json"
        if raw_path.exists():
            return eid, None
        try:
            raw = get_json(f"{BASE}/summary?event={eid}")
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            return eid, None
        except Exception as exc:  # noqa: BLE001
            return eid, str(exc)[:80]

    ok = 0
    fail: List[Tuple[str, str]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for eid, err in pool.map(fetch_one, ev_ids):
            if err:
                fail.append((eid, err))
            else:
                ok += 1
            done += 1
            if done % 100 == 0:
                log(f"  summaries {done}/{len(ev_ids)}")
    log(f"{year}: slice summaries ok={ok}, fail={len(fail)}")


def build() -> None:
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    local = HistoricalDataset.load(LOCAL_DATASET)
    local_keys = {}
    for m in local.matches_in_season("2025-26"):
        local_keys[(m.date.isoformat()[:10], m.home_team, m.away_team)] = m.match_id
    understat_keys = {}
    with UNDERSTAT_MATCHES.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            understat_keys[(row["datetime_utc"][:10], row["home_team"],
                            row["away_team"])] = row["match_id"]

    rows: List[Dict[str, Any]] = []
    audit: Dict[str, Any] = {"seasons": {}, "totals": {
        "events_processed": 0, "with_rosters": 0, "starting_xi_11": 0,
        "starting_xi_anomaly": 0, "published_at_complete": 0,
        "time_safe": 0, "unstable_lineup": 0, "mapped_2025_26": 0,
        "mapped_2024_25": 0, "unmapped_events": 0}}
    events_all: List[Dict[str, Any]] = []
    for year, label in SEASONS.items():
        ev_file = AUDIT_DIR / f"events_{year}.json"
        if not ev_file.exists():
            log(f"events_{year}.json missing - run --fetch-season {year} first")
            continue
        evs = json.loads(ev_file.read_text(encoding="utf-8"))["events"]
        events_all.extend(evs)
        n_xi = 0
        n_11 = 0
        n_anom = 0
        n_rost = 0
        for ev in evs:
            raw_path = RAW_DIR / f"{ev['id']}.json"
            if not raw_path.exists():
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            rosters = raw.get("rosters") or []
            n_rost += 1
            home_xi: List[str] = []
            away_xi: List[str] = []
            home_pids: List[str] = []
            away_pids: List[str] = []
            home_formation = ""
            away_formation = ""
            for team in rosters:
                is_home = team.get("homeAway") == "home"
                xi = home_xi if is_home else away_xi
                pids = home_pids if is_home else away_pids
                if is_home:
                    home_formation = team.get("formation", "")
                else:
                    away_formation = team.get("formation", "")
                for p in team.get("roster", []):
                    if p.get("starter"):
                        xi.append(p["athlete"]["displayName"])
                        pids.append(str(p["athlete"]["id"]))
            if len(home_xi) == 11 and len(away_xi) == 11:
                n_11 += 1
            else:
                n_anom += 1
            n_xi += 1
            h = TEAM_MAP.get(ev["home"], ev["home"])
            a = TEAM_MAP.get(ev["away"], ev["away"])
            date10 = (ev["date"] or "")[:10]
            rows.append({
                "season": label, "event_id": ev["id"],
                "kickoff_utc": ev["date"],
                "home_team": h, "away_team": a,
                "home_goals": ev["home_score"], "away_goals": ev["away_score"],
                "home_xi": "|".join(home_xi), "away_xi": "|".join(away_xi),
                "home_player_ids": "|".join(home_pids),
                "away_player_ids": "|".join(away_pids),
                "home_formation": home_formation, "away_formation": away_formation,
                "lineup_published_at": "",   # NOT provided by ESPN (retroactive)
                "lineup_last_change_at": "",  # NOT provided
                "time_safe": False,
                "unstable_lineup": True,   # final XI unknown pre-kickoff retroactively
                "source": "espn_summary_retroactive",
                "match_id_local_2025_26": local_keys.get((date10, h, a), ""),
                "match_id_understat_2024_25": understat_keys.get((date10, h, a), ""),
            })
        audit["seasons"][label] = {"events": len(evs), "with_rosters": n_rost,
                                   "starting_xi_parsed": n_xi, "xi_11": n_11,
                                   "xi_anomaly": n_anom}
        log(f"{label}: events={len(evs)}, rosters={n_rost}, xi_11={n_11}, "
            f"anomaly={n_anom}")

    audit["totals"]["events_processed"] = len(rows)
    audit["totals"]["with_rosters"] = sum(
        1 for r in rows if r["home_xi"] and r["away_xi"])
    audit["totals"]["starting_xi_11"] = sum(1 for r in rows
                                            if len(r["home_xi"].split("|")) == 11
                                            and len(r["away_xi"].split("|")) == 11)
    audit["totals"]["starting_xi_anomaly"] = sum(
        1 for r in rows if len(r["home_xi"].split("|")) != 11
        or len(r["away_xi"].split("|")) != 11)
    audit["totals"]["published_at_complete"] = sum(
        1 for r in rows if r["lineup_published_at"])
    audit["totals"]["time_safe"] = sum(1 for r in rows if r["time_safe"])
    audit["totals"]["unstable_lineup"] = sum(1 for r in rows if r["unstable_lineup"])
    audit["totals"]["mapped_2025_26"] = sum(1 for r in rows
                                            if r["match_id_local_2025_26"])
    audit["totals"]["mapped_2024_25"] = sum(1 for r in rows
                                            if r["match_id_understat_2024_25"])
    audit["totals"]["unmapped_events"] = sum(
        1 for r in rows if not r["match_id_local_2025_26"]
        and not r["match_id_understat_2024_25"])
    audit["missing_rate"] = round(
        1 - audit["totals"]["with_rosters"] / max(len(rows), 1), 4)
    audit["duplicates"] = len(rows) - len({r["event_id"] for r in rows})
    # player id coverage
    pids = [p for r in rows for p in r["home_player_ids"].split("|") if p]
    audit["player_id_total"] = len(pids)
    audit["player_id_unique"] = len(set(pids))
    audit["time_safety_verdict"] = (
        "ESPN retroactive summaries provide FINAL XIs only; no lineup_published_at "
        "and no pre-kickoff lineage is recoverable for 2024-25/2025-26. "
        "Per DIAG-007, time_safe=false for every record; 0 matches enterable "
        "into a time-safe main probe. Forward capture (75-minute rule) is the "
        "only path to time-safe lineup data.")
    audit["source_difference_reason"] = (
        "DATA-001 recommended official/Sportmonks; Sportmonks/API-Football "
        "require credentials (unavailable), FBref/worldfootball 403, "
        "TheSportsDB test key limited, Wikipedia timeout. ESPN public JSON API "
        "was reachable and provides structured historical lineups for both "
        "seasons - used instead, with the final-XI/time-safety caveat above.")

    csv_path = NORM_DIR / "lineups_all.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def sha256(p: Path) -> str:
        import hashlib
        return hashlib.sha256(p.read_bytes()).hexdigest()

    raw_hashes = {}
    for p in sorted(RAW_DIR.glob("*.json")):
        raw_hashes[p.stem] = sha256(p)
    combined = sha256(csv_path) + "".join(raw_hashes.values())
    import hashlib
    data_version = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    manifest = {
        "data_version": data_version,
        "fingerprint": data_version[:16],
        "source": "ESPN public JSON API (site.web.api.espn.com) - retroactive summaries",
        "scrape_time": datetime.utcnow().isoformat() + "Z",
        "parser_version": "data_003_lineup_freeze.py:v1",
        "seasons": SEASONS,
        "time_safety": {
            "lineup_published_at": "NOT AVAILABLE (retroactive)",
            "lineup_last_change_at": "NOT AVAILABLE",
            "time_safe_records": 0,
            "unstable_lineup_records": len(rows),
            "verdict": audit["time_safety_verdict"],
        },
        "source_difference_reason": audit["source_difference_reason"],
        "normalized_sha256": {"lineups_all.csv": sha256(csv_path)},
        "raw_file_count": len(raw_hashes),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    audit["manifest"] = manifest
    (AUDIT_DIR / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    log(f"fingerprint={data_version[:16]}, rows={len(rows)}")
    log("build DONE")


def repair_missing(workers: int = 8) -> None:
    """Scoreboard-by-date repair: reference matches (local 2025-26 dataset +
    Understat 2024-25) not covered by the team-schedule event list are looked
    up on ESPN's scoreboard by date and their summaries are fetched."""
    from concurrent.futures import ThreadPoolExecutor
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    rev = {v: k for k, v in TEAM_MAP.items()}

    refs: Dict[str, List[tuple]] = {"2024": [], "2025": []}
    local = HistoricalDataset.load(LOCAL_DATASET)
    for m in local.matches_in_season("2025-26"):
        refs["2025"].append((m.date.isoformat()[:10], m.home_team, m.away_team))
    with UNDERSTAT_MATCHES.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            refs["2024"].append((row["datetime_utc"][:10], row["home_team"],
                                 row["away_team"]))

    added = 0
    for year, ref_list in refs.items():
        ev_file = AUDIT_DIR / f"events_{year}.json"
        if not ev_file.exists():
            log(f"events_{year}.json missing")
            continue
        events = {e["id"]: e for e in json.loads(ev_file.read_text(encoding="utf-8"))["events"]}
        covered = set()
        for e in events.values():
            covered.add((e["date"][:10], TEAM_MAP.get(e["home"], e["home"]),
                         TEAM_MAP.get(e["away"], e["away"])))
        miss_dates = sorted({d for d, h, a in ref_list if (d, h, a) not in covered})
        log(f"{year}: uncovered reference dates = {len(miss_dates)}")
        year_added = 0
        for d in miss_dates:
            url = f"{BASE}/scoreboard?dates={d.replace('-', '')}"
            try:
                sb = get_json(url)
            except Exception as exc:  # noqa: BLE001
                log(f"scoreboard fail {d}: {exc}")
                continue
            for ev in sb.get("events", []):
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                sides = {c["homeAway"]: c for c in comps[0].get("competitors", [])}
                if "home" not in sides or "away" not in sides:
                    continue
                eid = ev["id"]
                if eid in events:
                    continue
                events[eid] = {
                    "id": eid, "date": ev.get("date"), "name": ev.get("name"),
                    "season": year,
                    "home": sides["home"]["team"]["displayName"],
                    "away": sides["away"]["team"]["displayName"],
                    "home_score": sides["home"].get("score"),
                    "away_score": sides["away"].get("score"),
                }
                year_added += 1
                added += 1
        (AUDIT_DIR / f"events_{year}.json").write_text(
            json.dumps({"events": list(events.values()), "summary_ok": 0,
                        "summary_fail": []}, indent=1), encoding="utf-8")
        # fetch summaries for the newly added events
        new_ids = [e["id"] for e in events.values()
                   if not (RAW_DIR / f"{e['id']}.json").exists()]
        log(f"{year}: new events added={year_added}, "
            f"summaries to fetch={len(new_ids)}")

        def fetch_one(eid: str):
            try:
                raw = get_json(f"{BASE}/summary?event={eid}")
                (RAW_DIR / f"{eid}.json").write_text(json.dumps(raw), encoding="utf-8")
                return eid, None
            except Exception as exc:  # noqa: BLE001
                return eid, str(exc)[:80]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for eid, err in pool.map(fetch_one, new_ids):
                if err:
                    log(f"  summary fail {eid}: {err}")
    log(f"repair DONE (added {added} events)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-season", default=None, choices=["2024", "2025"])
    parser.add_argument("--skip-schedule", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repair-missing", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.repair_missing:
        repair_missing(workers=args.workers)
    elif args.fetch_season:
        fetch_season(args.fetch_season, skip_schedule=args.skip_schedule,
                     offset=args.offset, limit=args.limit, workers=args.workers)
    elif args.build:
        build()
    else:
        raise SystemExit("specify --fetch-season/--repair-missing/--build")


if __name__ == "__main__":
    main()
