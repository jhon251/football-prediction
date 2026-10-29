"""v1.1.0 migration: season from source filename (canonical authority).

Reads v1.0.0 (never writes it). Rebuilds all rows with season := FILE_TO_SEASON.
Performs full 55-file season consistency audit, diff vs v1.0.0, provenance,
gates, freeze assembly. Any contradiction -> STOP.
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
FREEZE10 = BUILD / "freeze" / "1.0.0"
OUT11 = BUILD / "output" / "v1.1.0"
FREEZE11 = BUILD / "freeze" / "1.1.0"
MANIFEST_PATH = AUDIT / "manifests" / "canonical_manifest.json"

LEAGUE_TZ = {"E0": "Europe/London", "SP1": "Europe/Madrid", "I1": "Europe/Rome",
             "D1": "Europe/Berlin", "F1": "Europe/Paris"}
DATE_ONLY_SEASONS = {"2015-16", "2016-17", "2017-18", "2018-19"}
POST_STAT_COLS = {"Attendance", "HS", "AS", "HST", "AST", "HHW", "AHW", "HC", "AC",
                  "HF", "AF", "HFKC", "AFKC", "HO", "AO", "HY", "AY", "HR", "AR",
                  "HBP", "ABP", "HG", "AG", "Res"}
EXCLUDE_COLS = POST_STAT_COLS | {"HTHG", "HTAG", "HTR", "HxG", "AxG"}
IDENTITY_COLS = {"Div", "Date", "Time", "HomeTeam", "AwayTeam", "Referee"}
LABEL_COLS = {"FTHG", "FTAG", "FTR"}
RE_AH_LINE_H = re.compile(r"^(?P<base>[A-Za-z0-9]+?)AHh$")
RE_AH_LINE_BOOK = re.compile(r"^(?P<base>[A-Za-z0-9]+?)AH$")
RE_AH_PRICE = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)AH(?P<side>H|A)$")
RE_OU = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)(?P<mk>>2\.5|<2\.5)$")
RE_1X2 = re.compile(r"^(?P<base>[A-Za-z0-9]+?)(?P<c>C?)(?P<mk>H|D|A)$")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def file_season_of(fn: str):
    m = re.match(r"^E0(\d{2})(csv)?\.csv$", fn)
    if m:
        return f"20{m.group(1)}-{str(int(m.group(1)) + 1)[-2:]}"
    m = re.match(r"^(?:sp1|I1|D1|F1)(\d{2})\.csv$", fn, re.IGNORECASE)
    if m:
        return f"20{m.group(1)}-{str(int(m.group(1)) + 1)[-2:]}"
    m = re.match(r"^X(\d{2})~(\d{2})\.csv$", fn)
    if m:
        return f"20{m.group(1)}-{m.group(2)}"
    return None


def parse_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def season_of_date(d):
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def classify_col(name):
    if name in EXCLUDE_COLS or name in IDENTITY_COLS or name in LABEL_COLS:
        return None
    if RE_AH_LINE_H.match(name):
        return ("ah_line", False)
    if name == "AHCh":
        return ("ah_line", True)
    if RE_AH_LINE_BOOK.match(name):
        return ("ah_line", False)
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


def parse_float(s):
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
    dt0 = datetime(local_date.year, local_date.month, local_date.day, hh, mm, tzinfo=tz, fold=0)
    dt1 = dt0.replace(fold=1)
    ambiguous = dt0.astimezone(timezone.utc) != dt1.astimezone(timezone.utc)
    utc = dt0.astimezone(timezone.utc)
    anomalous = utc.date() != local_date or not (9 <= utc.hour <= 23)
    return utc.isoformat(), ambiguous, anomalous


def main() -> int:
    OUT11.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # ---- S0: season audit (all 55 files) ----
    file2season = {}
    undeterminable = []
    for m in man["canonical"]:
        s = file_season_of(m["file"])
        if s is None:
            undeterminable.append(m["file"])
        else:
            file2season[m["file"]] = s
    if undeterminable:
        print("STOP: cannot determine file season for:", undeterminable)
        return 9
    audit = []
    mismatch_total = []
    for m in man["canonical"]:
        p = Path(m["path"])
        with p.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        fseason = file2season[m["file"]]
        mism = []
        for i, r in enumerate(rows, start=2):
            d = parse_date((r.get("Date") or "").strip())
            if d is None:
                continue
            inf = season_of_date(d)
            if inf != fseason:
                mism.append({"row": i, "date": d.isoformat(),
                             "home": (r.get("HomeTeam") or "").strip(),
                             "away": (r.get("AwayTeam") or "").strip(),
                             "date_season": inf, "file_season": fseason})
        rate = len(mism) / len(rows) if rows else 0
        audit.append({"file": m["file"], "file_season": fseason, "rows": len(rows),
                      "mismatch_rows": len(mism), "mismatch_rate": round(rate, 4),
                      "mismatches": mism})
        mismatch_total.extend((m["file"], x) for x in mism)
        if rate > 0.10:
            print(f"STOP: filename/content contradiction {m['file']} rate={rate}")
            return 8
    print(f"S0 season audit: {len(audit)} files; total date-vs-filename mismatches = {len(mismatch_total)}")
    for a in audit:
        if a["mismatch_rows"]:
            print(f"   {a['file']}: {a['mismatch_rows']} mismatches (file_season={a['file_season']})")

    # ---- S1: verify 55 sources unchanged (same as v1.0.0) ----
    for m in man["canonical"]:
        if sha256_file(Path(m["path"])) != m["sha256"]:
            print("STOP: source changed:", m["file"])
            return 1
    print("S1 OK: 55/55 sources unchanged")

    # ---- S2: projection with file-season authority ----
    records = []
    nulled = []
    for m in man["canonical"]:
        p = Path(m["path"])
        with p.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        fseason = file2season[m["file"]]
        for i, r in enumerate(rows, start=2):
            home = (r.get("HomeTeam") or "").strip()
            away = (r.get("AwayTeam") or "").strip()
            date_s = (r.get("Date") or "").strip()
            if not home and not away and not date_s:
                continue
            d = parse_date(date_s)
            if d is None:
                print("STOP: date parse failure", m["file"], i, date_s)
                return 2
            season = fseason  # <-- canonical authority
            tier = "TIER_DATE_ONLY" if season in DATE_ONLY_SEASONS else "TIER_DATETIME"
            time_s = (r.get("Time") or "").strip()
            t_local = time_s if re.match(r"^\d{2}:\d{2}$", time_s) else None
            kickoff_utc = None
            if tier == "TIER_DATETIME" and t_local:
                kickoff_utc, _, _ = convert_utc(d, t_local, LEAGUE_TZ[m["league"]])
            pre, clos, meta = {}, {}, {}
            for col, val in r.items():
                c = classify_col(col)
                if c is None:
                    continue
                group, closing = c
                if group == "meta":
                    if val.strip():
                        meta[col] = val.strip()
                    continue
                fv = parse_float(val)
                if fv is None:
                    continue
                if group == "ah_line":
                    (clos if closing else pre)[col] = fv
                    continue
                if fv <= 1.0:
                    nulled.append((m["file"], i, col, val))
                    continue
                (clos if closing else pre)[col] = fv
            records.append(OrderedDict([
                ("league", m["league"]), ("season", season),
                ("home_team", home), ("away_team", away),
                ("kickoff_date", d.isoformat()),
                ("kickoff_time_local", t_local),
                ("kickoff_utc", kickoff_utc),
                ("temporal_tier", tier),
                ("referee", (r.get("Referee") or "").strip() or None),
                ("label", {"fthg": int((r.get("FTHG") or "").strip()),
                           "ftag": int((r.get("FTAG") or "").strip()),
                           "ftr": (r.get("FTR") or "").strip()}),
                ("odds", {"preclosing": pre, "closing": clos, "meta": meta}),
                ("provenance", {"source_file": m["file"], "source_row": i,
                                "source_hash": m["sha256"]}),
            ]))
    print(f"S2 OK: {len(records)} rows projected")

    # ---- S3: diff vs v1.0.0 ----
    v10 = [json.loads(l) for l in (FREEZE10 / "baseline_dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(records) != len(v10) != 19763:
        print("STOP: row count mismatch", len(records), len(v10))
        return 3
    def key_all_but_season(r):
        d = dict(r); d.pop("season"); return json.dumps(d, sort_keys=True)
    v10_by_key = Counter(key_all_but_season(r) for r in v10)
    v11_by_key = Counter(key_all_but_season(r) for r in records)
    if v10_by_key != v11_by_key:
        only10 = v10_by_key - v11_by_key
        only11 = v11_by_key - v10_by_key
        print("STOP: non-season fields changed!", dict(list(only10.items())[:3]), dict(list(only11.items())[:3]))
        return 4
    # rows whose season changed
    v10_map = {(r["provenance"]["source_file"], r["provenance"]["source_row"]): r for r in v10}
    v11_map = {(r["provenance"]["source_file"], r["provenance"]["source_row"]): r for r in records}
    changed = []
    for k, r10 in v10_map.items():
        r11 = v11_map[k]
        if r10["season"] != r11["season"]:
            changed.append((k, r10["season"], r11["season"], r10["league"], r10["kickoff_date"],
                            r10["home_team"], r10["away_team"]))
    print(f"S3 diff: {len(changed)} rows changed (season only)")
    for c in sorted(changed):
        print("   ", c)
    if len(changed) != 10 or any(c[1] != "2020-21" or c[2] != "2019-20" or c[3] != "I1" for c in changed):
        print("STOP: unexpected change set")
        return 5
    # gates
    per_season = Counter(r["season"] for r in records)
    per_league_season = Counter((r["league"], r["season"]) for r in records)
    gates = {
        "total==19763": len(records) == 19763,
        "seasons_2019_20==1725": per_season["2019-20"] == 1725,
        "seasons_2020_21==1826": per_season["2020-21"] == 1826,
        "I1_2019_20==380": per_league_season[("I1", "2019-20")] == 380,
        "I1_2020_21==380": per_league_season[("I1", "2020-21")] == 380,
        "F1_2019_20==279": per_league_season[("F1", "2019-20")] == 279,
    }
    for k, v in gates.items():
        print(f"   gate {k}: {'PASS' if v else 'FAIL'}")
    if not all(gates.values()):
        return 6

    # ---- S4/S5: tiers + output ----
    records.sort(key=lambda r: (r["league"], r["season"], r["kickoff_date"], r["home_team"], r["away_team"]))
    tier_c = Counter(r["temporal_tier"] for r in records)
    lines = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records) + "\n"
    dataset_path = OUT11 / "baseline_dataset.jsonl"
    dataset_path.write_bytes(lines.encode("utf-8"))
    row_checksum = sha256_bytes(lines.encode("utf-8"))

    schema_fields = ["league", "season", "home_team", "away_team", "kickoff_date",
                     "kickoff_time_local", "kickoff_utc", "temporal_tier", "referee",
                     "label.fthg", "label.ftag", "label.ftr",
                     "odds.preclosing.*", "odds.closing.*", "odds.meta.*",
                     "provenance.source_file", "provenance.source_row", "provenance.source_hash"]
    build_manifest = {
        "dataset_id": "HIST_FD_5L_2015_2026",
        "dataset_version": "1.1.0",
        "status": "BUILT",
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_version": "policy.v1",
        "row_count": len(records),
        "tier_counts": dict(tier_c),
        "schema_fingerprint": sha256_bytes(json.dumps(schema_fields).encode()),
        "source_fingerprint": {
            "manifest_ref": "backtest_output/hist_csv_audit/manifests/sha256_manifest.json",
            "sha256_of_sha256_manifest": sha256_file(AUDIT / "manifests" / "sha256_manifest.json"),
        },
        "row_checksum": row_checksum,
        "build_config": {
            "build_script_sha256": sha256_file(Path(__file__)),
            "canonical_manifest_sha256": sha256_file(MANIFEST_PATH),
        },
        "limitations": ["L1", "L2", "L3", "L4", "L5"],
        "migration": {
            "from_version": "1.0.0",
            "rule": "source filename season is canonical authority (supersedes date heuristic)",
            "changed_rows": len(changed),
            "evidence": "DQ_ADDENDUM_V1 correction 2 + SEASON_BOUNDARY_ADDENDUM.md",
        },
    }
    (OUT11 / "build_manifest.json").write_text(json.dumps(build_manifest, indent=1, ensure_ascii=False), encoding="utf-8")

    provenance = [{
        "v1.0.0_row": {"league": lg, "home_team": h, "away_team": a, "kickoff_date": dt,
                       "source_file": f, "source_row": row, "old_season": os_},
        "new_season": ns_,
        "reason": "Serie A 2019-20 final round postponed to 2020-08-01/02 (COVID); "
                  "source filename I119.csv = 2019-20 is authoritative",
        "rule": "source filename season > match date heuristic",
        "evidence": "SEASON_BOUNDARY_ADDENDUM.md / SEASON_BOUNDARY_CASES.json",
    } for (f, row), os_, ns_, lg, dt, h, a in changed]
    (OUT11 / "MIGRATION_1.0.0_to_1.1.0.json").write_text(
        json.dumps(provenance, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT11 / "SEASON_AUDIT_55_FILES.json").write_text(
        json.dumps({"files": audit, "total_mismatches": len(mismatch_total)}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"S4/S5 OK: dataset rows={len(records)} tier={dict(tier_c)} checksum={row_checksum[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
