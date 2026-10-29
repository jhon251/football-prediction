"""Inspect phases + rolling for EXP-REAL-EPL-BASE-001."""
import json

phases = json.load(open("backtest_output/real_epl_base_001/phases.json", encoding="utf-8"))
for model in ("elo", "full_system", "poisson", "home_advantage"):
    print(f"--- {model} ---")
    for phase in phases[model]:
        print(f"  {phase['phase']:14s} {phase['matches']:7s} acc={phase['accuracy']:.3f} "
              f"brier={phase['brier']:.4f} logloss={phase['log_loss']:.4f}")

rolling = json.load(open("backtest_output/real_epl_base_001/rolling.json", encoding="utf-8"))
print()
for model in ("elo", "full_system"):
    series = rolling[model]
    print(f"--- {model} rolling (idx 99/199/299/379) ---")
    for idx in (99, 199, 299, 379):
        entry = series[idx]
        print(f"  end={entry['match_index']:4d} brier={entry['brier']:.4f} "
              f"logloss={entry['log_loss']:.4f} acc={entry['accuracy']:.3f}")
