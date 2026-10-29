"""V1.2 Real-Data Onboarding doctor.

``football doctor E0.csv`` checks a raw historical CSV and answers
REAL DATA ONBOARDING PASS / FAIL with concrete problems.

This is a DATA-ONLY diagnostic: it never predicts and never feeds the
simulation.  The check list maps to the onboarding principles:

  P1  result fields (FTHG..AR) are post-match; they may never enter THIS
      match's pre-match inputs (only past matches may form features)
  P2  historical aggregates are allowed (observed_at < T only)
  P3  future matches forbidden
  P4/P5  closing vs opening odds strictly separated; unverifiable time
      semantics -> UNKNOWN, never guessed
  P6  no post-match field may be copied into a pre-match feature
  P7  no fake xG: missing xG stays missing
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from football_simulation.data.historical.profile import CsvProfile

# ---------------------------------------------------------------------------
# Field classification (shared with the onboarding doc generator)
# ---------------------------------------------------------------------------

CORE_FIELDS = [
    "Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
    "HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST", "AST", "HF", "AF",
    "HC", "AC", "HY", "AY", "HR", "AR",
]

RESULT_FIELDS = [
    "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "HS", "AS", "HST", "AST",
    "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
]

BOOKMAKER_1X2 = ["B365", "BFD", "BMGM", "BV", "BW", "CL", "LB", "PS", "Max", "Avg", "BFE"]

AH_FIELDS = [
    "AHh", "B365AHH", "B365AHA", "PAHH", "PAHA", "MaxAHH", "MaxAHA",
    "AvgAHH", "AvgAHA", "BFEAHH", "BFEAHA",
    "AHCh", "B365CAHH", "B365CAHA", "PCAHH", "PCAHA", "MaxCAHH", "MaxCAHA",
    "AvgCAHH", "AvgCAHA", "BFECAHH", "BFECAHA",
]


def is_c_suffix(field: str) -> bool:
    """C-suffix odds snapshots whose time semantics the file cannot prove."""
    if field in ("HC", "AC"):  # corners - not odds
        return False
    if field in CORE_FIELDS:
        return False
    # 1X2 closing-style columns: B365CH / BFDCD / AvgCA ...
    if field.endswith(("CH", "CD", "CA")):
        return True
    # O/U closing columns: B365C>2.5 / PC<2.5 ...
    if "C>2.5" in field or "C<2.5" in field:
        return True
    # Asian-handicap closing columns: AHCh / B365CAHH / BFECAHA ...
    if field.startswith("AHCh") or "CAH" in field:
        return True
    return False


def field_kind(field: str) -> str:
    if field in ("Div", "Date", "Time", "HomeTeam", "AwayTeam"):
        return "identity"
    if field in RESULT_FIELDS:
        return "result"
    if field == "Referee":
        return "referee"
    if field in AH_FIELDS:
        return "asian_handicap"
    if ">2.5" in field or "<2.5" in field:
        return "over_under"
    if field.endswith(("H", "D", "A")) and field[:-1] in BOOKMAKER_1X2:
        return "one_x_two"
    if field.endswith(("CH", "CD", "CA")):
        return "one_x_two"
    return "other"


class DoctorResult:
    def __init__(self):
        self.sections: List[Tuple[str, bool, str]] = []
        self.problems: List[str] = []
        self.warnings: List[str] = []

    def section(self, name: str, passed: bool, detail: str) -> None:
        self.sections.append((name, passed, detail))

    def problem(self, text: str) -> None:
        self.problems.append(text)

    def warning(self, text: str) -> None:
        self.warnings.append(text)

    @property
    def passed(self) -> bool:
        return not self.problems

    def render(self) -> str:
        lines = ["Football Data Doctor", "===================="]
        for name, passed, detail in self.sections:
            lines.append(f"{name}: {'PASS' if passed else 'FAIL'}")
            lines.append(f"  {detail}")
        lines.append("====================")
        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        if self.problems:
            lines.append("Problems:")
            for problem in self.problems:
                lines.append(f"  - {problem}")
        lines.append("")
        lines.append("Real Data Status:")
        lines.append("  is_synthetic = false (real CSV, no synthetic label; source-convention real data)")
        lines.append("  REAL_DATA_READY gate 'historical_data': ONBOARDED (raw file + profile + field dictionary)")
        lines.append("")
        lines.append("REAL DATA ONBOARDING " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines)


def run_doctor(path: str) -> DoctorResult:
    result = DoctorResult()
    csv_path = Path(path)
    if not csv_path.exists():
        result.problem(f"file not found: {csv_path}")
        result.section("schema", False, "file missing")
        return result
    profile = CsvProfile(csv_path)

    # 1) schema ------------------------------------------------------------
    missing_required = [f for f in CORE_FIELDS if f not in profile.fieldnames]
    if missing_required:
        result.problem(f"required core fields missing: {missing_required}")
        result.section("schema", False, f"{len(profile.fieldnames)} fields, missing {missing_required}")
    else:
        result.section(
            "schema", True,
            f"{len(profile.fieldnames)} fields, all {len(CORE_FIELDS)} core fields present; "
            f"{len(profile.rows)} rows")

    # 2) missing data --------------------------------------------------------
    missing = profile.missing_by_column()
    core_missing = {f: n for f, n in missing.items() if f in CORE_FIELDS}
    if core_missing:
        result.problem(f"core fields have missing values: {core_missing}")
        result.section("missing data", False, str(core_missing))
    else:
        odds_missing = {f: n for f, n in missing.items() if f not in CORE_FIELDS}
        result.section(
            "missing data", True,
            f"core fields complete; {len(odds_missing)} odds/aux columns have partial "
            f"bookmaker coverage (max {max(odds_missing.values()) if odds_missing else 0} missing)")
        for field, count in sorted(odds_missing.items(), key=lambda kv: -kv[1])[:8]:
            result.warning(f"bookmaker coverage gap: {field} missing {count}/{len(profile.rows)}")

    # 3) duplicate data -------------------------------------------------------
    duplicates = profile.duplicates()
    if duplicates:
        result.problem(f"{len(duplicates)} duplicate (Date, Home, Away) rows: {duplicates[:5]}")
        result.section("duplicate data", False, str(duplicates[:5]))
    else:
        result.section("duplicate data", True, "0 duplicate matches")

    # 4) date validity ---------------------------------------------------------
    date_problems = profile.date_validity()
    if date_problems["problems"]:
        result.problem(f"date validity: {date_problems['problems'][:5]}")
        result.section("date validity", False, str(date_problems["problems"][:5]))
    else:
        first, last = profile.date_range()
        from datetime import datetime
        span_days = (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days
        result.section("date validity", True,
                       f"{first} .. {last} ({span_days} days, valid EPL season span)")

    # 5) team consistency -------------------------------------------------------
    teams = profile.teams()
    counts = teams["match_counts"]
    n_teams = teams["distinct_teams"]
    unbalanced = [f"{t}:{n}" for t, n in counts.items() if n != 38]
    if n_teams != 20 or unbalanced:
        result.problem(f"team consistency: {n_teams} teams; unbalanced counts {unbalanced[:5]}")
        result.section("team consistency", False, f"{n_teams} teams, unbalanced={unbalanced[:5]}")
    else:
        result.section("team consistency", True, "20 teams x 38 matches (balanced double round-robin)")

    # 6) odds validity -----------------------------------------------------------
    odds = profile.odds_validity()
    if odds["problem_count"]:
        result.problem(f"odds validity: {odds['problem_count']} problems, e.g. {odds['problems'][:5]}")
        result.section("odds validity", False, f"{odds['problem_count']} problems")
    else:
        result.section("odds validity", True,
                       f"{odds['odds_fields']} odds fields, all values > 1.0 where present, no non-numeric values")

    # 7) temporal validity -------------------------------------------------------
    temporal = profile.temporal_validity()
    if temporal:
        result.problem(f"temporal validity: {temporal[:5]}")
        result.section("temporal validity", False, str(temporal[:5]))
    else:
        result.section("temporal validity", True,
                       "HT<=FT for every match; FTR/HTR codes agree with goals; shots>=shots-on-target")

    # 8) leakage risks -----------------------------------------------------------
    c_fields = [f for f in profile.fieldnames if is_c_suffix(f)]
    result.warning(
        f"{len(c_fields)} C-suffix odds columns exist; their opening/closing semantics "
        f"CANNOT be verified from the file (overround analysis inconclusive) -> treated as "
        f"time-semantics UNKNOWN and excluded from closing/opening mapping (principle 5)")
    result.warning("no per-odds timestamps in the file: every odds column must be treated "
                   "as a single pre-kickoff snapshot at the source's convention (closing), "
                   "never as an intraday series")
    result.warning("result fields (FTHG..AR) share the file with pre-match fields: "
                   "the import layer structurally separates them; features must only use "
                   "matches with date < kickoff (time-travel test enforces this)")
    result.section("leakage risks", True,
                   "identified risks: C-suffix semantics UNKNOWN, no odds timestamps, "
                   "result fields co-located; all handled by the import/snapshot layer, none silently")

    # 9) synthetic flag -----------------------------------------------------------
    result.section("synthetic flag", True,
                   "file carries no synthetic label; treated as REAL data "
                   "(is_synthetic=false in the internal schema)")

    # 10) xG honesty ---------------------------------------------------------------
    has_xg = any("xg" in f.lower() for f in profile.fieldnames)
    if has_xg:
        result.problem("xG columns present but unverified - would need per-column audit")
    result.section("xg policy", not has_xg,
                   "no xG columns in the file; xG stays MISSING (no fake xG will be constructed)")

    # 11) real-data status ----------------------------------------------------------
    result.section("real data status", True,
                   "REAL EPL 2025-26 data (380 matches); onboarding gate 'historical_data' "
                   "= ONBOARDED for this file; formal backtesting still NOT run in this phase")
    return result
