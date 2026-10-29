"""EXP-DIAG-EPL-004 (DIAG-004) execution: Elo Error Attribution Analysis.

Strictly follows docs/DIAG_004_ELO_ERROR_ATTRIBUTION_DESIGN.md (pre-registration).
Pure deterministic analysis over existing frozen/cached artifacts - NO new
simulations, NO production code changes, NO new unregistered variables.

Agent configs tested (all 380 matches):
    full_system      frozen baseline records.json (EXP-REAL-EPL-BASE-001)
    team_only        DIAG-003 preds_part2.json (400 sims, seed 20240101)
    team_psychology  DIAG-003 preds_part1.json (400 sims, seed 20240101)

Outputs (backtest_output/diag_004_elo_error/):
    classification.json  per-match category + 3-type proxy labels
    stats.json           S1/S2/S3 permutation tests, counts, CIs, Fisher tests
    baseline_manifest_*.json  integrity hashes of the frozen dirs
    experiments.jsonl    registry entry EXP-DIAG-EPL-004
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import baseline_manifest, reconstruct_prematch_layer
from football_simulation.backtest.experiments import ExperimentRegistry, data_version
from football_simulation.backtest.models import PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
DIAG2_DIR = Path("backtest_output/diag_002_tactical_amp")
DIAG3_DIR = Path("backtest_output/diag_003_structure_info")
OUT_DIR = Path("backtest_output/diag_004_elo_error")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]

PERM_SEED = 20240101          # pre-registered permutation seed
N_PERM = 10_000               # pre-registered permutation replicates
ALPHA = 0.05 / 9              # Bonferroni over 3 configs x 3 main tests (S1/S2/S3)

AGENT_SOURCES = {
    "full_system": (BASELINE_DIR / "records.json", "predictions"),
    "team_only": (DIAG3_DIR / "preds_part2.json", "preds"),
    "team_psychology": (DIAG3_DIR / "preds_part1.json", "preds"),
}

OUTCOMES = ["home_win", "draw", "away_win"]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def actual_outcome(hg: int, ag: int) -> str:
    if hg > ag:
        return "home_win"
    if hg < ag:
        return "away_win"
    return "draw"


def top_set(probs: Dict[str, float]) -> List[str]:
    m = max(probs.values())
    return [k for k in OUTCOMES if abs(probs[k] - m) < 1e-12]


def load_frozen_records() -> List[PredictionRecord]:
    raw = json.loads((BASELINE_DIR / "records.json").read_text(encoding="utf-8"))
    return [PredictionRecord.model_validate(r) for r in raw]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- 0) frozen integrity (read-only checks) --------------------------
    frozen_dirs = {"real_epl_base_001": BASELINE_DIR, "diagnosis_epl_001": DIAG1_DIR,
                   "diag_002_tactical_amp": DIAG2_DIR,
                   "diag_003_structure_info": DIAG3_DIR}
    for name, path in frozen_dirs.items():
        (OUT_DIR / f"baseline_manifest_{name}.json").write_text(
            json.dumps(baseline_manifest(Path(path)), indent=2), encoding="utf-8")
    stored = json.loads((DIAG1_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))
    if stored["files"] != baseline_manifest(BASELINE_DIR)["files"]:
        raise RuntimeError("FROZEN BASELINE EXP-REAL-EPL-BASE-001 CHANGED - aborting")
    log("frozen baselines intact (hashes verified)")

    # ---- 1) load data -----------------------------------------------------
    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season("2025-26")
    assert len(matches) == 380
    order = {m.match_id: i for i, m in enumerate(matches)}
    frozen = load_frozen_records()
    frozen_sorted = sorted(frozen, key=lambda r: order.get(r.match_id, 10 ** 9))
    assert len(frozen_sorted) == 380

    rows = reconstruct_prematch_layer(dataset)
    row_by_id = {r["match_id"]: r for r in rows}

    diag3_part1 = json.loads((DIAG3_DIR / "preds_part1.json").read_text(encoding="utf-8"))
    diag3_part2 = json.loads((DIAG3_DIR / "preds_part2.json").read_text(encoding="utf-8"))
    diag3 = {**diag3_part1, **diag3_part2}

    # ---- 2) per-match base vectors ----------------------------------------
    match_ids = [r.match_id for r in frozen_sorted]
    elo_probs: Dict[str, Dict[str, float]] = {}
    actual_out: Dict[str, str] = {}
    ft_goals: Dict[str, Tuple[int, int]] = {}
    ht_goals: Dict[str, Tuple[int, int]] = {}
    full_xg: Dict[str, float] = {}
    for r in frozen_sorted:
        elo_probs[r.match_id] = {k: getattr(r.predictions["elo"], k) for k in OUTCOMES}
        actual_out[r.match_id] = actual_outcome(r.actual_home_goals, r.actual_away_goals)
        ft_goals[r.match_id] = (r.actual_home_goals, r.actual_away_goals)
        ht_goals[r.match_id] = (r.actual_ht_home_goals, r.actual_ht_away_goals)
        full_xg[r.match_id] = r.predictions["full_system"].expected_goals

    # Elo-error set is match-level (Elo is deterministic) -> identical for all agents
    elo_top = {mid: top_set(elo_probs[mid]) for mid in match_ids}
    elo_error_ids = [mid for mid in match_ids if actual_out[mid] not in elo_top[mid]]
    elo_correct_ids = [mid for mid in match_ids if actual_out[mid] in elo_top[mid]]
    log(f"Elo error n={len(elo_error_ids)}, elo correct n={len(elo_correct_ids)}")

    # ---- 3) three-type proxy classification (pre-registered rules) -------
    tact_abs = np.asarray([abs(row_by_id[mid]["tactical_advantage_nohome"])
                           for mid in match_ids])
    tact_p80 = float(np.percentile(tact_abs, 80))
    proxies: Dict[str, Dict[str, Any]] = {}
    for mid in match_ids:
        row = row_by_id[mid]
        h, a = ft_goals[mid]
        hh, ha = ht_goals[mid]
        score_surprise = abs((h + a) - full_xg[mid])
        hs = 1 if hh > ha else (-1 if hh < ha else 0)
        fs = 1 if h > a else (-1 if h < a else 0)
        ht_reversal = (hs != 0 and fs != 0 and hs != fs)
        tact = abs(row["tactical_advantage_nohome"])
        trans_gap = abs(row["tactical_transition_risk_home"]
                        - row["tactical_transition_risk_away"])
        cong = max(row["fitness_congestion_home"], row["fitness_congestion_away"])
        elo_diff_abs = abs(row["elo_diff"])
        p = {
            "score_surprise": round(score_surprise, 4),
            "ht_reversal": bool(ht_reversal),
            "tactical_proxy": bool(tact >= tact_p80),
            "transition_proxy": bool(trans_gap >= 0.15),
            "congestion_proxy": bool(cong >= 3),
            "low_elo_confidence_proxy": bool(elo_diff_abs <= 15),
            "congestion_value": cong,
            "elo_diff_abs": round(elo_diff_abs, 3),
        }
        if p["score_surprise"] >= 2.0 or p["ht_reversal"]:
            p["type"] = "random_event"
        elif p["tactical_proxy"] or p["transition_proxy"]:
            p["type"] = "tactical_style"
        elif p["congestion_proxy"] or p["low_elo_confidence_proxy"]:
            p["type"] = "information_missing"
        else:
            p["type"] = "UNCLASSIFIED"
        proxies[mid] = p
    log(f"tact_p80 (frozen) = {tact_p80:.4f}")

    # ---- 4) per-agent category classification -----------------------------
    agent_preds: Dict[str, Dict[str, Dict[str, float]]] = {}
    classification: Dict[str, Any] = {"meta": {"tact_p80": tact_p80,
                                               "perm_seed": PERM_SEED,
                                               "n_perm": N_PERM,
                                               "alpha_bonferroni": round(ALPHA, 6)},
                                      "matches": {}, "agents": {}}
    for mid in match_ids:
        entry = {"match_id": mid, "actual": actual_out[mid],
                 "elo_top1": elo_top[mid][0] if elo_top[mid] else None,
                 "elo_error": mid in elo_error_ids,
                 "proxies": proxies[mid]}
        classification["matches"][mid] = entry

    for config, (path, mode) in AGENT_SOURCES.items():
        if mode == "predictions":
            records = json.loads(path.read_text(encoding="utf-8"))
            preds = {}
            for r in records:
                rr = PredictionRecord.model_validate(r)
                preds[rr.match_id] = {k: getattr(rr.predictions[config], k) for k in OUTCOMES}
        else:
            preds = {mid: {k: v[k] for k in OUTCOMES}
                     for mid, v in json.loads(path.read_text(encoding="utf-8"))[config].items()}
        agent_preds[config] = preds
        agent_top = {mid: top_set(preds[mid]) for mid in match_ids}
        cats = {"E+A+": 0, "E+A-": 0, "E-A+": 0, "E-A-": 0}
        for mid in match_ids:
            e_right = actual_out[mid] in elo_top[mid]
            a_right = actual_out[mid] in agent_top[mid]
            cat = ("E+" if e_right else "E-") + ("A+" if a_right else "A-")
            cats[cat] += 1
            classification["matches"][mid][f"{config}_top1"] = agent_top[mid][0] \
                if agent_top[mid] else None
            classification["matches"][mid][f"{config}_category"] = cat
        classification["agents"][config] = {"categories": cats, "top1_counts": {
            mid: agent_top[mid][0] if agent_top[mid] else None for mid in match_ids}}
        log(f"{config}: {cats}")

    # ---- 5) statistics -----------------------------------------------------
    stats: Dict[str, Any] = {}
    n_elo_error = len(elo_error_ids)
    n_elo_correct = len(elo_correct_ids)

    # type shares: Elo-error vs Elo-correct control (Fisher one-sided, greater)
    type_control: Dict[str, Any] = {}
    for tname in ("random_event", "tactical_style", "information_missing", "UNCLASSIFIED"):
        err_yes = sum(1 for mid in elo_error_ids if proxies[mid]["type"] == tname)
        corr_yes = sum(1 for mid in elo_correct_ids if proxies[mid]["type"] == tname)
        odds, p_fisher = sps.fisher_exact(
            [[err_yes, n_elo_error - err_yes],
             [corr_yes, n_elo_correct - corr_yes]], alternative="greater")
        type_control[tname] = {"elo_error_share": round(err_yes / n_elo_error, 4),
                               "elo_correct_share": round(corr_yes / n_elo_correct, 4),
                               "fisher_p_greater": round(float(p_fisher), 6),
                               "n_error": err_yes, "n_correct": corr_yes}
    unclassified_share = type_control["UNCLASSIFIED"]["elo_error_share"]
    stats["type_control"] = type_control
    stats["unclassified_share_among_elo_error"] = unclassified_share
    stats["tactical_proxy_is_elo_derived_exploratory_only"] = True
    stats["tact_p80"] = tact_p80

    # per-type descriptive agent correctness (exploratory)
    for tname in ("random_event", "tactical_style", "information_missing", "UNCLASSIFIED"):
        mids = [mid for mid in elo_error_ids if proxies[mid]["type"] == tname]
        type_control[tname]["n"] = len(mids)
        for config in AGENT_SOURCES:
            a_right = sum(1 for mid in mids
                          if actual_out[mid] in top_set(agent_preds[config][mid]))
            type_control[tname][f"{config}_correct_rate"] = \
                round(a_right / len(mids), 4) if mids else None

    # main tests per agent config
    actuals = np.asarray([OUTCOMES.index(actual_out[mid]) for mid in match_ids])
    rng = np.random.default_rng(PERM_SEED)
    main_tests: Dict[str, Any] = {}
    for config in AGENT_SOURCES:
        # per-match, per-outcome probabilities
        A = np.zeros((380, 3))
        E = np.zeros((380, 3))
        for i, mid in enumerate(match_ids):
            for o in OUTCOMES:
                A[i, OUTCOMES.index(o)] = agent_preds[config][mid][o]
                E[i, OUTCOMES.index(o)] = elo_probs[mid][o]
        # argmax-correct masks per outcome (tie rule)
        e_right = np.zeros((380, 3), dtype=bool)
        a_right = np.zeros((380, 3), dtype=bool)
        for i, mid in enumerate(match_ids):
            for o in OUTCOMES:
                e_right[i, OUTCOMES.index(o)] = o in elo_top[mid]
                a_right[i, OUTCOMES.index(o)] = o in top_set(agent_preds[config][mid])
        # observed S1 count
        e_wrong_obs = ~e_right[np.arange(380), actuals]
        a_right_obs = a_right[np.arange(380), actuals]
        s1_obs = int(np.sum(e_wrong_obs & a_right_obs))
        # observed S2 Murphy info term C = mean((A-E)(E-1)) on the actual outcome
        A_act = A[np.arange(380), actuals]
        E_act = E[np.arange(380), actuals]
        c_obs = float(np.mean((A_act - E_act) * (E_act - 1.0)))
        noise_obs = float(np.mean((A_act - E_act) ** 2))
        # sanity: single-outcome Brier diff == noise + 2*C (identity check)
        s2_brier_diff = float(np.mean((A_act - 1.0) ** 2) - np.mean((E_act - 1.0) ** 2))
        s2_identity_ok = bool(abs(s2_brier_diff - (noise_obs + 2.0 * c_obs)) < 1e-9)
        # full 3-outcome Brier per config (context row)
        y_mat = np.zeros((380, 3))
        y_mat[np.arange(380), actuals] = 1.0
        brier_full_agent = float(np.mean(np.sum((A - y_mat) ** 2, axis=1)))
        brier_full_elo = float(np.mean(np.sum((E - y_mat) ** 2, axis=1)))
        # observed S3 discordant pairs
        e_correct_obs = ~e_wrong_obs
        ea_minus = int(np.sum(e_correct_obs & ~a_right_obs))   # E+A-
        ea_plus = s1_obs                                        # E-A+
        mcnemar = sps.binomtest(ea_plus, ea_plus + ea_minus, 0.5, alternative="two-sided")
        # permutations
        s1_perm_counts = np.empty(N_PERM, dtype=np.int64)
        c_perm = np.empty(N_PERM)
        for rep in range(N_PERM):
            pa = rng.permutation(actuals)
            e_w = ~e_right[np.arange(380), pa]
            a_r = a_right[np.arange(380), pa]
            s1_perm_counts[rep] = np.sum(e_w & a_r)
            c_perm[rep] = float(np.mean(
                (A[np.arange(380), pa] - E[np.arange(380), pa])
                * (E[np.arange(380), pa] - 1.0)))
        s1_p = float(np.mean(s1_perm_counts >= s1_obs))
        c_p = float(np.mean(c_perm <= c_obs))
        main_tests[config] = {
            "categories": classification["agents"][config]["categories"],
            "s1_observed": s1_obs,
            "s1_perm_median": int(np.median(s1_perm_counts)),
            "s1_perm_p": round(s1_p, 6),
            "s1_pass": bool(s1_p < ALPHA and s1_obs > int(np.median(s1_perm_counts))),
            "s2_murphy_info_c": round(c_obs, 6),
            "s2_noise_term": round(noise_obs, 6),
            "s2_brier_diff_actual_outcome": round(s2_brier_diff, 6),
            "s2_identity_ok": s2_identity_ok,
            "s2_brier_full_agent": round(brier_full_agent, 6),
            "s2_brier_full_elo": round(brier_full_elo, 6),
            "s2_perm_p": round(c_p, 6),
            "s2_pass": bool(c_obs < 0 and c_p < ALPHA),
            "s3_ea_minus": ea_minus,
            "s3_ea_plus": ea_plus,
            "s3_mcnemar_p": round(float(mcnemar.pvalue), 6),
            "s3_pass": bool(mcnemar.pvalue < ALPHA and ea_plus > ea_minus),
            "any_pass": False,
        }
        main_tests[config]["any_pass"] = bool(
            main_tests[config]["s1_pass"] or main_tests[config]["s2_pass"]
            or main_tests[config]["s3_pass"])
        log(f"{config}: S1 obs={s1_obs} p={main_tests[config]['s1_perm_p']:.4f} | "
            f"S2 C={c_obs:+.5f} p={main_tests[config]['s2_perm_p']:.4f} | "
            f"S3 {ea_plus}/{ea_plus + ea_minus} p={main_tests[config]['s3_mcnemar_p']:.4f}")
    stats["main_tests"] = main_tests
    stats["answer_has_elo_extra_info"] = any(
        main_tests[c]["any_pass"] for c in main_tests)

    # per-config accuracy + rates + Clopper-Pearson CIs
    rates: Dict[str, Any] = {}
    for config in AGENT_SOURCES:
        cats = classification["agents"][config]["categories"]
        n = sum(cats.values())
        ci = {}
        for key in ("E+A+", "E+A-", "E-A+", "E-A-"):
            k = cats[key]
            lo, hi = sps.binomtest(k, n, 0.5).proportion_ci(
                confidence_level=0.95, method="exact")
            ci[key] = [round(float(lo), 4), round(float(hi), 4)]
        rates[config] = {"n": n, "counts": cats, "ci95": ci,
                         "agent_accuracy": round((cats["E+A+"] + cats["E-A+"]) / n, 4),
                         "elo_accuracy": round((cats["E+A+"] + cats["E+A-"]) / n, 4),
                         "e_minus_a_plus_rate": round(cats["E-A+"] / n, 4),
                         "elo_error_agent_right_share": round(
                             cats["E-A+"] / max(cats["E-A+"] + cats["E-A-"], 1), 4)}
    stats["rates"] = rates
    stats["n_elo_error"] = n_elo_error
    stats["n_elo_correct"] = n_elo_correct

    # descriptive: within Elo-error subset, agent P(actual) vs P(non-actual)
    desc: Dict[str, Any] = {}
    for config in AGENT_SOURCES:
        p_actual = []
        p_other = []
        for mid in elo_error_ids:
            p = agent_preds[config][mid]
            a = actual_out[mid]
            p_actual.append(p[a])
            p_other.append((sum(p.values()) - p[a]) / 2.0)
        desc[config] = {"mean_p_actual": round(float(np.mean(p_actual)), 4),
                        "mean_p_other": round(float(np.mean(p_other)), 4)}
    stats["elo_error_subset_descriptive"] = desc

    # 120-sample continuity subset (for cross-reference with DIAG-001)
    sub120 = [mid for mid in match_ids if mid in {matches[i].match_id
                                                  for i in SAMPLE_INDICES}]
    sub120_counts: Dict[str, Any] = {}
    for config in AGENT_SOURCES:
        cats = {"E+A+": 0, "E+A-": 0, "E-A+": 0, "E-A-": 0}
        for mid in sub120:
            e_right = actual_out[mid] in elo_top[mid]
            a_right = actual_out[mid] in top_set(agent_preds[config][mid])
            cats[("E+" if e_right else "E-") + ("A+" if a_right else "A-")] += 1
        sub120_counts[config] = cats
    stats["subsample_120"] = {"n": len(sub120), "counts": sub120_counts}
    log("stats computed")

    # top-2 sensitivity (pre-registered; does not affect the main verdict)
    top2: Dict[str, Any] = {}
    for config in AGENT_SOURCES:
        cats = {"E+A+": 0, "E+A-": 0, "E-A+": 0, "E-A-": 0}
        for mid in match_ids:
            e2 = sorted(elo_probs[mid], key=elo_probs[mid].get, reverse=True)[:2]
            a2 = sorted(agent_preds[config][mid], key=agent_preds[config][mid].get,
                        reverse=True)[:2]
            e_right = actual_out[mid] in e2
            a_right = actual_out[mid] in a2
            cats[("E+" if e_right else "E-") + ("A+" if a_right else "A-")] += 1
        top2[config] = cats
    stats["sensitivity_top2"] = top2
    log("top-2 sensitivity computed")

    # ---- 6) write outputs --------------------------------------------------
    (OUT_DIR / "classification.json").write_text(
        json.dumps(classification, indent=1), encoding="utf-8")
    (OUT_DIR / "stats.json").write_text(
        json.dumps(stats, indent=1), encoding="utf-8")

    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=PERM_SEED,
        train_period="walk-forward (frozen baseline reference)",
        test_period="2025-26",
        models=sorted(AGENT_SOURCES),
        matches_evaluated=380,
        metrics={"elo_error_n": n_elo_error, "elo_correct_n": n_elo_correct},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-004 (DIAG-004): Elo Error Attribution Analysis",
            "strictly follows docs/DIAG_004_ELO_ERROR_ATTRIBUTION_DESIGN.md "
            "(pre-registered thresholds/proxies/permutation seed 20240101, 10000 reps)",
            "deterministic analysis over frozen/cached artifacts only; NO new "
            "simulations; production code untouched",
            "agents: frozen full_system, DIAG-003 team_only, team_psychology (380)",
            "tactical_advantage_nohome / transition-risk gap are Elo-derived "
            "signals: exploratory interpretation only, NOT primary evidence",
            f"answer_has_elo_extra_info={stats['answer_has_elo_extra_info']} "
            "(see stats.json)",
        ],
    )
    log("registry entry EXP-DIAG-EPL-004 written")
    log(f"DONE in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
