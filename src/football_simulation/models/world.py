"""World Model: the strongly typed ``WorldState`` and its sub-states.

The WorldState is the single source of truth that every agent reads and that
every state transition rewrites.  State transitions create *new* WorldState
snapshots with a bumped ``state_version`` so the reasoning trace can always
point at an exact, immutable state.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import Side, new_id, utc_now
from football_simulation.models.entities import (
    CoachState,
    InjuryRecord,
    PlayerState,
    RefereeState,
    TeamState,
)


class MatchPhase(str, enum.Enum):
    PRE_MATCH = "pre_match"
    FIRST_HALF = "first_half"
    HALF_TIME = "half_time"
    SECOND_HALF = "second_half"
    FULL_TIME = "full_time"
    EXTRA_TIME = "extra_time"


class Mentality(str, enum.Enum):
    LEVEL = "level"
    LEADING = "leading"
    TRAILING = "trailing"


class TempoLevel(str, enum.Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class SpaceZone(str, enum.Enum):
    LEFT_WING = "left_wing"
    RIGHT_WING = "right_wing"
    HALF_SPACE_LEFT = "half_space_left"
    HALF_SPACE_RIGHT = "half_space_right"
    CENTRAL = "central"
    BEHIND_DEFENSE = "behind_defense"
    BETWEEN_LINES = "between_lines"
    SET_PIECE = "set_piece"


class TacticalTeamState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Side
    mentality: Mentality = Mentality.LEVEL
    formation: str = "4-3-3"
    pressing_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    defensive_line: float = Field(default=0.5, ge=0.0, le=1.0)
    attacking_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_level: float = Field(default=0.5, ge=0.0, le=1.0)
    tempo_contribution: float = Field(default=0.0, ge=-1.0, le=1.0)
    players_on_pitch: int = 11
    width_usage: float = Field(default=0.5, ge=0.0, le=1.0)
    style_tags: List[str] = Field(default_factory=list)
    counter_strength_current: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_risk: float = Field(default=0.5, ge=0.0, le=1.0)
    pressing_success_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    chance_creation_modifier: float = Field(default=1.0, ge=0.1, le=3.0)


class PsychologicalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Side
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    pressure: float = Field(default=0.5, ge=0.0, le=1.0)
    motivation: float = Field(default=0.5, ge=0.0, le=1.0)
    composure: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_appetite: float = Field(default=0.5, ge=0.0, le=1.0)
    crowd_support: float = Field(default=0.5, ge=0.0, le=1.0)
    decision_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    context_tags: List[str] = Field(default_factory=list)


class WeatherState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_c: Optional[float] = None
    humidity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rain: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    wind: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pitch_condition: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    altitude_m: Optional[float] = None
    impact: str = "low"  # low | medium | high
    notes: List[str] = Field(default_factory=list)
    known: bool = False


class RefereeMatchState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referee_id: str = ""
    name: str = ""
    yellow_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    red_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    penalty_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    foul_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    advantage_play: float = Field(default=0.5, ge=0.0, le=1.0)
    var_interaction: float = Field(default=0.5, ge=0.0, le=1.0)
    yellow_cards_given: int = 0
    red_cards_given: int = 0
    penalties_awarded: int = 0
    var_reviews: int = 0
    known: bool = False


class SubstitutionTeamState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Side
    subs_made: int = 0
    subs_limit: int = 5
    windows_used: List[str] = Field(default_factory=list)
    planned: List[Dict[str, Any]] = Field(
        default_factory=list, description="Planned substitutions: {minute, player_out, player_in, reason}"
    )
    forced: List[Dict[str, Any]] = Field(default_factory=list)


class SubstitutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home: SubstitutionTeamState = Field(default_factory=lambda: SubstitutionTeamState(side=Side.HOME))
    away: SubstitutionTeamState = Field(default_factory=lambda: SubstitutionTeamState(side=Side.AWAY))

    def for_side(self, side: Side) -> SubstitutionTeamState:
        return self.home if side is Side.HOME else self.away


class MatchInjury(BaseModel):
    model_config = ConfigDict(extra="forbid")

    injury_id: str = Field(default_factory=new_id)
    side: Side
    player_id: str
    minute: int
    severity: float = Field(default=0.5, ge=0.0, le=1.0)
    injury_type: str = "match_injury"
    player_returns: bool = False
    forced_substitution: bool = False


class InjuryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    injuries: List[MatchInjury] = Field(default_factory=list)
    pre_match_absent: Dict[str, List[str]] = Field(
        default_factory=dict, description="team_id -> player_ids ruled out before kickoff."
    )


class DangerousSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone: SpaceZone
    side: Side = Side.HOME  # which team currently benefits
    danger: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class LineupState(BaseModel):
    """Lineup Agent output (per team)."""

    model_config = ConfigDict(extra="forbid")

    team_id: str
    formation: str = "4-3-3"
    starters: List[str] = Field(default_factory=list)
    bench: List[str] = Field(default_factory=list)
    captain: Optional[str] = None
    confirmed: bool = False
    rotation_level: float = Field(default=0.0, ge=0.0, le=1.0)
    key_absences: List[str] = Field(default_factory=list)
    missing_players: List[str] = Field(default_factory=list)
    tactical_rotation: bool = False
    young_player_starts: bool = False
    backup_goalkeeper: bool = False
    notes: List[str] = Field(default_factory=list)

    def on_pitch_player_ids(self) -> List[str]:
        return list(self.starters)


class TriggerFlags(BaseModel):
    """Lightweight flags used by the event engine & rule engine."""

    model_config = ConfigDict(extra="allow")

    flags: Dict[str, float] = Field(default_factory=dict)

    def set(self, key: str, value: float = 1.0) -> None:
        self.flags[key] = value

    def get(self, key: str, default: float = 0.0) -> float:
        return self.flags.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.flags


class FitnessState(BaseModel):
    """Fitness Agent output for one team."""

    model_config = ConfigDict(extra="forbid")

    side: Side
    team_id: str = ""
    fatigue_score: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_fatigue_curve: List[float] = Field(default_factory=list)
    late_game_decline: float = Field(default=0.0, ge=0.0, le=1.0)
    days_since_last_match: Optional[int] = None
    matches_in_recent_period: int = 0
    average_minutes_recent: Optional[float] = None
    travel_burden: float = Field(default=0.0, ge=0.0, le=1.0)
    extra_time_recent: bool = False
    international_duty: str = "unknown"
    rotation_freshness: float = Field(default=0.5, ge=0.0, le=1.0)
    per_player_fatigue: Dict[str, float] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)


class OpeningState(BaseModel):
    """Opening Agent output (0-15 minute behavior)."""

    model_config = ConfigDict(extra="forbid")

    aggressive_side: Optional[Side] = None
    pressing_intensity_home: float = Field(default=0.5, ge=0.0, le=1.0)
    pressing_intensity_away: float = Field(default=0.5, ge=0.0, le=1.0)
    tempo: TempoLevel = TempoLevel.MEDIUM
    early_chance_modifier_home: float = Field(default=1.0, ge=0.1, le=3.0)
    early_chance_modifier_away: float = Field(default=1.0, ge=0.1, le=3.0)
    early_goal_risk_home: float = Field(default=0.0, ge=0.0, le=1.0)
    early_goal_risk_away: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""


class TacticalMatchupState(BaseModel):
    """Tactical Matchup Agent output."""

    model_config = ConfigDict(extra="forbid")

    tactical_advantage_home: float = Field(default=0.0, ge=-1.0, le=1.0)
    tactical_advantage_away: float = Field(default=0.0, ge=-1.0, le=1.0)
    dangerous_zones: List[str] = Field(default_factory=list)
    exploitable_spaces: List[str] = Field(default_factory=list)
    transition_risk_home: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_risk_away: float = Field(default=0.5, ge=0.0, le=1.0)
    pressing_success_home: float = Field(default=0.5, ge=0.0, le=1.0)
    pressing_success_away: float = Field(default=0.5, ge=0.0, le=1.0)
    chance_creation_home: float = Field(default=1.0, ge=0.1, le=3.0)
    chance_creation_away: float = Field(default=1.0, ge=0.1, le=3.0)
    possession_target_home: float = Field(default=0.5, ge=0.0, le=1.0)
    counter_shot_quality_bonus_home: float = 0.0
    counter_shot_quality_bonus_away: float = 0.0
    set_piece_xg_bonus_home: float = 0.0
    set_piece_xg_bonus_away: float = 0.0
    crossing_modifier_home: float = 0.0
    crossing_modifier_away: float = 0.0
    analysis: str = ""
    pattern_names: List[str] = Field(default_factory=list)


class WorldState(BaseModel):
    """The complete world model of one match at one instant."""

    model_config = ConfigDict(extra="forbid")

    # Identity / context
    match_id: str
    competition: str = ""
    season: str = ""
    kickoff: datetime = Field(default_factory=utc_now)
    as_of: datetime = Field(default_factory=utc_now)
    home_team: str = ""
    away_team: str = ""

    # Clock & phase
    current_minute: int = 0
    current_second: int = 0
    phase: MatchPhase = MatchPhase.PRE_MATCH
    state_version: int = 0

    # Score & core stats
    score_home: int = 0
    score_away: int = 0
    possession_home: float = Field(default=0.5, ge=0.0, le=1.0)
    possession_away: float = Field(default=0.5, ge=0.0, le=1.0)
    shots_home: int = 0
    shots_away: int = 0
    shots_on_target_home: int = 0
    shots_on_target_away: int = 0
    corners_home: int = 0
    corners_away: int = 0
    fouls_home: int = 0
    fouls_away: int = 0
    yellow_cards_home: int = 0
    yellow_cards_away: int = 0
    red_cards_home: int = 0
    red_cards_away: int = 0
    xg_home: float = 0.0
    xg_away: float = 0.0
    big_chances_home: int = 0
    big_chances_away: int = 0
    dangerous_attacks_home: int = 0
    dangerous_attacks_away: int = 0

    # Dynamics
    momentum_home: float = Field(default=0.5, ge=0.0, le=1.0)
    momentum_away: float = Field(default=0.5, ge=0.0, le=1.0)
    fatigue_home: float = Field(default=0.0, ge=0.0, le=1.0)
    fatigue_away: float = Field(default=0.0, ge=0.0, le=1.0)
    tempo: TempoLevel = TempoLevel.MEDIUM

    # Structured sub-states
    home_tactical_state: TacticalTeamState = Field(default_factory=lambda: TacticalTeamState(side=Side.HOME))
    away_tactical_state: TacticalTeamState = Field(default_factory=lambda: TacticalTeamState(side=Side.AWAY))
    home_psychological_state: PsychologicalState = Field(default_factory=lambda: PsychologicalState(side=Side.HOME))
    away_psychological_state: PsychologicalState = Field(default_factory=lambda: PsychologicalState(side=Side.AWAY))
    weather_state: WeatherState = Field(default_factory=WeatherState)
    referee_state: RefereeMatchState = Field(default_factory=RefereeMatchState)
    substitution_state: SubstitutionState = Field(default_factory=SubstitutionState)
    injury_state: InjuryState = Field(default_factory=InjuryState)
    dangerous_spaces: List[DangerousSpace] = Field(default_factory=list)
    active_scenarios: List[str] = Field(default_factory=list)
    trigger_flags: TriggerFlags = Field(default_factory=TriggerFlags)
    matchup_state: Optional[TacticalMatchupState] = None
    # Rule idempotency bookkeeping: rule_id -> whether the rule's condition
    # currently holds (and its effects are already baked into this state).
    # Prevents state-describing rules from compounding on every event.
    rule_conditions: Dict[str, bool] = Field(default_factory=dict)

    # Agent-enriched reference models (immutable during a simulation run)
    home_team_state: Optional[TeamState] = None
    away_team_state: Optional[TeamState] = None
    home_coach: Optional[CoachState] = None
    away_coach: Optional[CoachState] = None
    home_players: Dict[str, PlayerState] = Field(default_factory=dict)
    away_players: Dict[str, PlayerState] = Field(default_factory=dict)
    home_lineup: Optional[LineupState] = None
    away_lineup: Optional[LineupState] = None
    referee_profile: Optional[RefereeState] = None

    # Traceability
    last_event: Optional[str] = None
    expected_added_time_first_half: int = 0
    expected_added_time_second_half: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def minute_float(self) -> float:
        return float(self.current_minute) + self.current_second / 60.0

    def side_of(self, team_id: str) -> Side:
        if team_id == self.home_team:
            return Side.HOME
        if team_id == self.away_team:
            return Side.AWAY
        raise ValueError(f"Unknown team id {team_id!r} for match {self.match_id}")

    def team_id(self, side: Side) -> str:
        return self.home_team if side is Side.HOME else self.away_team

    def tactical(self, side: Side) -> TacticalTeamState:
        return self.home_tactical_state if side is Side.HOME else self.away_tactical_state

    def psychological(self, side: Side) -> PsychologicalState:
        return self.home_psychological_state if side is Side.HOME else self.away_psychological_state

    def score(self, side: Side) -> int:
        return self.score_home if side is Side.HOME else self.score_away

    def opponent_score(self, side: Side) -> int:
        return self.score_away if side is Side.HOME else self.score_home

    def momentum(self, side: Side) -> float:
        return self.momentum_home if side is Side.HOME else self.momentum_away

    def fatigue(self, side: Side) -> float:
        return self.fatigue_home if side is Side.HOME else self.fatigue_away

    def players(self, side: Side) -> Dict[str, PlayerState]:
        return self.home_players if side is Side.HOME else self.away_players

    def team_state(self, side: Side) -> Optional[TeamState]:
        return self.home_team_state if side is Side.HOME else self.away_team_state

    def coach(self, side: Side) -> Optional[CoachState]:
        return self.home_coach if side is Side.HOME else self.away_coach

    def lineup(self, side: Side) -> Optional[LineupState]:
        return self.home_lineup if side is Side.HOME else self.away_lineup

    def mentality(self, side: Side) -> Mentality:
        s = self.score(side)
        o = self.opponent_score(side)
        if s > o:
            return Mentality.LEADING
        if s < o:
            return Mentality.TRAILING
        return Mentality.LEVEL

    def players_on_pitch(self, side: Side) -> int:
        return 11 - self.red_cards(side)

    def red_cards(self, side: Side) -> int:
        return self.red_cards_home if side is Side.HOME else self.red_cards_away

    def yellow_cards(self, side: Side) -> int:
        return self.yellow_cards_home if side is Side.HOME else self.yellow_cards_away

    def evolution_snapshot(self, **changes: Any) -> "WorldState":
        """Return a new WorldState with ``changes`` applied and version bumped.

        Every state transition must go through this method so the reasoning
        trace can reference exact state versions.
        """
        updated = self.model_copy(update=changes)
        updated.state_version = self.state_version + 1
        return updated
