"""Quick profile printer for E0.csv onboarding."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.data.historical.profile import CsvProfile

profile = CsvProfile(Path("data/historical/raw/E0.csv"))
report = profile.full_report()
total = report["stats"]["rows"]
print("rows:", total, "| fields:", report["stats"]["fields"])
print("date range:", report["date_range"])
print("teams:", report["teams"]["distinct_teams"])
counts = report["teams"]["match_counts"]
print("match counts min/max:", min(counts.values()), max(counts.values()))
print("duplicates:", len(report["duplicates"]), report["duplicates"][:3])
print("date problems:", len(report["date_problems"]), report["date_problems"][:3])
print("temporal problems:", len(report["temporal_problems"]), report["temporal_problems"][:5])
print("result-field problems:", len(report["result_field_problems"]),
      report["result_field_problems"][:3])
print("odds problems:", report["odds_problem_count"], report["odds_problems"][:5])
missing = report["missing_by_column"]
print("columns with missing values:", len(missing))
for key, value in list(missing.items())[:30]:
    print(f"  {key}: {value}/{total}")
