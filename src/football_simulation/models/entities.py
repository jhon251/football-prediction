"""Entity domain models: teams, players, coaches, referees, competitions.

Profiles (``*Profile``) are raw structured data as delivered by the Data
Provider.  States (``*State``) are the versioned, agent-enriched behavioral
models produced by the Team / Coach / Player / Referee agents.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import VersionedModel, ensure_range, new_id, utc_now


# --------------------------------------------------------------------------
# Attribute schemas
# --------------------------------------------------------------------------


class Position(str, enum.Enum):
    GK = "GK"
    CB = "CB"
    LB = "LB"
    RB = "RB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    LW = "LW"
    RW = "RW"
    ST = "ST"


class PreferredSide(str, enum.Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    NONE = "none"


class PlayerTechnicalAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finishing: float = Field(default=0.5, ge=0.0, le=1.0)
    long_shots: float = Field(default=0.5, ge=0.0, le=1.0)
    passing: float = Field(default=0.5, ge=0.0, le=1.0)
    vision: float = Field(default=0.5, ge=0.0, le=1.0)
    dribbling: float = Field(default=0.5, ge=0.0, le=1.0)
    first_touch: float = Field(default=0.5, ge=0.0, le=1.0)
    crossing: float = Field(default=0.5, ge=0.0, le=1.0)
    set_pieces: float = Field(default=0.5, ge=0.0, le=1.0)
    heading: float = Field(default=0.5, ge=0.0, le=1.0)
    tackling: float = Field(default=0.5, ge=0.0, le=1.0)
    marking: float = Field(default=0.5, ge=0.0, le=1.0)
    interceptions: float = Field(default=0.5, ge=0.0, le=1.0)


class PlayerPhysicalAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pace: float = Field(default=0.5, ge=0.0, le=1.0)
    acceleration: float = Field(default=0.5, ge=0.0, le=1.0)
    stamina: float = Field(default=0.5, ge=0.0, le=1.0)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    agility: float = Field(default=0.5, ge=0.0, le=1.0)
    balance: float = Field(default=0.5, ge=0.0, le=1.0)
    jumping: float = Field(default=0.5, ge=0.0, le=1.0)


class PlayerMentalAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composure: float = Field(default=0.5, ge=0.0, le=1.0)
    concentration: float = Field(default=0.5, ge=0.0, le=1.0)
    decisions: float = Field(default=0.5, ge=0.0, le=1.0)
    positioning: float = Field(default=0.5, ge=0.0, le=1.0)
    aggression: float = Field(default=0.5, ge=0.0, le=1.0)
    bravery: float = Field(default=0.5, ge=0.0, le=1.0)
    work_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    leadership: float = Field(default=0.5, ge=0.0, le=1.0)


class PlayerBehaviorProfile(BaseModel):
    """How a player tends to act, 0..1 intensities."""

    model_config = ConfigDict(extra="forbid")

    pressing_behavior: float = Field(default=0.5, ge=0.0, le=1.0)
    progression_behavior: float = Field(default=0.5, ge=0.0, le=1.0)
    passing_behavior: float = Field(default=0.5, ge=0.0, le=1.0)
    shooting_behavior: float = Field(default=0.5, ge=0.0, le=1.0)
    defensive_behavior: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_behavior: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------
# Profiles (raw data)
# --------------------------------------------------------------------------


class Competition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_id: str
    name: str
    short_name: str = ""
    country: str = ""
    tier: int = 1
    kind: str = "league"  # league | cup | international


class TeamProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str
    name: str = ""
    short_name: str = ""
    competition_id: str = ""
    coach_id: Optional[str] = None

    # Base strength estimates (0..1).  These are *priors*, not predictions.
    attack_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    defense_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    goalkeeper_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    midfield_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    squad_depth: float = Field(default=0.5, ge=0.0, le=1.0)
    elo_rating: float = 1500.0

    # Style profile (raw observations, refined by the Team Agent into TeamState).
    preferred_formation: str = "4-3-3"
    build_up_style: str = "mixed"
    pressing_style: str = "medium_block"
    defensive_line: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_style: str = "balanced"
    counter_attack_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    possession_preference: float = Field(default=0.5, ge=0.0, le=1.0)
    crossing_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    central_attack_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    wing_attack_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    set_piece_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    set_piece_defense: float = Field(default=0.5, ge=0.0, le=1.0)
    home_advantage: float = Field(default=0.04, ge=0.0, le=1.0)

    # Extra context the provider *may* know.  Unknown data stays None/UNKNOWN -
    # never fabricated.
    matches_recent: int = 0
    minutes_recent: int = 0
    last_match_at: Optional[datetime] = None


class PlayerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str
    name: str = ""
    team_id: str = ""
    age: int = 24
    position: Position = Position.CM
    role: str = "balanced"
    preferred_side: PreferredSide = PreferredSide.BOTH
    technical: PlayerTechnicalAttributes = Field(default_factory=PlayerTechnicalAttributes)
    physical: PlayerPhysicalAttributes = Field(default_factory=PlayerPhysicalAttributes)
    mental: PlayerMentalAttributes = Field(default_factory=PlayerMentalAttributes)
    behaviors: PlayerBehaviorProfile = Field(default_factory=PlayerBehaviorProfile)
    fatigue_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    injury_risk: float = Field(default=0.2, ge=0.0, le=1.0)
    form: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    discipline: float = Field(default=0.5, ge=0.0, le=1.0)
    tactical_fit: float = Field(default=0.5, ge=0.0, le=1.0)


class CoachProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coach_id: str
    name: str = ""
    team_id: str = ""
    preferred_formations: List[str] = Field(default_factory=lambda: ["4-3-3"])
    tactical_flexibility: float = Field(default=0.5, ge=0.0, le=1.0)
    substitution_timing: Dict[str, float] = Field(
        default_factory=lambda: {"early": 0.2, "mid": 0.5, "late": 0.3}
    )
    substitution_patterns: List[str] = Field(default_factory=list)
    reaction_to_leading: str = "moderate"
    reaction_to_trailing: str = "moderate"
    reaction_to_red_card: str = "defensive"
    reaction_to_conceding: str = "moderate"
    reaction_to_scoring: str = "moderate"
    rotation_tendency: float = Field(default=0.4, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    big_match_behavior: str = "cautious"
    late_game_behavior: str = "game_management"
    aggressiveness: float = Field(default=0.5, ge=0.0, le=1.0)


class RefereeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referee_id: str
    name: str = ""
    competition_id: str = ""
    yellow_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    red_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    penalty_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    foul_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    advantage_play: float = Field(default=0.5, ge=0.0, le=1.0)
    var_interaction: float = Field(default=0.5, ge=0.0, le=1.0)
    matches_officiated: int = 0


class InjuryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    injury_id: str = Field(default_factory=new_id)
    player_id: str
    team_id: str = ""
    injury_type: str = "unknown"
    severity: float = Field(default=0.5, ge=0.0, le=1.0)
    expected_return: Optional[datetime] = None
    known_at: Optional[datetime] = Field(
        default_factory=utc_now, description="When this record became known (freeze enforcement)."
    )


class FixtureLineup(BaseModel):
    """Raw lineup as reported by the data provider (may be unconfirmed)."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = ""
    team_id: str
    formation: str = "4-3-3"
    starters: List[str] = Field(default_factory=list)
    bench: List[str] = Field(default_factory=list)
    captain: Optional[str] = None
    confirmed: bool = False
    reported_at: Optional[datetime] = Field(default_factory=utc_now)


