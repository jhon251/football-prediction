"""DATASET BUILD v1.0.0 (v2) — implements BUILD_SPEC S1..S5 (read-only on sources).

Deterministic, stdlib-only. Writes ONLY into backtest_output/dataset_build/.
Frozen CANONICAL_SCHEMA gate: odds > 1.0 else NULL (invalid price cells are
nulled per policy and recorded as warnings; raw CSVs are NEVER modified).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(r"C:\football")
AUDIT = ROOT / "backtest_output" / "hist_csv_audit"
BUILD = ROOT / "backtest_output" / "dataset_build"
OUT = BUILD / "output"
FREEZE = BUILD / "freeze" / "1.0.0"
MANIFEST_PATH = AUDIT / "manifests" / "canonical_manifest.json"
SHA_MANIFEST_PATH = AUDIT / "manifests" / "sha256_manifest.json"

LEAGUE_TZ = {"E0": "Europe/London", "SP1": "Europe/Madrid", "I1": "Europe/Rome",
             "D1": "Europe/Berlin", "F1": "Europe/Paris"}
DATE_ONLY_SEASONS = {"2015-16", "2016-17", "2017-18", "2018-19"}
EXPECTED_RAW_PER_LEAGUE = {"E0": 4180, "SP1": 4180, "I1": 4181, "D1": 3366, "F1": 3858}
EXPECTED_QC_PER_LEAGUE = {"E0": 4180, "SP1": 4180, "I1": 4180, "D1": 3366, "F1": 3857}
EXPECTED_RAW = 19765
EXPECTED_QC = 19763

POST_STAT_COLS = {"Attendance", "HS", "AS", "HST", "AST", "HHW", "AHW", "HC", "AC",
                  "HF", "AF", "HFKC", "AFKC", "HO", "AO", "HY", "AY", "HR", "AR",
                  "HBP", "ABP", "HG", "AG", "Res"}
EXCLUDE_COLS = POST_STAT_COLS | {"HTHG", "HTAG", "HTR", "HxG", "AxG"}
IDENTITY_COLS = {"Div", "Date", "Time", "HomeTeam", "AwayTeam", "Referee"}
LABEL_COLS = {"FTHG", "FTAG", "FTR"}

# ORDER MATTERS: AH line patterns MUST be checked before 1X2 (e.g. BbAH, B365AH
# end with H but are handicap LINES, not 1X2 prices).
RE_AH_LINE_H = re.compile(r"^(?P<base>[A-Za-z0-9]+?)AHh$")
RE_AH_LINE_BOOK = re.compile(r"^(?P<base>[A-Za-z0-9]+?)AH$")
RE_AH_PRICE = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)AH(?P<side>H|A)$")
RE_OU = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)(?P<mk>>2\.5|<2\.5)$")
RE_1X2 = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)(?P<mk>H|D|A)$")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def parse_date(s: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def season_of(d) -> str:
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def classify_col(name: str):
    """Return (group, closing_flag) or None if excluded/identity/label."""
    if name in EXCLUDE_COLS or name in IDENTITY_COLS or name in LABEL_COLS:
        return None
    m = RE_AH_LINE_H.match(name)
    if m:
        return ("ah_line", False)
    if name == "AHCh":
        return ("ah_line", True)
    m = RE_AH_LINE_BOOK.match(name)
    if m:
        return ("ah_line", False)  # book-specific handicap line (pre-closing)
    m = RE_AH_PRICE.match(name)
    if m:
        return ("ah_price", bool(m.group("c")))
    m = RE_OU.match(name)
    if m:
        return ("ou", bool(m.group("c")))
    m = RE_1X2.match(name)
    if m:
        return ("1x2", bool(m.group("c")))
    return ("meta", False)


def parse_float(s: str):
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def convert_utc(local_date, time_str, tz_name):
    tz = ZoneInfo(tz_name)
    hh, mm = int(time_str[:2]), int(time_str[3:5])
    dt0 = datetime(local_date.year, local_date.month, local_date.day, hh, mm,
                   tzinfo=tz, fold=0)
    dt1 = dt0.replace(fold=1)
    ambiguous = dt0.astimezone(timezone.utc) != dt1.astimezone(timezone.utc)
    utc = dt0.astimezone(timezone.utc)
    anomalous = utc.date() != local_date or not (9 <= utc.hour <= 23)
    return utc.isoformat(), ambiguous, anomalous


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"stages": {}}
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sha_man = json.loads(SHA_MANIFEST_PATH.read_text(encoding="utf-8"))

    # ---------------- S1 validation ----------------
    s1 = {"files_checked": 0, "mismatches": []}
    for m in man["canonical"]:
        p = Path(m["path"])
        if not p.exists():
            s1["mismatches"].append(f"{m['file']}: MISSING"); continue
        if sha256_file(p) != m["sha256"]:
            s1["mismatches"].append(f"{m['file']}: SHA256 MISMATCH"); continue
        with p.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if len(rows) != m["rows"]:
            s1["mismatches"].append(f"{m['file']}: rows {len(rows)} != {m['rows']}"); continue
        if not ({"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"} <= set(rows[0].keys())):
            s1["mismatches"].append(f"{m['file']}: schema not recognizable"); continue
        s1["files_checked"] += 1
    report["stages"]["S1"] = s1
    if s1["mismatches"]:
        print("S1 FAIL:", s1["mismatches"])
        (BUILD / "build_report_fail.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return 1
    print(f"S1 OK: {s1['files_checked']}/55 files verified (sha256+rows+schema)")

    # ---------------- S2 projection ----------------
    records = []
    league_raw = Counter()
    league_qc = Counter()
    empty_rows = []
    nulled_price_cells = []
    team_anomalies = []
    date_failures = []
    ftr_mismatches = []
    time_missing_datetime = 0
    ambiguous_rows = []
    utc_anomaly_rows = []

    TEAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'&-]{0,29}$")
    for m in man["canonical"]:
        p = Path(m["path"])
        with p.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for i, r in enumerate(rows, start=2):
            league = (r.get("Div") or "").strip()
            home = (r.get("HomeTeam") or "").strip()
            away = (r.get("AwayTeam") or "").strip()
            date_s = (r.get("Date") or "").strip()
            league_raw[m["league"]] += 1  # raw count attributed to manifest league
            if not home and not away and not date_s:
                empty_rows.append((m["file"], i))
                continue
            league_qc[m["league"]] += 1
            d = parse_date(date_s)
            if d is None:
                date_failures.append((m["file"], i, date_s)); continue
            season = season_of(d)
            fthg_s = (r.get("FTHG") or "").strip()
            ftag_s = (r.get("FTAG") or "").strip()
            ftr_s = (r.get("FTR") or "").strip()
            if fthg_s.isdigit() and ftag_s.isdigit():
                exp = "H" if int(fthg_s) > int(ftag_s) else ("A" if int(ftag_s) > int(fthg_s) else "D")
                if exp != ftr_s:
                    ftr_mismatches.append((m["file"], i))
            if not TEAM_RE.match(home) or not TEAM_RE.match(away):
                team_anomalies.append((m["file"], i, home, away))
            tier = "TIER_DATE_ONLY" if season in DATE_ONLY_SEASONS else "TIER_DATETIME"
            time_s = (r.get("Time") or "").strip()
            t_local = time_s if re.match(r"^\d{2}:\d{2}$", time_s) else None
            kickoff_utc = None
            if tier == "TIER_DATETIME":
                if t_local:
                    try:
                        kickoff_utc, amb, anom = convert_utc(d, t_local, LEAGUE_TZ[league])
                        if amb:
                            ambiguous_rows.append((m["file"], i))
                        if anom:
                            utc_anomaly_rows.append((m["file"], i))
                    except Exception:  # noqa: BLE001
                        kickoff_utc = None
                else:
                    time_missing_datetime += 1
            pre, clos, meta = {}, {}, {}
            for col, val in r.items():
                c = classify_col(col)
                if c is None:
                    continue
                group, closing = c
                if group == "meta":
                    if val.strip() != "":
                        meta[col] = val.strip()
                    continue
                fv = parse_float(val)
                if fv is None:
                    continue  # blank -> absent (NULL semantics)
                if group == "ah_line":
                    (clos if closing else pre)[col] = fv
                    continue
                if fv <= 1.0:
                    # frozen schema gate: odds > 1.0 else NULL (recorded, not an error)
                    nulled_price_cells.append((m["file"], i, col, val))
                    continue
                (clos if closing else pre)[col] = fv
            records.append(OrderedDict([
                ("league", league), ("season", season),
                ("home_team", home), ("away_team", away),
                ("kickoff_date", d.isoformat()),
                ("kickoff_time_local", t_local),
                ("kickoff_utc", kickoff_utc),
                ("temporal_tier", tier),
                ("referee", (r.get("Referee") or "").strip() or None),
                ("label", {"fthg": int(fthg_s), "ftag": int(ftag_s), "ftr": ftr_s}),
                ("odds", {"preclosing": pre, "closing": clos, "meta": meta}),
                ("provenance", {"source_file": m["file"], "source_row": i,
                                "source_hash": m["sha256"]}),
            ]))
    report["stages"]["S2"] = {"projected": len(records), "empty_rows_excluded": empty_rows,
                              "league_raw": dict(league_raw), "league_qc": dict(league_qc),
                              "nulled_price_cells": nulled_price_cells}
    print(f"S2 OK: projected {len(records)} rows; empty excluded {len(empty_rows)}; "
          f"nulled invalid price cells {len(nulled_price_cells)}")

    # ---------------- S3 quality gate ----------------
    dup = Counter((r["league"], r["season"], r["home_team"], r["away_team"],
                   r["kickoff_date"]) for r in records)
    dups = {k: v for k, v in dup.items() if v > 1}
    prov_ok = all(r["provenance"]["source_file"] and r["provenance"]["source_row"]
                  and r["provenance"]["source_hash"] for r in records)
    identity_label_ok = all(r["league"] and r["home_team"] and r["away_team"]
                            and r["kickoff_date"] and r["label"]["ftr"] for r in records)
    # leakage: output must contain no post-stat / xG / half-time fields
    forbidden = set()
    for r in records:
        forbidden |= set(r.keys()) & EXCLUDE_COLS
    s3 = {
        "raw_rows": sum(league_raw.values()),
        "basic_qc_rows": len(records),
        "duplicate_match_count": len(dups),
        "date_failures": date_failures,
        "team_anomalies": team_anomalies,
        "ftr_mismatches": ftr_mismatches,
        "nulled_price_cells": nulled_price_cells,
        "provenance_complete": prov_ok,
        "identity_label_complete": identity_label_ok,
        "forbidden_fields_in_output": sorted(forbidden),
        "league_raw": dict(league_raw),
        "league_qc": dict(league_qc),
        "empty_rows": empty_rows,
    }
    gates = {
        "raw==19765": sum(league_raw.values()) == EXPECTED_RAW,
        "qc==19763": len(records) == EXPECTED_QC,
        "league_raw_expected": dict(league_raw) == EXPECTED_RAW_PER_LEAGUE,
        "league_qc_expected": dict(league_qc) == EXPECTED_QC_PER_LEAGUE,
        "no_duplicates": not dups,
        "no_date_failures": not date_failures,
        "no_team_anomalies": not team_anomalies,
        "no_ftr_mismatches": not ftr_mismatches,
        "null_policy_applied_no_remaining_invalid": (not forbidden and all(
            (classify_col(col) is not None and classify_col(col)[0] == "ah_line")
            or v > 1.0
            for r in records for grp in ("preclosing", "closing")
            for col, v in r["odds"][grp].items())),
        "provenance_complete": prov_ok,
        "identity_label_complete": identity_label_ok,
        "empty_rows_exactly_2": len(empty_rows) == 2,
    }
    s3["gates"] = gates
    report["stages"]["S3"] = s3
    for k, v in gates.items():
        print(f"S3 gate {k}: {'PASS' if v else 'FAIL'}")
    if not all(gates.values()):
        print("S3 FAIL - STOP")
        (BUILD / "build_report_fail.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        return 2

    # ---------------- S4 temporal tiers + DST validation ----------------
    date_only = [r for r in records if r["temporal_tier"] == "TIER_DATE_ONLY"]
    dt_tier = [r for r in records if r["temporal_tier"] == "TIER_DATETIME"]
    utc_ok = sum(1 for r in dt_tier if r["kickoff_utc"])
    dst_validation = "PASS" if not ambiguous_rows and not utc_anomaly_rows else "FAIL"
    s4 = {
        "tier_date_only_rows": len(date_only),
        "tier_datetime_rows": len(dt_tier),
        "datetime_with_utc": utc_ok,
        "datetime_missing_time": time_missing_datetime,
        "ambiguous_fold_rows": len(ambiguous_rows),
        "utc_date_mismatch_rows": len(utc_anomaly_rows),
        "dst_validation": dst_validation,
    }
    report["stages"]["S4"] = s4
    print(f"S4 tiers: DATE_ONLY={len(date_only)} DATETIME={len(dt_tier)} "
          f"utc_ok={utc_ok} missing_time={time_missing_datetime} "
          f"ambiguous={len(ambiguous_rows)} anomalies={len(utc_anomaly_rows)}")
    if dst_validation == "FAIL":
        print("S4 DST validation FAIL - zeroing UTC, keeping local datetime (per policy)")
        for r in records:
            r["kickoff_utc"] = None
        (BUILD / "build_report_fail.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        return 3

    # ---------------- S5 output ----------------
    records.sort(key=lambda r: (r["league"], r["season"], r["kickoff_date"],
                                r["home_team"], r["away_team"]))
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records]
    dataset_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    dataset_path = OUT / "baseline_dataset.jsonl"
    dataset_path.write_bytes(dataset_bytes)

    schema_fields = ["league", "season", "home_team", "away_team", "kickoff_date",
                     "kickoff_time_local", "kickoff_utc", "temporal_tier", "referee",
                     "label.fthg", "label.ftag", "label.ftr",
                     "odds.preclosing.*", "odds.closing.*", "odds.meta.*",
                     "provenance.source_file", "provenance.source_row", "provenance.source_hash"]
    spec_files = {
        "DATASET_CONTRACT.md": BUILD / "DATASET_CONTRACT.md",
        "CANONICAL_SCHEMA.md": BUILD / "CANONICAL_SCHEMA.md",
        "FEATURE_AVAILABILITY_REGISTRY.md": BUILD / "FEATURE_AVAILABILITY_REGISTRY.md",
        "DATASET_BUILD_SPEC.md": BUILD / "DATASET_BUILD_SPEC.md",
        "DATASET_FREEZE_SPEC.md": BUILD / "DATASET_FREEZE_SPEC.md",
    }
    spec_hashes = {k: sha256_file(v) if v.exists() else "MISSING" for k, v in spec_files.items()}
    build_manifest = {
        "dataset_id": "HIST_FD_5L_2015_2026",
        "dataset_version": "1.0.0",
        "status": "BUILT",
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_version": "policy.v1",
        "row_count": len(records),
        "tier_counts": {"TIER_DATE_ONLY": len(date_only), "TIER_DATETIME": len(dt_tier)},
        "schema_fingerprint": sha256_bytes(json.dumps(schema_fields).encode()),
        "source_fingerprint": {
            "manifest_ref": "backtest_output/hist_csv_audit/manifests/sha256_manifest.json",
            "sha256_of_sha256_manifest": sha256_file(SHA_MANIFEST_PATH),
        },
        "row_checksum": sha256_bytes(dataset_bytes),
        "build_config": {
            "build_script_sha256": sha256_file(Path(__file__)),
            "spec_sha256": spec_hashes,
            "canonical_manifest_sha256": sha256_file(MANIFEST_PATH),
        },
        "limitations": ["L1", "L2", "L3", "L4", "L5"],
        "dq_report_ref": "backtest_output/hist_csv_audit/DATASET_QUALIFICATION_REPORT.md",
        "nulled_price_cells": nulled_price_cells,
    }
    (OUT / "build_manifest.json").write_text(
        json.dumps(build_manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "tier_summary.json").write_text(json.dumps({
        "tier_date_only_rows": len(date_only),
        "tier_datetime_rows": len(dt_tier),
        "datetime_with_utc": utc_ok,
        "datetime_missing_time": time_missing_datetime,
        "odds_coverage": {
            "rows_with_any_preclosing": sum(1 for r in records if r["odds"]["preclosing"]),
            "rows_with_any_closing": sum(1 for r in records if r["odds"]["closing"]),
        },
    }, indent=1), encoding="utf-8")
    report["stages"]["S5"] = {
        "dataset_path": str(dataset_path), "row_count": len(records),
        "row_checksum": build_manifest["row_checksum"],
        "schema_fingerprint": build_manifest["schema_fingerprint"],
    }
    (BUILD / "build_report.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"S5 OK: {dataset_path} rows={len(records)} checksum={build_manifest['row_checksum'][:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
