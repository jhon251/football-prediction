"""Historical data sources (V1.2).

- ``CsvFootballDataCoUkSource``: importer for the football-data.co.uk CSV
  format (the real-data adapter - used the moment a CSV file is available).
- ``SyntheticPremierLeagueSource``: the clearly-labeled DEVELOPMENT stand-in
  used ONLY because no network access exists in this environment.  Every row
  it produces carries ``is_synthetic=True`` and source="synthetic_development";
  nothing from it may ever be presented as real football evidence.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from football_simulation.core.rng import SeedableRNG
from football_simulation.data.historical.schema import (
    HistoricalEvents,
    HistoricalMatch,
    HistoricalOdds,
)


class CsvFootballDataCoUkSource:
    """Real-data adapter for https://www.football-data.co.uk CSV files.

    Maps the standard column layout into ``HistoricalMatch``.  Odds columns
    are pre-match closing prices (published before kickoff by the source);
    they are stamped with the match date and marked kind="closing" - the
    leakage audit re-verifies this assumption for every row.
    """

    def __init__(self, competition: str = "premier_league"):
        self.competition = competition

    def parse_bytes(self, data: bytes, season: str, source_label: str) -> List[HistoricalMatch]:
        text = data.decode("utf-8-sig", errors="replace")
        return self.parse(text, season, source_label)

    def parse(self, text: str, season: str, source_label: str) -> List[HistoricalMatch]:
        rows = list(csv.DictReader(io.StringIO(text)))
        matches: List[HistoricalMatch] = []
        for row in rows:
            if not row.get("Date") or not row.get("HomeTeam"):
                continue
            try:
                kickoff = self._parse_date(row["Date"], row.get("Time", ""))
            except ValueError:
                continue
            closing, raw_odds, semantics_note = self._extract_odds(row, kickoff)
            match = HistoricalMatch(
                match_id=f"{season}-{len(matches):03d}",
                competition=self.competition,
                season=season,
                date=kickoff,
                home_team=(row["HomeTeam"] or "").strip(),
                away_team=(row["AwayTeam"] or "").strip(),
                home_goals=self._int(row.get("FTHG")),
                away_goals=self._int(row.get("FTAG")),
                half_time_home_goals=self._int(row.get("HTHG")),
                half_time_away_goals=self._int(row.get("HTAG")),
                home_shots=self._int_or_none(row.get("HS")),
                away_shots=self._int_or_none(row.get("AS")),
                home_shots_on_target=self._int_or_none(row.get("HST")),
                away_shots_on_target=self._int_or_none(row.get("AST")),
                home_fouls=self._int_or_none(row.get("HF")),
                away_fouls=self._int_or_none(row.get("AF")),
                home_corners=self._int_or_none(row.get("HC")),
                away_corners=self._int_or_none(row.get("AC")),
                home_yellow_cards=self._int_or_none(row.get("HY")),
                away_yellow_cards=self._int_or_none(row.get("AY")),
                home_red_cards=self._int_or_none(row.get("HR")),
                away_red_cards=self._int_or_none(row.get("AR")),
                referee=row.get("Referee") or None,
                events=HistoricalEvents(complete=False),
                source=source_label,
                is_synthetic=False,
                closing_odds=closing,
                opening_odds=None,  # the file carries no verifiable opening snapshot
                raw_odds=raw_odds,
                odds_semantics_note=semantics_note,
            )
            matches.append(match)
        return matches

    # ------------------------------------------------------------------
    # Odds extraction with explicit time-semantics labeling (V1.2 P4/P5).
    # ------------------------------------------------------------------
    _CLOSING_CONVENTION = "closing_convention_pre_kickoff"
    _UNKNOWN_SEMANTICS = "unknown_time_semantics"

    @classmethod
    def _extract_odds(cls, row: Dict[str, str], kickoff: datetime):
        """Returns (closing HistoricalOdds, raw_odds dict, semantics note).

        * The file carries no per-odds timestamps, so EVERY odds column is
          stamped with the match kickoff and labeled by convention.
        * Plain 1X2/O-U/AH columns: source convention = pre-match closing
          snapshot -> ``closing_convention_pre_kickoff``.
        * C-suffix columns: opening/closing role CANNOT be verified from the
          file (overround analysis was inconclusive) -> labeled
          ``unknown_time_semantics`` and never promoted to closing/opening.
        """
        closing = cls._plain_odds(row, kickoff, prefer="Avg")
        if closing is None:
            closing = cls._plain_odds(row, kickoff, prefer="B365")
        raw: Dict[str, Any] = {}
        for field, value in row.items():
            if field in ("Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG",
                         "FTAG", "FTR", "HTHG", "HTAG", "HTR", "Referee", "HS",
                         "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY",
                         "HR", "AR"):
                continue
            if not value or not (value or "").strip():
                continue
            if cls._is_c_suffix(field):
                raw[field] = {"value": float(value),
                              "time_semantics": cls._UNKNOWN_SEMANTICS}
            else:
                raw[field] = {"value": float(value),
                              "time_semantics": cls._CLOSING_CONVENTION}
        note = (
            "no per-odds timestamps in source: plain columns stamped at kickoff "
            "under the source's closing convention; C-suffix columns carry "
            "unknown_time_semantics and were NOT mapped to closing/opening"
        )
        return closing, raw, note

    @staticmethod
    def _is_c_suffix(field: str) -> bool:
        if field in ("HC", "AC"):
            return False
        if field.endswith(("CH", "CD", "CA")) or field.startswith("AHCh"):
            return True
        if "C>2.5" in field or "C<2.5" in field or "CAH" in field:
            return True
        return False

    @classmethod
    def _plain_odds(cls, row: Dict[str, str], kickoff: datetime,
                    prefer: str) -> Optional[HistoricalOdds]:
        h, d, a = row.get(f"{prefer}H"), row.get(f"{prefer}D"), row.get(f"{prefer}A")
        try:
            return HistoricalOdds(
                home=float(h), draw=float(d), away=float(a),
                bookmaker=prefer,
                odds_timestamp=kickoff,
                kind="closing",
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int(value: Optional[str]) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _int_or_none(value: Optional[str]) -> Optional[int]:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(date: str, time_str: str) -> datetime:
        parts = date.split("/")
        day, month = int(parts[0]), int(parts[1])
        year = int(parts[2])
        if year < 100:
            year += 2000
        hour, minute = 15, 0
        if time_str and ":" in time_str:
            try:
                hour, minute = int(time_str.split(":")[0]), int(time_str.split(":")[1])
            except ValueError:
                pass
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Synthetic development stand-in (CLEARLY LABELED - never real evidence)
# ---------------------------------------------------------------------------

SYNTHETIC_TEAMS = [
    "Alpha FC", "Beta United", "Gamma City", "Delta Town", "Epsilon Rovers",
    "Zeta Albion", "Eta Wanderers", "Theta Athletic", "Iota County", "Kappa Villa",
    "Lambda Park", "Mu Rangers", "Nu Palace", "Xi Forest", "Omicron Hotspur",
    "Pi Argyle", "Rho Vale", "Sigma Bridge", "Tau Lions", "Upsilon Heath",
]

SYNTHETIC_REFEREES = ["A. Referee", "B. Referee", "C. Referee", "D. Referee",
                      "E. Referee", "F. Referee", "G. Referee", "H. Referee"]


class SyntheticPremierLeagueSource:
    """DEVELOPMENT STAND-IN ONLY.  Generates structurally realistic league
    seasons with seeded randomness.  Every produced match is marked
    ``is_synthetic=True`` - the system refuses to treat it as real evidence."""

    label = "synthetic_development"

    def __init__(self, seasons=("2021-22", "2022-23", "2023-24", "2024-25"),
                 matches_per_season: int = 380):
        self.seasons = list(seasons)
        self.matches_per_season = matches_per_season

    def generate(self, seed: int = 20240101) -> List[HistoricalMatch]:
        rng = SeedableRNG(seed)
        matches: List[HistoricalMatch] = []
        team_strengths: Dict[str, Dict[str, float]] = {}
        base_strength = {team: rng.normal(0.0, 0.55) for team in SYNTHETIC_TEAMS}

        for season_index, season in enumerate(self.seasons):
            # strength evolution: correlated across seasons, reversion to mean
            strengths: Dict[str, float] = {}
            for team in SYNTHETIC_TEAMS:
                prev = base_strength.get(team, 0.0)
                evolved = 0.75 * prev + 0.25 * rng.normal(0.0, 0.55) + rng.normal(0.0, 0.15)
                strengths[team] = evolved
                team_strengths.setdefault(team, {})[season] = evolved
            base_strength = dict(strengths)

            start = datetime(int(season[:4]), 8, 10, tzinfo=timezone.utc)
            elapsed_days = 0
            for round_no in range(self.matches_per_season // 10):
                rng_local = SeedableRNG(seed * (season_index + 1) * 1000 + round_no * 7 + 3)
                # realistic cadence: mostly weekly, with a congested festive
                # spell every 8 rounds (3-day gaps -> fixture congestion varies)
                if round_no == 0:
                    gap = 0
                elif round_no % 8 == 0:
                    gap = 3
                else:
                    gap = 7
                elapsed_days += gap
                pairs = self._round_robin_pairings(rng_local, SYNTHETIC_TEAMS, round_no)
                for home, away in pairs:
                    match_date = start + timedelta(days=elapsed_days, hours=rng_local.randint(12, 20))
                    # realistic scoring: league avg ~2.8, home advantage
                    lam_home = 1.55 + 0.45 * (strengths[home] - strengths[away])
                    lam_away = 1.15 - 0.40 * (strengths[home] - strengths[away])
                    lam_home = max(0.25, lam_home)
                    lam_away = max(0.25, lam_away)
                    ht_h = int(rng_local.poisson(lam_home * 0.42))
                    ht_a = int(rng_local.poisson(lam_away * 0.40))
                    sh_h = int(rng_local.poisson(lam_home - 0.42 * lam_home + 0.01))
                    sh_a = int(rng_local.poisson(lam_away - 0.40 * lam_away + 0.01))
                    fthg = ht_h + sh_h
                    ftag = ht_a + sh_a
                    shots_home = int(rng_local.poisson(12.5 + 1.5 * strengths[home]))
                    shots_away = int(rng_local.poisson(10.5 + 1.5 * strengths[away]))
                    sot_home = int(min(shots_home, rng_local.poisson(4.2 + strengths[home])))
                    sot_away = int(min(shots_away, rng_local.poisson(3.6 + strengths[away])))
                    hy = int(rng_local.poisson(2.0))
                    ay = int(rng_local.poisson(1.9))
                    hr = 1 if rng_local.random() < 0.12 else 0
                    ar = 1 if rng_local.random() < 0.10 else 0

                    # pre-match closing odds from the TRUE strengths + noise
                    # (the generator knows the truth; the model must not)
                    diff = strengths[home] - strengths[away]
                    p_home = 1 / (1 + 10 ** (-(diff + 0.32) / 1.4))
                    p_draw = max(0.16, 0.29 - 0.09 * abs(diff))
                    p_away = max(0.03, 1.0 - p_home - p_draw)
                    total = p_home + p_draw + p_away
                    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total
                    margin = 1.055
                    odds_h = max(1.01, round(1 / (p_home * margin), 2))
                    odds_d = max(1.01, round(1 / (p_draw * margin), 2))
                    odds_a = max(1.01, round(1 / (p_away * margin), 2))

                    match_id = f"syn-{season}-{len(matches):03d}"
                    matches.append(HistoricalMatch(
                        match_id=match_id,
                        competition="premier_league",
                        season=season,
                        date=match_date,
                        home_team=home,
                        away_team=away,
                        home_goals=fthg,
                        away_goals=ftag,
                        half_time_home_goals=ht_h,
                        half_time_away_goals=ht_a,
                        home_shots=shots_home,
                        away_shots=shots_away,
                        home_shots_on_target=sot_home,
                        away_shots_on_target=sot_away,
                        home_fouls=int(rng_local.poisson(11.0)),
                        away_fouls=int(rng_local.poisson(10.0)),
                        home_yellow_cards=hy,
                        away_yellow_cards=ay,
                        home_red_cards=hr,
                        away_red_cards=ar,
                        referee=SYNTHETIC_REFEREES[rng_local.randint(0, len(SYNTHETIC_REFEREES))],
                        events=HistoricalEvents(complete=False),
                        source=self.label,
                        is_synthetic=True,
                        closing_odds=HistoricalOdds(
                            home=odds_h, draw=odds_d, away=odds_a,
                            bookmaker="syn", odds_timestamp=match_date - timedelta(hours=1),
                            kind="closing",
                        ),
                    ))
        return matches

    @staticmethod
    def _round_robin_pairings(rng: SeedableRNG, teams: List[str], round_no: int) -> List[tuple]:
        """Standard circle-method schedule (every team once per round)."""
        n = len(teams)
        rest = list(teams[1:])
        shift = round_no % (n - 1)
        rest = rest[shift:] + rest[:shift]
        order = [teams[0]] + rest
        pairs = []
        for i in range(n // 2):
            a = order[i]
            b = order[n - 1 - i]
            if round_no % 2 == 1:
                a, b = b, a
            pairs.append((a, b))
        return pairs
