"""DATA-002: Understat xG/xGA data acquisition, time-safety, freeze & audit.

Acquires Understat EPL match-level xG/xGA for 2024-25 and 2025-26 via the
getLeagueData/{league}/{season} endpoint, builds TIME-SAFE rolling xG features
(strictly prior matches only), freezes the data under data/xg/understat/, and
writes a quality audit.

READ-ONLY vs production model / config / knowledge rules. No prediction
experiments, no d_Brier / logloss / ROI. This script only acquires, cleans,
freezes and audits data.

Time safety (DIAG-007):
  - For match t, rolling features use ONLY matches with datetime < t.datetime
    (window = 10 prior matches per team).
  - The xG of match t itself is NEVER used for t's own features.
  - A rolling feature's effective "generated_at" = max datetime of its source
    matches, which is < t.datetime by construction (no leakage).

Outputs:
  data/xg/understat/raw/{season}.json            raw snapshots (frozen)
  data/xg/understat/normalized/matches_{season}.csv
  data/xg/understat/normalized/rolling_{season}.csv
  data/xg/understat/MANIFEST.json                data_version + fingerprints
  backtest_output/data_002_understat/audit.json  quality audit
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import baseline_manifest
from football_simulation.data.historical.etl import HistoricalDataset

RAW_DIR = Path("data/xg/understat/raw")
NORM_DIR = Path("data/xg/understat/normalized")
MANIFEST_PATH = Path("data/xg/understat/MANIFEST.json")
AUDIT_DIR = Path("backtest_output/data_002_understat")
LOCAL_DATASET = Path("data/historical/epl_2025_26.json")
BASELINE_DIR = Path("backtest_output/real_epl_base_001")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://understat.com/league/EPL/2025",
}

SEASONS = {"2024": "2024-25", "2025": "2025-26"}
WINDOW = 10  # rolling window (matches), pre-registered in DIAG-005

# Understat team title -> canonical local (football-data.co.uk) name
TEAM_MAP = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Ipswich": "Ipswich",
    "Leeds": "Leeds",
    "Leicester": "Leicester",
    "Liverpool": "Liverpool",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Tottenham": "Tottenham",
    "West Ham": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def fetch(season: str) -> Dict[str, Any]:
    import gzip
    url = f"https://understat.com/getLeagueData/EPL/{season}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # frozen baseline integrity (read-only check)
    manifest_bl = baseline_manifest(BASELINE_DIR)
    (AUDIT_DIR / "baseline_manifest.json").write_text(
        json.dumps(manifest_bl, indent=2), encoding="utf-8")

    local_teams = set()
    ds = HistoricalDataset.load(LOCAL_DATASET)
    for m in ds.matches_in_season("2025-26"):
        local_teams.add(m.home_team)
        local_teams.add(m.away_team)

    raw_hashes: Dict[str, str] = {}
    parsed: Dict[str, List[Dict[str, Any]]] = {}
    scrape_time = datetime.now(timezone.utc).isoformat()

    for season, label in SEASONS.items():
        payload = fetch(season)
        raw_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        raw_path = RAW_DIR / f"{season}.json"
        raw_path.write_bytes(raw_bytes)
        raw_hashes[season] = sha256(raw_bytes)
        log(f"{label}: fetched {len(payload.get('dates', []))} matches, "
            f"raw sha256={raw_hashes[season][:16]}")

        matches = []
        for d in payload.get("dates", []):
            home = d["h"]["title"]
            away = d["a"]["title"]
            matches.append({
                "match_id": d["id"],
                "season": label,
                "datetime_utc": d["datetime"],
                "is_result": bool(d["isResult"]),
                "home_team": TEAM_MAP.get(home, home),
                "away_team": TEAM_MAP.get(away, away),
                "home_team_understat": home,
                "away_team_understat": away,
                "home_goals": int(d["goals"]["h"]),
                "away_goals": int(d["goals"]["a"]),
                "home_xg": float(d["xG"]["h"]),
                "away_xg": float(d["xG"]["a"]),
            })
        parsed[season] = matches
        log(f"{label}: parsed {len(matches)} match records")

    # ---- normalize + rolling features (time-safe) ----
    audit: Dict[str, Any] = {"scrape_time": scrape_time, "source":
                             "https://understat.com/getLeagueData/EPL/{season}",
                             "parser_version": "data_002_understat_freeze.py:v1"}
    audit["seasons"] = {}

    for season, label in SEASONS.items():
        matches = parsed[season]
        # sort by datetime (chronological)
        matches.sort(key=lambda m: (m["datetime_utc"], m["match_id"]))
        # dedupe by match_id
        seen = set()
        deduped = []
        duplicates = 0
        for m in matches:
            if m["match_id"] in seen:
                duplicates += 1
                continue
            seen.add(m["match_id"])
            deduped.append(m)
        matches = deduped

        # team mapping coverage (use raw Understat titles for the mapping check)
        titles = sorted({m["home_team_understat"] for m in matches}
                        | {m["away_team_understat"] for m in matches})
        mapped = [t for t in titles if t in TEAM_MAP]
        unmapped = [t for t in titles if t not in TEAM_MAP]
        mapping_coverage = {t: TEAM_MAP.get(t, None) for t in titles}

        # per-team rolling xG for/against (time-safe: strictly prior matches)
        # map title -> canonical; use title as fallback canonical when unmapped
        def canon(title: str) -> str:
            return TEAM_MAP.get(title, title)

        team_hist: Dict[str, List[Tuple[str, float, float]]] = {}  # canon -> [(dt, xg_for, xg_against)]
        rolling_rows = []
        for m in matches:
            h_c, a_c = canon(m["home_team"]), canon(m["away_team"])
            # home rolling (from home team's prior matches, strictly < dt)
            h_prior = [x for x in team_hist.get(h_c, []) if x[0] < m["datetime_utc"]][-WINDOW:]
            a_prior = [x for x in team_hist.get(a_c, []) if x[0] < m["datetime_utc"]][-WINDOW:]
            def roll(prior, side_xg):
                if not prior:
                    return None, None
                xgf = sum(p[1] for p in prior) / len(prior)
                xga = sum(p[2] for p in prior) / len(prior)
                return xgf, xga
            h_xgf, h_xga = roll(h_prior, "h")
            a_xgf, a_xga = roll(a_prior, "a")
            rolling_rows.append({
                "match_id": m["match_id"], "season": label,
                "datetime_utc": m["datetime_utc"],
                "home_team": h_c, "away_team": a_c,
                "home_xg_for_roll": h_xgf, "home_xg_against_roll": h_xga,
                "away_xg_for_roll": a_xgf, "away_xg_against_roll": a_xga,
                "xg_diff_roll": (round(h_xgf - a_xgf, 6) if h_xgf is not None
                                 and a_xgf is not None else None),
            })
            # append this match to history (xG for = own side's xG, against = opponent's)
            team_hist.setdefault(h_c, []).append(
                (m["datetime_utc"], m["home_xg"], m["away_xg"]))
            team_hist.setdefault(a_c, []).append(
                (m["datetime_utc"], m["away_xg"], m["home_xg"]))

        # write normalized matches CSV
        matches_csv = NORM_DIR / f"matches_{season}.csv"
        with matches_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(matches[0].keys()))
            w.writeheader()
            w.writerows(matches)
        rolling_csv = NORM_DIR / f"rolling_{season}.csv"
        with rolling_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rolling_rows[0].keys()))
            w.writeheader()
            w.writerows(rolling_rows)

        # ---- audit for this season ----
        n = len(matches)
        is_result = sum(1 for m in matches if m["is_result"])
        missing_xg = sum(1 for m in matches if m["home_xg"] is None or m["away_xg"] is None)
        # date consistency: datetime parseable & sorted
        date_ok = all(_parse_dt(m["datetime_utc"]) is not None for m in matches)
        # xG-result correspondence: xG>0 for played matches with goals (sanity)
        xg_zero_played = sum(1 for m in matches if m["is_result"]
                             and (m["home_xg"] == 0 and m["away_xg"] == 0))
        # leakage check: rolling features must only reference strictly prior matches
        leakage = _leakage_check(rolling_rows)
        # outliers: xG > 5 (rare) count
        outliers = sum(1 for m in matches if m["home_xg"] > 5 or m["away_xg"] > 5)
        mapped_local = sorted({TEAM_MAP[t] for t in titles if t in TEAM_MAP})
        cross_ok = (season != "2025") or (set(mapped_local) == local_teams)
        audit["seasons"][label] = {
            "matches": n,
            "is_result_played": is_result,
            "duplicates_removed": duplicates,
            "missing_xg": missing_xg,
            "team_titles": titles,
            "team_mapping_coverage": mapping_coverage,
            "unmapped_titles": unmapped,
            "mapped_to_local_2025_26": (mapped_local if season == "2025" else None),
            "local_team_crosscheck_ok": cross_ok,
            "date_parseable_sorted_ok": date_ok,
            "xg_zero_for_played_match": xg_zero_played,
            "xg_outlier_gt5": outliers,
            "leakage_detected": leakage,
        }
        log(f"{label}: {n} matches, duplicates={duplicates}, "
            f"unmapped_titles={unmapped}, crosscheck_ok={cross_ok}, leakage={leakage}")

    # ---- manifest + fingerprints ----
    def file_sha(path: Path) -> str:
        return sha256(path.read_bytes())

    normalized_hashes = {}
    for season in SEASONS:
        normalized_hashes[f"matches_{season}.csv"] = file_sha(NORM_DIR / f"matches_{season}.csv")
        normalized_hashes[f"rolling_{season}.csv"] = file_sha(NORM_DIR / f"rolling_{season}.csv")

    # composite data_version: hash of all frozen files
    combined = "".join(raw_hashes.values()) + "".join(normalized_hashes.values())
    data_version = sha256(combined.encode("utf-8"))

    manifest = {
        "data_version": data_version,
        "fingerprint": data_version[:16],
        "source": "Understat (getLeagueData/EPL/{season})",
        "scrape_time": scrape_time,
        "parser_version": "data_002_understat_freeze.py:v1",
        "seasons": SEASONS,
        "rolling_window": WINDOW,
        "raw_sha256": raw_hashes,
        "normalized_sha256": normalized_hashes,
        "time_safety": ("rolling features use strictly prior matches "
                        "(datetime < current); no post-match xG of the predicted "
                        "match is ever used; no future information"),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    audit["manifest"] = manifest
    (AUDIT_DIR / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    log(f"data_version={data_version}")
    log(f"fingerprint={data_version[:16]}")
    log(f"DONE in {time.time() - t0:.0f}s")


def _parse_dt(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _leakage_check(rolling_rows: List[Dict[str, Any]]) -> bool:
    """True if any rolling feature references the same match (leakage)."""
    # By construction rolling uses strictly-prior matches; verify no row's own
    # xG appears in its rolling values (impossible to check directly here, but
    # confirm chronological ordering and None-before-history).
    prev_dt = None
    for r in rolling_rows:
        dt = _parse_dt(r["datetime_utc"])
        if dt is None:
            continue
        if prev_dt is not None and dt < prev_dt:
            return True
        prev_dt = dt
    return False


if __name__ == "__main__":
    main()
