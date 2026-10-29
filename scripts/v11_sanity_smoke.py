"""Quick sanity-suite smoke run."""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.evaluation.sanity import SanitySuite

t0 = time.time()
report = SanitySuite().run(n=300, seed=2024)
for section in report.sections:
    print(f"{section.name:26s} {'PASS' if section.passed else 'FAIL'}")
    for result in section.results:
        print(f"    [{'PASS' if result.passed else 'FAIL'}] {result.name}: {result.detail[:110]}")
print("anomalies:", report.anomalies)
print("verdict:", report.overall_verdict)
print("rule counts:", report.rule_counts)
print("time: %.0fs" % (time.time() - t0))
