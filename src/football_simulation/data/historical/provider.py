"""HistoricalDataProvider: serves ONE frozen match snapshot to the pipeline.

Post-match methods raise ``FutureDataError`` unconditionally - the actual
result is held by the backtest runner, not by the provider, so the frozen
prediction path can never touch outcomes.  Missing data is returned as
UNKNOWN (empty / None / known=False), never fabricated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.schema import HistoricalPreMatchSnapshot, LineupTriState
from football_simulation.data.provider import DataProvider, FutureDataError
from football_simulation.models.base import ensure_range
from football_simulation.models.data import (
    DataQualityInfo,
    MatchHistory,
    MatchHistoryEntry,
    OddsData,
    WeatherData,
)
from football_simulation.models.entities import (
    CoachProfile,
    Competition,
    FixtureLineup,
    InjuryRecord,
    MatchRequest,
    PlayerProfile,
    RefereeProfile,
    TeamProfile,
)
from football_simulation.models.events import MatchEvent


class HistoricalDataProvider(DataProvider):
    """DataProvider over one HistoricalPreMatchSnapshot."""

    name = "historical"

    def __init__(self, dataset: HistoricalDataset, snapshot: HistoricalPreMatchSnapshot,
                 use_extended_features: bool = False, expose_odds: bool = True):
        self.dataset = dataset
        self.snapshot = snapshot
        self._kickoff = snapshot.kickoff
        # EXP-REAL-EPL-BASE-001: consume the richer walk-forward stat
        # aggregates (shots/SOT/corners/fouls/cards).  All transforms are
        # FIXED documented formulas - no fitted parameters, no tuning.
        self.use_extended_features = use_extended_features
        # EXP-REAL-EPL-BASE-001 excludes ALL market information: with
        # expose_odds=False the provider returns no odds at all.
        self.expose_odds = expose_odds

    # ------------------------------------------------------------------
    # Derived, documented transformations (fixed formulas - no learned params)
    # ------------------------------------------------------------------
    def _team_profile(self, team_id: str) -> TeamProfile:
        side = "home" if team_id == self.snapshot.home_team else "away"
        feat = self.snapshot.team_features.get(side, {})
        league = self.snapshot.team_features.get("league", {})
        elo = feat.get("elo", 1500.0)
        attack_rate = feat.get("attack_rate", 1.35)
        defense_rate = feat.get("defense_rate", 1.35)
        # Fixed, documented transforms from walk-forward features.
        elo_strength = ensure_range(0.5 + (elo - 1500.0) / 1200.0, 0.3, 0.85)
        attack = ensure_range(0.5 + (attack_rate - 1.4) * 0.18, 0.35, 0.8)
        defense = ensure_range(0.5 - (defense_rate - 1.4) * 0.18, 0.35, 0.8)
        goalkeeper = 0.5
        set_piece_strength = 0.5
        set_piece_defense = 0.5
        if self.use_extended_features:
            stats = feats.rolling_match_stats(self.dataset.matches, team_id, self._kickoff)
            if stats.get("n_sot", 0) >= 3:
                efficiency_for = (stats["sot_for"] / stats["n_sot"]
                                  - (stats["shots_for"] / stats["n_shots"] if stats.get("n_shots") else 0.35))
                efficiency_against = (stats["sot_against"] / stats["n_sot"]
                                      - (stats["shots_against"] / stats["n_shots"] if stats.get("n_shots") else 0.35))
                # shooting efficiency (+/-10pp shot-quality drift) -> attack/defense
                attack = ensure_range(attack + 0.10 * efficiency_for, 0.3, 0.85)
                defense = ensure_range(defense - 0.10 * efficiency_against, 0.3, 0.85)
                # keeper: goals conceded per shot-on-target against, vs ~0.33 baseline
                if stats.get("n_sot", 0) >= 5:
                    goals_conceded_recent = (defense_rate * stats["n_sot"]
                                             if stats.get("matches", 0) else 0.0)
                    conversion = goals_conceded_recent / max(1e-6, stats["sot_against"])
                    goalkeeper = ensure_range(0.5 - 0.8 * (conversion - 0.33), 0.35, 0.75)
            if stats.get("n_corners", 0) >= 3:
                corner_edge = (stats["corners_for"] - stats["corners_against"]) / max(1.0, stats["n_corners"])
                set_piece_strength = ensure_range(0.5 + 0.12 * corner_edge, 0.35, 0.7)
                set_piece_defense = ensure_range(0.5 - 0.12 * corner_edge, 0.35, 0.7)
            # fouls/cards are COLLECTED here but currently no pipeline channel
            # consumes them - reported honestly in the experiment notes.
        home_rate = league.get("home", 1 / 3)
        home_advantage = ensure_range(0.02 + 0.5 * (home_rate - 1 / 3), 0.01, 0.10)
        return TeamProfile(
            team_id=team_id,
            name=team_id,
            competition_id="premier_league",
            coach_id=f"unknown-coach-{team_id}",
            attack_strength=attack,
            defense_strength=defense,
            goalkeeper_strength=goalkeeper,
            midfield_strength=ensure_range(0.5 + (elo - 1500.0) / 1600.0, 0.35, 0.8),
            squad_depth=0.5,  # NO_SIGNAL
            elo_rating=elo,
            preferred_formation="4-3-3",  # NO_SIGNAL: style unknown
            build_up_style="mixed",
            pressing_style="mid_block",
            defensive_line=0.5,
            transition_style="balanced",
            counter_attack_strength=0.5,
            possession_preference=0.5,
            crossing_preference=0.4,
            central_attack_preference=0.4,
            wing_attack_preference=0.4,
            set_piece_strength=set_piece_strength,
            set_piece_defense=set_piece_defense,
            home_advantage=home_advantage,
        )

    # ------------------------------------------------------------------
    # DataProvider implementation
    # ------------------------------------------------------------------
    def get_competition_info(self, competition_id: str) -> Competition:
        return Competition(competition_id="premier_league", name="Premier League",
                           short_name="EPL", country="England", tier=1, kind="league")

    def get_team_data(self, team_id: str) -> TeamProfile:
        if team_id not in (self.snapshot.home_team, self.snapshot.away_team):
            raise KeyError(f"Unknown team for this match: {team_id!r}")
        return self._team_profile(team_id)

    def get_player_data(self, team_id: str) -> List[PlayerProfile]:
        # UNKNOWN: the historical source carries no per-player data.
        # The Director substitutes clearly-flagged neutral placeholder squads.
        return []

    def get_coach_data(self, coach_id: str) -> CoachProfile:
        # NO_SIGNAL: no historical coach model available
        return CoachProfile(coach_id=coach_id, name="UNKNOWN-COACH")

    def get_match_history(
        self, team_id: str, competition_id: str, season: str, before: datetime
    ) -> MatchHistory:
        entries: List[MatchHistoryEntry] = []
        for match in self.dataset.team_matches_before(team_id, self._kickoff):
            home = match.home_team == team_id
            entries.append(MatchHistoryEntry(
                date=match.date,
                opponent=match.away_team if home else match.home_team,
                home=home,
                goals_for=match.home_goals if home else match.away_goals,
                goals_against=match.away_goals if home else match.home_goals,
                xg_for=None, xg_against=None,
                competition="premier_league",
            ))
        return MatchHistory(team_id=team_id, competition_id="premier_league",
                            season=season, entries=entries)

    def get_lineup(self, team_id: str, match_id: str) -> Optional[FixtureLineup]:
        home = team_id == self.snapshot.home_team
        status = self.snapshot.home_lineup_status if home else self.snapshot.away_lineup_status
        xi = self.snapshot.home_lineup if home else self.snapshot.away_lineup
        if status == LineupTriState.UNKNOWN or not xi:
            return None
        return FixtureLineup(
            match_id=match_id,
            team_id=team_id,
            formation="4-3-3",  # NO_SIGNAL
            starters=xi,
            bench=[],
            confirmed=status == LineupTriState.CONFIRMED,
            reported_at=self.snapshot.kickoff,
        )

    def get_injury(self, team_id: str, before: datetime) -> List[InjuryRecord]:
        # UNKNOWN: no injury data in the historical source
        return []

    def get_referee_data(self, referee_id: str) -> RefereeProfile:
        # name known, tendencies NO_SIGNAL
        return RefereeProfile(
            referee_id=referee_id,
            name=referee_id,
            yellow_card_tendency=0.5, red_card_tendency=0.5,
            penalty_tendency=0.5, foul_tolerance=0.5,
            advantage_play=0.5, var_interaction=0.5,
            matches_officiated=0,  # -> evidence quality 0, flagged
        )

    def get_weather(self, match_id: str, venue: str) -> WeatherData:
        return WeatherData(match_id=match_id, venue=venue, known=False)

    def get_odds(self, match_id: str) -> Optional[OddsData]:
        if not self.expose_odds:
            # EXP-REAL-EPL-BASE-001: market information fully excluded
            return None
        odds = self.snapshot.odds
        if odds is None or odds.home is None:
            return None
        return OddsData(
            match_id=match_id,
            home_win=odds.home, draw=odds.draw, away_win=odds.away,
            as_of=odds.odds_timestamp or self._kickoff,
            bookmaker=odds.bookmaker,
        )

    def get_event_data(self, match_id: str) -> List[MatchEvent]:
        raise FutureDataError("historical provider is frozen pre-match; outcomes are "
                              "held by the backtest runner, never the provider.")

    def get_match_result(self, match_id: str):
        raise FutureDataError("historical provider is frozen pre-match; outcomes are "
                              "held by the backtest runner, never the provider.")

    def get_match_request(self, match_id: str) -> MatchRequest:
        return MatchRequest(
            match_id=match_id,
            home_team_id=self.snapshot.home_team,
            away_team_id=self.snapshot.away_team,
            competition_id="premier_league",
            season=self.snapshot.team_features.get("season", ""),
            kickoff=self._kickoff,
            as_of=self._kickoff,
        )

    def referee_for_match(self, match_id: str) -> Optional[str]:
        return self.snapshot.referee

    def data_quality(self, request: MatchRequest) -> DataQualityInfo:
        unknowns = list(self.snapshot.unknowns)
        no_signal = list(self.snapshot.no_signal)
        slots = 9.0
        completeness = max(0.0, 1.0 - (len(unknowns) + 0.5 * len(no_signal)) / slots)
        return DataQualityInfo(
            completeness=round(min(completeness, 1.0), 3),
            unknowns=unknowns,
            lineup_confirmed={
                self.snapshot.home_team: self.snapshot.home_lineup_status == LineupTriState.CONFIRMED,
                self.snapshot.away_team: self.snapshot.away_lineup_status == LineupTriState.CONFIRMED,
            },
            notes=["historical snapshot: unknowns and NO_SIGNAL fields are reported, never guessed"]
                   + [f"no_signal: {field}" for field in no_signal],
        )
