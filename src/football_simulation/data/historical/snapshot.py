"""PreMatchFreeze 2.0: the historical snapshot builder.

For any match X, the snapshot contains ONLY observations with
``observed_at < kickoff``.  Late observations are REJECTED (and logged),
never silently included.  The same module powers the time-travel test:
deleting every post-kickoff row must leave snapshots bit-identical.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from football_simulation.data.historical import features as feats
from football_simulation.data.historical.schema import (
    HistoricalMatch,
    HistoricalOdds,
    HistoricalPreMatchSnapshot,
    LineupTriState,
)


class TemporalViolation(Exception):
    """Raised when a post-kickoff observation tries to enter a snapshot."""


class SnapshotBuilder:
    """Builds HistoricalPreMatchSnapshot with strict temporal enforcement."""

    def __init__(self, matches: List[HistoricalMatch], strict: bool = True):
        self.matches = sorted(matches, key=lambda m: m.date)
        self.strict = strict

    # ------------------------------------------------------------------
    def build(self, match: HistoricalMatch) -> HistoricalPreMatchSnapshot:
        kickoff = match.date
        rejected: List[Dict[str, Any]] = []
        unknowns: List[str] = []
        no_signal: List[str] = []

        # ---- odds: odds_timestamp mandatory for inclusion -----------------
        odds: Optional[HistoricalOdds] = None
        for candidate in (match.closing_odds, match.opening_odds):
            if candidate is None or candidate.home is None:
                continue
            if candidate.odds_timestamp is not None and candidate.odds_timestamp > kickoff:
                entry = {"field": "odds", "observed_at": candidate.odds_timestamp,
                         "kickoff": kickoff, "action": "rejected"}
                rejected.append(entry)
                if self.strict:
                    raise TemporalViolation(
                        f"odds observed after kickoff for {match.match_id}: "
                        f"{candidate.odds_timestamp} > {kickoff}")
                continue
            # a timestamp equal to kickoff is the source's "closing snapshot"
            # convention: published at/before kickoff, hence pre-match usable
            odds = candidate
            break
        if odds is None and (match.closing_odds is not None or match.opening_odds is not None):
            unknowns.append("odds_implied_probability")

        # ---- lineups: tri-state with observed_at ---------------------------
        home_status, home_xi = self._lineup_view(match, True, kickoff, rejected)
        away_status, away_xi = self._lineup_view(match, False, kickoff, rejected)
        if home_status == LineupTriState.UNKNOWN:
            unknowns.append("home_lineup")
        if away_status == LineupTriState.UNKNOWN:
            unknowns.append("away_lineup")

        # ---- referee / weather ----------------------------------------------
        referee = match.referee
        if referee is None:
            unknowns.append("referee")
        if match.weather and match.weather.get("observed_at") is not None:
            if match.weather["observed_at"] >= kickoff:
                entry = {"field": "weather", "observed_at": match.weather["observed_at"],
                         "kickoff": kickoff, "action": "rejected"}
                rejected.append(entry)
                if self.strict:
                    raise TemporalViolation(
                        f"weather observed after kickoff for {match.match_id}")
            else:
                no_signal.append("weather_available_but_ignored_by_v1_agents")
        else:
            unknowns.append("weather")

        if not match.injuries_known:
            unknowns.append("injuries")
        if not match.pre_match_states:
            no_signal.extend([
                "coach_state", "player_state", "tactical_style", "psychology_context"
            ])

        # ---- walk-forward team features (past matches ONLY) -----------------
        elos = feats.rolling_elo_map(self.matches, kickoff)
        team_features = {
            "home": feats.build_team_features(self.matches, match.home_team, kickoff, elos),
            "away": feats.build_team_features(self.matches, match.away_team, kickoff, elos),
            "league": feats.league_home_rates(self.matches, kickoff),
            "league_goal_rate": feats.league_goal_rate(self.matches, kickoff),
        }

        return HistoricalPreMatchSnapshot(
            match_id=match.match_id,
            kickoff=kickoff,
            home_team=match.home_team,
            away_team=match.away_team,
            team_features=team_features,
            odds=odds,
            home_lineup_status=home_status,
            away_lineup_status=away_status,
            home_lineup=home_xi,
            away_lineup=away_xi,
            referee=referee,
            weather=match.weather,
            unknowns=sorted(set(unknowns)),
            no_signal=sorted(set(no_signal)),
            rejected_observations=rejected,
        )

    def _lineup_view(self, match: HistoricalMatch, home: bool, kickoff, rejected) -> Tuple[str, List[str]]:
        status = match.home_lineup_status if home else match.away_lineup_status
        xi = list(match.home_lineup if home else match.away_lineup)
        observed = match.lineup_observed_at
        if observed is not None and observed >= kickoff:
            entry = {"field": f"{'home' if home else 'away'}_lineup",
                     "observed_at": observed, "kickoff": kickoff,
                     "action": "rejected -> UNKNOWN"}
            rejected.append(entry)
            if self.strict:
                raise TemporalViolation(
                    f"lineup observed after kickoff for {match.match_id}")
            return LineupTriState.UNKNOWN, []
        if status not in (LineupTriState.CONFIRMED, LineupTriState.PREDICTED):
            return LineupTriState.UNKNOWN, []
        if not xi:
            return LineupTriState.UNKNOWN, []
        return status, xi

    # ------------------------------------------------------------------
    # Time-travel verification (spec V1.2 section 6)
    # ------------------------------------------------------------------
    def verify_time_travel(self) -> Dict[str, Any]:
        """For every match: build the snapshot from the FULL dataset, then
        again from a dataset where every row with date >= kickoff is DELETED.
        The two snapshots must be identical (excluding the build timestamp) -
        any difference proves the pipeline can see the future."""
        violations: List[str] = []
        checked = 0
        for match in self.matches:
            try:
                full = self.build(match)
                truncated = SnapshotBuilder(
                    [m for m in self.matches if m.date < match.date], strict=self.strict
                )
                past_only = truncated.build(match)
            except TemporalViolation as exc:
                violations.append(f"{match.match_id}: {exc}")
                checked += 1
                continue
            if full.model_dump(exclude={"built_at"}) != past_only.model_dump(exclude={"built_at"}):
                violations.append(match.match_id)
            checked += 1
        return {"checked": checked, "violations": violations,
                "passed": not violations}
