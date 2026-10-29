"""V1.2 Real-Data Onboarding: full profile of the raw E0.csv.

This is a DATA-ONLY tool: it never predicts and never touches the simulation.
Output: per-field dictionary, missing/duplicate/date/team/odds/temporal checks.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class CsvProfile:
    def __init__(self, path: Path):
        self.path = Path(path)
        with self.path.open(encoding="utf-8-sig", errors="replace") as handle:
            reader = csv.DictReader(handle)
            self.fieldnames = list(reader.fieldnames or [])
            self.rows = [dict(row) for row in reader]

    # ------------------------------------------------------------------
    def basic_stats(self) -> Dict[str, Any]:
        return {
            "fields": len(self.fieldnames),
            "rows": len(self.rows),
        }

    def date_range(self) -> Tuple[Optional[str], Optional[str]]:
        dates = []
        for row in self.rows:
            parsed = self._parse_date(row.get("Date", ""))
            if parsed:
                dates.append(parsed)
        if not dates:
            return None, None
        return min(dates).strftime("%Y-%m-%d"), max(dates).strftime("%Y-%m-%d")

    def teams(self) -> Dict[str, Any]:
        teams: Counter = Counter()
        for row in self.rows:
            teams[row.get("HomeTeam", "")] += 1
            teams[row.get("AwayTeam", "")] += 1
        named = {t for t in teams if t.strip()}
        return {
            "distinct_teams": len(named),
            "match_counts": dict(teams.most_common()),
        }

    def duplicates(self) -> List[str]:
        seen = set()
        duplicates = []
        for i, row in enumerate(self.rows):
            key = (row.get("Date"), row.get("HomeTeam"), row.get("AwayTeam"))
            if key in seen:
                duplicates.append(f"row {i + 2}: {key}")
            seen.add(key)
        return duplicates

    def missing_by_column(self) -> Dict[str, int]:
        missing: Dict[str, int] = {}
        for field in self.fieldnames:
            count = sum(1 for row in self.rows if (row.get(field) or "").strip() == "")
            if count:
                missing[field] = count
        return missing

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        try:
            day, month, year = value.split("/")
            return datetime(int(year), int(month), int(day))
        except (ValueError, AttributeError):
            return None

    def date_validity(self) -> Dict[str, Any]:
        problems: List[str] = []
        parsed: List[datetime] = []
        for i, row in enumerate(self.rows):
            date = self._parse_date(row.get("Date", ""))
            if date is None:
                problems.append(f"row {i + 2}: unparseable date {row.get('Date')!r}")
            else:
                parsed.append(date)
        if parsed:
            first, last = min(parsed), max(parsed)
            span = (last - first).days
            if not (270 <= span <= 340):
                problems.append(f"season span {span} days looks wrong (expected ~270-340)")
            # no out-of-season stragglers
            for i, row in enumerate(self.rows):
                date = self._parse_date(row.get("Date", ""))
                if date and (date < first or date > last):
                    problems.append(f"row {i + 2}: out-of-range date {row.get('Date')}")
        return {"problems": problems, "count": len(parsed)}

    def temporal_validity(self) -> List[str]:
        """HT <= FT consistency and FTR/HTR code agreement."""
        problems: List[str] = []
        for i, row in enumerate(self.rows):
            def num(key: str) -> Optional[int]:
                try:
                    return int(row.get(key))
                except (TypeError, ValueError):
                    return None
            fthg, ftag, hthg, htag = num("FTHG"), num("FTAG"), num("HTHG"), num("HTAG")
            if None in (fthg, ftag, hthg, htag):
                problems.append(f"row {i + 2}: non-numeric goals")
                continue
            if hthg > fthg or htag > ftag:
                problems.append(f"row {i + 2}: HT > FT goals")
            expected_ftr = "H" if fthg > ftag else ("A" if fthg < ftag else "D")
            if row.get("FTR") not in (expected_ftr, "", None):
                problems.append(f"row {i + 2}: FTR {row.get('FTR')!r} != goals {fthg}-{ftag}")
            expected_htr = "H" if hthg > htag else ("A" if hthg < htag else "D")
            if row.get("HTR") not in (expected_htr, "", None):
                problems.append(f"row {i + 2}: HTR {row.get('HTR')!r} != HT goals {hthg}-{htag}")
        return problems

    def odds_validity(self) -> Dict[str, Any]:
        problems: List[str] = []
        odds_fields = [f for f in self.fieldnames
                       if not f.endswith("h") and f[:1].isupper() and f not in
                       ("Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG",
                        "FTR", "HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST",
                        "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR")]
        for i, row in enumerate(self.rows):
            for field in odds_fields:
                value = (row.get(field) or "").strip()
                if not value:
                    continue
                try:
                    number = float(value)
                except ValueError:
                    problems.append(f"row {i + 2}: {field}={value!r} not numeric")
                    continue
                if number <= 1.0:
                    problems.append(f"row {i + 2}: {field}={number} <= 1.0")
        return {"problems": problems[:20], "problem_count": len(problems),
                "odds_fields": len(odds_fields)}

    def result_field_agreement(self) -> List[str]:
        """FTR/HTR vs goals; also shots >= shots on target sanity."""
        problems: List[str] = []
        for i, row in enumerate(self.rows):
            def num(key: str) -> Optional[int]:
                try:
                    return int(row.get(key))
                except (TypeError, ValueError):
                    return None
            for prefix in ("H", "A"):
                shots = num(f"{prefix}S")
                sot = num(f"{prefix}ST")
                if shots is not None and sot is not None and sot > shots:
                    problems.append(f"row {i + 2}: {prefix}ST > {prefix}S")
        return problems

    # ------------------------------------------------------------------
    def full_report(self) -> Dict[str, Any]:
        date_problems = self.date_validity()
        temporal = self.temporal_validity()
        odds = self.odds_validity()
        stats = self.basic_stats()
        teams = self.teams()
        return {
            "file": str(self.path),
            "stats": stats,
            "date_range": self.date_range(),
            "teams": teams,
            "duplicates": self.duplicates(),
            "missing_by_column": self.missing_by_column(),
            "date_problems": date_problems["problems"],
            "temporal_problems": temporal,
            "result_field_problems": self.result_field_agreement(),
            "odds_problems": odds["problems"],
            "odds_problem_count": odds["problem_count"],
            "odds_fields": odds["odds_fields"],
        }
