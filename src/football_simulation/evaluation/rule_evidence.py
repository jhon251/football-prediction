"""V1.2 Rule Evidence backfill + Counterexample store.

Five-level lifecycle: ASSUMPTION -> TENTATIVE -> SUPPORTED -> VALIDATED,
plus CONTRADICTED when real matches disagree with the rule's direction.

Criteria (pre-defined, documented):
  - SUPPORTED:    verified_matches >= 50 AND success_rate > 0.52
  - VALIDATED:    verified_matches >= 200 AND success_rate >= 0.55
                  AND binomial p-value (vs 0.5) < 0.05
  - CONTRADICTED: verified_matches >= 50 AND success_rate < 0.45
  - otherwise:    TENTATIVE (evidence not yet conclusive)

Evidence sources are ONLY observables available in the historical dataset
(HT/FT scores, cards, schedule).  Rules whose conditions are not observable
in this data stay at 0 evidence with an explicit ``not_observable`` reason -
never estimated, never guessed.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.schema import HistoricalMatch
from football_simulation.models.base import KnowledgeStatus, new_id, utc_now
from football_simulation.models.knowledge import KnowledgeBase, KnowledgeRule

# ---------------------------------------------------------------------------
# Evidence definitions: rule_id -> observable evaluator
# ---------------------------------------------------------------------------

SUPPORT_MIN_N = 50
VALIDATED_MIN_N = 200
SUPPORT_RATE = 0.52
VALIDATED_RATE = 0.55
CONTRADICTED_RATE = 0.45


class CounterExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterexample_id: str = Field(default_factory=new_id)
    rule_id: str
    match_id: str
    kickoff: datetime
    condition: str
    what_happened: str
    why_contradicts: str
    recorded_at: datetime = Field(default_factory=utc_now)


class RuleEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    observable: bool
    reason: str = ""
    verified_matches: int = 0
    success_rate: Optional[float] = None
    counter_examples: int = 0
    new_status: str = ""
    statistical_note: str = ""


def binomial_p_value(k: int, n: int, p0: float = 0.5) -> float:
    """Two-sided binomial test p-value (normal approximation)."""
    if n == 0:
        return 1.0
    p_hat = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return 0.0 if p_hat != p0 else 1.0
    z = (p_hat - p0) / se
    # two-sided normal approximation
    from math import erf
    return 1.0 - erf(abs(z) / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# Observables (all walk-forward; per-match support/counter judgments)
# ---------------------------------------------------------------------------

def _ht_state(match: HistoricalMatch, team: str) -> str:
    home = match.home_team == team
    gf = match.half_time_home_goals if home else match.half_time_away_goals
    ga = match.half_time_away_goals if home else match.half_time_home_goals
    if gf > ga:
        return "leading"
    if gf < ga:
        return "trailing"
    return "level"


def _sh_goals(match: HistoricalMatch, team: str) -> int:
    home = match.home_team == team
    return (match.home_goals - match.half_time_home_goals) if home else (
        match.away_goals - match.half_time_away_goals)


def _opponent(match: HistoricalMatch, team: str) -> str:
    return match.away_team if match.home_team == team else match.home_team


def _match_congestion(dataset: HistoricalDataset, match: HistoricalMatch, team: str) -> int:
    return feats.fixture_congestion(dataset.matches, team, match.date)


class RuleEvidenceBackfill:
    """Evaluates every evaluable rule against the historical dataset."""

    def __init__(self, dataset: HistoricalDataset, knowledge: Dict[str, KnowledgeBase]):
        self.dataset = dataset
        self.knowledge = knowledge
        self.synthetic = bool(dataset.matches) and all(m.is_synthetic for m in dataset.matches)
        self.counterexamples: List[CounterExample] = []
        self.results: List[RuleEvidenceResult] = []

    # ------------------------------------------------------------------
    def run(self) -> List[RuleEvidenceResult]:
        for pack in self.knowledge.values():
            for rule in pack.rules:
                evaluator = _EVALUATORS.get(rule.rule_id)
                if evaluator is None:
                    self.results.append(RuleEvidenceResult(
                        rule_id=rule.rule_id, observable=False,
                        reason="condition not observable in the available historical data",
                        new_status=rule.status.value,
                    ))
                    continue
                self.results.append(self._evaluate(rule, evaluator))
        return self.results

    def _evaluate(self, rule: KnowledgeRule, evaluator) -> RuleEvidenceResult:
        support = 0
        counters = 0
        seen = 0
        for match in self.dataset.matches:
            verdict = evaluator(self.dataset, match)
            if verdict is None:
                continue
            seen += 1
            if verdict:
                support += 1
            else:
                counters += 1
                if rule.rule_id in _COUNTEREXAMPLE_RULES:
                    self.counterexamples.append(CounterExample(
                        rule_id=rule.rule_id,
                        match_id=match.match_id,
                        kickoff=match.date,
                        condition=_CONDITION_TEXT.get(rule.rule_id, rule.name),
                        what_happened=_WHAT_HAPPENED.get(rule.rule_id, "") or
                                      f"match {match.match_id}",
                        why_contradicts=_WHY_TEXT.get(rule.rule_id, "outcome against the rule direction"),
                    ))
        rate = (support / seen) if seen else None
        if self.synthetic:
            # SYNTHETIC DATA NEVER confers validation: the mechanism runs for
            # pipeline verification, but statuses and evidence stay untouched.
            status = rule.status.value
            note = (f"SYNTHETIC DATA (development-only): {support}/{seen} agree with "
                    f"the rule direction - NOT counted as evidence")
        else:
            status = self._classify(seen, rate)
            note = (f"{support}/{seen} agree with the rule direction"
                    if seen else "no observable instances")
        return RuleEvidenceResult(
            rule_id=rule.rule_id,
            observable=True,
            verified_matches=seen,
            success_rate=round(rate, 4) if rate is not None else None,
            counter_examples=counters,
            new_status=status,
            statistical_note=note,
        )

    @staticmethod
    def _classify(n: int, rate: Optional[float]) -> str:
        if n < SUPPORT_MIN_N or rate is None:
            return KnowledgeStatus.TENTATIVE.value
        if rate < CONTRADICTED_RATE:
            return KnowledgeStatus.CONTRADICTED.value
        if n >= VALIDATED_MIN_N and rate >= VALIDATED_RATE:
            p_value = binomial_p_value(int(round(rate * n)), n)
            if p_value < 0.05:
                return KnowledgeStatus.VALIDATED.value
            return KnowledgeStatus.SUPPORTED.value
        if rate > SUPPORT_RATE:
            return KnowledgeStatus.SUPPORTED.value
        return KnowledgeStatus.TENTATIVE.value

    # ------------------------------------------------------------------
    def apply_to_knowledge(self) -> Dict[str, int]:
        """Write evidence fields + new statuses back into the knowledge packs.

        SYNTHETIC DATA NEVER WRITES ANYTHING: statuses and evidence fields
        stay untouched, so the packs remain honest (0 real evidence).
        """
        by_id = {r.rule_id: r for pack in self.knowledge.values() for r in pack.rules}
        counts: Dict[str, int] = {}
        for result in self.results:
            rule = by_id.get(result.rule_id)
            if rule is None:
                continue
            if self.synthetic:
                counts[rule.status.value] = counts.get(rule.status.value, 0) + 1
                continue
            rule.verified_matches = result.verified_matches
            rule.success_rate = result.success_rate
            rule.counter_examples = result.counter_examples
            if result.observable:
                rule.status = KnowledgeStatus(result.new_status)
                rule.last_verified_at = utc_now()
            counts[result.new_status] = counts.get(result.new_status, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Evaluators: per-match verdicts that AGREE (True) or CONTRADICT (False)
# ---------------------------------------------------------------------------

def _eval_trailing_push(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Trailing teams push': a team trailing at HT keeps attacking in the
    second half -> its 2H goal count should be at least the opponent's."""
    trailing = None
    for team in (match.home_team, match.away_team):
        if _ht_state(match, team) == "trailing":
            trailing = team
            break
    if trailing is None:
        return None
    opp = _opponent(match, trailing)
    return _sh_goals(match, trailing) >= _sh_goals(match, opp)


