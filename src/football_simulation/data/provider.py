"""Data Provider interface - the ONLY way agents may obtain data.

V1 ships without a data-collection agent (no scrapers / APIs / suppliers), but
defines the standard interface a future provider must implement:

    get_team_data / get_player_data / get_coach_data / get_match_history /
    get_lineup / get_injury / get_referee_data / get_weather / get_odds /
    get_event_data

Business agents are forbidden from touching websites, files or database
tables directly - everything flows through this layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from football_simulation.models.data import (
    ActualMatchResult,
    DataQualityInfo,
    MatchHistory,
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


class FutureDataError(RuntimeError):
    """Raised when frozen prediction code attempts to read post-kickoff data."""


class DataProvider(ABC):
    """Standard data access contract (spec section 3)."""

    name: str = "abstract"

    # ------------------------------------------------------------------
    # Core read methods - implement these for a real provider
    # ------------------------------------------------------------------
    @abstractmethod
    def get_competition_info(self, competition_id: str) -> Competition: ...

    @abstractmethod
    def get_team_data(self, team_id: str) -> TeamProfile: ...

    @abstractmethod
    def get_player_data(self, team_id: str) -> List[PlayerProfile]: ...

    @abstractmethod
    def get_coach_data(self, coach_id: str) -> CoachProfile: ...

    @abstractmethod
    def get_match_history(
        self, team_id: str, competition_id: str, season: str, before: datetime
    ) -> MatchHistory: ...

    @abstractmethod
    def get_lineup(self, team_id: str, match_id: str) -> Optional[FixtureLineup]: ...

    @abstractmethod
    def get_injury(self, team_id: str, before: datetime) -> List[InjuryRecord]: ...

    @abstractmethod
    def get_referee_data(self, referee_id: str) -> RefereeProfile: ...

    @abstractmethod
    def get_weather(self, match_id: str, venue: str) -> WeatherData: ...

    @abstractmethod
    def get_odds(self, match_id: str) -> Optional[OddsData]: ...

    @abstractmethod
    def get_event_data(self, match_id: str) -> List[MatchEvent]: ...

    @abstractmethod
    def get_match_result(self, match_id: str) -> Optional[ActualMatchResult]: ...

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def get_match_request(self, match_id: str) -> MatchRequest:
        raise NotImplementedError("Provider does not expose match requests.")

    def referee_for_match(self, match_id: str) -> Optional[str]:
        """Optional: provider may know which referee is appointed."""
        return None

    def data_quality(self, request: MatchRequest) -> DataQualityInfo:
        """Default completeness estimate; providers may override."""
        return DataQualityInfo(completeness=0.5)


class PreMatchFreeze(DataProvider):
    """PRE_MATCH_FREEZE gate.

    Wraps any provider.  Before ``freeze(kickoff)`` everything passes through.
    After freezing:

    * post-match methods (``get_event_data`` / ``get_match_result``) raise
      ``FutureDataError``;
    * lineup/injury records that became known only after the kickoff are
      filtered out (no future information leakage - spec sections 41/42).

    The Learning / Post-Match Evaluation pipeline intentionally uses an
    *unfrozen* provider so it may consume results - but its output can never
    flow back into the frozen prediction.
    """

    def __init__(self, inner: DataProvider):
        self._inner = inner
        self.name = f"frozen[{inner.name}]"
        self._frozen = False
        self._cutoff: Optional[datetime] = None

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def cutoff(self) -> Optional[datetime]:
        return self._cutoff

    def freeze(self, kickoff: datetime) -> None:
        self._frozen = True
        self._cutoff = kickoff

    def unfreeze(self) -> None:
        self._frozen = False
        self._cutoff = None

    # -- pass-through ----------------------------------------------------
    def get_competition_info(self, competition_id: str) -> Competition:
        return self._inner.get_competition_info(competition_id)

    def get_team_data(self, team_id: str) -> TeamProfile:
        return self._inner.get_team_data(team_id)

    def get_player_data(self, team_id: str) -> List[PlayerProfile]:
        return self._inner.get_player_data(team_id)

    def get_coach_data(self, coach_id: str) -> CoachProfile:
        return self._inner.get_coach_data(coach_id)

    def get_match_history(
        self, team_id: str, competition_id: str, season: str, before: datetime
    ) -> MatchHistory:
        history = self._inner.get_match_history(team_id, competition_id, season, before)
        if self._frozen and self._cutoff is not None:
            kept = [e for e in history.entries if e.date < self._cutoff]
            history = history.model_copy(update={"entries": kept})
        return history

    def get_lineup(self, team_id: str, match_id: str) -> Optional[FixtureLineup]:
        lineup = self._inner.get_lineup(team_id, match_id)
        if lineup is None:
            return None
        if self._frozen and self._cutoff is not None and lineup.reported_at is not None:
            if lineup.reported_at > self._cutoff:
                # Reported after kickoff: as of freeze time the lineup is unknown.
                return lineup.model_copy(update={"confirmed": False, "starters": [], "bench": []})
        return lineup

    def get_injury(self, team_id: str, before: datetime) -> List[InjuryRecord]:
        records = self._inner.get_injury(team_id, before)
        if self._frozen and self._cutoff is not None:
            records = [r for r in records if r.known_at is None or r.known_at <= self._cutoff]
        return records

    def get_referee_data(self, referee_id: str) -> RefereeProfile:
        return self._inner.get_referee_data(referee_id)

    def get_weather(self, match_id: str, venue: str) -> WeatherData:
        return self._inner.get_weather(match_id, venue)

    def get_odds(self, match_id: str) -> Optional[OddsData]:
        odds = self._inner.get_odds(match_id)
        if odds is not None and self._frozen and self._cutoff is not None and odds.as_of is not None:
            if odds.as_of > self._cutoff:
                raise FutureDataError(
                    f"Odds for {match_id} are newer than the frozen cutoff {self._cutoff}."
                )
        return odds

    def get_event_data(self, match_id: str) -> List[MatchEvent]:
        self._guard_post_match("get_event_data")
        return self._inner.get_event_data(match_id)

    def get_match_result(self, match_id: str) -> Optional[ActualMatchResult]:
        self._guard_post_match("get_match_result")
        return self._inner.get_match_result(match_id)

    def get_match_request(self, match_id: str) -> MatchRequest:
        return self._inner.get_match_request(match_id)

    def referee_for_match(self, match_id: str) -> Optional[str]:
        return self._inner.referee_for_match(match_id)

    def data_quality(self, request: MatchRequest) -> DataQualityInfo:
        return self._inner.data_quality(request)

    def _guard_post_match(self, method: str) -> None:
        if not self._frozen:
            return
        raise FutureDataError(
            f"{method} would expose post-match information; the pipeline is "
            "frozen before kickoff.  Use an unfrozen provider inside the "
            "Learning / Post-Match Evaluation layer only."
        )
