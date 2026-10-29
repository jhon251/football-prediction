"""Learning Agent + Post-Match Evaluation Agent + Learning Store.

Post-match, the Learning Agent compares prediction/simulation/scenario with
the ACTUAL match, records prediction errors, and proposes Candidate Rules.
V1 NEVER auto-modifies core football rules: candidate rules must be validated
before they can become Validated Rules (spec sections 39/40).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, KnowledgeStatus, RiskLevel, new_id, utc_now
from football_simulation.models.data import ActualMatchResult
from football_simulation.models.report import MatchPredictionReport


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class CandidateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(default_factory=new_id)
    name: str
    category: str = "rules"
    description: str = ""
    condition: Dict[str, Any] = Field(default_factory=dict)
    effects: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "candidate"
    evidence_count: int = 1
    proposal_reason: str = ""
    proposed_at: datetime = Field(default_factory=utc_now)


class PostMatchEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    evaluated_at: datetime = Field(default_factory=utc_now)
    prediction_accuracy: float = Field(ge=0.0, le=1.0)
    scenario_accuracy: float = Field(ge=0.0, le=1.0)
    tactical_accuracy: float = Field(ge=0.0, le=1.0)
    event_accuracy: float = Field(ge=0.0, le=1.0)
    result_accuracy: str = "incorrect"
    score_accuracy: str = "incorrect"
    ou_accuracy: str = "incorrect"
    btts_accuracy: str = "incorrect"
    htft_accuracy: str = "incorrect"
    upset_detection_accuracy: str = "n/a"
    expected_total_goals: float = 0.0
    actual_total_goals: int = 0
    expected_goals_error: float = 0.0
    notes: List[str] = Field(default_factory=list)


class LearningRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=new_id)
    match_id: str
    created_at: datetime = Field(default_factory=utc_now)
    evaluation: PostMatchEvaluation
    candidate_rules: List[CandidateRule] = Field(default_factory=list)
    prediction_summary: Dict[str, Any] = Field(default_factory=dict)
    actual_summary: Dict[str, Any] = Field(default_factory=dict)


class LearningStore:
    """JSON persistence for learning records (never touches core knowledge)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else Path("learning_store.json")
        self.records: List[LearningRecord] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = [LearningRecord.model_validate(r) for r in payload.get("records", [])]

    def save(self) -> None:
        payload = {"records": [r.model_dump(mode="json") for r in self.records]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, record: LearningRecord) -> None:
        self.records.append(record)
        self.save()

    def candidates(self) -> List[CandidateRule]:
        out: List[CandidateRule] = []
        for record in self.records:
            out.extend(record.candidate_rules)
        return out


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------

class PostMatchEvaluationAgent(BaseAgent[PostMatchEvaluation]):
    name = "PostMatchEvaluationAgent"
    description = "Evaluates prediction vs actual match across all output dimensions."

    def evaluate(
        self, prediction: MatchPredictionReport, actual: ActualMatchResult
    ) -> PostMatchEvaluation:
        notes: List[str] = []
        result = prediction.result_probability
        predicted_outcome = result.outcome()
        actual_outcome = (
            "home_win" if actual.score_home > actual.score_away
            else ("away_win" if actual.score_away > actual.score_home else "draw")
        )
        result_correct = predicted_outcome == actual_outcome
        if result_correct:
            notes.append("prediction success: correct 1X2 outcome")
        else:
            notes.append(f"prediction failure: predicted {predicted_outcome}, actual {actual_outcome}")

        pred_prob = getattr(result, predicted_outcome)
        prediction_accuracy = pred_prob if result_correct else 0.0

        # score accuracy
        pred_score = prediction.score_probability.top(1)[0]["score"] if prediction.score_probability.matrix else ""
        actual_score = f"{actual.score_home}-{actual.score_away}"
        score_correct = pred_score == actual_score
        if not score_correct:
            note = f"score prediction missed: predicted {pred_score}, actual {actual_score}"
            if prediction.score_probability.matrix.get(actual_score, 0.0) > 0.05:
                note += " (actual score still in the top mass)"
            notes.append(note)

        # O/U accuracy at 2.5
        total = actual.score_home + actual.score_away
        p_over = prediction.goals_probability.over.get("2.5", 0.5)
        ou_correct = (p_over >= 0.5) == (total > 2.5)
        notes.append(f"O/U 2.5: predicted over {p_over:.2f}, actual total {total}")

        # BTTS
        btts_actual = actual.score_home > 0 and actual.score_away > 0
        btts_correct = (prediction.btts.yes >= 0.5) == btts_actual

        # HTFT
        ht = "home" if actual.ht_score_home > actual.ht_score_away else (
            "away" if actual.ht_score_away > actual.ht_score_home else "draw"
        )
        ft = actual_outcome
        htft_key = f"{ht}/{ft}"
        htft_correct = prediction.half_time_full_time.combinations.get(htft_key, 0.0) >= max(
            prediction.half_time_full_time.combinations.values(), default=0.0
        )

        # event accuracy: expected vs actual goals
        expected_goals = prediction.goals_probability.expected_total_goals
        error = abs(expected_goals - total)
        event_accuracy = max(0.0, 1.0 - error / 2.5)

        # scenario accuracy: did any top scenario match the actual result?
        scenario_accuracy = 0.0
        for scenario in prediction.scenarios[:5]:
            if scenario.final_result.get("result") == actual_outcome:
                scenario_accuracy = max(scenario_accuracy, scenario.probability)
                break

        # tactical accuracy (formation-level, when available)
        tactical_accuracy = 0.0
        pred_form_home = ""
        pred_form_away = ""
        if prediction.scenarios and prediction.scenarios[0].initial_conditions:
            pred_form_home = prediction.scenarios[0].initial_conditions.get("formation_home") or ""
            pred_form_away = prediction.scenarios[0].initial_conditions.get("formation_away") or ""
        if pred_form_home or pred_form_away:
            hits = 0
            total_checks = 0
            if pred_form_home:
                total_checks += 1
                hits += 1 if pred_form_home == actual.home_formation else 0
            if pred_form_away:
                total_checks += 1
                hits += 1 if pred_form_away == actual.away_formation else 0
            tactical_accuracy = hits / total_checks
        else:
            tactical_accuracy = 0.5  # unknown formations: neutral

        # upset detection: was the actual outcome an upset per our model?
        upset_prob = getattr(result, actual_outcome)
        upset_detected = upset_prob < 0.25
        upset_detection_accuracy = "n/a"
        if prediction.upset_risk.level in (RiskLevel.HIGH, RiskLevel.VERY_HIGH):
            upset_detection_accuracy = "correct" if upset_detected else "false_positive"
        else:
            upset_detection_accuracy = "correct_negative" if not upset_detected else "missed_upset"

        return PostMatchEvaluation(
            match_id=actual.match_id,
            prediction_accuracy=round(prediction_accuracy, 4),
            scenario_accuracy=round(scenario_accuracy, 4),
            tactical_accuracy=round(tactical_accuracy, 4),
            event_accuracy=round(event_accuracy, 4),
            result_accuracy="correct" if result_correct else "incorrect",
            score_accuracy="correct" if score_correct else "incorrect",
            ou_accuracy="correct" if ou_correct else "incorrect",
            btts_accuracy="correct" if btts_correct else "incorrect",
            htft_accuracy="correct" if htft_correct else "incorrect",
            upset_detection_accuracy=upset_detection_accuracy,
            expected_total_goals=round(expected_goals, 3),
            actual_total_goals=total,
            expected_goals_error=round(error, 3),
            notes=notes,
        )

    def run(self, context: AgentContext) -> AgentResult[PostMatchEvaluation]:
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        prediction = extra.get("prediction")
        actual = extra.get("actual")
        if prediction is None or actual is None:
            return self.fail(context, "missing prediction or actual result")
        evaluation = self.evaluate(prediction, actual)
        return self.ok(
            context,
            evaluation,
            confidence=0.85,
            evidence=evaluation.notes,
            reasoning="Evaluation compares every output section against ground truth.",
        )