def _eval_leading_management(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Leading teams manage the game': a team leading at HT concedes fewer
    2H goals than it scores (holds the lead)."""
    leading = None
    for team in (match.home_team, match.away_team):
        if _ht_state(match, team) == "leading":
            leading = team
            break
    if leading is None:
        return None
    opp = _opponent(match, leading)
    return _sh_goals(match, leading) >= _sh_goals(match, opp)


def _eval_red_card(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Down a man is worse': the carded side must not win the match."""
    if match.home_red_cards and not match.away_red_cards:
        return match.home_goals <= match.away_goals
    if match.away_red_cards and not match.home_red_cards:
        return match.away_goals <= match.home_goals
    return None


def _eval_home_crowd(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Home crowd helps': home side wins more than it loses."""
    if match.home_goals == match.away_goals:
        return None
    return match.home_goals > match.away_goals


def _eval_fatigue_late(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Fixture congestion hurts late': the MORE congested team (>=2 matches
    in 14 days AND strictly more than its opponent) concedes at least as many
    2H goals as the fresher side."""
    congestion = {
        team: _match_congestion(dataset, match, team)
        for team in (match.home_team, match.away_team)
    }
    if min(congestion.values()) < 2:
        return None
    home_c, away_c = congestion[match.home_team], congestion[match.away_team]
    if home_c == away_c:
        return None
    team = match.home_team if home_c > away_c else match.away_team
    opp = _opponent(match, team)
    return _sh_goals(match, team) <= _sh_goals(match, opp)


def _eval_trailing_desperate_late(dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[bool]:
    """'Late desperation': trailing at HT, the chasing side's 2H attacking
    output does not collapse below the leader's."""
    return _eval_trailing_push(dataset, match)


# NOTE: R_FATIGUE_LATE_DECLINE is intentionally NOT evaluable with this
# dataset: a pure single-competition round-robin gives BOTH teams identical
# fixture congestion every round, so no 'congested vs fresher' contrast
# exists.  It needs multi-competition (cup/Europe) schedules to be tested -
# recording it as not-observable is the honest choice, not a silent skip.

_EVALUATORS = {
    "R_MENTALITY_TRAIL_PUSH": _eval_trailing_push,
    "R_MENTALITY_TRAIL_PUSH_AWAY": _eval_trailing_push,
    "R_TRAIL_DESPERATE_LATE": _eval_trailing_desperate_late,
    "R_TRAIL_DESPERATE_LATE_AWAY": _eval_trailing_desperate_late,
    "R_MENTALITY_LEAD_TEMPO": _eval_leading_management,
    "R_MENTALITY_LEAD_AWAY_TEMPO": _eval_leading_management,
    "R_LEAD_LATE_GAME_MANAGEMENT": _eval_leading_management,
    "R_LEAD_LATE_GAME_MANAGEMENT_AWAY": _eval_leading_management,
    "R_RED_CARD_HOME_DISADVANTAGE": _eval_red_card,
    "R_RED_CARD_AWAY_DISADVANTAGE": _eval_red_card,
    "R_HOME_CROWD_SUPPORT": _eval_home_crowd,
}

_COUNTEREXAMPLE_RULES = set(_EVALUATORS)

_CONDITION_TEXT = {
    "R_MENTALITY_TRAIL_PUSH": "team trailing at half time",
    "R_MENTALITY_TRAIL_PUSH_AWAY": "team trailing at half time",
    "R_TRAIL_DESPERATE_LATE": "team trailing at half time",
    "R_TRAIL_DESPERATE_LATE_AWAY": "team trailing at half time",
    "R_MENTALITY_LEAD_TEMPO": "team leading at half time",
    "R_MENTALITY_LEAD_AWAY_TEMPO": "team leading at half time",
    "R_LEAD_LATE_GAME_MANAGEMENT": "team leading at half time",
    "R_LEAD_LATE_GAME_MANAGEMENT_AWAY": "team leading at half time",
    "R_RED_CARD_HOME_DISADVANTAGE": "home side received a red card",
    "R_RED_CARD_AWAY_DISADVANTAGE": "away side received a red card",
    "R_HOME_CROWD_SUPPORT": "home match",
    "R_FATIGUE_LATE_DECLINE": "team with 3+ matches in 14 days",
    "R_FATIGUE_LATE_DECLINE_AWAY": "team with 3+ matches in 14 days",
}

_WHAT_HAPPENED = {
    "R_RED_CARD_HOME_DISADVANTAGE": "carded home side still won",
    "R_RED_CARD_AWAY_DISADVANTAGE": "carded away side still won",
}

_WHY_TEXT = {
    "R_MENTALITY_TRAIL_PUSH": "trailing side scored fewer 2H goals than the leader",
    "R_MENTALITY_TRAIL_PUSH_AWAY": "trailing side scored fewer 2H goals than the leader",
    "R_TRAIL_DESPERATE_LATE": "trailing side scored fewer 2H goals than the leader",
    "R_TRAIL_DESPERATE_LATE_AWAY": "trailing side scored fewer 2H goals than the leader",
    "R_MENTALITY_LEAD_TEMPO": "leading side conceded more 2H goals than it scored",
    "R_MENTALITY_LEAD_AWAY_TEMPO": "leading side conceded more 2H goals than it scored",
    "R_LEAD_LATE_GAME_MANAGEMENT": "leading side conceded more 2H goals than it scored",
    "R_LEAD_LATE_GAME_MANAGEMENT_AWAY": "leading side conceded more 2H goals than it scored",
    "R_RED_CARD_HOME_DISADVANTAGE": "down a man, the side still won",
    "R_RED_CARD_AWAY_DISADVANTAGE": "down a man, the side still won",
    "R_HOME_CROWD_SUPPORT": "home side lost",
    "R_FATIGUE_LATE_DECLINE": "congested side outscored the rested opponent in 2H",
    "R_FATIGUE_LATE_DECLINE_AWAY": "congested side outscored the rested opponent in 2H",
}


# ---------------------------------------------------------------------------
# Counterexample store
# ---------------------------------------------------------------------------

class CounterexampleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: List[CounterExample] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = [CounterExample.model_validate(e) for e in payload.get("counterexamples", [])]

    def add_many(self, entries: List[CounterExample]) -> None:
        self.entries.extend(entries)
        self.save()

    def save(self) -> None:
        payload = {"counterexamples": [e.model_dump(mode="json") for e in self.entries]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
