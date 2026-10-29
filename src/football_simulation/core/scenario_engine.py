"""Scenario Engine: Match Script Agent + Scenario Ranking Agent.

Scenarios are NOT invented separately from the simulation: the Monte Carlo
batch is classified into named archetypes (Match Script Agent) and the
archetype shares become the scenario distribution (Scenario Ranking Agent).
Leftover mass goes to an explicit Long Tail bucket (spec sections 24/25/49).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, Side, new_id
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.scenario import (
    Scenario,
    ScenarioKeyEvent,
    ScenarioRanking,
    ScenarioTimelineEntry,
    ScorePathEntry,
)
from football_simulation.models.simulation import SimulationBatch

# archetype -> (human name, description)
ARCHETYPE_LIBRARY: Dict[str, Tuple[str, str]] = {
    "home_early_goal_control": (
        "主队开场闪击并控制局面",
        "主队前15分钟破门后掌控节奏，通过控球与压迫逐步杀死比赛，最终以两球优势获胜。",
    ),
    "home_early_goal_nervous_finish": (
        "主队早进球后惊险守成",
        "主队早早领先，但此后让出主动权，客队反扑未果，主队一球小胜。",
    ),
    "away_early_goal_control": (
        "客队闪击并客场完胜",
        "客队开场即进球打乱主队部署，随后稳守反击，客场带走大胜。",
    ),
    "away_early_goal_nervous_finish": (
        "客队早进球后艰难守胜",
        "客队早段领先，主队围攻但破门乏术，客队一球险胜。",
    ),
    "home_dominant_win": ("主队全面压制", "主队场面与机会全面占优，以两球以上优势取胜。"),
    "away_dominant_win": ("客队反客为主", "客队压制主队，客场取得两球以上大胜。"),
    "tight_home_win": ("主队一球小胜", "势均力敌的比赛，主队抓住一次关键机会一球小胜。"),
    "tight_away_win": ("客队一球小胜", "势均力敌的比赛，客队效率更高，一球客场取胜。"),
    "comeback_home": ("主队逆转", "主队半场落后，下半场调整后连入两球完成逆转。"),
    "comeback_away": ("客队逆转", "客队上半场落后，下半场反扑成功客场逆转。"),
    "goalless_draw": ("闷平", "双方机会寥寥，0:0 收场。"),
    "scoring_draw_1_1": ("1:1 平局", "双方各入一球，比赛在均衡中结束。"),
    "high_scoring_draw": ("高比分平局", "对攻大战，双方合计三球以上且不分胜负。"),
    "high_scoring_home_win": ("主队对攻胜出", "节奏开放的比赛，主队在进球大战中胜出。"),
    "high_scoring_away_win": ("客队对攻胜出", "节奏开放的比赛，客队在进球大战中客场胜出。"),
    "red_card_match_home_win": ("红牌改变比赛(主胜)", "红牌改变了人数均势，主队最终取胜。"),
    "red_card_match_away_win": ("红牌改变比赛(客胜)", "红牌改变了人数均势，客队最终取胜。"),
    "red_card_match_draw": ("红牌改变比赛(平局)", "红牌后双方均未能打破平衡，平局收场。"),
    "penalty_decided_home_win": ("点球决定比赛(主胜)", "点球成为比赛的转折点，主队凭此取胜。"),
    "penalty_decided_away_win": ("点球决定比赛(客胜)", "点球成为比赛的转折点，客队凭此取胜。"),
    "penalty_decided_draw": ("点球决定比赛(平局)", "点球改变走势但未能分出胜负。"),
    "late_show_home": ("主队终场绝杀", "比赛胶着到最后阶段，主队终场前一击制胜。"),
    "late_show_away": ("客队终场绝杀", "比赛胶着到最后阶段，客队终场前一击制胜。"),
    "own_goal_home_win": ("乌龙改变比赛(主胜)", "对方的乌龙球成为转折，主队因此取胜。"),
    "own_goal_away_win": ("乌龙改变比赛(客胜)", "对方的乌龙球成为转折，客队因此取胜。"),
    "own_goal_draw": ("乌龙改变比赛(平局)", "乌龙球出现但双方最终战平。"),
    "goal_fest_home_win": ("进球大战(主胜)", "单场6球以上的疯狂对攻，主队笑到最后。"),
    "goal_fest_away_win": ("进球大战(客胜)", "单场6球以上的疯狂对攻，客队笑到最后。"),
    "goal_fest_draw": ("进球大战(平局)", "单场6球以上的疯狂对攻，双方握手言和。"),
    "keeper_error_home_win": ("门将失误(主胜)", "门将失误送礼改变了比赛，主队取胜。"),
    "keeper_error_away_win": ("门将失误(客胜)", "门将失误送礼改变了比赛，客队取胜。"),
    "keeper_error_draw": ("门将失误(平局)", "门将失误出现但未能改变平局结局。"),
    "long_tail": ("长尾情景", "所有低频、极端的情景（罕见红牌组合、门将失误、乌龙等）的集合。"),
}

TOP_SCENARIOS = 25
LONG_TAIL_MIN_SHARE = 0.005  # archetypes below this share fold into the long tail


class MatchScriptAgent(BaseAgent[Dict[str, Any]]):
    name = "MatchScriptAgent"
    description = "Generates candidate match scenarios from simulated archetypes."

    def build_scenarios(self, batch: SimulationBatch, match_id: str) -> List[Scenario]:
        n = max(1, batch.runs)
        counts = batch.scenario_counts()
        representatives: Dict[str, Any] = {}
        for match in batch.results:
            representatives.setdefault(match.scenario_tag, match)

        scenarios: List[Scenario] = []
        for tag, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            share = count / n
            name, description = ARCHETYPE_LIBRARY.get(tag, (tag, "模拟生成的比赛情景。"))
            rep = representatives[tag]
            timeline = self._timeline(rep)
            key_events = self._key_events(rep)
            score_path = self._score_path(rep)
            consistency = min(1.0, (count / n) ** 0.25 + 0.2)
            scenarios.append(
                Scenario(
                    scenario_id=new_id("scn"),
                    name=name,
                    probability=round(share, 6),
                    description=description,
                    initial_conditions={"formation_home": None, "formation_away": None},
                    timeline=timeline,
                    key_events=key_events,
                    tactical_changes=[],
                    score_path=score_path,
                    final_result={
                        "score_home": rep.score_home,
                        "score_away": rep.score_away,
                        "result": (
                            "home_win" if rep.score_home > rep.score_away
                            else ("away_win" if rep.score_away > rep.score_home else "draw")
                        ),
                    },
                    failure_conditions=self._failure_conditions(tag),
                    confidence=round(min(0.9, 0.45 + 0.5 * consistency), 3),
                    consistency=round(consistency, 3),
                    plausibility=0.9,
                    archetype=tag,
                    sample_count=count,
                )
            )
        return scenarios

    def _timeline(self, match) -> List[ScenarioTimelineEntry]:
        entries: List[ScenarioTimelineEntry] = []
        states = [
            (0, "balanced"),
            (15, "opening_settled"),
        ]
        for minute, state in states:
            entries.append(ScenarioTimelineEntry(minute=minute, state=state))
        for event in match.events:
            if event.event_type in (EventType.GOAL, EventType.RED_CARD, EventType.PENALTY):
                entries.append(
                    ScenarioTimelineEntry(
                        minute=event.minute,
                        state="scoreline_change",
                        event=f"{event.side.value}_{event.event_type.value}",
                    )
                )
        entries.append(ScenarioTimelineEntry(minute=90, state="final"))
        return entries

    def _key_events(self, match) -> List[ScenarioKeyEvent]:
        out: List[ScenarioKeyEvent] = []
        for event in match.events:
            if event.event_type in (
                EventType.GOAL, EventType.RED_CARD, EventType.SECOND_YELLOW,
                EventType.PENALTY, EventType.OWN_GOAL, EventType.INJURY,
            ):
                out.append(
                    ScenarioKeyEvent(
                        minute=event.minute,
                        side=event.side,
                        event_type=event.event_type.value,
                        detail=event.detail,
                    )
                )
        return out[:12]

    def _score_path(self, match) -> List[ScorePathEntry]:
        path: List[ScorePathEntry] = []
        h = a = 0
        for event in match.events:
            if event.event_type in (EventType.GOAL, EventType.OWN_GOAL):
                if event.side is Side.HOME:
                    h += 1
                else:
                    a += 1
                path.append(ScorePathEntry(minute=event.minute, score_home=h, score_away=a))
        return path

    @staticmethod
    def _failure_conditions(tag: str) -> List[str]:
        return [
            "若开场15分钟内先丢球，剧本将切换至落后型剧本",
            "若出现红牌，人数变化将改写局面",
            "若核心球员伤退，攻防结构需重构",
        ]

    def run(self, context: AgentContext) -> AgentResult[Dict[str, Any]]:
        batch = context.batch
        if batch is None:
            return self.fail(context, "missing simulation batch")
        scenarios = self.build_scenarios(batch, context.match_id)
        return self.ok(
            context,
            {"scenarios": scenarios},
            confidence=0.7,
            evidence=[f"{len(scenarios)} scenario archetypes generated from {batch.runs} simulations"],
            reasoning="Scenarios = classified Monte Carlo archetypes (not independent predictions).",
        )


class ScenarioRankingAgent(BaseAgent[ScenarioRanking]):
    name = "ScenarioRankingAgent"
    description = "Ranks scenarios by probability x consistency x plausibility; keeps a long tail."

    def rank(self, scenarios: List[Scenario]) -> ScenarioRanking:
        long_tail_mass = 0.0
        long_tail_count = 0
        kept: List[Scenario] = []
        for scenario in sorted(scenarios, key=lambda s: -s.probability):
            if scenario.archetype == "long_tail":
                long_tail_mass += scenario.probability
                long_tail_count += scenario.sample_count
                continue
            if len(kept) < TOP_SCENARIOS and scenario.probability >= LONG_TAIL_MIN_SHARE:
                kept.append(scenario)
            else:
                long_tail_mass += scenario.probability
                long_tail_count += scenario.sample_count
        if long_tail_mass > 0:
            name, description = ARCHETYPE_LIBRARY["long_tail"]
            kept.append(
                Scenario(
                    scenario_id=new_id("scn"),
                    name=name,
                    probability=round(long_tail_mass, 6),
                    description=description,
                    archetype="long_tail",
                    sample_count=long_tail_count,
                    confidence=0.4,
                    consistency=0.3,
                    plausibility=0.5,
                    final_result={"result": "long_tail"},
                    failure_conditions=["极端事件组合概率被事件依赖规则约束"],
                )
            )
        kept.sort(key=lambda s: -s.probability)
        # keep the long tail visually at the end regardless of its mass
        long_tail = next((s for s in kept if s.archetype == "long_tail"), None)
        if long_tail is not None:
            kept.remove(long_tail)
            kept.append(long_tail)
        return ScenarioRanking(scenarios=kept, long_tail_probability=round(long_tail_mass, 6), long_tail_count=long_tail_count)

    def run(self, context: AgentContext) -> AgentResult[ScenarioRanking]:
        if context.knowledge is None or not isinstance(context.knowledge, dict):
            return self.fail(context, "missing scenarios in knowledge")
        scenarios = context.knowledge.get("scenarios")
        if not scenarios:
            return self.fail(context, "missing scenarios")
        ranking = self.rank(scenarios)
        return self.ok(
            context,
            ranking,
            confidence=0.75,
            evidence=[
                f"top scenario {ranking.scenarios[0].name}: {ranking.scenarios[0].probability:.3f}"
                if ranking.scenarios else "no scenarios",
                f"long tail mass {ranking.long_tail_probability:.3f}",
            ],
            reasoning="Ranked by probability x consistency x plausibility; residual mass kept as long tail.",
        )
