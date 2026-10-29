# -*- coding: utf-8 -*-
"""External signal gating — status management ONLY.

Signals never modify prediction probabilities (PREDICTION_MATRIX invariant P3):
a signal becomes a *candidate* only when
    dq_namespace == "forward"  AND  dq_status == "time_safe"
    AND retrieved_at < kickoff_utc,
and even then its status is AVAILABLE_NOT_VALIDATED: the pre-registered
increment test (FORWARD_INCREMENT_TEST_PRE_REGISTRATION.md, gates: >=300
time_safe matches per league-season, complete season, mean dLL >= 0.003,
direction stability, AUC non-inferiority) has not been evaluated.

TIME_SAFE_VALIDATED can only be granted to sources listed in
validated_signal_registry.json (none exists as of 2026-09-13), never hardcoded.

Understat historical retrospective data (namespace dq_validation /
historical_retro label / frozen-season data) is REJECTED for prediction —
permanently, per PHASE5.3_FORWARD_VALIDATION_RE-SCOPE.md.

generated_at / published_at are never inferred: absent means UNKNOWN.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

OVERALL_NOT_AVAILABLE = "NOT_AVAILABLE"
OVERALL_CANDIDATE = "AVAILABLE_NOT_VALIDATED"
OVERALL_VALIDATED = "TIME_SAFE_VALIDATED"
OVERALL_REJECTED = "REJECTED"

SIGNAL_STATUSES = ("candidate", "rejected", "unknown", "validated")

_FORBIDDEN_NAMESPACES = {"dq_validation", "historical_retro", "retro", "historical"}
_VALID_REGISTRY_NAME = "validated_signal_registry.json"


def _parse_iso(ts) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _load_validated_registry() -> dict:
    """Validated-signal registry (currently absent -> no source can be TIME_SAFE_VALIDATED)."""
    p = Path(__file__).resolve().parent / _VALID_REGISTRY_NAME
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {s["source"]: s for s in data.get("validated_sources", [])}
    except Exception:
        return {}


def gate_signal(sig: dict, kickoff_utc: datetime | None) -> dict:
    """Evaluate one external-signal record. Returns a status record (never alters probabilities)."""
    src = str(sig.get("source", "unknown"))
    ns = str(sig.get("namespace", "unknown")).lower()
    dq = str(sig.get("dq_status", "unknown")).lower()
    retrieved = _parse_iso(sig.get("retrieved_at"))
    gen = sig.get("generated_at")
    pub = sig.get("published_at")

    rec = {
        "source": src,
        "namespace": ns,
        "dq_status": dq,
        "retrieved_at": sig.get("retrieved_at"),
        "generated_at": gen,
        "published_at": pub,
        "generated_at_status": "UNKNOWN" if gen is None else "RECORDED",
        "published_at_status": "UNKNOWN" if pub is None else "RECORDED",
        "status": "rejected",
        "reason": "",
    }

    if ns in _FORBIDDEN_NAMESPACES or dq == "historical_retro":
        rec["reason"] = "historical retrospective data permanently excluded from prediction"
        return rec
    if ns != "forward":
        rec["reason"] = f"namespace '{ns}' is not the forward namespace"
        return rec
    if dq != "time_safe":
        rec["reason"] = f"dq_status '{dq}' is not time_safe"
        return rec
    if retrieved is None:
        rec["reason"] = "retrieved_at missing or unparseable; time-safety unprovable"
        rec["status"] = "unknown"
        return rec
    if kickoff_utc is None:
        rec["reason"] = "kickoff_utc missing; cannot evaluate retrieved_at < kickoff"
        rec["status"] = "unknown"
        return rec
    if retrieved >= kickoff_utc:
        rec["reason"] = "retrieved_at >= kickoff_utc (not time-safe for this match)"
        return rec

    if src in _load_validated_registry():
        rec["status"] = "validated"
        rec["reason"] = "source present in validated_signal_registry (increment gates passed)"
        return rec
    rec["status"] = "candidate"
    rec["reason"] = ("time-safe forward candidate; increment value NOT validated "
                     "(pre-registered gates unevaluated) — never used in probabilities")
    return rec


def gate_signals(signals: list | None, kickoff_utc: datetime | None) -> dict:
    """Gate all signals; produce the aggregate signal-layer status."""
    records = [gate_signal(s, kickoff_utc) for s in (signals or [])]
    statuses = [r["status"] for r in records]
    if not records:
        overall = OVERALL_NOT_AVAILABLE
    elif "validated" in statuses:
        overall = OVERALL_VALIDATED
    elif "candidate" in statuses:
        overall = OVERALL_CANDIDATE
    elif "unknown" in statuses:
        overall = OVERALL_NOT_AVAILABLE
    else:
        overall = OVERALL_REJECTED
    return {
        "overall_status": overall,
        "signals_used_in_prediction": False,   # invariant P3 — structurally false today
        "signals": records,
        "evidence_level": "Hypothesis" if overall == OVERALL_CANDIDATE else "Unknown",
        "note": ("xG/increment value unproven: FORWARD_INCREMENT_TEST_PRE_REGISTRATION.md gates "
                 "unevaluated; TIME_SAFE_VALIDATED requires validated_signal_registry.json (absent)"),
    }
