"""Print the EXP-REAL-EPL-BASE-001 headline numbers."""
import json

metrics = json.load(open("backtest_output/real_epl_base_001/metrics.json", encoding="utf-8"))
for model, data in metrics.items():
    one = data["one_x_two"]
    cal = data["calibration"]
    print(f"{model:22s} acc={one['accuracy']:.3f} brier={one['brier']:.4f} "
          f"logloss={one['log_loss']:.4f} top2={one['top2_accuracy']:.3f} "
          f"ece={cal['ece']:.4f}")

ablation = json.load(open("backtest_output/real_epl_base_001/ablation.json", encoding="utf-8"))
print()
for name, row in ablation.items():
    print(f"{name:24s} acc={row['accuracy']:.3f} brier={row['brier']:.4f} "
          f"logloss={row['log_loss']:.4f} dBrier={row.get('delta_brier_vs_full', 0):+.4f}")
