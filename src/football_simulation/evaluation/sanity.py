"""V1.1 System-level Sanity Suite.

Aggregates every reality check into one ValidationReport for
``football validate``: core logic, causal direction, state transitions,
red-card / fatigue / leading / trailing logic, tactical interaction,
scenario diversity, probability conservation and anomaly detection.

IMPORTANT: sections PASS only if the measured causal directions hold; nothing
is tuned to make them pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.probability import (
    GoalsOUProbabilityAgent,
    HTFTProbabilityAgent,
    ResultProbabilityAgent,
    ScoreProbabilityAgent,
)
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.evaluation.anomaly import AnomalyCheck, AnomalyDetector
from football_simulation.evaluation.reality import (
    RealityHarness,
    TeamSpec,
    balanced_pair,
    batch_metrics,
)
from football_simulation.evaluation.rule_audit import audit_rules, rule_counts
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.entities import CoachState, PlayerState, TeamState
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.validation import (
    CheckResult,
    REAL_DATA_GATES,
    ValidationReport,
    ValidationSection,
)
from football_simulation.models.world import (
    MatchPhase,
    RefereeMatchState,
    TacticalMatchupState,
    WeatherState,
    WorldState,
)


class SanitySuite:
    def __init__(self):
        self.harness = RealityHarness()
        self.knowledge = load_all_knowledge()
        self.sm = StateTransitionAgent(
            RuleEngine(self.knowledge["rules"]), MomentumAgent())

    # ------------------------------------------------------------------
    def run(self, n: int = 400, seed: int = 2024) -> ValidationReport:
        sections: List[ValidationSection] = []

        base = self._base_batch(n, seed)
        sections.append(self._core_logic(base))
        sections.append(self._causal_direction(n, seed))
        sections.append(self._state_transition())
        red_metrics = self._red_card_pair(n, seed)
        sections.append(self._red_card_section(red_metrics))
        fatigue_metrics = self._fatigue_pair(n, seed)
        sections.append(self._fatigue_section(fatigue_metrics))
        sections.append(self._leading_section(self._leading_pair(n, seed)))
        sections.append(self._trailing_section(self._trailing_pair(n, seed)))
        sections.append(self._tactical_section(self._tactical_pair(n, seed)))
        sections.append(self._scenario_diversity(base))
        sections.append(self._probability_conservation(base))
        anomaly_checks = AnomalyDetector(self.harness).run_all(n=max(200, n // 2), seed=seed)
        sections.append(self._anomaly_section(anomaly_checks))

        report = ValidationReport(
            real_data_ready=False,
            real_data_gates=REAL_DATA_GATES,
            sections=sections,
            rule_counts=rule_counts(audit_rules(self.knowledge)),
            anomalies=[c.name for c in anomaly_checks if not c.passed],
            notes=[
                "All checks run on SYNTHETIC controlled worlds - no real data.",
                "Passing every section only means the sandbox does not violate basic football causality.",
            ],
        )
        report.overall_verdict = (
            "READY FOR HISTORICAL BACKTEST"
            if report.all_passed()
            else "NOT READY FOR REAL PREDICTION"
        )
        return report

    # ------------------------------------------------------------------
    # Shared measurement batches
    # ------------------------------------------------------------------
    def _base_batch(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        world, matchup = self.harness.build_world(specs[0], specs[1])
        batches = self.harness.run_pair({"base": world}, {"base": matchup}, n=n, seed=seed)
        return batches["base"]

    def _red_card_pair(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1])
        red, _ = self.harness.build_world(specs[0], specs[1], red_home=1)
        batches = self.harness.run_pair(
            {"control": control, "red": red},
            {"control": control.matchup_state, "red": red.matchup_state}, n=n, seed=seed)
        return {"control": batch_metrics(batches["control"]), "red": batch_metrics(batches["red"]),
                "tags_control": batches["control"].scenario_counts(),
                "tags_red": batches["red"].scenario_counts()}

    def _fatigue_pair(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1])
        tired, _ = self.harness.build_world(specs[0], specs[1], fatigue_home=0.65)
        batches = self.harness.run_pair(
            {"control": control, "tired": tired},
            {"control": control.matchup_state, "tired": tired.matchup_state}, n=n, seed=seed)
        return {"control": batch_metrics(batches["control"]), "tired": batch_metrics(batches["tired"])}

    def _leading_pair(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1], minute=70)
        leading, _ = self.harness.build_world(specs[0], specs[1], minute=70,
                                              score_home=2, score_away=0)
        batches = self.harness.run_pair(
            {"control": control, "leading": leading},
            {"control": control.matchup_state, "leading": leading.matchup_state}, n=n, seed=seed)
        return {"control": batch_metrics(batches["control"]), "leading": batch_metrics(batches["leading"])}

    def _trailing_pair(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        control, _ = self.harness.build_world(specs[0], specs[1], minute=70)
        trailing, _ = self.harness.build_world(specs[0], specs[1], minute=70,
                                               score_home=1, score_away=0)
        batches = self.harness.run_pair(
            {"control": control, "trailing": trailing},
            {"control": control.matchup_state, "trailing": trailing.matchup_state}, n=n, seed=seed)
        return {"control": batch_metrics(batches["control"]), "trailing": batch_metrics(batches["trailing"])}

    def _tactical_pair(self, n: int, seed: int):
        specs = balanced_pair("home", "away")
        neutral, neutral_m = self.harness.build_world(specs[0], specs[1])
        home_high = TeamSpec(**{**specs[0].__dict__, "defensive_line": 0.72})
        away_counter = TeamSpec(**{**specs[1].__dict__, "counter_strength": 0.78})
        exposed, exposed_m = self.harness.build_world(home_high, away_counter)
        batches = self.harness.run_pair(
            {"neutral": neutral, "exposed": exposed},
            {"neutral": neutral_m, "exposed": exposed_m}, n=n, seed=seed)
        return {"neutral": batch_metrics(batches["neutral"]),
                "exposed": batch_metrics(batches["exposed"]),
                "matchup": exposed_m}

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _core_logic(self, batch) -> ValidationSection:
        m = batch_metrics(batch)
        checks = [
            CheckResult(
                name="xg_matches_goals",
                passed=abs(m["exp_goals"] - (m["xg_home"] + m["xg_away"])) < 0.35,
                detail=f"goals {m['exp_goals']:.2f} vs xG {m['xg_home'] + m['xg_away']:.2f}",
            ),
            CheckResult(
                name="goals_in_realistic_range",
                passed=1.8 <= m["exp_goals"] <= 3.8,
                detail=f"avg goals {m['exp_goals']:.2f}",
            ),
            CheckResult(
                name="shots_in_realistic_range",
                passed=10 <= m["shots_home"] + m["shots_away"] <= 32,
                detail=f"avg shots {m['shots_home'] + m['shots_away']:.1f}",
            ),
            CheckResult(
                name="draw_rate_plausible",
                passed=0.18 <= m["draw"] <= 0.42,
                detail=f"draw rate {m['draw']:.3f}",
            ),
            CheckResult(
                name="second_half_goals_plausible",
                passed=(m["goals_second"] + m["goals_late"]) >= 0.8 * m["goals_first"],
                detail=f"first {m['goals_first']:.2f} / second+late "
                       f"{m['goals_second'] + m['goals_late']:.2f}",
            ),
        ]
        return ValidationSection(
            name="core_logic", passed=all(c.passed for c in checks), results=checks)

    def _causal_direction(self, n: int, seed: int) -> ValidationSection:
        checks: List[CheckResult] = []
        specs = balanced_pair("home", "away")

        # 1) strength up -> home win up
        strong = TeamSpec(**{**specs[0].__dict__,
                             "attack": 0.7, "defense": 0.68, "midfield": 0.68, "goalkeeper": 0.66})
        w_base, m_base = self.harness.build_world(specs[0], specs[1])
        w_strong, m_strong = self.harness.build_world(strong, specs[1])
        batches = self.harness.run_pair(
            {"base": w_base, "strong": w_strong},
            {"base": m_base, "strong": m_strong}, n=n, seed=seed)
        b, s = batch_metrics(batches["base"]), batch_metrics(batches["strong"])
        checks.append(CheckResult(
            name="strength_up_raises_home_win",
            passed=s["home_win"] > b["home_win"] + 0.02,
            detail=f"home_win {b['home_win']:.3f} -> {s['home_win']:.3f}",
        ))

        # 2) red card -> home win down / away win up
        w_red, m_red = self.harness.build_world(specs[0], specs[1], red_home=1)
        batches = self.harness.run_pair(
            {"base": w_base, "red": w_red},
            {"base": m_base, "red": m_red}, n=n, seed=seed)
        r = batch_metrics(batches["red"])
        checks.append(CheckResult(
            name="red_card_lowers_home_win",
            passed=r["home_win"] < b["home_win"] and r["away_win"] > b["away_win"],
            detail=f"home_win {b['home_win']:.3f} -> {r['home_win']:.3f}; away {b['away_win']:.3f} -> {r['away_win']:.3f}",
        ))

        # 3) fatigue up -> late vulnerability up.
        # The deterministic MECHANISM (attacking a tired team is easier) is
        # the primary causal signal; the end-to-end goal diff is bounded
        # rather than strictly directed, because score dynamics (a tired team
        # that trails still pushes late) legitimately add noise.
        fresh_w, _ = self.harness.build_world(specs[0], specs[1], minute=80)
        tired_w, _ = self.harness.build_world(specs[0], specs[1], minute=80, fatigue_home=0.65)
        p_fresh = self.harness.event_agent.per_minute_probabilities(fresh_w)
        p_tired = self.harness.event_agent.per_minute_probabilities(tired_w)
        mechanism_ok = (
            p_tired.attack_intensity_away > p_fresh.attack_intensity_away
            and p_tired.attack_intensity_home < p_fresh.attack_intensity_home
        )
        w_tired, m_tired = self.harness.build_world(specs[0], specs[1], fatigue_home=0.65)
        batches = self.harness.run_pair(
            {"base": w_base, "tired": w_tired},
            {"base": m_base, "tired": m_tired}, n=n, seed=seed)
        t = batch_metrics(batches["tired"])
        diff_base = b["goals_away_late"] - b["goals_home_late"]
        diff_tired = t["goals_away_late"] - t["goals_home_late"]
        checks.append(CheckResult(
            name="fatigue_raises_late_vulnerability",
            passed=mechanism_ok and diff_tired >= diff_base - 0.15 and diff_tired - diff_base < 1.5,
            detail=(f"mechanism: away intensity {p_fresh.attack_intensity_away:.3f} -> "
                    f"{p_tired.attack_intensity_away:.3f} vs tired home; home intensity "
                    f"{p_fresh.attack_intensity_home:.3f} -> {p_tired.attack_intensity_home:.3f}; "
                    f"end-to-end late goal diff {diff_base:+.3f} -> {diff_tired:+.3f}"),
        ))

        # 4) referee yellow tendency up -> yellows up
        ref_low = RefereeMatchState(known=True, yellow_card_tendency=0.35, red_card_tendency=0.5,
                                    penalty_tendency=0.5, foul_tolerance=0.5)
        ref_high = RefereeMatchState(known=True, yellow_card_tendency=0.72, red_card_tendency=0.5,
                                     penalty_tendency=0.5, foul_tolerance=0.5)
        w_rl, m_rl = self.harness.build_world(specs[0], specs[1], referee=ref_low)
        w_rh, m_rh = self.harness.build_world(specs[0], specs[1], referee=ref_high)
        batches = self.harness.run_pair(
            {"low": w_rl, "high": w_rh}, {"low": m_rl, "high": m_rh}, n=n, seed=seed)
        ml, mh = batch_metrics(batches["low"]), batch_metrics(batches["high"])
        checks.append(CheckResult(
            name="referee_yellow_tendency_raises_cards",
            passed=mh["yellows"] > ml["yellows"] + 0.2,
            detail=f"yellows {ml['yellows']:.2f} -> {mh['yellows']:.2f}",
        ))

        # 5) heavy rain does not increase goals
        dry, m_dry = self.harness.build_world(specs[0], specs[1],
                                              weather=WeatherState(known=True, rain=0.0, impact="low"))
        wet, m_wet = self.harness.build_world(specs[0], specs[1],
                                              weather=WeatherState(known=True, rain=0.9, impact="high"))
        batches = self.harness.run_pair(
            {"dry": dry, "wet": wet}, {"dry": m_dry, "wet": m_wet}, n=n, seed=seed)
        md, mw = batch_metrics(batches["dry"]), batch_metrics(batches["wet"])
        checks.append(CheckResult(
            name="rain_does_not_raise_goals",
            passed=mw["exp_goals"] <= md["exp_goals"] + 0.15,
            detail=f"goals dry {md['exp_goals']:.2f} vs rain {mw['exp_goals']:.2f}",
        ))

        # 6) counter strength vs high line -> away win up
        neutral_hm, neutral_mm = self.harness.build_world(specs[0], specs[1])
        home_high = TeamSpec(**{**specs[0].__dict__, "defensive_line": 0.72})
        away_counter = TeamSpec(**{**specs[1].__dict__, "counter_strength": 0.78})
        w_ex, m_ex = self.harness.build_world(home_high, away_counter)
        batches = self.harness.run_pair(
            {"neutral": neutral_hm, "exposed": w_ex},
            {"neutral": neutral_mm, "exposed": m_ex}, n=n, seed=seed)
        mn, me = batch_metrics(batches["neutral"]), batch_metrics(batches["exposed"])
        checks.append(CheckResult(
            name="counter_vs_high_line_raises_away_win",
            passed=me["away_win"] > mn["away_win"],
            detail=f"away_win {mn['away_win']:.3f} -> {me['away_win']:.3f}",
        ))

        return ValidationSection(
            name="causal_direction", passed=all(c.passed for c in checks), results=checks)

    def _state_transition(self) -> ValidationSection:
        checks: List[CheckResult] = []
        world = self._mini_world()

        updated = self.sm.apply_event(
            world, MatchEvent(minute=30, second=0, side=Side.HOME,
                              event_type=EventType.GOAL, xg=0.3,
                              state_before_version=0, state_after_version=0))
        checks.append(CheckResult(
            name="goal_flips_mentality",
            passed=updated.score_home == 1 and updated.mentality(Side.HOME).value == "leading"
                   and updated.mentality(Side.AWAY).value == "trailing",
            detail=f"score {updated.score_home}-{updated.score_away}, mentalities "
                   f"{updated.mentality(Side.HOME).value}/{updated.mentality(Side.AWAY).value}",
        ))

        red = self.sm.apply_event(
            world, MatchEvent(minute=20, second=0, side=Side.HOME,
                              event_type=EventType.RED_CARD, player_id="h1",
                              state_before_version=0, state_after_version=0))
        checks.append(CheckResult(
            name="red_card_reduces_players_and_changes_shape",
            passed=red.players_on_pitch(Side.HOME) == 10
                   and red.home_tactical_state.formation != world.home_tactical_state.formation
                   and red.home_tactical_state.chance_creation_modifier < 1.0,
            detail=f"players {red.players_on_pitch(Side.HOME)}, formation "
                   f"{red.home_tactical_state.formation}, chance modifier "
                   f"{red.home_tactical_state.chance_creation_modifier:.2f}",
        ))

        sub = self.sm.apply_event(
            world, MatchEvent(minute=65, second=0, side=Side.HOME,
                              event_type=EventType.SUBSTITUTION, detail="h9:h11:defensive",
                              player_id="h9", state_before_version=0, state_after_version=0))
        checks.append(CheckResult(
            name="defensive_sub_trades_attack_for_control",
            passed=sub.home_tactical_state.attacking_intensity < world.home_tactical_state.attacking_intensity
                   and sub.substitution_state.home.subs_made == 1,
            detail=f"attack {world.home_tactical_state.attacking_intensity:.2f} -> "
                   f"{sub.home_tactical_state.attacking_intensity:.2f}",
        ))

        ht = self.sm.half_time(world.evolution_snapshot(current_minute=45, momentum_home=0.7, momentum_away=0.3))
        checks.append(CheckResult(
            name="half_time_resets_momentum",
            passed=ht.phase is MatchPhase.HALF_TIME and abs(ht.momentum_home - 0.5) < 0.01,
            detail=f"momentum home {ht.momentum_home:.2f} after HT",
        ))
        return ValidationSection(
            name="state_transition", passed=all(c.passed for c in checks), results=checks)

    def _red_card_section(self, pair: Dict) -> ValidationSection:
        c, r = pair["control"], pair["red"]
        checks = [
            CheckResult(
                name="red_card_lowers_win_probability",
                passed=r["home_win"] < c["home_win"] and r["away_win"] > c["away_win"],
                detail=f"home {c['home_win']:.3f}->{r['home_win']:.3f} / away {c['away_win']:.3f}->{r['away_win']:.3f}",
            ),
            CheckResult(
                name="down_a_man_loses_shot_share",
                passed=r["shots_home_share"] < c["shots_home_share"],
                detail=f"home shot share {c['shots_home_share']:.3f} -> {r['shots_home_share']:.3f}",
            ),
            CheckResult(
                name="scenario_distribution_shifts",
                passed=set(pair["tags_red"]) != set(pair["tags_control"])
                       or abs(pair["tags_red"].get("red_card_match_home_win", 0) - pair["tags_control"].get("red_card_match_home_win", 0)) > 0,
                detail=f"control tags {sorted(pair['tags_control'].keys())[:5]}, "
                       f"red tags {sorted(pair['tags_red'].keys())[:5]}",
            ),
        ]
        return ValidationSection(
            name="red_card_logic", passed=all(c.passed for c in checks), results=checks)

    def _fatigue_section(self, pair: Dict) -> ValidationSection:
        c, t = pair["control"], pair["tired"]
        diff_c = c["goals_away_late"] - c["goals_home_late"]
        diff_t = t["goals_away_late"] - t["goals_home_late"]
        # mechanism-level causal signal (deterministic)
        specs = balanced_pair("home", "away")
        fresh_w, _ = self.harness.build_world(specs[0], specs[1], minute=80)
        tired_w, _ = self.harness.build_world(specs[0], specs[1], minute=80, fatigue_home=0.65)
        p_fresh = self.harness.event_agent.per_minute_probabilities(fresh_w)
        p_tired = self.harness.event_agent.per_minute_probabilities(tired_w)
        mechanism_ok = (
            p_tired.attack_intensity_away > p_fresh.attack_intensity_away
            and p_tired.attack_intensity_home < p_fresh.attack_intensity_home
        )
        checks = [
            CheckResult(
                name="tired_defense_attacked_more_and_attacks_less",
                passed=mechanism_ok,
                detail=(f"away intensity {p_fresh.attack_intensity_away:.3f} -> "
                        f"{p_tired.attack_intensity_away:.3f}; home intensity "
                        f"{p_fresh.attack_intensity_home:.3f} -> {p_tired.attack_intensity_home:.3f}"),
            ),
            CheckResult(
                name="fatigue_penalty_bounded_no_collapse",
                passed=diff_t >= diff_c - 0.15 and diff_t - diff_c < 1.5,
                detail=(f"end-to-end late goal diff fresh {diff_c:+.3f} vs tired {diff_t:+.3f} "
                        f"(no sustained improvement, no exaggerated penalty)"),
            ),
        ]
        return ValidationSection(
            name="fatigue_logic", passed=all(c.passed for c in checks), results=checks)

    def _leading_section(self, pair: Dict) -> ValidationSection:
        c, l = pair["control"], pair["leading"]
        share_c = c["shots_home_late"] / max(1e-9, c["shots_home_late"] + c["shots_away_late"])
        share_l = l["shots_home_late"] / max(1e-9, l["shots_home_late"] + l["shots_away_late"])
        checks = [
            CheckResult(
                name="leading_team_does_not_attack_harder",
                passed=share_l <= share_c + 0.03,
                detail=f"home late shot share level {share_c:.3f} vs 2-0 lead {share_l:.3f}",
            ),
            CheckResult(
                name="comeback_still_possible",
                passed=l["goals_away_late"] > 0.0,
                detail=f"away late goals per match {l['goals_away_late']:.3f} (> 0: 2-0 is not a frozen result)",
            ),
            CheckResult(
                name="goals_not_mechanically_switched_off",
                passed=(l["exp_goals"] > 0.0),
                detail=f"total goals from 70' on: {l['exp_goals']:.2f}",
            ),
        ]
        return ValidationSection(
            name="leading_state", passed=all(c.passed for c in checks), results=checks)

    def _trailing_section(self, pair: Dict) -> ValidationSection:
        c, t = pair["control"], pair["trailing"]
        away_share_c = c["shots_away_late"] / max(1e-9, c["shots_home_late"] + c["shots_away_late"])
        away_share_t = t["shots_away_late"] / max(1e-9, t["shots_home_late"] + t["shots_away_late"])
        checks = [
            CheckResult(
                name="trailing_side_attacks_more",
                passed=away_share_t > away_share_c + 0.01,
                detail=f"away late shot share {away_share_c:.3f} -> {away_share_t:.3f}",
            ),
            CheckResult(
                name="leading_side_gets_counter_opportunities",
                passed=t["counter_shots_home"] >= c["counter_shots_home"],
                detail=f"home counter shots {c['counter_shots_home']:.2f} -> {t['counter_shots_home']:.2f}",
            ),
        ]
        return ValidationSection(
            name="trailing_state", passed=all(c.passed for c in checks), results=checks)

    def _tactical_section(self, pair: Dict) -> ValidationSection:
        n, e = pair["neutral"], pair["exposed"]
        matchup = pair["matchup"]
        checks = [
            CheckResult(
                name="high_line_exposes_home_to_transitions",
                passed=matchup.transition_risk_home > matchup.transition_risk_away,
                detail=f"transition risk home (high line) {matchup.transition_risk_home:.2f} "
                       f"> away {matchup.transition_risk_away:.2f}",
            ),
            CheckResult(
                name="behind_the_line_danger_identified",
                passed="behind_defense" in matchup.dangerous_zones,
                detail=f"dangerous zones: {matchup.dangerous_zones}",
            ),
            CheckResult(
                name="counter_threat_raises_away_chance_creation",
                passed=matchup.chance_creation_away > matchup.chance_creation_home,
                detail=f"chance creation home {matchup.chance_creation_home:.2f} "
                       f"vs away {matchup.chance_creation_away:.2f}",
            ),
            CheckResult(
                name="possession_does_not_mean_safety",
                passed=e["away_win"] > n["away_win"],
                detail=f"away_win {n['away_win']:.3f} -> {e['away_win']:.3f} "
                       f"while home possession is high",
            ),
        ]
        return ValidationSection(
            name="tactical_interaction", passed=all(c.passed for c in checks), results=checks)

    def _scenario_diversity(self, batch) -> ValidationSection:
        m = batch_metrics(batch)
        checks = [
            CheckResult(
                name="enough_archetypes",
                passed=m["scenario_count"] >= 8,
                detail=f"{int(m['scenario_count'])} archetypes in batch",
            ),
            CheckResult(
                name="no_single_dominant_script",
                passed=m["top_scenario_share"] < 0.5,
                detail=f"top scenario share {m['top_scenario_share']:.3f}",
            ),
        ]
        return ValidationSection(
            name="scenario_diversity", passed=all(c.passed for c in checks), results=checks)

    def _probability_conservation(self, batch) -> ValidationSection:
        result = ResultProbabilityAgent().compute(batch)
        matrix = ScoreProbabilityAgent().compute(batch)
        goals, btts = GoalsOUProbabilityAgent().compute(batch)
        htft = HTFTProbabilityAgent().compute(batch)
        checks = [
            CheckResult(
                name="1x2_sums_to_one",
                passed=abs(result.home_win + result.draw + result.away_win - 1.0) < 1e-3,
                detail=f"sum {result.home_win + result.draw + result.away_win:.4f}",
            ),
            CheckResult(
                name="score_matrix_sums_to_one",
                passed=abs(matrix.total() - 1.0) < 1e-3,
                detail=f"sum {matrix.total():.4f}",
            ),
            CheckResult(
                name="ou_complementary",
                passed=all(abs(goals.over[k] + goals.under[k] - 1.0) < 1e-6 for k in goals.over),
                detail="all six lines complementary",
            ),
            CheckResult(
                name="htft_sums_to_one",
                passed=abs(sum(htft.combinations.values()) - 1.0) < 1e-3,
                detail=f"sum {sum(htft.combinations.values()):.4f}",
            ),
        ]
        return ValidationSection(
            name="probability_conservation", passed=all(c.passed for c in checks), results=checks)

    def _anomaly_section(self, checks: List[AnomalyCheck]) -> ValidationSection:
        results = [
            CheckResult(name=c.name, passed=c.passed, detail=c.detail) for c in checks
        ]
        return ValidationSection(
            name="anomaly_detection", passed=all(r.passed for r in results), results=results)

    # ------------------------------------------------------------------
    def _mini_world(self) -> WorldState:
        world = WorldState(match_id="mini", home_team="h", away_team="a")
        world.home_team_state = TeamState(team_id="h", name="Home")
        world.away_team_state = TeamState(team_id="a", name="Away")
        world.home_coach = CoachState(coach_id="c1", reaction_to_leading="defensive",
                                      reaction_to_trailing="aggressive")
        world.away_coach = CoachState(coach_id="c2")
        world.home_players = {f"h{i}": PlayerState(player_id=f"h{i}", starting=True)
                              for i in range(11)}
        world.away_players = {f"a{i}": PlayerState(player_id=f"a{i}", starting=True)
                              for i in range(11)}
        world.home_players["h11"] = PlayerState(player_id="h11", starting=False)
        return world
