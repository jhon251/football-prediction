"""Competition registry.

The set of supported competitions is DATA, not code: no hardcoded "big five"
leagues.  The default fixture defines the five major leagues plus extension
placeholders (Portuguese/ Dutch leagues, UEFA competitions, national teams),
all of which can be extended without touching code.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Dict, List, Optional

from football_simulation.models.entities import Competition


class CompetitionRegistry:
    def __init__(self, competitions: List[Competition], teams: Dict[str, List[str]]):
        self._competitions: Dict[str, Competition] = {c.competition_id: c for c in competitions}
        self._teams: Dict[str, List[str]] = {k: list(v) for k, v in teams.items()}

    def list_competitions(self) -> List[Competition]:
        return sorted(self._competitions.values(), key=lambda c: c.competition_id)

    def competition(self, competition_id: str) -> Competition:
        if competition_id not in self._competitions:
            raise KeyError(f"Unknown competition: {competition_id!r}")
        return self._competitions[competition_id]

    def team_ids(self, competition_id: str) -> List[str]:
        return list(self._teams.get(competition_id, []))

    def has(self, competition_id: str) -> bool:
        return competition_id in self._competitions

    def competition_of_team(self, team_id: str) -> Optional[str]:
        for comp_id, teams in self._teams.items():
            if team_id in teams:
                return comp_id
        return None


def load_registry_from_package() -> CompetitionRegistry:
    """Load the bundled competitions fixture."""
    raw = resources.files("football_simulation.data").joinpath("competitions.json").read_text(
        encoding="utf-8"
    )
    payload = json.loads(raw)
    competitions = [
        Competition.model_validate({k: v for k, v in c.items() if k != "team_ids"})
        for c in payload["competitions"]
    ]
    teams: Dict[str, List[str]] = {}
    for item in payload["competitions"]:
        teams[item["competition_id"]] = item.get("team_ids", [])
    return CompetitionRegistry(competitions, teams)