# --------------------------------------------------------------------------
# States (agent outputs)
# --------------------------------------------------------------------------


class TeamState(VersionedModel):
    """Behavioral model of a team for one match (Team Agent output)."""

    team_id: str
    name: str = ""

    preferred_formation: str = "4-3-3"
    build_up_style: str = "mixed"
    pressing_style: str = "medium_block"
    defensive_line: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_style: str = "balanced"
    counter_attack_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    possession_preference: float = Field(default=0.5, ge=0.0, le=1.0)
    crossing_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    central_attack_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    wing_attack_preference: float = Field(default=0.4, ge=0.0, le=1.0)
    set_piece_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    set_piece_defense: float = Field(default=0.5, ge=0.0, le=1.0)
    reaction_to_leading: str = "moderate"
    reaction_to_trailing: str = "moderate"
    reaction_to_draw: str = "balanced"
    late_game_behavior: str = "game_management"
    home_behavior: str = "standard"
    away_behavior: str = "standard"
    home_advantage: float = Field(default=0.04, ge=0.0, le=1.0)
    tempo_preference: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)

    # Normalized strengths (0..1)
    attack_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    defense_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    goalkeeper_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    midfield_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    squad_depth: float = Field(default=0.5, ge=0.0, le=1.0)
    elo_rating: float = 1500.0


