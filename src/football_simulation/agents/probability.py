"""Probability agents: statistics computed FROM simulation results.

None of these agents predicts independently - they aggregate the Monte Carlo
batch produced by the Match Simulation Engine (spec sections 28-31).
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult
from football_simulation.models.report import (
    BTTSProbability,
    GoalsLineProbability,
    HTFTProbability,
    ResultProbability,
    ScoreProbability,
)
from football_simulation.models.simulation import SimulationBatch

LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]


class ResultProbabilityAgent(BaseAgent[ResultProbability]):
    name = "ResultProbabilityAgent"
    description = "Home/Draw/Away probabilities from simulated results."

    def compute(self, batch: SimulationBatch) -> ResultProbability:
        n = max(1, batch.runs)
        counts = batch.result_counts()
        return ResultProbability(
            home_win=round(counts["home_win"] / n, 6),
            draw=round(counts["draw"] / n, 6),
            away_win=round(counts["away_win"] / n, 6),
        )

    def run(self, context: AgentContext) -> AgentResult[ResultProbability]:
        batch = context.batch
        if batch is None:
            return self.fail(context, "missing simulation batch")
        result = self.compute(batch)
        return self.ok(
            context,
            result,
            confidence=0.9,
            evidence=[
                f"home_win {result.home_win:.4f} / draw {result.draw:.4f} / away_win {result.away_win:.4f} "
                f"(sum {result.home_win + result.draw + result.away_win:.4f})"
            ],
            reasoning="Counted from the Monte Carlo batch, not predicted independently.",
        )


class ScoreProbabilityAgent(BaseAgent[ScoreProbability]):
    name = "ScoreProbabilityAgent"
    description = "Full scoreline probability matrix (0-6+, capped)."

    def compute(self, batch: SimulationBatch, cap: int = 6) -> ScoreProbability:
        n = max(1, batch.runs)
        counts = batch.score_counts()
        matrix: Dict[str, float] = {}
        for key, count in counts.items():
            h, a = key.split("-")
            hh, aa = int(h), int(a)
            hh = min(hh, cap)
            aa = min(aa, cap)
            matrix[f"{hh}-{aa}"] = matrix.get(f"{hh}-{aa}", 0.0) + count / n
        return ScoreProbability(matrix={k: round(v, 6) for k, v in matrix.items()}, max_goals_individual=cap)

    def run(self, context: AgentContext) -> AgentResult[ScoreProbability]:
        batch = _batch_from(context)
        if batch is None:
            return self.fail(context, "missing simulation batch")
        result = self.compute(batch)
        total = result.total()
        return self.ok(
            context,
            result,
            confidence=0.9,
            evidence=[f"matrix covers {len(result.matrix)} scorelines, total mass {total:.4f}"],
            reasoning="Scoreline matrix counted from simulated scorelines (0..6+ capped).",
        )


class GoalsOUProbabilityAgent(BaseAgent[GoalsLineProbability]):
    name = "GoalsOUProbabilityAgent"
    description = "Over/Under lines, BTTS and expected total goals."

    def compute(self, batch: SimulationBatch) -> tuple:
        totals = batch.total_goals()
        n = max(1, len(totals))
        counter = Counter(totals)
        over: Dict[str, float] = {}
        under: Dict[str, float] = {}
        for line in LINES:
            o = sum(1 for t in totals if t > line)
            over[str(line)] = round(o / n, 6)
            under[str(line)] = round(1 - o / n, 6)
        expected = sum(totals) / n

        # total goals distribution (0..10+)
        dist: Dict[str, float] = {}
        for total in range(0, 11):
            dist[str(total)] = round(counter.get(total, 0) / n, 6)
        dist["10+"] = round(sum(c for t, c in counter.items() if t > 10) / n, 6)

        # BTTS
        btts_yes = 0
        for m in batch.results:
            if m.score_home > 0 and m.score_away > 0:
                btts_yes += 1
        btts = BTTSProbability(yes=round(btts_yes / n, 6), no=round(1 - btts_yes / n, 6))

        goals = GoalsLineProbability(
            over=over,
            under=under,
            expected_total_goals=round(expected, 4),
            total_goals_distribution=dist,
        )
        return goals, btts

    def run(self, context: AgentContext) -> AgentResult[GoalsLineProbability]:
        batch = _batch_from(context)
        if batch is None:
            return self.fail(context, "missing simulation batch")
        goals, btts = self.compute(batch)
        evidence = [
            f"expected goals {goals.expected_total_goals:.2f}",
            f"O2.5 {goals.over['2.5']:.4f} / U2.5 {goals.under['2.5']:.4f}",
            f"BTTS yes {btts.yes:.4f}",
        ]
        return self.ok(
            context,
            goals,
            confidence=0.9,
            evidence=evidence,
            reasoning="O/U lines complementary by construction; BTTS from both-teams-scored counts.",
        )


class HTFTProbabilityAgent(BaseAgent[HTFTProbability]):
    name = "HTFTProbabilityAgent"
    description = "Half-time / full-time 9-combination matrix."

    def compute(self, batch: SimulationBatch) -> HTFTProbability:
        n = max(1, batch.runs)
        combos: Dict[str, float] = {}
        ht_counts = {"home": 0, "draw": 0, "away": 0}
        for m in batch.results:
            ht = "home" if m.ht_score_home > m.ht_score_away else (
                "away" if m.ht_score_away > m.ht_score_home else "draw"
            )
            ft = "home" if m.score_home > m.score_away else (
                "away" if m.score_away > m.score_home else "draw"
            )
            ht_counts[ht] += 1
            key = f"{ht}/{ft}"
            combos[key] = combos.get(key, 0.0) + 1 / n
        return HTFTProbability(
            combinations={k: round(v, 6) for k, v in combos.items()},
            ht_home_win=round(ht_counts["home"] / n, 6),
            ht_draw=round(ht_counts["draw"] / n, 6),
            ht_away_win=round(ht_counts["away"] / n, 6),
        )

    def run(self, context: AgentContext) -> AgentResult[HTFTProbability]:
        batch = _batch_from(context)
        if batch is None:
            return self.fail(context, "missing simulation batch")
        result = self.compute(batch)
        return self.ok(
            context,
            result,
            confidence=0.9,
            evidence=[f"HT 1X2: {result.ht_home_win:.3f}/{result.ht_draw:.3f}/{result.ht_away_win:.3f}"],
            reasoning="HT/FT combinations counted from simulated half and full time scores.",
        )


def _batch_from(context: AgentContext):
    """The Director injects the batch via ``context.batch``."""
    return context.batch
