"""Lineup Agent: starting XI, bench, formation, rotation & absence detection.

Must identify: core-player absences, key-position absences, rotation, young
players starting, backup goalkeeper, tactical rotation - and propagate the
impact into the WorldState.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.agents.quality import estimate_player_quality
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.entities import (
    CoachState,
    FixtureLineup,
    InjuryRecord,
    PlayerState,
    Position,
    TeamState,
)
from football_simulation.models.world import LineupState


class LineupAgent(BaseAgent[Dict]):
    name = "LineupAgent"
    description = "Determines XI/bench/formation and detects absences & rotation."

    def build_lineup(
        self,
        team_id: str,
        team_state: TeamState,
        coach: CoachState,
        players: Dict[str, PlayerState],
        raw_lineup: Optional[FixtureLineup],
        injuries: List[InjuryRecord],
    ) -> Tuple[LineupState, Dict[str, float], List[str]]:
        """Return (LineupState, impact dict, evidence lines)."""
        evidence: List[str] = []
        squad = sorted(players.values(), key=lambda p: -estimate_player_quality(p))
        injured_ids = {i.player_id for i in injuries}
        available = [p for p in squad if p.player_id not in injured_ids]

        formation = team_state.preferred_formation
        notes: List[str] = []
        key_absences: List[str] = []
        missing: List[str] = []

        for pid in sorted(injured_ids):
            if pid in players:
                p = players[pid]
                missing.append(p.player_id)
                if estimate_player_quality(p) > 0.70:
                    key_absences.append(f"{p.name} ({p.position.value})")
                    notes.append(f"key absence: {p.name} ({p.position.value})")

        confirmed = bool(raw_lineup and raw_lineup.confirmed)
        if raw_lineup and raw_lineup.starters:
            starters = [
                pid for pid in raw_lineup.starters if pid in players and pid not in injured_ids
            ]
            bench = [
                pid
                for pid in raw_lineup.bench
                if pid in players and pid not in injured_ids and pid not in starters
            ]
            formation = raw_lineup.formation or formation
        else:
            starters, bench = [], []

        if not starters:
            # Unconfirmed/absent lineup: build expected best XI from availability.
            expected = self._best_xi(available, formation)
            starters = [p.player_id for p in expected[:11]]
            bench = [p.player_id for p in available if p.player_id not in starters][:11]
            if not confirmed:
                notes.append("lineup NOT confirmed - expected XI used (uncertainty flagged)")

        # --- rotation detection -------------------------------------------
        best_ids = {p.player_id for p in available[:11]}
        rotation_count = len([pid for pid in starters if pid not in best_ids])
        rotation_level = ensure_range(rotation_count / max(1, len(starters)) * 1.5)

        young_starts = any(
            players[pid].age <= 21 for pid in starters if pid in players
        )
        backup_gk = self._detect_backup_gk(starters, players)

        tactical_rotation = rotation_level >= 0.25 and coach.rotation_tendency >= 0.5
        if tactical_rotation:
            notes.append("tactical rotation detected (coach rotation tendency + lineup changes)")
        if young_starts:
            notes.append("young player(s) in the starting XI")
        if backup_gk:
            notes.append("backup goalkeeper starting")

        key_positions_missing = self._key_position_gaps(starters, players)
        for gap in key_positions_missing:
            notes.append(f"key position weakened: {gap}")
            key_absences.append(gap)

        # --- strength impact ---------------------------------------------
        starting_quality = self._avg_quality(starters, players)
        best_quality = self._avg_quality(best_ids, players)
        drop = max(0.0, best_quality - starting_quality)
        attack_impact = -0.5 * drop - (0.05 if any("ST" in gap for gap in key_positions_missing) else 0.0)
        defense_impact = -0.5 * drop - (0.05 if any("GK" in gap for gap in key_positions_missing) else 0.0)
        depth_impact = -0.3 * max(0.0, 0.65 - self._avg_quality(bench[:7], players)) if bench else -0.1

        lineup = LineupState(
            team_id=team_id,
            formation=formation,
            starters=starters,
            bench=bench,
            captain=raw_lineup.captain if raw_lineup else None,
            confirmed=confirmed,
            rotation_level=rotation_level,
            key_absences=key_absences,
            missing_players=missing,
            tactical_rotation=tactical_rotation,
            young_player_starts=young_starts,
            backup_goalkeeper=backup_gk,
            notes=notes,
        )
        impact = {
            "attack_strength_delta": attack_impact,
            "defense_strength_delta": defense_impact,
            "depth_delta": depth_impact,
            "starting_quality": starting_quality,
            "bench_quality": self._avg_quality(bench, players) if bench else 0.5,
        }
        evidence.append(
            f"{team_id}: XI quality {starting_quality:.2f} (best {best_quality:.2f}), "
            f"rotation {rotation_level:.2f}, absences {len(missing)}"
        )
        evidence.extend(notes)
        return lineup, impact, evidence

    # ------------------------------------------------------------------
    def _best_xi(self, available: List[PlayerState], formation: str) -> List[PlayerState]:
        """Greedy best XI that respects a rough shape (1 GK, >=3 defenders...)."""
        gk = next((p for p in available if p.position is Position.GK), None)
        defenders = [p for p in available if p.position in (Position.CB, Position.LB, Position.RB)]
        mids = [p for p in available if p.position in (Position.DM, Position.CM, Position.AM)]
        attackers = [p for p in available if p.position in (Position.LW, Position.RW, Position.ST)]

        n_def = 4 if formation.startswith("4") else (5 if formation.startswith("5") else 3)
        n_mid = 3 if formation in ("4-3-3", "4-2-3-1", "3-4-3") else 4
        n_att = 3 if formation in ("4-3-3", "4-2-3-1", "3-4-3") else 2

        xi: List[PlayerState] = []
        if gk:
            xi.append(gk)
        xi += defenders[:n_def]
        xi += mids[:n_mid]
        rest = n_att
        taken = {p.player_id for p in xi}
        for p in attackers:
            if p.player_id not in taken and rest > 0:
                xi.append(p)
                rest -= 1
        # fill remaining slots with best available players
        for p in available:
            if len(xi) >= 11:
                break
            if p.player_id not in taken:
                xi.append(p)
        return xi[:11]

    def _detect_backup_gk(self, starters: List[str], players: Dict[str, PlayerState]) -> bool:
        gks = [p for p in players.values() if p.position is Position.GK]
        if not gks:
            return False
        best_gk = max(gks, key=estimate_player_quality)
        return best_gk.player_id not in starters

    def _key_position_gaps(self, starters: List[str], players: Dict[str, PlayerState]) -> List[str]:
        """Detect missing GK / CB / ST among the starters."""
        gaps: List[str] = []
        on = [players[pid] for pid in starters if pid in players]
        if not any(p.position is Position.GK for p in on):
            gaps.append("GK")
        if sum(1 for p in on if p.position is Position.CB) < 2:
            gaps.append("CB")
        if not any(p.position is Position.ST for p in on):
            gaps.append("ST")
        return gaps

    @staticmethod
    def _avg_quality(ids, players: Dict[str, PlayerState]) -> float:
        if not ids:
            return 0.0
        vals = [estimate_player_quality(players[pid]) for pid in ids if pid in players]
        return sum(vals) / len(vals) if vals else 0.0

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[Dict]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world

        out: Dict = {}
        all_evidence: List[str] = []
        for team_id, side_players, team_state, coach, is_home in (
            (
                request.home_team_id,
                world.home_players,
                world.home_team_state,
                world.home_coach,
                True,
            ),
            (
                request.away_team_id,
                world.away_players,
                world.away_team_state,
                world.away_coach,
                False,
            ),
        ):
            raw = context.data.get_lineup(team_id, request.match_id)
            injuries = context.data.get_injury(team_id, request.kickoff)
            lineup, impact, evidence = self.build_lineup(
                team_id, team_state, coach, side_players, raw, injuries
            )
            side = "home" if is_home else "away"
            out[side] = {"lineup": lineup, "impact": impact}
            all_evidence.extend(evidence)

        lineup_certain = all(
            out[s]["lineup"].confirmed for s in ("home", "away")
        )
        return self.ok(
            context,
            out,
            confidence=0.85 if lineup_certain else 0.55,
            evidence=all_evidence,
            reasoning="Lineups resolved (confirmed or expected); absences/rotation impact propagated.",
            warnings=[] if lineup_certain else ["lineup(s) unconfirmed - lineup uncertainty"],
        )