class CoachState(VersionedModel):
    """Coach behavioral model for one match (Coach Agent output)."""

    coach_id: str
    name: str = ""
    team_id: str = ""

    preferred_formations: List[str] = Field(default_factory=lambda: ["4-3-3"])
    tactical_flexibility: float = Field(default=0.5, ge=0.0, le=1.0)
    substitution_timing: Dict[str, float] = Field(
        default_factory=lambda: {"early": 0.2, "mid": 0.5, "late": 0.3}
    )
    substitution_patterns: List[str] = Field(default_factory=list)
    reaction_to_leading: str = "moderate"
    reaction_to_trailing: str = "moderate"
    reaction_to_red_card: str = "defensive"
    reaction_to_conceding: str = "moderate"
    reaction_to_scoring: str = "moderate"
    rotation_tendency: float = Field(default=0.4, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    big_match_behavior: str = "cautious"
    late_game_behavior: str = "game_management"
    aggressiveness: float = Field(default=0.5, ge=0.0, le=1.0)

    # This-match gameplan decided by the coach.
    gameplan_formation: str = "4-3-3"
    gameplan_pressing_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    gameplan_defensive_line: float = Field(default=0.5, ge=0.0, le=1.0)
    gameplan_tempo: float = Field(default=0.5, ge=0.0, le=1.0)
    gameplan_risk_level: float = Field(default=0.5, ge=0.0, le=1.0)


class PlayerState(VersionedModel):
    """Player state for one match, subject to fatigue / score / tactics /
    matchup / psychology / time (Player Agent output)."""

    player_id: str
    name: str = ""
    team_id: str = ""
    age: int = 24
    position: Position = Position.CM
    role: str = "balanced"
    preferred_side: PreferredSide = PreferredSide.BOTH
    technical: PlayerTechnicalAttributes = Field(default_factory=PlayerTechnicalAttributes)
    physical: PlayerPhysicalAttributes = Field(default_factory=PlayerPhysicalAttributes)
    mental: PlayerMentalAttributes = Field(default_factory=PlayerMentalAttributes)
    behaviors: PlayerBehaviorProfile = Field(default_factory=PlayerBehaviorProfile)
    fatigue_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    injury_risk: float = Field(default=0.2, ge=0.0, le=1.0)
    form: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    discipline: float = Field(default=0.5, ge=0.0, le=1.0)
    tactical_fit: float = Field(default=0.5, ge=0.0, le=1.0)

    # Match-dynamic fields (initialized by Fitness/Lineup/Psychology agents,
    # updated during simulation).
    current_fatigue: float = Field(default=0.0, ge=0.0, le=1.0)
    fitness_score: float = Field(default=0.8, ge=0.0, le=1.0)
    expected_fatigue_curve: List[float] = Field(default_factory=list)
    available: bool = True
    starting: bool = False
    minutes_played: int = 0
    injury: Optional[InjuryRecord] = None

    def overall_quality(self) -> float:
        """Blended quality estimate used by simulation intensity models."""
        tech = (
            self.technical.passing
            + self.technical.finishing
            + self.technical.first_touch
            + self.technical.dribbling
        ) / 4.0
        phys = (self.physical.pace + self.physical.stamina + self.physical.strength) / 3.0
        ment = (self.mental.composure + self.mental.decisions + self.mental.concentration) / 3.0
        quality = 0.40 * tech + 0.25 * phys + 0.25 * ment + 0.10 * self.form
        quality *= 0.75 + 0.25 * self.tactical_fit
        quality *= 0.80 + 0.20 * self.confidence
        fatigue_penalty = 0.15 * self.current_fatigue
        return ensure_range(quality * (1.0 - fatigue_penalty))


class RefereeState(VersionedModel):
    """Referee behavior model for one match (Referee Agent output).

    The referee never decides a result directly - these tendencies only shift
    *event probabilities*.
    """

    referee_id: str
    name: str = ""
    competition_id: str = ""

    yellow_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    red_card_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    penalty_tendency: float = Field(default=0.5, ge=0.0, le=1.0)
    foul_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    advantage_play: float = Field(default=0.5, ge=0.0, le=1.0)
    var_interaction: float = Field(default=0.5, ge=0.0, le=1.0)
    matches_officiated: int = 0
    evidence_quality: float = Field(default=0.3, ge=0.0, le=1.0)


class MatchRequest(BaseModel):
    """Everything needed to analyze/simulate one match."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = Field(default_factory=new_id)
    home_team_id: str
    away_team_id: str
    competition_id: str = ""
    season: str = ""
    kickoff: datetime = Field(default_factory=utc_now)
    venue: str = ""
    as_of: datetime = Field(
        default_factory=utc_now,
        description="Data cutoff. No information newer than this may be used.",
    )


# --------------------------------------------------------------------------
# Default unknown-values policy
# --------------------------------------------------------------------------

UNKNOWN = "unknown"
"""Sentinel used whenever a data point genuinely does not exist.

Agents must propagate UNKNOWN rather than inventing a value; the Data Quality
layer penalizes unknowns when computing Confidence.
"""
