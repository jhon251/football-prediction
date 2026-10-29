"""V1.1 xG calibration sweep.

After the causal fix (goal draw = xG directly, no on-target gate), the shot
quality parameters must be re-scaled so the model still produces realistic
totals (~2.5-2.8 goals, xG == goals).  This script sweeps candidate
parameters; the chosen set is written into knowledge/event_defaults.json.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.substitution import SubstitutionAgent
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.data import MockDataProvider
from football_simulation.knowledge import load_all_knowledge


def run_trial(defaults, overrides, runs=600, seed=11):
    cfg = copy.deepcopy(defaults)
    for key, value in overrides.items():
        cfg["attack"][key] = value
    director = DirectorAgent(MockDataProvider(), DirectorConfig(simulation_runs=runs, seed=seed))
    context, world, matchup, agreement, dq, lc = director.prepare_world("match-demo-001")
    knowledge = load_all_knowledge()
    rule_engine = RuleEngine(knowledge["rules"])
    sm = StateTransitionAgent(rule_engine, MomentumAgent())
    event_agent = EventTriggerAgent(cfg)
    engine = MatchSimulationEngine(
        world, rule_engine, MomentumAgent(), event_agent,
        SubstitutionAgent(), sm, matchup, SimulationConfig(default_runs=runs),
    )
    batch = engine.simulate_n_matches(n=runs, base_seed=seed)
    goals = sum(m.score_home + m.score_away for m in batch.results) / runs
    xg = sum(m.home_stats.xg + m.away_stats.xg for m in batch.results) / runs
    shots = sum(m.home_stats.shots + m.away_stats.shots for m in batch.results) / runs
    sot = sum(m.home_stats.shots_on_target + m.away_stats.shots_on_target for m in batch.results) / runs
    draws = sum(1 for m in batch.results if m.score_home == m.score_away) / runs
    home_wins = sum(1 for m in batch.results if m.score_home > m.score_away) / runs
    return goals, xg, shots, sot, home_wins, draws


def main():
    knowledge = load_all_knowledge()
    defaults = copy.deepcopy(knowledge["event_defaults"])
    print(f"baseline params: mean={defaults['attack']['shot_quality_mean']}, "
          f"sigma={defaults['attack']['shot_quality_sigma']}, "
          f"big={defaults['attack']['big_chance_xg_mean']}, counter={defaults['attack']['counter_shot_quality_bonus']}")
    trials = [
        {"shot_quality_mean": 0.068, "shot_quality_sigma": 0.37,
         "big_chance_xg_mean": 0.23, "counter_shot_quality_bonus": 0.04},
        {"shot_quality_mean": 0.065, "shot_quality_sigma": 0.37,
         "big_chance_xg_mean": 0.23, "counter_shot_quality_bonus": 0.04},
    ]
    for i, trial in enumerate(trials):
        goals, xg, shots, sot, hw, dr = run_trial(defaults, trial)
        print(f"trial {i}: {trial}")
        print(f"  goals={goals:.2f} xg={xg:.2f} shots={shots:.1f} sot={sot:.1f} "
              f"home_win={hw:.3f} draw={dr:.3f} | xg/goals={xg/max(goals,1e-9):.2f}")


if __name__ == "__main__":
    main()
