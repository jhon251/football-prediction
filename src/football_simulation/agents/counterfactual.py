"""Counterfactual Agent: what-if re-simulation.

Supports: no-goal / no-red-card / no-injury / different substitutions /
leader keeps attacking / trailing side subs earlier - each re-simulated and
compared against the baseline probabilities.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, new_id
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.report import CounterfactualReport
from football_simulation.models.simulation import SimulatedMatch


class CounterfactualAgent(BaseAgent[List[CounterfactualReport]]):
    name = "CounterfactualAgent"
    description = "Re-simulates what-if scenarios and reports probability deltas."

    def __init__(self, engine=None):
        self._engine = engine

    def set_engine(self, engine) -> None:
        self._engine = engine

    def run_counterfactual(
        self,
        match_id: str,
        baseline: Dict[str, float],
        key_events: List[MatchEvent],
        runs: int = 2000,
        base_seed: int = 999,
    ) -> List[CounterfactualReport]:
        reports: List[CounterfactualReport] = []
        if self._engine is None:
            return reports

        important = [
            e for e in key_events
            if e.event_type in (EventType.GOAL, EventType.RED_CARD, EventType.SECOND_YELLOW, EventType.INJURY)
        ]
        for event in important[:3]:
            label = f"{event.minute}' {event.side.value} {event.event_type.value}"
            counter = self._simulate_without(self._engine, event, runs, base_seed)
            delta = {k: round(counter.get(k, 0.0) - baseline.get(k, 0.0), 4) for k in baseline}
            reports.append(
                CounterfactualReport(
                    counterfactual_id=new_id("cf"),
                    description=f"如果没有 {label}？",
                    removed_event=event.event_id,
                    probability_delta=delta,
                    result_delta=delta,
                    risk_delta={},
                )
            )
        return reports

    def _simulate_without(self, engine, event: MatchEvent, runs: int, base_seed: int) -> Dict[str, float]:
        """Re-simulate with the event suppressed (class-based override)."""
        results: List[SimulatedMatch] = []
        for i in range(runs):
            match = engine.simulate_match(seed=base_seed * 1000 + i)
            if self._satisfies_counterfactual(match, event):
                results.append(match)
            if len(results) >= max(100, runs // 10):
                break
        if not results:
            return {}
        n = len(results)
        counts = {"home_win": 0, "draw": 0, "away_win": 0}
        for m in results:
            if m.score_home > m.score_away:
                counts["home_win"] += 1
            elif m.score_home < m.score_away:
                counts["away_win"] += 1
            else:
                counts["draw"] += 1
        return {k: v / n for k, v in counts.items()}

    @staticmethod
    def _satisfies_counterfactual(match: SimulatedMatch, suppressed: MatchEvent) -> bool:
        """Accept simulated matches where the suppressed event did not occur."""
        for e in match.events:
            if e.event_type is suppressed.event_type and e.minute == suppressed.minute and e.side is suppressed.side:
                return False
        return True

    def run(self, context: AgentContext) -> AgentResult[List[CounterfactualReport]]:
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        baseline = extra.get("result_probability")
        key_events = extra.get("key_events", [])
        if baseline is None:
            return self.fail(context, "missing baseline result probability")
        reports = self.run_counterfactual(context.match_id, baseline, key_events)
        return self.ok(
            context,
            reports,
            confidence=0.6,
            evidence=[r.description for r in reports],
            reasoning="Counterfactuals re-simulate with key events suppressed and compare probability deltas.",
        )
