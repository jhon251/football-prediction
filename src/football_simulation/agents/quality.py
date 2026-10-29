"""Shared quality estimation helpers for players and lineups."""

from __future__ import annotations

from football_simulation.models.entities import PlayerState, Position
from football_simulation.models.base import ensure_range


def estimate_player_quality(player: PlayerState) -> float:
    """Blended overall quality 0..1 for lineup selection & simulation.

    Position-aware: attackers weight finishing, defenders weight defending.
    """
    tech = player.technical
    phys = player.physical
    ment = player.mental

    if player.position is Position.GK:
        return ensure_range(
            0.55 * (tech.first_touch + tech.passing) / 2
            + 0.25 * ment.positioning
            + 0.20 * ment.concentration
            + 0.05 * player.form
            - 0.15 * player.current_fatigue
        )

    if player.position in (Position.CB, Position.LB, Position.RB):
        quality = (
            0.28 * (tech.tackling + tech.marking) / 2
            + 0.12 * tech.heading
            + 0.15 * phys.pace
            + 0.15 * phys.strength
            + 0.20 * (ment.positioning + ment.concentration) / 2
            + 0.10 * player.form
        )
    elif player.position in (Position.LW, Position.RW, Position.ST):
        quality = (
            0.30 * (tech.finishing + tech.dribbling) / 2
            + 0.15 * phys.pace
            + 0.15 * tech.first_touch
            + 0.15 * ment.composure
            + 0.15 * ment.positioning
            + 0.10 * player.form
        )
    else:  # DM / CM / AM
        quality = (
            0.30 * (tech.passing + tech.vision) / 2
            + 0.15 * ment.decisions
            + 0.15 * tech.first_touch
            + 0.10 * phys.stamina
            + 0.10 * tech.tackling
            + 0.10 * phys.pace
            + 0.10 * player.form
        )
    quality *= 0.75 + 0.25 * player.tactical_fit
    quality *= 0.85 + 0.15 * player.confidence
    quality *= 1.0 - 0.20 * player.current_fatigue
    return ensure_range(quality)
