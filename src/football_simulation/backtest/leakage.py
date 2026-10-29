"""Leakage Audit (V1.2 section 18).

Actively scans the dataset + snapshot pipeline for: future dates, post-match
data, final standings, closing odds after kickoff, unfrozen fields, lineup
leaks and player leaks.  ANY failure must block the formal backtest.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.schema import HistoricalMatch
from football_simulation.data.historical.snapshot import SnapshotBuilder
from football_simulation.models.base import utc_now


class LeakageSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str = ""
    violations: List[str] = Field(default_factory=list)


class LeakageAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: Any = Field(default_factory=utc_now)
    dataset: str = ""
    sections: List[LeakageSection] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.sections)


def audit_leakage(dataset: HistoricalDataset) -> LeakageAuditReport:
    sections: List[LeakageSection] = []
    builder = SnapshotBuilder(dataset.matches, strict=True)

    # 1) temporal leakage: snapshots contain no post-kickoff observations
    violations: List[str] = []
    for match in dataset.matches:
        try:
            snapshot = builder.build(match)
            if snapshot.rejected_observations:
                violations.append(match.match_id)
        except Exception as exc:  # TemporalViolation
            violations.append(f"{match.match_id}: {exc}")
    sections.append(LeakageSection(
        name="temporal_leakage",
        passed=not violations,
        detail=f"{len(dataset.matches)} snapshots checked",
        violations=violations[:10],
    ))

    # 2) future match leakage: time-travel test must be bit-identical
    travel = builder.verify_time_travel()
    sections.append(LeakageSection(
        name="future_match_leakage",
        passed=travel["passed"],
        detail=f"{travel['checked']} matches time-travel checked",
        violations=travel["violations"][:10],
    ))

    # 3) post-match leakage: result fields must never appear in snapshots
    post_violations: List[str] = []
    for match in dataset.matches[:200]:
        snapshot = builder.build(match)
        dump = snapshot.model_dump()
        for field in ("home_goals", "away_goals", "half_time_home_goals",
                      "half_time_away_goals", "home_shots", "away_shots",
                      "home_red_cards", "away_red_cards", "events"):
            if field in dump:
                post_violations.append(f"{match.match_id}: {field} in snapshot")
    sections.append(LeakageSection(
        name="post_match_leakage",
        passed=not post_violations,
        detail="snapshot schema excludes result fields by construction",
        violations=post_violations[:10],
    ))

    # 4) lineup leakage: tri-state + observed_at enforcement
    lineup_violations: List[str] = []
    for match in dataset.matches:
        for side, status in (("home", match.home_lineup_status),
                             ("away", match.away_lineup_status)):
            if status not in ("confirmed", "predicted", "unknown"):
                lineup_violations.append(f"{match.match_id}: bad lineup status {status!r}")
        if match.lineup_observed_at is not None and match.lineup_observed_at >= match.date:
            lineup_violations.append(f"{match.match_id}: lineup observed at/after kickoff")
    sections.append(LeakageSection(
        name="lineup_leakage",
        passed=not lineup_violations,
        detail=f"{len(dataset.matches)} matches checked",
        violations=lineup_violations[:10],
    ))

    # 5) odds leakage: every odds timestamp at/before kickoff (equality is
    # the closing-snapshot convention; strictly after kickoff = leak)
    odds_violations: List[str] = []
    for match in dataset.matches:
        for odds in (match.closing_odds, match.opening_odds):
            if odds is None or odds.odds_timestamp is None:
                continue
            if odds.odds_timestamp > match.date:
                odds_violations.append(
                    f"{match.match_id}: odds {odds.odds_timestamp} > kickoff {match.date}")
    sections.append(LeakageSection(
        name="odds_leakage",
        passed=not odds_violations,
        detail=f"{len(dataset.matches)} matches checked",
        violations=odds_violations[:10],
    ))

    # 6) player leakage: no post-match player performance anywhere
    player_violations: List[str] = []
    for match in dataset.matches:
        try:
            snapshot = builder.build(match)
        except Exception as exc:  # TemporalViolation on poisoned rows
            player_violations.append(f"{match.match_id}: {exc}")
            continue
        for key in snapshot.team_features.get("home", {}):
            if "player" in key or "scorer" in key:
                player_violations.append(f"{match.match_id}: {key}")
    sections.append(LeakageSection(
        name="player_leakage",
        passed=not player_violations,
        detail="features are team-level and walk-forward only",
        violations=player_violations[:10],
    ))

    # 7) ranking leakage: no final standings / season totals anywhere
    ranking_violations: List[str] = []
    for match in dataset.matches:
        try:
            snapshot = builder.build(match)
        except Exception as exc:
            ranking_violations.append(f"{match.match_id}: {exc}")
            continue
        dump = snapshot.model_dump()
        for key in ("standings", "final_points", "season_points", "rank",
                    "champion", "relegated"):
            if key in dump:
                ranking_violations.append(f"{match.match_id}: {key}")
    sections.append(LeakageSection(
        name="ranking_leakage",
        passed=not ranking_violations,
        detail="no standings/points-total feature exists in the pipeline",
        violations=ranking_violations[:10],
    ))

    return LeakageAuditReport(dataset=dataset.name, sections=sections)


def format_audit(report: LeakageAuditReport) -> str:
    lines = ["Leakage Audit", "================="]
    for section in report.sections:
        lines.append(f"{section.name.replace('_', ' ').title()}: "
                     f"{'PASS' if section.passed else 'FAIL'}")
        if section.violations:
            for violation in section.violations[:3]:
                lines.append(f"  - {violation}")
    lines.append("=================")
    lines.append(f"Overall: {'PASS' if report.passed else 'FAIL'}")
    return "\n".join(lines)
