"""Demo runner: end-to-end demonstration of the V1 pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.data import MockDataProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Football sandbox demo")
    parser.add_argument("--runs", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--match", default="match-demo-001")
    parser.add_argument("--counterfactuals", action="store_true")
    parser.add_argument("--convergence", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    director = DirectorAgent(
        MockDataProvider(),
        DirectorConfig(
            simulation_runs=args.runs,
            seed=args.seed,
            run_counterfactuals=args.counterfactuals,
            run_convergence=args.convergence,
        ),
    )
    report = director.analyze(args.match)

    print(report.explanation)
    print()
    if args.output:
        Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Full JSON report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
