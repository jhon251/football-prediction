"""V1.1 Football common-sense scenario tests (spec V1.1 section 2, A-H).

Every assertion checks a CAUSAL DIRECTION against a controlled baseline, not
a specific number.  Worlds differ only in the single factor under test.
"""

import unittest

from football_simulation.evaluation.reality import (
    TeamSpec,
    balanced_pair,
    batch_metrics,
)
from football_simulation.models.base import Side
from tests.football_reality.common import get_harness

N = 350
SEED = 77


class TestScenarioA_StrongVsWeak(unittest.TestCase):
    def test_strong_team_wins_more_and_creates_more(self):
        harness = get_harness()
        strong = TeamSpec(team_id="strong", name="Strong", attack=0.78, defense=0.75,
                          midfield=0.75, goalkeeper=0.74)
        weak = TeamSpec(team_id="weak", name="Weak", attack=0.42, defense=0.45,
                        midfield=0.45, goalkeeper=0.46)
        world, matchup = harness.build_world(strong, weak)
        batches = harness.run_pair({"w": world}, {"w": matchup}, n=N, seed=SEED)
        m = batch_metrics(batches["w"])
        self.assertGreater(m["home_win"], m["away_win"] + 0.10,
                           f"strong {m['home_win']:.3f} vs weak {m['away_win']:.3f}")
        self.assertGreater(m["shots_home_share"], 0.56,
                           f"strong shot share {m['shots_home_share']:.3f}")

    def test_upset_still_possible_but_weak_never_dominant(self):
        harness = get_harness()
        strong = TeamSpec(team_id="strong", attack=0.78, defense=0.75,
                          midfield=0.75, goalkeeper=0.74)
        weak = TeamSpec(team_id="weak", attack=0.42, defense=0.45,
                        midfield=0.45, goalkeeper=0.46)
        world, matchup = harness.build_world(strong, weak)
        batches = harness.run_pair({"w": world}, {"w": matchup}, n=N, seed=SEED)
        weak_wins = sum(1 for r in batches["w"].results
                        if r.score_away > r.score_home)
        # upsets exist (long tail preserved)
        self.assertGreater(weak_wins, 0, "weak team must win at least once (upset exists)")
        # ... but the weak team never dominates the batch
        self.assertLess(weak_wins / N, 0.45)


class TestScenarioB_EarlyGoal(unittest.TestCase):
    def test_early_home_goal_changes_the_match(self):
        from football_simulation.agents.momentum import MomentumAgent
        from football_simulation.core.rule_engine import RuleEngine
        from football_simulation.core.state_machine import StateTransitionAgent
        from football_simulation.knowledge import load_all_knowledge
        from football_simulation.models.events import EventType, MatchEvent

        harness = get_harness()
        specs = balanced_pair("home", "away")
        control, c_matchup = harness.build_world(specs[0], specs[1], minute=10)
        early, e_matchup = harness.build_world(specs[0], specs[1], minute=10)
        # the goal happens through the real state machine, not by hand-set score
        sm = StateTransitionAgent(RuleEngine(load_all_knowledge()["rules"]), MomentumAgent())
        goal = MatchEvent(minute=10, second=0, side=Side.HOME,
                          event_type=EventType.GOAL, xg=0.3,
                          state_before_version=0, state_after_version=0)
        early = sm.apply_event(early, goal)

        # state must NOT stay identical to 0-0
        self.assertEqual(early.score_home, 1)
        self.assertEqual(early.mentality(Side.HOME).value, "leading")
        self.assertEqual(early.mentality(Side.AWAY).value, "trailing")
        # momentum favors the scorer
        self.assertGreater(early.momentum_home, control.momentum_home)
        # conceding raises the away side's pressure
        self.assertGreater(early.away_psychological_state.pressure,
                           control.away_psychological_state.pressure)
        # simulation: away attacks harder over the remainder of the half
        # (trailing push engages from the 15th minute on)
        batches = harness.run_pair(
            {"control": control, "early": early},
            {"control": c_matchup, "early": e_matchup}, n=N, seed=SEED)
        mc = batch_metrics(batches["control"])
        me = batch_metrics(batches["early"])
        away_share_c = mc["shots_away"] / max(1e-9, mc["shots_home"] + mc["shots_away"])
        away_share_e = me["shots_away"] / max(1e-9, me["shots_home"] + me["shots_away"])
        self.assertGreater(away_share_e, away_share_c,
                           f"away shot share {away_share_c:.3f} -> {away_share_e:.3f}")