class LearningAgent(BaseAgent[LearningRecord]):
    name = "LearningAgent"
    description = "Records prediction errors and proposes Candidate Rules (never auto-modifies core rules)."

    def learn(
        self, prediction: MatchPredictionReport, actual: ActualMatchResult,
        evaluator: PostMatchEvaluationAgent, store: LearningStore,
    ) -> LearningRecord:
        evaluation = evaluator.evaluate(prediction, actual)
        candidate_rules = self._propose_candidates(prediction, actual, evaluation)
        record = LearningRecord(
            match_id=actual.match_id,
            evaluation=evaluation,
            candidate_rules=candidate_rules,
            prediction_summary={
                "result": prediction.result_probability.model_dump(),
                "expected_goals": prediction.goals_probability.expected_total_goals,
                "upset_level": prediction.upset_risk.level.value,
            },
            actual_summary={
                "score": [actual.score_home, actual.score_away],
                "xg": [actual.xg_home, actual.xg_away],
                "formation_home": actual.home_formation,
            },
        )
        store.add(record)
        return record

    def _propose_candidates(
        self, prediction: MatchPredictionReport, actual: ActualMatchResult,
        evaluation: PostMatchEvaluation,
    ) -> List[CandidateRule]:
        candidates: List[CandidateRule] = []
        # Goal-rate calibration proposals (evidence-based, candidate only)
        if evaluation.expected_goals_error > 1.0:
            direction = "lower" if evaluation.expected_total_goals > evaluation.actual_total_goals else "raise"
            candidates.append(
                CandidateRule(
                    name="goal_rate_calibration",
                    category="rules",
                    description=f"Match {actual.match_id}: expected goals {evaluation.expected_total_goals:.2f} "
                                f"vs actual {evaluation.actual_total_goals} -> {direction} base attack intensity slightly.",
                    proposal_reason=f"expected-goals error {evaluation.expected_goals_error:.2f} exceeded 1.0",
                )
            )
        if evaluation.result_accuracy == "incorrect" and getattr(
            prediction.result_probability, prediction.result_probability.outcome()
        ) > 0.6:
            candidates.append(
                CandidateRule(
                    name="high_confidence_miss",
                    category="principles",
                    description=f"Match {actual.match_id}: model was >60% confident in "
                                f"{prediction.result_probability.outcome()} yet the actual outcome differed.",
                    proposal_reason="high-confidence miss detected",
                )
            )
        return candidates

    def run(self, context: AgentContext) -> AgentResult[LearningRecord]:
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        prediction = extra.get("prediction")
        actual = extra.get("actual")
        store = extra.get("learning_store")
        if prediction is None or actual is None or store is None:
            return self.fail(context, "missing prediction/actual/store")
        record = self.learn(prediction, actual, PostMatchEvaluationAgent(), store)
        return self.ok(
            context,
            record,
            confidence=0.7,
            evidence=[f"recorded {len(record.candidate_rules)} candidate rule(s)"],
            reasoning="Learning writes records + candidate rules only; core rules remain untouched.",
        )
