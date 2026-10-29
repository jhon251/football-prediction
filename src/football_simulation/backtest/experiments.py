"""Experiment Registry (V1.2 section 17) + version fingerprints."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from football_simulation.backtest.models import ExperimentRecord

ROOT = Path(__file__).resolve().parents[3]


def _hash_files(paths: List[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.exists():
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    digest.update(str(child).encode("utf-8"))
                    digest.update(child.read_bytes())
        else:
            digest.update(str(path).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def code_fingerprint() -> str:
    return _hash_files([ROOT / "src"])


def data_version(dataset_path: Path) -> str:
    return _hash_files([dataset_path])


def knowledge_version() -> str:
    return _hash_files([ROOT / "src" / "football_simulation" / "knowledge"])


def parameter_version() -> str:
    return _hash_files([ROOT / "config" / "default.json"])


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(ROOT), timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return "unavailable"


class ExperimentRegistry:
    """JSONL store under experiments/ - every run is reproducible metadata."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else ROOT / "experiments" / "registry.jsonl"

    def record(
        self,
        *,
        data_version: str,
        random_seed: int,
        train_period: str,
        test_period: str,
        models: List[str],
        matches_evaluated: int,
        metrics: Dict[str, Any],
        synthetic_data: bool,
        market_data: bool = False,
        notes: Optional[List[str]] = None,
    ) -> ExperimentRecord:
        entry = ExperimentRecord(
            git_commit=git_commit(),
            code_fingerprint=code_fingerprint(),
            data_version=data_version,
            knowledge_version=knowledge_version(),
            parameter_version=parameter_version(),
            random_seed=random_seed,
            train_period=train_period,
            test_period=test_period,
            models=models,
            matches_evaluated=matches_evaluated,
            metrics=metrics,
            synthetic_data=synthetic_data,
            market_data=market_data,
            notes=notes or [],
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return entry

    def list(self) -> List[ExperimentRecord]:
        if not self.path.exists():
            return []
        entries: List[ExperimentRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(ExperimentRecord.model_validate(json.loads(line)))
        return entries
