# -*- coding: utf-8 -*-
"""Orchestration service: fixture -> pre-match odds capture -> predictor ->
derived score matrix. The glue behind the webapp's one-click predict.

Design notes:
  * football_prediction.predictor.predict_match is called UNMODIFIED — this
    layer only assembles its prediction_input.v1 and attaches the derived
    score_matrix block to the returned payload (the frozen pipeline and its
    invariants P1..P6 are untouched);
  * pre-match eligibility is enforced twice: fixtures only list pre-match
    events, and predict_event re-checks state right before capture, so a
    match that kicked off since the feed was built is rejected with a clear
    code instead of silently feeding in-play odds to the time-safety gate;
  * every prediction is appended to backtest_output/webapp_predict_log.jsonl
    (append-only audit line; logging failures never break a prediction).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from football_prediction import injuries_feed as FD
from football_prediction import odds_api as TOA
from football_prediction import odds_feed as F
from football_prediction.predictor import predict_match
from football_prediction.score_matrix import derive_score_matrix
from football_prediction.upset_risk import derive_upset_risk

ROOT = Path(__file__).resolve().parents[2]
PREDICT_LOG = ROOT / "backtest_output" / "webapp_predict_log.jsonl"
CACHE_TTL_SECONDS = 600.0  # repeated clicks within 10 min reuse the capture
                           # (0 the-odds-api credits); odds move slowly pre-match


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _err(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


def build_prediction_input(fresh: dict, books: dict[str, dict[str, float]],
                           providers: list[dict],
                           retrieved_at: Optional[str] = None) -> dict:
    """Assemble a prediction_input.v1 payload from a fresh fixture + captured
    odds. Pure function (network-free) so tests can drive it with canned data.
    """
    by_source: dict[str, list[str]] = {}
    for p in providers:
        by_source.setdefault(p.get("source", "espn"), []).append(
            str(p.get("provider")))
    source = " + ".join(
        f"{src}({', '.join(names)})" for src, names in by_source.items())
    return {
        "schema_version": "prediction_input.v1",
        "match": {
            "home_team": fresh["home"],
            "away_team": fresh["away"],
            "league": fresh.get("league_name") or fresh["league"],
            "kickoff_utc": fresh["kickoff_utc"],
        },
        "odds": {
            "context": "preclosing",
            "source": source or "unspecified",
            "retrieved_at": retrieved_at or _now().isoformat(),
            "books": books,
        },
    }


def attach_score_matrix(out: dict) -> dict:
    """Attach the derived score-matrix block to a prediction_output payload
    (in place and returned). The frozen predictor itself stays untouched.
    """
    ftr_probs = (out.get("ftr") or {}).get("probabilities")
    if ftr_probs:
        ou_probs = (out.get("ou25") or {}).get("probabilities") or {}
        try:
            out["score_matrix"] = derive_score_matrix(
                ftr_probs["home"], ftr_probs["draw"], ftr_probs["away"],
                ou_probs.get("over"))
        except ValueError as exc:
            out["score_matrix"] = {"status": "UNAVAILABLE", "reason": str(exc)}
    else:
        out["score_matrix"] = {"status": "UNAVAILABLE",
                               "reason": "no market 1X2 probabilities"}
    return out


def attach_upset_risk(out: dict) -> dict:
    """Attach the derived upset-risk block (in place and returned).

    Mirrors System A UpsetRiskAgent thresholds on the devigged 1X2, enriched
    with extreme cold scorelines from the derived matrix and market
    self-uncertainty drivers. Frozen predictor stays untouched.
    """
    ftr_probs = (out.get("ftr") or {}).get("probabilities")
    if not ftr_probs:
        out["upset_risk"] = {"status": "UNAVAILABLE",
                             "reason": "no market 1X2 probabilities"}
        return out
    uncertainty = out.get("uncertainty") or {}
    n_books = ((out.get("ftr") or {}).get("method") or {}).get("n_books")
    try:
        out["upset_risk"] = derive_upset_risk(
            ftr_probs["home"], ftr_probs["draw"], ftr_probs["away"],
            score_matrix=out.get("score_matrix")
            if isinstance(out.get("score_matrix"), dict) else None,
            ftr_entropy_bits=uncertainty.get("ftr_entropy_bits"),
            book_dispersion=uncertainty.get("book_dispersion_max_ftr"),
            n_books=n_books)
    except ValueError as exc:
        out["upset_risk"] = {"status": "UNAVAILABLE", "reason": str(exc)}
    return out


class PredictionService:
    """Stateful singleton behind the webapp: feed cache + prediction cache."""

    def __init__(self, feed_path: Optional[Path] = None,
                 predict_log_path: Optional[Path] = None):
        self._feed_path = feed_path or F.FEED_PATH
        self._log_path = predict_log_path or PREDICT_LOG
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._last_auto_refresh = 0.0  # monotonic guard for _find_fixture
        self.odds_api_status: dict = {"configured": False}

    # ------------------------------------------------------------- fixtures
    def list_fixtures(self, refresh: bool = False) -> dict:
        fixtures, fetched_at = F.load_feed(self._feed_path)
        age = F.feed_age_hours(fetched_at)
        if refresh or not fixtures or age is None:
            fetched = F.fetch_fixtures()
            # never clobber a non-empty feed with an empty fetch (e.g. total
            # network failure) — an empty result is only persisted when there
            # is nothing to lose
            if fetched or not self._feed_path.exists():
                try:
                    F.write_feed(fetched, _now(), path=self._feed_path)
                except OSError:
                    pass  # read-only checkout: keep serving in-memory list
                fixtures, fetched_at = fetched, _now().isoformat()
                age = 0.0
        return {
            "fixtures": fixtures,
            "fetched_at": fetched_at,
            "age_hours": None if age is None else round(age, 2),
            "stale": age is None or age > 6.0,
            "count": len(fixtures),
        }

    def _find_fixture(self, event_id: str) -> Optional[dict]:
        fixtures, fetched_at = F.load_feed(self._feed_path)
        rec = next((f for f in fixtures if str(f.get("event_id")) == str(event_id)),
                   None)
        if rec is None:
            # a full ESPN re-fetch costs ~1 min, so only pay it when the feed
            # itself looks outdated (older than 30 min / missing) AND at most
            # once per 10 min; otherwise 404 immediately — the caller can
            # force 刷新赛程 explicitly
            age = F.feed_age_hours(fetched_at)
            now = time.monotonic()
            with self._lock:
                cooled = (now - self._last_auto_refresh) > 600.0
                if cooled:
                    self._last_auto_refresh = now
            if cooled and (age is None or age > 0.5):
                self.list_fixtures(refresh=True)
                fixtures, _ = F.load_feed(self._feed_path)
                rec = next((f for f in fixtures
                            if str(f.get("event_id")) == str(event_id)), None)
        return rec

    # ------------------------------------------------------------- predict
    def predict_event(self, event_id: str, force: bool = False) -> tuple[int, dict]:
        """Returns (http_status, payload)."""
        with self._lock:
            cached = self._cache.get(str(event_id))
            if cached and not force and (_now().timestamp() - cached[0]) < CACHE_TTL_SECONDS:
                payload = dict(cached[1])
                payload["from_cache"] = True
                return 200, payload

        fixture = self._find_fixture(event_id)
        if fixture is None:
            return 404, _err("EVENT_NOT_FOUND",
                             f"event {event_id} is not in the fixtures feed")
        kickoff = F.parse_espn_date(fixture["kickoff_utc"])
        if kickoff is None:
            return 422, _err("BAD_KICKOFF", "fixture kickoff unparseable",
                             kickoff_utc=fixture["kickoff_utc"])

        try:
            fresh, comp = F.get_event(fixture["league"], str(event_id),
                                      kickoff.date())
        except F.OddsFeedError as exc:
            return 502, _err("ESPN_UNREACHABLE", str(exc))

        state = fresh.get("state") or ""
        if state not in ("pre", "scheduled"):
            return 409, _err("MATCH_NOT_PRE",
                             f"match state is '{state}' — only pre-match "
                             f"capture is allowed (time safety)",
                             state=state)

        books, providers = F.extract_books(comp)
        for p in providers:
            p.setdefault("source", "espn")
        # multi-book merge (the-odds-api) — raises confidence LOW -> MEDIUM/HIGH
        # via the frozen predictor's own grading; skipped entirely without a key
        toa_books, toa_providers, toa_meta = TOA.capture_for(fresh, TOA.get_odds_api_key())
        with self._lock:
            self.odds_api_status = {
                "configured": bool(toa_meta.get("configured")),
                **{k: v for k, v in toa_meta.items()
                   if k in ("requests_remaining", "requests_used", "error")},
            }
        for code, legs in toa_books.items():
            books.setdefault(code, legs)  # ESPN live capture wins on collisions
        providers.extend(toa_providers)
        books_1x2 = {c: legs for c, legs in books.items()
                     if all(k in legs for k in ("H", "D", "A"))}
        if not books_1x2:
            return 409, _err("NO_ODDS",
                             "neither ESPN nor the-odds-api carries complete "
                             "1X2 odds for this event",
                             providers=providers)

        raw = build_prediction_input(fresh, books, providers)

        # injury/suspension intel (football-data.org): enters ONLY as an
        # external signal — gated to AVAILABLE_NOT_VALIDATED, probabilities
        # untouched (P3); surfaced separately for the intel card
        injuries_intel: dict = {"configured": FD.is_configured()}
        if FD.is_configured():
            try:
                signals, injuries_intel = FD.capture_injuries(fresh, FD.get_key())
                if signals:
                    raw.setdefault("external_signals", []).extend(signals)
            except FD.InjuriesApiError as exc:
                injuries_intel = {"configured": True, "error": str(exc)}

        out = attach_upset_risk(attach_score_matrix(predict_match(raw)))

        payload = {
            "event_id": str(event_id),
            "fixture": fresh,
            "captured_at": _now().isoformat(),
            "providers": providers,
            "odds_api": toa_meta,
            "injuries": injuries_intel,
            "books": books,
            "prediction_input": raw,
            "prediction": out,
        }
        self._log_prediction(payload)
        with self._lock:
            self._cache[str(event_id)] = (_now().timestamp(), payload)
        return 200, payload

    # ----------------------------------------------------------------- log
    def _log_prediction(self, payload: dict) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "ts": payload["captured_at"],
                "event_id": payload["event_id"],
                "league": payload["fixture"].get("league"),
                "kickoff_utc": payload["fixture"].get("kickoff_utc"),
                "providers": [p["provider"] for p in payload["providers"]],
                "sources": sorted({p.get("source", "espn")
                                   for p in payload["providers"]}),
                "books": sorted(payload["books"]),
                "overall_status": (payload["prediction"].get("overall_status")),
                "ftr": (payload["prediction"].get("ftr") or {}).get("probabilities"),
                "score_matrix_status": (payload["prediction"].get("score_matrix") or {})
                .get("status"),
                "upset_level": (payload["prediction"].get("upset_risk") or {})
                .get("level"),
                "injuries": {k: payload.get("injuries", {}).get(k)
                             for k in ("count", "route")
                             if payload.get("injuries", {}).get(k) is not None},
            }
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass
