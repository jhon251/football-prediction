"""Environment Agent: weather/pitch/altitude/travel -> bounded effects.

Environment factors must NOT produce huge arbitrary effects: each impact is
classified low / medium / high, and the coefficients are tunable knowledge so
they can later be learned from history.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.data import WeatherData
from football_simulation.models.world import WeatherState


class EnvironmentAgent(BaseAgent[WeatherState]):
    name = "EnvironmentAgent"
    description = "Classifies weather/pitch impact and produces bounded modifiers."

    def build_state(self, weather: WeatherData, home_advantage: float) -> Tuple[WeatherState, List[str]]:
        evidence: List[str] = []
        notes: List[str] = []

        impact_score = 0.0
        if weather.known:
            if weather.rain is not None and weather.rain > 0.6:
                impact_score += 0.35
                notes.append(f"heavy rain ({weather.rain:.0%})")
            elif weather.rain is not None and weather.rain > 0.25:
                impact_score += 0.12
                notes.append(f"some rain ({weather.rain:.0%})")
            if weather.wind is not None and weather.wind > 0.7:
                impact_score += 0.2
                notes.append("strong wind")
            if weather.temperature_c is not None and weather.temperature_c > 30:
                impact_score += 0.2
                notes.append(f"hot ({weather.temperature_c:.0f}C)")
            elif weather.temperature_c is not None and weather.temperature_c < 2:
                impact_score += 0.2
                notes.append("near freezing")
            if weather.pitch_condition is not None and weather.pitch_condition < 0.6:
                impact_score += 0.25
                notes.append("poor pitch condition")
            if weather.altitude_m is not None and weather.altitude_m > 2000:
                impact_score += 0.2
                notes.append(f"altitude {weather.altitude_m:.0f}m")
            evidence.append(f"weather known: {notes or ['benign']}")
        else:
            notes.append("weather unknown - neutral assumptions flagged")
            evidence.append("weather unknown")

        impact = "low" if impact_score < 0.25 else ("medium" if impact_score < 0.55 else "high")
        evidence.append(f"environment impact: {impact} ({impact_score:.2f})")
        evidence.append(f"home advantage factor: {home_advantage:.3f}")

        state = WeatherState(
            temperature_c=weather.temperature_c,
            humidity=weather.humidity,
            rain=weather.rain,
            wind=weather.wind,
            pitch_condition=weather.pitch_condition,
            altitude_m=weather.altitude_m,
            impact=impact,
            notes=notes,
            known=weather.known,
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[WeatherState]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world
        weather = context.data.get_weather(request.match_id, request.venue)
        home_team = world.home_team_state
        home_advantage = home_team.home_advantage if home_team is not None else 0.04
        state, evidence = self.build_state(weather, home_advantage)
        return self.ok(
            context,
            state,
            confidence=0.8 if weather.known else 0.4,
            evidence=evidence,
            reasoning="Environment impact classified low/medium/high; coefficients are knowledge-tunable.",
            warnings=[] if weather.known else ["weather unknown"],
        )
