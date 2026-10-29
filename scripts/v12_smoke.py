"""V1.2 chain smoke test: audit + snapshot + one full-system prediction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.leakage import audit_leakage, format_audit
from football_simulation.backtest.runner import WalkForwardBacktester
from football_simulation.data.historical.etl import HistoricalDataset

dataset = HistoricalDataset.load(Path("data/historical/synthetic_epl.json"))
print(dataset.summary())

audit = audit_leakage(dataset)
print(format_audit(audit))

runner = WalkForwardBacktester(dataset, runs=120, seed=42,
                               cache_dir=Path("backtest_output/_smoke_cache"))
season = "2024-25"
records = runner.run_season(season)
print(f"\npredicted {len(records)} matches")
for record in records[:3]:
    print(f"  {record.home_team} {record.actual_home_goals}-{record.actual_away_goals} {record.away_team}")
    for model, pred in record.predictions.items():
        print(f"    {model:20s} {pred.home_win:.3f}/{pred.draw:.3f}/{pred.away_win:.3f}")
    print(f"    unknowns={record.unknowns} no_signal={record.no_signal[:3]}")