class TestScenarioC_RedCard(unittest.TestCase):
    def test_red_card_changes_structure_and_scenarios(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        control, c_matchup = harness.build_world(specs[0], specs[1], red_home=1)
        # structural effects
        self.assertEqual(control.players_on_pitch(Side.HOME), 10)
        self.assertLess(control.home_tactical_state.chance_creation_modifier, 1.0)
        self.assertNotEqual(control.home_tactical_state.formation, "4-3-3")
        no_red, n_matchup = harness.build_world(specs[0], specs[1])
        batches = harness.run_pair(
            {"no_red": no_red, "red": control},
            {"no_red": n_matchup, "red": c_matchup}, n=N, seed=SEED)
        mn = batch_metrics(batches["no_red"])
        mr = batch_metrics(batches["red"])
        self.assertLess(mr["home_win"], mn["home_win"],
                        f"home win {mn['home_win']:.3f} -> {mr['home_win']:.3f}")
        self.assertLess(mr["shots_home_share"], mn["shots_home_share"])
        # scenario distribution visibly changes
        self.assertNotEqual(set(batches["red"].scenario_counts()),
                            set(batches["no_red"].scenario_counts()))


class TestScenarioD_HighLineVsCounter(unittest.TestCase):
    def test_counter_threat_punishes_high_line(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        home_high = TeamSpec(**{**specs[0].__dict__, "defensive_line": 0.72})
        away_counter = TeamSpec(**{**specs[1].__dict__, "counter_strength": 0.78})
        neutral_w, neutral_m = harness.build_world(specs[0], specs[1])
        world, matchup = harness.build_world(home_high, away_counter)
        # home exposed by its own line against a counter threat
        self.assertGreater(matchup.transition_risk_home, matchup.transition_risk_away)
        self.assertIn("behind_defense", matchup.dangerous_zones)
        self.assertGreater(matchup.chance_creation_away, matchup.chance_creation_home)
        # possession is NOT safety: home keeps the ball yet away wins more
        self.assertGreaterEqual(matchup.possession_target_home, 0.5)
        batches = harness.run_pair(
            {"neutral": neutral_w, "exposed": world},
            {"neutral": neutral_m, "exposed": matchup}, n=N, seed=SEED)
        mn = batch_metrics(batches["neutral"])
        me = batch_metrics(batches["exposed"])
        self.assertGreater(me["away_win"], mn["away_win"],
                           f"away_win {mn['away_win']:.3f} -> {me['away_win']:.3f}")


class TestScenarioE_LeadingTwoNil(unittest.TestCase):
    def test_leading_team_manages_game_but_match_not_frozen(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        control, c_matchup = harness.build_world(specs[0], specs[1], minute=70)
        leading, l_matchup = harness.build_world(specs[0], specs[1], minute=70,
                                                 score_home=2, score_away=0)
        self.assertEqual(leading.home_tactical_state.mentality.value, "leading")
        # leading team does not become MORE aggressive than at 0-0
        self.assertLessEqual(leading.home_tactical_state.risk_level,
                             control.home_tactical_state.risk_level + 0.01)
        # trailing team pushes
        self.assertGreater(leading.away_tactical_state.risk_level,
                           control.away_tactical_state.risk_level)
        batches = harness.run_pair(
            {"control": control, "leading": leading},
            {"control": c_matchup, "leading": l_matchup}, n=N, seed=SEED)
        mc = batch_metrics(batches["control"])
        ml = batch_metrics(batches["leading"])
        home_share_c = mc["shots_home_late"] / max(1e-9, mc["shots_home_late"] + mc["shots_away_late"])
        home_share_l = ml["shots_home_late"] / max(1e-9, ml["shots_home_late"] + ml["shots_away_late"])
        self.assertLessEqual(home_share_l, home_share_c + 0.03,
                             "leading 2-0 must not attack harder than at 0-0")
        # comeback still possible: trailing side scores late sometimes
        self.assertGreater(ml["goals_away_late"], 0.0)
        # goals are not mechanically switched off
        self.assertGreater(ml["exp_goals"], 0.5)


class TestScenarioF_TrailingAway(unittest.TestCase):
    def test_trailing_side_attacks_and_exposes_counter(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        control, c_matchup = harness.build_world(specs[0], specs[1], minute=70)
        trailing, t_matchup = harness.build_world(specs[0], specs[1], minute=70,
                                                  score_home=1, score_away=0)
        self.assertEqual(trailing.away_tactical_state.mentality.value, "trailing")
        self.assertGreater(trailing.away_tactical_state.attacking_intensity,
                           control.away_tactical_state.attacking_intensity)
        self.assertGreater(trailing.away_tactical_state.risk_level,
                           control.away_tactical_state.risk_level)
        batches = harness.run_pair(
            {"control": control, "trailing": trailing},
            {"control": c_matchup, "trailing": t_matchup}, n=N, seed=SEED)
        mc = batch_metrics(batches["control"])
        mt = batch_metrics(batches["trailing"])
        away_share_c = mc["shots_away_late"] / max(1e-9, mc["shots_home_late"] + mc["shots_away_late"])
        away_share_t = mt["shots_away_late"] / max(1e-9, mt["shots_home_late"] + mt["shots_away_late"])
        self.assertGreater(away_share_t, away_share_c + 0.01,
                           f"away late shot share {away_share_c:.3f} -> {away_share_t:.3f}")
        # home gets more counter opportunities against the pushing away side
        self.assertGreater(mt["counter_shots_home"], mc["counter_shots_home"],
                           f"home counter shots {mc['counter_shots_home']:.2f} -> "
                           f"{mt['counter_shots_home']:.2f}")


class TestScenarioG_Fatigue(unittest.TestCase):
    def test_tired_side_declines_late_without_exaggeration(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        # mechanism: the tired team's defense is attacked more and attacks less
        fresh_w, _ = harness.build_world(specs[0], specs[1], minute=80)
        tired_w, _ = harness.build_world(specs[0], specs[1], minute=80, fatigue_home=0.65)
        self.assertGreater(tired_w.fatigue_home, fresh_w.fatigue_home)
        p_fresh = harness.event_agent.per_minute_probabilities(fresh_w)
        p_tired = harness.event_agent.per_minute_probabilities(tired_w)
        self.assertGreater(p_tired.attack_intensity_away, p_fresh.attack_intensity_away)
        self.assertLess(p_tired.attack_intensity_home, p_fresh.attack_intensity_home)
        # end-to-end: late-game vulnerability bounded both ways (no sustained
        # improvement, no exaggerated linear collapse)
        fresh, f_matchup = harness.build_world(specs[0], specs[1])
        tired, t_matchup = harness.build_world(specs[0], specs[1], fatigue_home=0.65)
        batches = harness.run_pair(
            {"fresh": fresh, "tired": tired},
            {"fresh": f_matchup, "tired": t_matchup}, n=N, seed=SEED)
        mf = batch_metrics(batches["fresh"])
        mt = batch_metrics(batches["tired"])
        diff_f = mf["goals_away_late"] - mf["goals_home_late"]
        diff_t = mt["goals_away_late"] - mt["goals_home_late"]
        self.assertGreaterEqual(diff_t, diff_f - 0.15,
                                f"late goal diff {diff_f:+.3f} -> {diff_t:+.3f}")
        self.assertLess(diff_t - diff_f, 1.5,
                        f"swing {diff_t - diff_f:+.3f} must stay bounded")


class TestScenarioH_Substitutions(unittest.TestCase):
    def test_defensive_and_attacking_subs_trade_off(self):
        from football_simulation.agents.momentum import MomentumAgent
        from football_simulation.core.rule_engine import RuleEngine
        from football_simulation.core.state_machine import StateTransitionAgent
        from football_simulation.knowledge import load_all_knowledge
        from football_simulation.models.entities import CoachState, PlayerState, TeamState
        from football_simulation.models.events import EventType, MatchEvent
        from football_simulation.models.world import WorldState

        knowledge = load_all_knowledge()
        sm = StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent())

        def make_world(coach_reaction: str):
            world = WorldState(match_id="sub-test", home_team="h", away_team="a")
            world.home_team_state = TeamState(team_id="h", name="Home")
            world.away_team_state = TeamState(team_id="a", name="Away")
            world.home_coach = CoachState(coach_id="c1", reaction_to_leading=coach_reaction)
            world.away_coach = CoachState(coach_id="c2")
            world.home_players = {f"h{i}": PlayerState(player_id=f"h{i}", starting=True)
                                  for i in range(11)}
            world.home_players["h11"] = PlayerState(player_id="h11", starting=False)
            return world

        def sub_event(sub_type: str) -> MatchEvent:
            return MatchEvent(minute=65, second=0, side=Side.HOME,
                              event_type=EventType.SUBSTITUTION,
                              detail=f"h9:h11:{sub_type}", player_id="h9",
                              state_before_version=0, state_after_version=0)

        # leading team -> defensive substitution: defense first, attack slightly down
        world = make_world("defensive")
        after = sm.apply_event(world, sub_event("defensive"))
        self.assertLess(after.home_tactical_state.attacking_intensity,
                        world.home_tactical_state.attacking_intensity)
        self.assertLess(after.home_tactical_state.risk_level,
                        world.home_tactical_state.risk_level)

        # trailing team -> attacking substitution: attack up, stability slightly down
        world = make_world("aggressive")
        after = sm.apply_event(world, sub_event("attacking"))
        self.assertGreater(after.home_tactical_state.attacking_intensity,
                           world.home_tactical_state.attacking_intensity)
        self.assertGreater(after.home_tactical_state.risk_level,
                           world.home_tactical_state.risk_level)
        self.assertEqual(after.substitution_state.home.subs_made, 1)


if __name__ == "__main__":
    unittest.main()
