"""V1.1 Agent Contribution / Ablation analysis.

Runs the full Director pipeline in cumulative configurations - every agent
disabled at baseline, then enabled one at a time in a fixed order - and
measures how each agent moves the simulated probabilities.

Nothing here tunes results; it only measures marginal contributions.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.data import DataProvider, MockDataProvider
from football_simulation.models.validation import AgentContributionRow

ABLATION_ORDER = [
    "Team",
    "Coach",
    "Player",
    "Fitness",
    "Psychology",
    "Tactical",
    "Environment",
    "Referee",
    "Momentum",
    "Scenario",
    "Counterfactual",
]


class AblationRunner:
    def __init__(self, provider: Optional[DataProvider] = None):
        self.provider = provider or MockDataProvider()

    def run(
        self,
        match_id: str,
        runs: int = 500,
        seed: int = 42,
        order: Optional[List[str]] = None,
    ) -> List[AgentContributionRow]:
        order = order or ABLATION_ORDER
        rows: List[AgentContributionRow] = []

        # baseline: every listed agent disabled
        baseline = self._analyze(match_id, runs, seed, disabled=set(order))
        prev = baseline.result_probability
        rows.append(AgentContributionRow(
            config="baseline (all agents off)",
            home_win=round(prev.home_win, 4),
            draw=round(prev.draw, 4),
            away_win=round(prev.away_win, 4),
            expected_goals=round(baseline.goals_probability.expected_total_goals, 3),
            note="neutral world: no agent input",
        ))

        disabled: set = set(order)
        for agent in order:
            disabled.discard(agent)
            report = self._analyze(match_id, runs, seed, disabled=set(disabled))
            prob = report.result_probability
            rows.append(AgentContributionRow(
                config=f"+ {agent}",
                home_win=round(prob.home_win, 4),
                draw=round(prob.draw, 4),
                away_win=round(prob.away_win, 4),
                expected_goals=round(report.goals_probability.expected_total_goals, 3),
                delta_home_win=round(prob.home_win - prev.home_win, 4),
            ))
            prev = prob

        full = self._analyze(match_id, runs, seed, disabled=set())
        prob = full.result_probability
        rows.append(AgentContributionRow(
            config="full system",
            home_win=round(prob.home_win, 4),
            draw=round(prob.draw, 4),
            away_win=round(prob.away_win, 4),
            expected_goals=round(full.goals_probability.expected_total_goals, 3),
            delta_home_win=round(prob.home_win - prev.home_win, 4),
            note="all agents on",
        ))
        return rows

    @staticmethod
    def _analyze(match_id: str, runs: int, seed: int, disabled: set):
        director = DirectorAgent(
            MockDataProvider(),
            DirectorConfig(
                simulation_runs=runs,
                seed=seed,
                disabled_agents=sorted(disabled),
                run_counterfactuals="Counterfactual" not in disabled and False,
            ),
        )
        return director.analyze(match_id)
