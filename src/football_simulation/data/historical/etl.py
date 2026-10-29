"""Historical dataset container + ETL validation (V1.2)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from football_simulation.data.historical.schema import HistoricalMatch


class HistoricalDataset:
    """Canonical, validated collection of HistoricalMatch rows."""

    def __init__(self, matches: List[HistoricalMatch], name: str = "unnamed"):
        self.name = name
        self.matches = sorted(matches, key=lambda m: m.date)
        self._by_id = {m.match_id: m for m in self.matches}

    # ------------------------------------------------------------------
    def get(self, match_id: str) -> HistoricalMatch:
        return self._by_id[match_id]

    def matches_before(self, ts) -> List[HistoricalMatch]:
        return [m for m in self.matches if m.date < ts]

    def team_matches_before(self, team: str, ts) -> List[HistoricalMatch]:
        return [m for m in self.matches
                if m.date < ts and team in (m.home_team, m.away_team)]

    def seasons(self) -> List[str]:
        return sorted({m.season for m in self.matches})

    def teams(self) -> List[str]:
        return sorted({t for m in self.matches for t in (m.home_team, m.away_team)})

    def matches_in_season(self, season: str) -> List[HistoricalMatch]:
        return [m for m in self.matches if m.season == season]

    # ------------------------------------------------------------------
    def validate(self) -> List[str]:
        """Structural integrity checks. Returns a list of problems."""
        problems: List[str] = []
        ids: set = set()
        for match in self.matches:
            if match.match_id in ids:
                problems.append(f"duplicate match_id {match.match_id}")
            ids.add(match.match_id)
            if match.home_goals < match.half_time_home_goals:
                problems.append(f"{match.match_id}: FT home goals < HT home goals")
            if match.away_goals < match.half_time_away_goals:
                problems.append(f"{match.match_id}: FT away goals < HT away goals")
            if match.home_team == match.away_team:
                problems.append(f"{match.match_id}: same team both sides")
            if match.home_goals < 0 or match.away_goals < 0:
                problems.append(f"{match.match_id}: negative goals")
            if not match.season:
                problems.append(f"{match.match_id}: missing season")
            if match.closing_odds is not None:
                for key in ("home", "draw", "away"):
                    value = getattr(match.closing_odds, key)
                    if value is not None and value < 1.0:
                        problems.append(f"{match.match_id}: closing odds {key} < 1.0")
            if match.is_synthetic and "synthetic" not in match.source.lower():
                problems.append(f"{match.match_id}: synthetic flag without source label")
        return problems

    def summary(self) -> Dict[str, Any]:
        seasons = self.seasons()
        by_season: Dict[str, int] = {s: len(self.matches_in_season(s)) for s in seasons}
        synthetic = sum(1 for m in self.matches if m.is_synthetic)
        odds_available = sum(1 for m in self.matches if m.closing_odds is not None)
        return {
            "name": self.name,
            "matches": len(self.matches),
            "seasons": seasons,
            "matches_by_season": by_season,
            "teams": len(self.teams()),
            "synthetic": synthetic,
            "closing_odds_available": odds_available,
            "date_range": [
                self.matches[0].date.isoformat() if self.matches else None,
                self.matches[-1].date.isoformat() if self.matches else None,
            ],
        }

    # ------------------------------------------------------------------
    def save(self, path: Path) -> None:
        payload = {
            "name": self.name,
            "note": ("SYNTHETIC DEVELOPMENT DATASET - NOT REAL FOOTBALL DATA" if self._all_synthetic()
                     else "historical dataset"),
            "matches": [m.model_dump(mode="json") for m in self.matches],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    def _all_synthetic(self) -> bool:
        return bool(self.matches) and all(m.is_synthetic for m in self.matches)

    @classmethod
    def load(cls, path: Path) -> "HistoricalDataset":
        payload = json.loads(path.read_text(encoding="utf-8"))
        matches = [HistoricalMatch.model_validate(m) for m in payload["matches"]]
        return cls(matches, name=payload.get("name", path.stem))
