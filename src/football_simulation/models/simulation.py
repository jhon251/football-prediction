"""Simulation result models (Match Simulation Engine outputs)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.events import MatchEvent


class TeamMatchStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals: int = 0
    ht_goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    xg: float = 0.0
    big_chances: int = 0
    dangerous_attacks: int = 0
    possession_avg: float = 0.5
    possession_sum: float = 0.0
    possession_samples: int = 0


class ScoreTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int
    score_home: int
    score_away: int


class SimulatedMatch(BaseModel):
    """One full simulated match (0 -> 90+)."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    seed: int
    score_home: int = 0
    score_away: int = 0
    ht_score_home: int = 0
    ht_score_away: int = 0
    home_stats: TeamMatchStats = Field(default_factory=TeamMatchStats)
    away_stats: TeamMatchStats = Field(default_factory=TeamMatchStats)
    events: List[MatchEvent] = Field(default_factory=list)
    timeline: List[ScoreTimelineEntry] = Field(default_factory=list)
    scenario_tag: str = "long_tail"
    minutes_played: int = 90


class SimulationBatch(BaseModel):
    """Aggregated Monte Carlo batch."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    runs: int
    base_seed: int
    results: List[SimulatedMatch] = Field(default_factory=list)
    keep_events: bool = False

    def result_counts(self) -> Dict[str, int]:
        counts = {"home_win": 0, "draw": 0, "away_win": 0}
        for m in self.results:
            if m.score_home > m.score_away:
                counts["home_win"] += 1
            elif m.score_home < m.score_away:
                counts["away_win"] += 1
            else:
                counts["draw"] += 1
        return counts

    def score_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for m in self.results:
            key = f"{m.score_home}-{m.score_away}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def ht_score_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for m in self.results:
            key = f"{m.ht_score_home}-{m.ht_score_away}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def scenario_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for m in self.results:
            counts[m.scenario_tag] = counts.get(m.scenario_tag, 0) + 1
        return counts

    def total_goals(self) -> List[int]:
        return [m.score_home + m.score_away for m in self.results]
