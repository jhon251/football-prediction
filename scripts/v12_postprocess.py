"""Post-process the formal backtest: failure analysis + calibration + scores."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.failure_analysis import failure_summary, sample_failures
from football_simulation.backtest.metrics import full_metrics
from football_simulation.backtest.models import PredictionRecord

records = [PredictionRecord.model_validate(r) for r in
           json.load(open("backtest_output/v12_formal/records.json", encoding="utf-8"))["records"]]
print("records:", len(records))

failures = sample_failures(records, model="full_system", n=20)
print("failure locations:", failure_summary(failures))
for case in failures[:6]:
    print(f"  {case.match_id} pred_top={case.prediction['top_outcome']} "
          f"p={case.probability:.2f} actual={case.actual_result['result']} "
          f"({case.actual_result['score']}) -> {case.error_location}")
json.dump([f.model_dump(mode="json") for f in failures],
          open("backtest_output/v12_formal/failures.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

cal = full_metrics(records, "full_system")["calibration"]
print(f"\nfull_system calibration: ECE={cal['ece']} max_overconfidence={cal['max_overconfidence']}")
for b in cal["bins"]:
    print(f"  bin {b['bin']:8s} n={b['count']:5d} predicted={b['mean_predicted']:.3f} "
          f"actual={b['empirical']:.3f}")

for model in ("full_system", "elo", "market_odds", "poisson", "home_advantage"):
    sm = full_metrics(records, model)["score"]
    one = full_metrics(records, model)["one_x_two"]
    print(f"{model:20s} exact_score={sm['exact_score_accuracy']:.4f} "
          f"top3={sm['top3_score_coverage']:.4f} top5={sm['top5_score_coverage']:.4f} "
          f"acc={one['accuracy']:.3f}")
