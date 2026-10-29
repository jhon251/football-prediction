"""V1.1 Directional Causality Tests (spec V1.1 section 3).

Change ONE factor between two otherwise identical worlds; assert only the
DIRECTION of the resulting change - never a specific magnitude.
"""

import unittest

from football_simulation.evaluation.reality import (
    TeamSpec,
    balanced_pair,
    batch_metrics,
)
from football_simulation.models.world import RefereeMatchState, WeatherState
from tests.football_reality.common import get_harness

N = 350
SEED = 99


def _pair(harness, mutate, **world_kwargs):
    """Build control & treated worlds; mutate(spec_home, spec_away) returns specs."""
    specs = balanced_pair("home", "away")
    control, c_matchup = harness.build_world(specs[0], specs[1], **world_kwargs)
    h, a = mutate(specs[0], specs[1])
    treated, t_matchup = harness.build_world(h, a, **world_kwargs)
    batches = harness.run_pair(
        {"control": control, "treated": treated},
        {"control": c_matchup, "treated": t_matchup}, n=N, seed=SEED)
    return batch_metrics(batches["control"]), batch_metrics(batches["treated"])


class TestDirectionalCausality(unittest.TestCase):
    def test_home_attack_up_raises_home_win(self):
        m0, m1 = _pair(get_harness(),
                       lambda h, a: (TeamSpec(**{**h.__dict__, "attack": 0.68}), a))
        self.assertGreater(m1["home_win"], m0["home_win"] + 0.01,
                           f"{m0['home_win']:.3f} -> {m1['home_win']:.3f}")

    def test_home_defense_up_raises_home_win(self):
        m0, m1 = _pair(get_harness(),
                       lambda h, a: (TeamSpec(**{**h.__dict__, "defense": 0.70}), a))
        self.assertGreater(m1["home_win"], m0["home_win"],
                           f"{m0['home_win']:.3f} -> {m1['home_win']:.3f}")

    def test_away_strength_up_lowers_home_win(self):
        m0, m1 = _pair(
            get_harness(),
            lambda h, a: (h, TeamSpec(**{**a.__dict__, "attack": 0.68, "defense": 0.66})),
        )
        self.assertLess(m1["home_win"], m0["home_win"],
                        f"{m0['home_win']:.3f} -> {m1['home_win']:.3f}")

    def test_home_red_card_lowers_home_win_raises_away(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        control, c_m = harness.build_world(specs[0], specs[1])
        treated, t_m = harness.build_world(specs[0], specs[1], red_home=1)
        batches = harness.run_pair(
            {"control": control, "treated": treated},
            {"control": c_m, "treated": t_m}, n=N, seed=SEED)
        m0 = batch_metrics(batches["control"])
        m1 = batch_metrics(batches["treated"])
        self.assertLess(m1["home_win"], m0["home_win"],
                        f"home {m0['home_win']:.3f} -> {m1['home_win']:.3f}")
        self.assertGreater(m1["away_win"], m0["away_win"],
                           f"away {m0['away_win']:.3f} -> {m1['away_win']:.3f}")

    def test_home_fatigue_raises_late_vulnerability(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        # deterministic mechanism check: attacking a tired team is easier and
        # the tired team creates less
        fresh_w, _ = harness.build_world(specs[0], specs[1], minute=80)
        tired_w, _ = harness.build_world(specs[0], specs[1], minute=80, fatigue_home=0.65)
        p_fresh = harness.event_agent.per_minute_probabilities(fresh_w)
        p_tired = harness.event_agent.per_minute_probabilities(tired_w)
        self.assertGreater(p_tired.attack_intensity_away, p_fresh.attack_intensity_away,
                           f"away intensity {p_fresh.attack_intensity_away:.3f} -> "
                           f"{p_tired.attack_intensity_away:.3f}")
        self.assertLess(p_tired.attack_intensity_home, p_fresh.attack_intensity_home,
                        f"home intensity {p_fresh.attack_intensity_home:.3f} -> "
                        f"{p_tired.attack_intensity_home:.3f}")
        # end-to-end bound: no SUSTAINED late improvement for the tired side
        # and no exaggerated swing (score dynamics legitimately add noise)
        control, c_m = harness.build_world(specs[0], specs[1])
        treated, t_m = harness.build_world(specs[0], specs[1], fatigue_home=0.65)
        batches = harness.run_pair(
            {"control": control, "treated": treated},
            {"control": c_m, "treated": t_m}, n=N, seed=SEED)
        m0 = batch_metrics(batches["control"])
        m1 = batch_metrics(batches["treated"])
        diff0 = m0["goals_away_late"] - m0["goals_home_late"]
        diff1 = m1["goals_away_late"] - m1["goals_home_late"]
        self.assertGreaterEqual(diff1, diff0 - 0.15,
                                f"late goal diff {diff0:+.3f} -> {diff1:+.3f}")
        self.assertLess(diff1 - diff0, 1.5,
                        f"swing {diff1 - diff0:+.3f} must stay bounded")

    def test_referee_yellow_tendency_raises_cards(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        ref_low = RefereeMatchState(known=True, yellow_card_tendency=0.35,
                                    red_card_tendency=0.5, penalty_tendency=0.5,
                                    foul_tolerance=0.5)
        ref_high = RefereeMatchState(known=True, yellow_card_tendency=0.72,
                                     red_card_tendency=0.5, penalty_tendency=0.5,
                                     foul_tolerance=0.5)
        w0, m0 = harness.build_world(specs[0], specs[1], referee=ref_low)
        w1, m1 = harness.build_world(specs[0], specs[1], referee=ref_high)
        batches = harness.run_pair({"low": w0, "high": w1}, {"low": m0, "high": m1},
                                   n=N, seed=SEED)
        a = batch_metrics(batches["low"])
        b = batch_metrics(batches["high"])
        self.assertGreater(b["yellows"], a["yellows"] + 0.2,
                           f"{a['yellows']:.2f} -> {b['yellows']:.2f}")

    def test_heavy_rain_does_not_raise_goals(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        dry, m0 = harness.build_world(specs[0], specs[1],
                                      weather=WeatherState(known=True, rain=0.0, impact="low"))
        wet, m1 = harness.build_world(specs[0], specs[1],
                                      weather=WeatherState(known=True, rain=0.9, impact="high"))
        batches = harness.run_pair({"dry": dry, "wet": wet}, {"dry": m0, "wet": m1},
                                   n=N, seed=SEED)
        a = batch_metrics(batches["dry"])
        b = batch_metrics(batches["wet"])
        self.assertLessEqual(b["exp_goals"], a["exp_goals"] + 0.15,
                             f"dry {a['exp_goals']:.2f} vs wet {b['exp_goals']:.2f}")

    def test_counter_vs_high_line_raises_away_win(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        neutral, m0 = harness.build_world(specs[0], specs[1])
        home_high = TeamSpec(**{**specs[0].__dict__, "defensive_line": 0.72})
        away_counter = TeamSpec(**{**specs[1].__dict__, "counter_strength": 0.78})
        exposed, m1 = harness.build_world(home_high, away_counter)
        batches = harness.run_pair(
            {"neutral": neutral, "exposed": exposed},
            {"neutral": m0, "exposed": m1}, n=N, seed=SEED)
        a = batch_metrics(batches["neutral"])
        b = batch_metrics(batches["exposed"])
        self.assertGreater(b["away_win"], a["away_win"],
                           f"{a['away_win']:.3f} -> {b['away_win']:.3f}")

    def test_home_goalkeeper_up_lowers_away_goals(self):
        m0, m1 = _pair(get_harness(),
                       lambda h, a: (TeamSpec(**{**h.__dict__, "goalkeeper": 0.78}), a))
        # a better keeper converts fewer opponent shots into goals
        self.assertLess(m1["goals_away"], m0["goals_away"],
                        f"away goals {m0['goals_away']:.3f} -> {m1['goals_away']:.3f}")
        self.assertLess(m1["away_win"], m0["away_win"] + 0.005,
                        f"away_win {m0['away_win']:.3f} -> {m1['away_win']:.3f}")

    def test_high_press_vs_direct_buildup_raises_home_shot_share(self):
        harness = get_harness()
        specs = balanced_pair("home", "away")
        base_h, base_a = specs[0], specs[1]
        neutral, m0 = harness.build_world(base_h, base_a)
        pressing = TeamSpec(**{**base_h.__dict__, "pressing_style": "high_press"})
        direct = TeamSpec(**{**base_a.__dict__, "build_up_style": "direct"})
        treated, m1 = harness.build_world(pressing, direct)
        batches = harness.run_pair(
            {"neutral": neutral, "treated": treated},
            {"neutral": m0, "treated": m1}, n=N, seed=SEED)
        a = batch_metrics(batches["neutral"])
        b = batch_metrics(batches["treated"])
        self.assertGreater(b["shots_home_share"], a["shots_home_share"],
                           f"{a['shots_home_share']:.3f} -> {b['shots_home_share']:.3f}")


if __name__ == "__main__":
    unittest.main()
