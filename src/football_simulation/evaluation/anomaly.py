"""V1.1 Anomaly Detector.

After running paired simulations, automatically flag outcomes that VIOLATE
basic football causality (e.g. weak team dominating the strong one, a red
card RAISING the carded team's win probability, tired teams improving late).

The detector only measures; it never patches results.  A flagged anomaly
means the causal chain itself must be inspected and fixed (spec V1.1 sec 4/5).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.evaluation.reality import (
    RealityHarness,
    TeamSpec,
    balanced_pair,
    batch_metrics,
    paired_deltas,
)
from football_simulation.models.base import Side
from football_simulation.models.world import RefereeMatchState, WeatherState


class AnomalyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str = ""
    evidence: Dict[str, Any] = Field(default_factory=dict)


def _strong_weak_pair() -> Dict[str, TeamSpec]:
    strong = TeamSpec(team_id="strong", name="Strong", attack=0.78, defense=0.75,
                      midfield=0.75, goalkeeper=0.74, depth=0.7)
    weak = TeamSpec(team_id="weak", name="Weak", attack=0.42, defense=0.45,
                    midfield=0.45, goalkeeper=0.46, depth=0.4)
    return {"strong": strong, "weak": weak}


class AnomalyDetector:
    def __init__(self, harness: Optional[RealityHarness] = None):
        self.harness = harness or RealityHarness()

    # ------------------------------------------------------------------
    def run_all(self, n: int = 400, seed: int = 2024) -> List[AnomalyCheck]:
        checks: List[AnomalyCheck] = []
        checks.append(self.check_strong_beats_weak(n, seed))
        checks.append(self.check_weak_never_dominant(n, seed))
        checks.append(self.check_red_card_hurts(n, seed))
        checks.append(self.check_down_a_man_shot_share(n, seed))
        checks.append(self.check_fatigue_no_late_improvement(n, seed))
        checks.append(self.check_xg_calibration(n, seed))
        checks.append(self.check_no_goal_explosion(n, seed))
        checks.append(self.check_second_half_goals(n, seed))
        checks.append(self.check_referee_yellow_monotonic(n, seed))
        checks.append(self.check_rain_never_increases_goals(n, seed))
        return checks

    # ------------------------------------------------------------------
    def check_strong_beats_weak(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = _strong_weak_pair()
        home, _ = self.harness.build_world(specs["strong"], specs["weak"])
        worlds = {"strong": home}
        matchups = {"strong": home.matchup_state}
        batches = self.harness.run_pair(worlds, matchups, n=n, seed=seed)
        m = batch_metrics(batches["strong"])
        passed = m["home_win"] > m["away_win"] + 0.05
        return AnomalyCheck(
            name="strong_team_beats_weak",
            passed=passed,
            detail=f"strong home_win={m['home_win']:.3f} vs weak away_win={m['away_win']:.3f}",
            evidence=m,
        )

    def check_weak_never_dominant(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = _strong_weak_pair()
        home, _ = self.harness.build_world(specs["strong"], specs["weak"])
        batches = self.harness.run_pair({"s": home}, {"s": home.matchup_state}, n=n, seed=seed)
        m = batch_metrics(batches["s"])
        passed = m["away_win"] < 0.45
        return AnomalyCheck(
            name="weak_team_not_dominant",
            passed=passed,
            detail=f"weak team win rate {m['away_win']:.3f} (must stay < 0.45 across the batch)",
            evidence={"away_win": m["away_win"]},
        )

    def check_red_card_hurts(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1])
        treated, _ = self.harness.build_world(specs[0], specs[1], red_home=1)
        batches = self.harness.run_pair(
            {"control": control, "red": treated},
            {"control": control.matchup_state, "red": treated.matchup_state},
            n=n, seed=seed,
        )
        m_control = batch_metrics(batches["control"])
        m_red = batch_metrics(batches["red"])
        passed = m_red["home_win"] < m_control["home_win"] and m_red["away_win"] > m_control["away_win"]
        return AnomalyCheck(
            name="red_card_hurts_card_side",
            passed=passed,
            detail=(f"control home_win={m_control['home_win']:.3f} -> with red card "
                    f"{m_red['home_win']:.3f}; away_win {m_control['away_win']:.3f} -> {m_red['away_win']:.3f}"),
            evidence={"control": m_control, "red": m_red},
        )

    def check_down_a_man_shot_share(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1])
        treated, _ = self.harness.build_world(specs[0], specs[1], red_home=1)
        batches = self.harness.run_pair(
            {"control": control, "red": treated},
            {"control": control.matchup_state, "red": treated.matchup_state},
            n=n, seed=seed,
        )
        m_control = batch_metrics(batches["control"])
        m_red = batch_metrics(batches["red"])
        passed = m_red["shots_home_share"] < m_control["shots_home_share"]
        return AnomalyCheck(
            name="down_a_man_shot_share_drops",
            passed=passed,
            detail=(f"home shot share {m_control['shots_home_share']:.3f} -> "
                    f"{m_red['shots_home_share']:.3f} after red card"),
            evidence={"control_share": m_control["shots_home_share"], "red_share": m_red["shots_home_share"]},
        )

    def check_fatigue_no_late_improvement(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        fresh_w, _ = self.harness.build_world(specs[0], specs[1], minute=80)
        tired_w, _ = self.harness.build_world(specs[0], specs[1], minute=80, fatigue_home=0.65)

        # MECHANISM check (deterministic, state-level): attacking a tired team
        # must be easier, and the tired team must create less.
        p_fresh = self.harness.event_agent.per_minute_probabilities(fresh_w)
        p_tired = self.harness.event_agent.per_minute_probabilities(tired_w)
        mechanism_ok = (
            p_tired.attack_intensity_away > p_fresh.attack_intensity_away
            and p_tired.attack_intensity_home < p_fresh.attack_intensity_home
        )

        # END-TO-END bound: score-state dynamics (a tired side that trails
        # still pushes late) legitimately add noise, so only flag a
        # SUSTAINED improvement beyond 0.15 or an unbounded swing.
        control, _ = self.harness.build_world(specs[0], specs[1])
        tired, _ = self.harness.build_world(specs[0], specs[1], fatigue_home=0.65)
        batches = self.harness.run_pair(
            {"control": control, "tired": tired},
            {"control": control.matchup_state, "tired": tired.matchup_state},
            n=n, seed=seed,
        )
        m_control = batch_metrics(batches["control"])
        m_tired = batch_metrics(batches["tired"])
        diff0 = m_control["goals_away_late"] - m_control["goals_home_late"]
        diff1 = m_tired["goals_away_late"] - m_tired["goals_home_late"]
        endtoend_ok = diff1 >= diff0 - 0.15 and diff1 - diff0 < 1.5

        passed = mechanism_ok and endtoend_ok
        return AnomalyCheck(
            name="fatigue_no_late_improvement",
            passed=passed,
            detail=(
                f"mechanism: away intensity vs tired home {p_tired.attack_intensity_away:.3f} > "
                f"fresh {p_fresh.attack_intensity_away:.3f}; home intensity {p_fresh.attack_intensity_home:.3f} -> "
                f"{p_tired.attack_intensity_home:.3f}; end-to-end late goal diff {diff0:+.3f} -> {diff1:+.3f}"
            ),
            evidence={"fresh_diff": diff0, "tired_diff": diff1, "mechanism_ok": mechanism_ok},
        )

    def check_xg_calibration(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        home, _ = self.harness.build_world(specs[0], specs[1])
        batches = self.harness.run_pair({"w": home}, {"w": home.matchup_state}, n=n, seed=seed)
        m = batch_metrics(batches["w"])
        xg_sum = m["xg_home"] + m["xg_away"]
        ratio = xg_sum / max(1e-9, m["exp_goals"])
        passed = abs(m["exp_goals"] - xg_sum) < 0.35
        return AnomalyCheck(
            name="xg_matches_goals",
            passed=passed,
            detail=f"avg goals={m['exp_goals']:.2f} vs xG={xg_sum:.2f} (ratio {ratio:.2f})",
            evidence={"goals": m["exp_goals"], "xg": xg_sum},
        )

    def check_no_goal_explosion(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        home, _ = self.harness.build_world(specs[0], specs[1])
        batches = self.harness.run_pair({"w": home}, {"w": home.matchup_state}, n=n, seed=seed)
        max_goals = max(m.score_home + m.score_away for m in batches["w"].results)
        avg = sum(m.score_home + m.score_away for m in batches["w"].results) / n
        passed = max_goals <= 11 and 1.5 <= avg <= 4.0
        return AnomalyCheck(
            name="no_goal_explosion",
            passed=passed,
            detail=f"max goals in batch {max_goals}, avg {avg:.2f}",
            evidence={"max_goals": max_goals, "avg_goals": avg},
        )

    def check_second_half_goals(self, n: int = 400, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        home, _ = self.harness.build_world(specs[0], specs[1])
        batches = self.harness.run_pair({"w": home}, {"w": home.matchup_state}, n=n, seed=seed)
        m = batch_metrics(batches["w"])
        # second halves (incl. 75+) normally produce >= first halves
        second_total = m["goals_second"] + m["goals_late"]
        passed = second_total >= 0.8 * m["goals_first"]
        return AnomalyCheck(
            name="second_half_goals_not_fewer",
            passed=passed,
            detail=f"first-half goals {m['goals_first']:.2f}, second-half {second_total:.2f}",
            evidence={"first": m["goals_first"], "second": second_total},
        )

    def check_referee_yellow_monotonic(self, n: int = 300, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        ref_low = RefereeMatchState(known=True, yellow_card_tendency=0.35,
                                    red_card_tendency=0.5, penalty_tendency=0.5,
                                    foul_tolerance=0.5)
        ref_high = RefereeMatchState(known=True, yellow_card_tendency=0.7,
                                     red_card_tendency=0.5, penalty_tendency=0.5,
                                     foul_tolerance=0.5)
        low, _ = self.harness.build_world(specs[0], specs[1], referee=ref_low)
        high, _ = self.harness.build_world(specs[0], specs[1], referee=ref_high)
        batches = self.harness.run_pair(
            {"low": low, "high": high},
            {"low": low.matchup_state, "high": high.matchup_state}, n=n, seed=seed)
        m_low = batch_metrics(batches["low"])
        m_high = batch_metrics(batches["high"])
        passed = m_high["yellows"] > m_low["yellows"]
        return AnomalyCheck(
            name="referee_yellow_tendency_monotonic",
            passed=passed,
            detail=f"yellows/match low-tendency {m_low['yellows']:.2f} vs high-tendency {m_high['yellows']:.2f}",
            evidence={"low": m_low["yellows"], "high": m_high["yellows"]},
        )

    def check_rain_never_increases_goals(self, n: int = 300, seed: int = 2024) -> AnomalyCheck:
        specs = balanced_pair("home", "away")
        dry, _ = self.harness.build_world(specs[0], specs[1],
                                          weather=WeatherState(known=True, rain=0.0, impact="low"))
        wet, _ = self.harness.build_world(specs[0], specs[1],
                                          weather=WeatherState(known=True, rain=0.9, impact="high"))
        batches = self.harness.run_pair(
            {"dry": dry, "wet": wet},
            {"dry": dry.matchup_state, "wet": wet.matchup_state}, n=n, seed=seed)
        m_dry = batch_metrics(batches["dry"])
        m_wet = batch_metrics(batches["wet"])
        passed = m_wet["exp_goals"] <= m_dry["exp_goals"] + 0.15
        return AnomalyCheck(
            name="rain_does_not_increase_goals",
            passed=passed,
            detail=f"goals dry {m_dry['exp_goals']:.2f} vs heavy rain {m_wet['exp_goals']:.2f}",
            evidence={"dry": m_dry["exp_goals"], "wet": m_wet["exp_goals"]},
        )
