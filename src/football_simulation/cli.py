"""Command-line interface (argparse, zero extra dependencies).

    football analyze MATCH_ID [--runs 10000] [--seed 12345]
    football simulate MATCH_ID --runs 10000
    football scenarios MATCH_ID
    football trace MATCH_ID
    football post-match MATCH_ID
    football demo
    football api [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _provider():
    from football_simulation.data import MockDataProvider

    return MockDataProvider()


def _director(config: Optional[Dict[str, Any]] = None, **overrides: Any):
    from football_simulation.agents.director import DirectorAgent
    from football_simulation.config import director_config

    dconfig = director_config(config)
    for key, value in overrides.items():
        if value is not None:
            setattr(dconfig, key, value)
    return DirectorAgent(_provider(), dconfig)


def _fmt_pct(p: float) -> str:
    return f"{p * 100:.2f}%"


def cmd_analyze(args: argparse.Namespace) -> int:
    from football_simulation.config import load_config

    config = load_config(args.config)
    director = _director(
        config,
        simulation_runs=args.runs,
        seed=args.seed,
        run_counterfactuals=args.counterfactuals,
        run_convergence=args.convergence,
    )
    print(f"Analyzing {args.match_id} ({args.runs} simulations, seed {args.seed}) ...")
    report = director.analyze(args.match_id)

    r = report.result_probability
    print("\n== 胜平负 ==")
    print(f"主胜: {_fmt_pct(r.home_win)}  平局: {_fmt_pct(r.draw)}  客胜: {_fmt_pct(r.away_win)}")

    print("\n== 最可能比分 (Top 10) ==")
    for item in report.score_probability.top(10):
        print(f"  {item['score']}: {_fmt_pct(item['probability'])}")

    print("\n== 大小球 ==")
    for line in ("0.5", "1.5", "2.5", "3.5", "4.5", "5.5"):
        print(f"  O{line}: {_fmt_pct(report.goals_probability.over[line])}  "
              f"U{line}: {_fmt_pct(report.goals_probability.under[line])}")
    print(f"  期望总进球: {report.goals_probability.expected_total_goals:.2f}")

    print("\n== BTTS ==")
    print(f"  Yes: {_fmt_pct(report.btts.yes)}  No: {_fmt_pct(report.btts.no)}")

    print("\n== 半全场 ==")
    for combo, p in sorted(report.half_time_full_time.combinations.items(), key=lambda kv: -kv[1]):
        print(f"  {combo}: {_fmt_pct(p)}")

    print("\n== 最可能比赛剧本 (Top 5) ==")
    for scenario in report.scenarios[:5]:
        print(f"  [{_fmt_pct(scenario.probability)}] {scenario.name} - {scenario.description[:60]}")

    print("\n== 爆冷风险 ==")
    print(f"  等级: {report.upset_risk.level.value}  方向: {report.upset_risk.direction}  "
          f"概率: {_fmt_pct(report.upset_risk.probability)}")
    for driver in report.upset_risk.drivers:
        print(f"    - {driver}")

    print("\n== 主要风险 ==")
    for component in report.risk.components:
        if component.score >= 0.3:
            print(f"  {component.name}: {component.level.value} ({component.score:.2f})")

    print("\n== 预测失效条件 ==")
    for condition in report.failure_conditions:
        print(f"  - {condition.condition}")

    print(f"\n== 置信度: {report.confidence.level.value} ({report.confidence.score:.2f}) ==")
    for reason in report.confidence.reasons:
        print(f"  - {reason}")

    if args.output:
        Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nFull JSON report written to {args.output}")
    if args.explanation:
        Path(args.explanation).write_text(report.explanation, encoding="utf-8")
        print(f"Explanation written to {args.explanation}")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from football_simulation.config import load_config

    config = load_config(args.config)
    director = _director(config, simulation_runs=args.runs, seed=args.seed)
    report = director.analyze(args.match_id)
    r = report.result_probability
    print(f"{args.match_id}: {args.runs} simulations, seed {args.seed}")
    print(f"主胜 {_fmt_pct(r.home_win)} / 平局 {_fmt_pct(r.draw)} / 客胜 {_fmt_pct(r.away_win)}")
    if args.output:
        Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Report written to {args.output}")
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    from football_simulation.config import load_config

    config = load_config(args.config)
    director = _director(config, simulation_runs=args.runs, seed=args.seed)
    report = director.analyze(args.match_id)
    for i, scenario in enumerate(report.scenarios, 1):
        print(f"{i:2d}. [{_fmt_pct(scenario.probability)}] {scenario.name} (archetype={scenario.archetype})")
        print(f"    {scenario.description}")
        key = ", ".join(
            f"{e.minute}' {e.event_type}" for e in scenario.key_events[:5]
        )
        if key:
            print(f"    关键事件: {key}")
    print(f"\n长尾: {_fmt_pct(report.scenario_ranking['long_tail_probability'])} "
          f"({report.scenario_ranking['long_tail_count']} 场模拟)")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    from football_simulation.config import load_config

    config = load_config(args.config)
    director = _director(config, simulation_runs=args.runs, seed=args.seed)
    report = director.analyze(args.match_id)
    for step in report.trace:
        print(f"[{step['sequence']:2d}] {step['kind']:16s} {step['summary']}")
        if step.get("detail"):
            print(f"      {step['detail']}")
    return 0


def cmd_post_match(args: argparse.Namespace) -> int:
    from football_simulation.agents.director import DirectorAgent
    from football_simulation.config import director_config, load_config
    from football_simulation.evaluation.learning import LearningAgent, LearningStore

    config = load_config(args.config)
    provider = _provider()
    request = provider.get_match_request(args.match_id)
    actual = provider.get_match_result(args.match_id)
    if actual is None:
        print(f"No actual result available for {args.match_id}")
        return 1

    director = DirectorAgent(provider, director_config(config))
    if args.runs:
        director.config.simulation_runs = args.runs
    if args.seed:
        director.config.seed = args.seed
    prediction = director.analyze(args.match_id)
    store_path = Path(config.get("learning", {}).get("store_path", "learning_store.json"))
    store = LearningStore(store_path)
    record = LearningAgent().learn(prediction, actual, __import__(
        "football_simulation.evaluation.learning", fromlist=["PostMatchEvaluationAgent"]
    ).PostMatchEvaluationAgent(), store)

    print(f"== Post-Match Evaluation: {args.match_id} ==")
    print(f"实际比分: {actual.score_home}-{actual.score_away} (HT {actual.ht_score_home}-{actual.ht_score_away})")
    ev = record.evaluation
    print(f"结果准确: {ev.result_accuracy} | 比分准确: {ev.score_accuracy} | O/U: {ev.ou_accuracy} | BTTS: {ev.btts_accuracy}")
    print(f"期望进球: {ev.expected_total_goals:.2f} vs 实际 {ev.actual_total_goals} (误差 {ev.expected_goals_error:.2f})")
    print(f"剧本准确度: {ev.scenario_accuracy:.3f} | 事件准确度: {ev.event_accuracy:.3f}")
    print(f"爆冷检测: {ev.upset_detection_accuracy}")
    for note in ev.notes:
        print(f"  - {note}")
    print(f"候选规则提案: {len(record.candidate_rules)}")
    for candidate in record.candidate_rules:
        print(f"  - {candidate.name}: {candidate.description[:80]}")
    print(f"学习记录已写入 {store.path}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from football_simulation.config import load_config

    config = load_config(args.config)
    director = _director(config, simulation_runs=args.runs, seed=args.seed)
    print("Football Digital Twin demo - Arsenal vs Chelsea (synthetic fixture data)")
    report = director.analyze("match-demo-001")
    print(report.explanation)
    print("\n---")
    print(report.model_dump_json(exclude={"trace", "explanation"}, indent=2)[:4000])
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """V1.1 system-level Football Reality Validation dashboard."""
    from football_simulation.config import load_config
    from football_simulation.evaluation.ablation import AblationRunner
    from football_simulation.evaluation.rule_audit import audit_dict, audit_rules, rule_counts
    from football_simulation.evaluation.sanity import SanitySuite
    from football_simulation.knowledge import load_all_knowledge

    config = load_config(args.config)
    validation_cfg = config.get("validation", {})
    runs = args.runs if args.runs is not None else validation_cfg.get("default_runs_per_check", 400)
    seed = args.seed if args.seed is not None else validation_cfg.get("seed", 2024)
    rrd = config.get("real_data_ready", {})

    print("Football Reality Validation")
    print("============================")
    print(f"(synthetic worlds only; {runs} runs per check, seed {seed}; "
          f"REAL_DATA_READY={rrd.get('status', False)})")
    print()

    suite = SanitySuite()
    report = suite.run(n=runs, seed=seed)

    for section in report.sections:
        status = "PASS" if section.passed else "FAIL"
        print(f"{section.name.replace('_', ' ').title()}:")
        print(f"{status}")
        for result in section.results:
            marker = "PASS" if result.passed else "FAIL"
            print(f"  [{marker}] {result.name}: {result.detail}")
        print()

    print("============================")
    print("Agent Contribution:")
    print(f"(cumulative ablation, {max(1, runs // 2)} runs per config, demo match)")
    ablation = AblationRunner().run("match-demo-001", runs=max(1, runs // 2), seed=seed)
    for row in ablation:
        delta = f"{row.delta_home_win:+.4f}" if row.delta_home_win is not None else "   -"
        print(f"  {row.config:32s} home_win={row.home_win:.4f} "
              f"draw={row.draw:.4f} away={row.away_win:.4f} "
              f"exp_goals={row.expected_goals:.2f}  (delta_home_win {delta})")
    print()

    print("============================")
    print("Rules:")
    counts = rule_counts(audit_rules(load_all_knowledge()))
    for key in ("validated", "tentative", "unverified", "assumption"):
        print(f"  {key.title()}: {counts.get(key, 0)}")
    print()

    if report.anomalies:
        print("ANOMALIES DETECTED:")
        for name in report.anomalies:
            print(f"  - {name}")
    else:
        print("Anomaly Detection: PASS")

    print()
    print("============================")
    print("Overall:")
    print(report.overall_verdict)
    print(f"REAL_DATA_READY: {rrd.get('status', False)} "
          f"(gates: {', '.join(rrd.get('required_gates', []))[:120]}...)")

    if args.output:
        payload = report.model_dump(mode="json")
        payload["ablation"] = [row.model_dump() for row in ablation]
        payload["rule_audit"] = audit_dict(audit_rules(load_all_knowledge()))
        Path(args.output).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nFull validation report written to {args.output}")
    return 0


def _load_backtest_dataset(path: Optional[str]):
    from football_simulation.data.historical.etl import HistoricalDataset
    from football_simulation.data.historical.source import SyntheticPremierLeagueSource

    if path:
        return HistoricalDataset.load(Path(path))
    default = Path("data/historical/synthetic_epl.json")
    if default.exists():
        return HistoricalDataset.load(default)
    # generate the clearly-labeled development stand-in on demand
    matches = SyntheticPremierLeagueSource().generate()
    dataset = HistoricalDataset(matches, name="synthetic_epl_development_standin")
    default.parent.mkdir(parents=True, exist_ok=True)
    dataset.save(default)
    print(f"generated synthetic development dataset -> {default}")
    return dataset


def cmd_backtest(args: argparse.Namespace) -> int:
    from football_simulation.backtest import run_backtest
    from football_simulation.backtest.leakage import audit_leakage, format_audit
    from football_simulation.backtest.metrics import model_comparison
    from football_simulation.backtest.experiments import ExperimentRegistry, data_version
    from football_simulation.backtest.failure_analysis import sample_failures, failure_summary

    dataset = _load_backtest_dataset(args.dataset)
    print(json.dumps(dataset.summary(), indent=2, ensure_ascii=False))
    if dataset.matches and dataset.matches[0].is_synthetic:
        print("\n*** SYNTHETIC DEVELOPMENT DATASET - results carry NO real-world meaning ***")

    # leakage audit gates the formal backtest
    audit = audit_leakage(dataset)
    print("\n" + format_audit(audit))
    if not audit.passed:
        print("\nLeakage audit FAILED - formal backtest is BLOCKED.")
        return 1

    seasons = args.seasons or [dataset.seasons()[-1]]
    cache = Path(args.output_dir) / "records" if args.output_dir else None
    records_by_season = run_backtest(
        dataset, seasons=seasons, runs=args.runs, seed=args.seed,
        cache_dir=cache, include_system=not args.no_system,
    )
    all_records = [r for records in records_by_season.values() for r in records]

    comparison = model_comparison(all_records)
    print("\n=== 1X2 Brier / LogLoss / Accuracy (test seasons: %s) ===" % ", ".join(seasons))
    header = f"{'model':22s} {'brier':>8s} {'logloss':>9s} {'acc':>7s} {'top2':>7s} {'ECE':>7s}"
    print(header)
    for model, metrics in comparison.items():
        one = metrics["one_x_two"]
        cal = metrics["calibration"]
        print(f"{model:22s} {one['brier']:8.4f} {one['log_loss']:9.4f} "
              f"{one['accuracy']:7.3f} {one['top2_accuracy']:7.3f} {cal['ece']:7.4f}")
    print("\n=== O/U 2.5 / BTTS ===")
    for model, metrics in comparison.items():
        ou = metrics.get("ou25") or {}
        btts = metrics.get("btts") or {}
        print(f"{model:22s} OU25 brier={ou.get('brier', float('nan')):.4f} "
              f"acc={ou.get('accuracy', float('nan')):.3f} | "
              f"BTTS brier={btts.get('brier', float('nan')):.4f} "
              f"acc={btts.get('accuracy', float('nan')):.3f}")

    failures = sample_failures(all_records, model="full_system", n=20) if not args.no_system else []
    if failures:
        print("\n=== Failure analysis (20 sampled, full_system) ===")
        for location, count in failure_summary(failures).items():
            print(f"  {location}: {count}")

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "records.json").write_text(
            json.dumps({"seasons": seasons,
                        "records": [r.model_dump(mode="json") for r in all_records]},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        (out / "metrics.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=1), encoding="utf-8")
        if failures:
            (out / "failures.json").write_text(
                json.dumps([f.model_dump(mode="json") for f in failures],
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        registry = ExperimentRegistry(out / "experiments.jsonl")
        registry.record(
            data_version=data_version(Path(args.dataset) if args.dataset
                                      else Path("data/historical/synthetic_epl.json")),
            random_seed=args.seed,
            train_period=f"all matches before each test season ({seasons})",
            test_period=",".join(seasons),
            models=sorted(comparison.keys()),
            matches_evaluated=len(all_records),
            metrics={model: {"brier": m["one_x_two"]["brier"],
                             "log_loss": m["one_x_two"]["log_loss"],
                             "accuracy": m["one_x_two"]["accuracy"]}
                     for model, m in comparison.items()},
            synthetic_data=all(r.synthetic for r in all_records),
            notes=["V1.2 walk-forward backtest"] + (
                ["SYNTHETIC STAND-IN DATA - not real football evidence"]
                if all_records and all_records[0].synthetic else []),
        )
        print(f"\nOutputs + experiment entry written to {out}")
    return 0


def cmd_audit_leakage(args: argparse.Namespace) -> int:
    from football_simulation.backtest.leakage import audit_leakage, format_audit

    dataset = _load_backtest_dataset(args.dataset)
    audit = audit_leakage(dataset)
    print(format_audit(audit))
    if args.output:
        Path(args.output).write_text(
            json.dumps(audit.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8")
        print(f"audit JSON written to {args.output}")
    return 0 if audit.passed else 1


def cmd_backfill_evidence(args: argparse.Namespace) -> int:
    from football_simulation.evaluation.rule_evidence import (
        CounterexampleStore,
        RuleEvidenceBackfill,
    )
    from football_simulation.knowledge import load_all_knowledge

    dataset = _load_backtest_dataset(args.dataset)
    knowledge = {"rules": load_all_knowledge()["rules"],
                 "tactical_patterns": load_all_knowledge()["tactical_patterns"]}
    backfill = RuleEvidenceBackfill(dataset, knowledge)
    results = backfill.run()
    counts = backfill.apply_to_knowledge()

    print("Rule Evidence Backfill")
    print("======================")
    if dataset.matches and dataset.matches[0].is_synthetic:
        print("*** SYNTHETIC STAND-IN DATA: statuses and evidence are NOT written; "
              "the mechanism runs for pipeline verification only ***")
    print(f"status counts: {counts}")
    for result in sorted(results, key=lambda r: r.rule_id):
        if result.observable:
            print(f"  {result.rule_id:38s} n={result.verified_matches:5d} "
                  f"rate={result.success_rate} -> {result.new_status} [{result.statistical_note}]")
        else:
            print(f"  {result.rule_id:38s} NOT OBSERVABLE ({result.reason})")

    store_path = Path(args.output) if args.output else Path(
        "data/evidence/counterexamples.json")
    if dataset.matches and dataset.matches[0].is_synthetic:
        print(f"\n{len(backfill.counterexamples)} counterexamples found on SYNTHETIC data "
              f"- NOT persisted to {store_path} (only real-data counterexamples may enter the store)")
    else:
        store = CounterexampleStore(store_path)
        store.add_many(backfill.counterexamples)
        print(f"\n{len(backfill.counterexamples)} counterexamples recorded -> {store_path}")
    return 0


def cmd_experiments(args: argparse.Namespace) -> int:
    from football_simulation.backtest.experiments import ExperimentRegistry

    entries = ExperimentRegistry().list()
    # also scan per-run registries under backtest_output/
    for path in sorted(Path("backtest_output").glob("*/experiments.jsonl")):
        entries.extend(ExperimentRegistry(path).list())
    if not entries:
        print("No experiments recorded yet.")
        return 0
    for entry in sorted(entries, key=lambda e: e.created_at):
        print(f"{entry.experiment_id}  test={entry.test_period:24s} "
              f"matches={entry.matches_evaluated:5d} seed={entry.random_seed} "
              f"code={entry.code_fingerprint} data={entry.data_version} "
              f"synthetic={entry.synthetic_data}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """V1.2 real-data onboarding doctor."""
    from football_simulation.data.historical.doctor import run_doctor

    result = run_doctor(args.path)
    print(result.render())
    return 0 if result.passed else 1


def cmd_api(args: argparse.Namespace) -> int:
    from football_simulation.app.server import run_server

    run_server(host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="football",
        description="Football Match Digital Twin & Simulation System (V1)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="Full pre-match analysis (all output sections)")
    p.add_argument("match_id")
    p.add_argument("--runs", type=int, default=10000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--counterfactuals", action="store_true")
    p.add_argument("--convergence", action="store_true")
    p.add_argument("--output", help="write full JSON report to this file")
    p.add_argument("--explanation", help="write the explanation text to this file")
    p.add_argument("--config", help="user config JSON/YAML to merge over defaults")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("simulate", help="Monte Carlo simulation only")
    p.add_argument("match_id")
    p.add_argument("--runs", type=int, default=10000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--output")
    p.add_argument("--config")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("scenarios", help="Scenario distribution")
    p.add_argument("match_id")
    p.add_argument("--runs", type=int, default=10000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--config")
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("trace", help="Reasoning trace")
    p.add_argument("match_id")
    p.add_argument("--runs", type=int, default=10000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--config")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("post-match", help="Post-match evaluation + learning")
    p.add_argument("match_id")
    p.add_argument("--runs", type=int, default=2000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--config")
    p.set_defaults(func=cmd_post_match)

    p = sub.add_parser("demo", help="Run the bundled demo match")
    p.add_argument("--runs", type=int, default=2000)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--config")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("validate", help="V1.1 Football Reality Validation dashboard")
    p.add_argument("--runs", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--output", help="write the full validation JSON to this file")
    p.add_argument("--config")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("backtest", help="V1.2 walk-forward historical backtest")
    p.add_argument("--dataset", help="canonical dataset JSON (default: synthetic stand-in)")
    p.add_argument("--seasons", nargs="+", help="test seasons (default: latest season)")
    p.add_argument("--runs", type=int, default=1000, help="simulations per match")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--output-dir", default="backtest_output")
    p.add_argument("--no-system", action="store_true", help="baselines only")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("audit-leakage", help="V1.2 leakage audit (blocks formal backtest on FAIL)")
    p.add_argument("--dataset")
    p.add_argument("--output")
    p.set_defaults(func=cmd_audit_leakage)

    p = sub.add_parser("backfill-evidence", help="V1.2 rule evidence backfill + counterexamples")
    p.add_argument("--dataset")
    p.add_argument("--output")
    p.set_defaults(func=cmd_backfill_evidence)

    p = sub.add_parser("experiments", help="list the experiment registry")
    p.set_defaults(func=cmd_experiments)

    p = sub.add_parser("doctor", help="V1.2 real-data onboarding doctor (REAL DATA ONBOARDING PASS/FAIL)")
    p.add_argument("path", help="raw CSV file (e.g. E0.csv)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("api", help="Start the HTTP API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_api)

    return parser


def main(argv: Optional[list] = None) -> int:
    # Force UTF-8 output regardless of the console codepage (GBK on some
    # Windows hosts would otherwise garble or break piped consumers).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # pragma: no cover
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
