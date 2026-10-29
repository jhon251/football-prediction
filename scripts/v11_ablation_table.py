"""Dump the V1.1 ablation table (for the validation report)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.evaluation.ablation import AblationRunner, ABLATION_ORDER

rows = AblationRunner().run("match-demo-001", runs=500, seed=42, order=ABLATION_ORDER)
print(f"{'config':34s} {'home_win':>10s} {'draw':>8s} {'away_win':>9s} {'exp_goals':>10s} {'delta_hw':>9s}")
for row in rows:
    delta = f"{row.delta_home_win:+.4f}" if row.delta_home_win is not None else "   -"
    print(f"{row.config:34s} {row.home_win:10.4f} {row.draw:8.4f} {row.away_win:9.4f} {row.expected_goals:10.3f} {delta:>9s}")
