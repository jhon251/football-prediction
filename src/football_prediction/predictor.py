# -*- coding: utf-8 -*-
"""Minimal prediction orchestrator.

Pipeline (fixed order, see PREDICTION_MODULE_SPEC.md §3):
  structure validation -> leakage guards -> time-safety gate -> frozen
  fingerprint check -> market baseline M4/O2 (reused Phase 4A algorithm) ->
  external-signal gating (status only) -> uncertainty/confidence -> output.

Hard invariants (PREDICTION_MATRIX.md):
  P1 probabilities sum to 1 and come only from devig;
  P2 missing odds -> null probabilities, never fabricated;
  P3 external signals never modify probabilities;
  P4 every output carries provenance;
  P5 fallbacks are recorded and downgrade status to CONDITIONAL;
  P6 leakage / frozen-fingerprint drift -> STOP, report-only.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from football_prediction import market as M
from football_prediction import signals as S
from football_prediction.provenance import frozen_fingerprint
from football_prediction.schema import PredictionInput, worst_state

MODEL_VERSION = "football_prediction 0.1.0 (market M4/O2, shin solver pinned to phase4a run_phase4a.py)"
SCHEMA_VERSION = "prediction_output.v1"
FORBIDDEN_USE = ("research prediction only; no betting / ROI / EV / stake / profit claims; "
                 "not an Agent, not a validated signal model")

_FORBIDDEN_LABEL_KEYS = {"fthg", "ftag", "ftr", "label", "result", "score",
                         "home_score", "away_score", "home_goals", "away_goals"}
# football-data.co.uk closing convention: closing marker 'C' sits between the book
# code and the leg letter (B365CH), so in nested form a closing book is a code
# whose de-C'd form is a registered book, and a closing leg is exactly CH/CD/CA/C>/C<.
_CLOSING_LEGS = {"CH", "CD", "CA", "C>", "C<"}
_REGISTERED_CODES = set(M.BOOKS_1X2) | set(M.BOOKS_OU)


def _is_closing_book(code: str) -> bool:
    return code.endswith("C") and code[:-1] in _REGISTERED_CODES


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_output(match: dict | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "prediction_utc": _now_utc(),
        "match": match or {},
        "ftr": {"status": None, "probabilities": None, "method": None,
                "evidence_level": "Evidence", "evidence_refs": ["phase3b", "phase4a"]},
        "ou25": {"status": None, "probabilities": None, "method": None,
                 "evidence_level": "Evidence", "evidence_refs": ["phase3b", "phase4a"]},
        "market_data": {},
        "external_signals": {},
        "data_quality": {},
        "uncertainty": {},
        "confidence": {},
        "frozen_dataset_provenance": {},
        "forbidden_use": FORBIDDEN_USE,
    }


def _rejected(match: dict, reasons: list[str], violations: list[str] | None = None) -> dict:
    out = _base_output(match)
    out["ftr"]["status"] = out["ou25"]["status"] = "REJECTED"
    out["overall_status"] = "REJECTED"
    out["rejection_reasons"] = reasons
    out["data_quality"] = {"leakage_guards": {"triggered": True, "violations": violations or reasons}}
    return out


def _stopped(match: dict, reason: str, provenance: dict) -> dict:
    out = _base_output(match)
    out["ftr"]["status"] = out["ou25"]["status"] = "STOP"
    out["overall_status"] = "STOP"
    out["stop_reason"] = reason
    out["frozen_dataset_provenance"] = provenance
    return out


def _pre_scan(raw: dict) -> tuple[list[str], list[str]]:
    """Return (rejection_reasons, csuffix_dropped_keys). Label fields anywhere -> reject."""
    reasons, dropped = [], set()

    def scan(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if kl in _FORBIDDEN_LABEL_KEYS and not path.startswith("external_signals"):
                    reasons.append(f"forbidden label-like field '{k}' at {path or '<root>'} "
                                   f"(label leakage guard)")
                scan(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, f"{path}[{i}]")

    scan(raw, "")
    odds = raw.get("odds") or {}
    books = odds.get("books") if isinstance(odds, dict) else None
    if isinstance(books, dict):
        for code, legs in dict(books).items():
            if _is_closing_book(str(code)):
                dropped.update(f"{code}.{leg}" for leg in (legs or {}))
                del books[code]
            elif isinstance(legs, dict):
                for leg in list(legs):
                    if str(leg) in _CLOSING_LEGS:
                        del legs[leg]
                        dropped.add(f"{code}.{leg}")
    return reasons, sorted(dropped)


def _market_block(res: M.MethodResult | None, time_safe_unknown: bool,
                  kickoff_missing: bool) -> dict:
    if res is None:
        return {"status": "INSUFFICIENT_DATA", "probabilities": None, "method": None,
                "evidence_level": "Evidence", "evidence_refs": ["phase3b", "phase4a"]}
    status = "CONDITIONAL" if res.fallback_chain else "VALID"
    if time_safe_unknown:
        status = "CONDITIONAL"
        res.fallback_chain.append("time_safe UNKNOWN (odds retrieved_at or kickoff missing)")
    probs = {"home": res.probabilities[0], "draw": res.probabilities[1], "away": res.probabilities[2]} \
        if len(res.probabilities) == 3 else {"over": res.probabilities[0], "under": res.probabilities[1]}
    method = {
        "method_id": res.method_id, "norm": "shin", "input": "multi-book" if res.n_books > 1 else "single-book",
        "n_books": res.n_books, "books_used": res.books_used,
        "shin_z": None if res.shin_z is None else round(res.shin_z, 6),
        "overround": None if res.overround is None else round(res.overround, 6),
        "books_dropped": res.dropped_books, "fallback_chain": res.fallback_chain,
        "kickoff_missing": kickoff_missing,
    }
    return {"status": status, "probabilities": probs, "method": method,
            "evidence_level": "Evidence", "evidence_refs": ["phase3b", "phase4a"]}


def predict_match(raw: dict, frozen_path=None) -> dict:
    """Predict one match. Never raises for bad input; returns prediction_output.v1."""
    if not isinstance(raw, dict):
        return _rejected({}, ["input is not a JSON object"])

    # 1-2) leakage pre-scan (label fields, C-suffix odds keys)
    reasons, csuffix_dropped = _pre_scan(raw)
    if reasons:
        return _rejected(raw.get("match") if isinstance(raw.get("match"), dict) else {}, reasons)

    # 3) structure validation
    try:
        inp = PredictionInput.model_validate(raw)
    except ValidationError as e:
        return _rejected(raw.get("match") if isinstance(raw.get("match"), dict) else {},
                         ["input schema validation failed"],
                         [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()])

    match = inp.match.model_dump()
    kickoff = S._parse_iso(match["kickoff_utc"])
    kickoff_missing = kickoff is None
    if kickoff_missing:
        # schema requires the string; unparseable content -> cannot evaluate time safety
        return _rejected(match, [f"kickoff_utc '{match['kickoff_utc']}' is not parseable ISO8601"])

    # 4) frozen fingerprint check (STOP on drift)
    prov = frozen_fingerprint(frozen_path)
    if prov.get("drift"):
        return _stopped(match, "frozen dataset fingerprint drift detected", prov)

    # 5) market time-safety gate
    retrieved = S._parse_iso(inp.odds.retrieved_at)
    if retrieved is not None and retrieved >= kickoff:
        return _rejected(match, [f"odds retrieved_at ({inp.odds.retrieved_at}) >= kickoff_utc "
                                 f"({match['kickoff_utc']}): post-kickoff odds are not a "
                                 f"pre-match input (time-safety gate)"])
    time_safe_unknown = retrieved is None

    # 6) market baselines (reused Phase 4A algorithm)
    ftr_res = M.ftr_prediction(inp.odds.books)
    ou_res = M.ou25_prediction(inp.odds.books)
    ftr_block = _market_block(ftr_res, time_safe_unknown, False)
    ou_block = _market_block(ou_res, time_safe_unknown, False)

    out = _base_output(match)
    out["ftr"] = ftr_block
    out["ou25"] = ou_block

    # 7) external signals (status only — invariant P3)
    out["external_signals"] = S.gate_signals(inp.external_signals, kickoff)

    # 8) data quality / provenance
    missing_fields = []
    for code, legs in inp.odds.books.items():
        missing = [leg for leg in ("H", "D", "A", ">2.5", "<2.5") if leg not in legs]
        if missing:
            missing_fields.append(f"{code}: missing {','.join(missing)}")
    completeness = "COMPLETE"
    if missing_fields or time_safe_unknown or ftr_block["status"] != "VALID" \
            or ou_block["status"] != "VALID":
        completeness = "PARTIAL"
    if ftr_block["status"] == "INSUFFICIENT_DATA" and ou_block["status"] == "INSUFFICIENT_DATA":
        completeness = "INSUFFICIENT"
    out["market_data"] = {
        "context": inp.odds.context, "source": inp.odds.source,
        "retrieved_at": inp.odds.retrieved_at,
        "books_declared": sorted(inp.odds.books), "missing_fields": missing_fields,
        "csuffix_keys_dropped": csuffix_dropped,
    }
    out["data_quality"] = {
        "time_safe_status": "UNKNOWN" if time_safe_unknown else "TIME_SAFE",
        "completeness": completeness,
        "leakage_guards": {"closing_input_rejected": False, "label_field_detected": False,
                           "csuffix_keys_dropped": len(csuffix_dropped)},
    }
    out["frozen_dataset_provenance"] = prov

    # 9) descriptive uncertainty (not a model posterior)
    disp_ftr = M.book_dispersion_max(inp.odds.books, M.FTR_LEGS)
    entropy = M.entropy_bits(ftr_block["probabilities"].values()) if ftr_block["probabilities"] else None
    notes = ["entropy is match-intrinsic uncertainty, not a data-quality measure"]
    grade = "LOW"
    if disp_ftr is not None and disp_ftr > 0.05:
        grade, notes = "HIGH", notes + [f"cross-book dispersion {disp_ftr:.3f} > 0.05"]
    elif disp_ftr is None or disp_ftr > 0.02 or ftr_block["method"]["n_books"] < 2:
        grade = "MEDIUM"
        notes.append("few/no multi-book dispersion evidence" if disp_ftr is None else "moderate dispersion")
    if ftr_block["status"] != "VALID" or ou_block["status"] != "VALID":
        grade = "HIGH" if grade == "MEDIUM" else grade
        notes.append("fallback/insufficient market input raises uncertainty")
    out["uncertainty"] = {
        "ftr_entropy_bits": None if entropy is None else round(entropy, 4),
        "book_dispersion_max_ftr": None if disp_ftr is None else round(disp_ftr, 4),
        "grade": grade, "notes": notes,
    }

    # 10) confidence
    reasons_c = []
    if ftr_block["status"] == "VALID" and ou_block["status"] == "VALID" \
            and not ftr_block["method"]["fallback_chain"] \
            and ftr_block["method"]["n_books"] >= 4 and not time_safe_unknown:
        grade_c, reasons_c = "HIGH", ["both markets VALID via registered baselines, >=4 books, time-safe"]
    elif ftr_block["status"] in ("VALID", "CONDITIONAL") or ou_block["status"] in ("VALID", "CONDITIONAL"):
        grade_c = "LOW" if "fallback/insufficient market input raises uncertainty" in notes or time_safe_unknown else "MEDIUM"
        reasons_c = ["partial market input, fallback, or unknown time-safety"] if grade_c == "LOW" \
            else ["market input usable with minor caveats"]
    else:
        grade_c, reasons_c = "N/A", ["no market probabilities available"]
    out["confidence"] = {"grade": grade_c, "reasons": reasons_c}
    out["confidence"]["reasons"] = reasons_c + (["confidence is not a probability of correctness"] if grade_c != "N/A" else [])

    out["overall_status"] = worst_state([ftr_block["status"], ou_block["status"]])
    out["unrecognized_fields"] = sorted(set(raw) - set(PredictionInput.model_fields))
    return out
