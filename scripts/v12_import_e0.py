"""V1.2 Real-Data Onboarding: import E0.csv into the canonical dataset.

Data-only step: no prediction, no simulation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.leakage import audit_leakage, format_audit
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.source import CsvFootballDataCoUkSource

raw_path = Path("data/historical/raw/E0.csv")
text = raw_path.read_text(encoding="utf-8-sig")
matches = CsvFootballDataCoUkSource().parse(text, season="2025-26",
                                            source_label="football-data.co.uk E0 2025-26 (real)")
print(f"imported {len(matches)} matches")

dataset = HistoricalDataset(matches, name="epl_2025_26_real")
problems = dataset.validate()
print("validation problems:", problems[:10] if problems else "none")

out = Path("data/historical/epl_2025_26.json")
dataset.save(out)
print(f"saved -> {out}")

# sanity: closing odds mapping + raw odds labeling on the first match
first = matches[0]
print(f"\nfirst match: {first.date} {first.home_team} {first.home_goals}-{first.away_goals} {first.away_team}")
print(f"closing_odds: {first.closing_odds} (bookmaker={first.closing_odds.bookmaker if first.closing_odds else None})")
print(f"opening_odds: {first.opening_odds}")
raw_keys = list(first.raw_odds.keys())
print(f"raw_odds entries: {len(raw_keys)}")
c_semantics = sum(1 for v in first.raw_odds.values()
                  if v.get("time_semantics") == "unknown_time_semantics")
print(f"  of which unknown_time_semantics (C-suffix): {c_semantics}")
print(f"semantics note: {first.odds_semantics_note}")

audit = audit_leakage(dataset)
print("\n" + format_audit(audit))
