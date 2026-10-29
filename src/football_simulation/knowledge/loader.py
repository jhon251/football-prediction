"""Knowledge layer: loaders for versioned knowledge packs.

Knowledge (rules, principles, tactical patterns, event baseline parameters)
lives in JSON files under ``football_simulation/knowledge/`` - never hardcoded
in agent logic.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict, List

from football_simulation.models.knowledge import KnowledgeBase, KnowledgeRule


def _load_json(name: str) -> Dict[str, Any]:
    data = resources.files("football_simulation.knowledge").joinpath(name).read_text(encoding="utf-8")
    return json.loads(data)


def load_default_knowledge_base() -> KnowledgeBase:
    """Load the default state-transition/psychology rule pack."""
    payload = _load_json("default_knowledge.json")
    rules = [KnowledgeRule.model_validate(r) for r in payload.pop("rules", [])]
    return KnowledgeBase(rules=rules, **payload)


def load_tactical_patterns() -> KnowledgeBase:
    """Load the tactical matchup pattern pack."""
    payload = _load_json("tactical_patterns.json")
    rules = [KnowledgeRule.model_validate(r) for r in payload.pop("rules", [])]
    return KnowledgeBase(rules=rules, **payload)


def load_event_defaults() -> Dict[str, Any]:
    """Load event-engine baseline parameters and dependency rules."""
    return _load_json("event_defaults.json")


def load_all_knowledge() -> Dict[str, Any]:
    """Aggregate every knowledge pack into one structure for the Director."""
    return {
        "rules": load_default_knowledge_base(),
        "tactical_patterns": load_tactical_patterns(),
        "event_defaults": load_event_defaults(),
    }
