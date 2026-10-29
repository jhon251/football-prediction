# -*- coding: utf-8 -*-
"""Frozen-dataset provenance guard.

The prediction module reads NO data from the frozen dataset (it needs only
preclosing odds), but it pins the frozen v1.1.0 fingerprint so that any drift
of the research substrate is surfaced as STOP rather than silently ignored.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FROZEN_SHA256 = "8f885fbcc38aca3f4ea0b88a925b07db23244fccec7ed09b1f7cb55c45b13442"
_DEFAULT_PATH = (Path(__file__).resolve().parents[2] / "backtest_output" / "dataset_build"
                 / "freeze" / "1.1.0" / "baseline_dataset.jsonl")

_cached = {"path": None, "result": None}


def frozen_fingerprint(path: Path | str | None = None) -> dict:
    """Verify the frozen dataset sha256. Returns {referenced_sha256, verified, path, note}."""
    p = Path(path) if path else _DEFAULT_PATH
    if path is None and _cached["path"] == str(p) and _cached["result"] is not None:
        return _cached["result"]
    if not p.exists():
        result = {"referenced_sha256": FROZEN_SHA256, "verified": False, "path": str(p),
                  "note": "frozen dataset file not found; provenance UNKNOWN (odds-only prediction unaffected)"}
    else:
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got == FROZEN_SHA256:
            result = {"referenced_sha256": FROZEN_SHA256, "verified": True, "path": str(p),
                      "note": "frozen v1.1.0 fingerprint verified"}
        else:
            result = {"referenced_sha256": FROZEN_SHA256, "verified": False, "path": str(p),
                      "note": f"FROZEN FINGERPRINT DRIFT: got {got}", "drift": True}
    if path is None:
        _cached["path"] = str(p)
        _cached["result"] = result
    return result
