"""Opinion Fusion Layer.

The Director never simply averages agent opinions: opinions are weighted by
confidence x evidence strength x impact and their disagreement is measured
and reported (spec section 37).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from football_simulation.models.base import AgentOpinion

_IMPACT_WEIGHT = {"low": 0.5, "medium": 1.0, "high": 1.5}


class OpinionFusionLayer:
    """Fuses AgentOpinions on the same subject into one value + agreement."""

    def fuse(self, opinions: List[AgentOpinion], subject: Optional[str] = None) -> Dict[str, float]:
        """Return {'value': fused, 'agreement': 0..1, 'spread': float}."""
        if subject is not None:
            opinions = [o for o in opinions if o.subject == subject]
        if not opinions:
            return {"value": 0.0, "agreement": 0.0, "spread": 1.0}

        weights = []
        for o in opinions:
            evidence_weight = min(1.0, 0.4 + 0.3 * len(o.evidence))
            weights.append(
                o.confidence * evidence_weight * _IMPACT_WEIGHT.get(o.impact.value, 1.0)
            )
        total = sum(weights)
        if total <= 0:
            return {"value": sum(o.value for o in opinions) / len(opinions), "agreement": 0.0, "spread": 1.0}

        fused = sum(o.value * w for o, w in zip(opinions, weights)) / total
        values = [o.value for o in opinions]
        mean = sum(values) / len(values)
        if len(values) > 1:
            variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            std = math.sqrt(variance)
            scale = max(0.001, (max(values) - min(values)))
            spread = std / scale if scale > 0 else 0.0
            agreement = max(0.0, min(1.0, 1.0 - spread))
        else:
            agreement = 1.0
            spread = 0.0
        return {"value": fused, "agreement": round(agreement, 4), "spread": round(spread, 4)}

    def fuse_all(self, opinions: List[AgentOpinion]) -> Dict[str, Dict[str, float]]:
        """Fuse per subject."""
        subjects = sorted({o.subject for o in opinions})
        return {subject: self.fuse(opinions, subject) for subject in subjects}
