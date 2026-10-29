"""Walk-forward backtest runner (V1.2).

For every match: build the frozen pre-match snapshot, evaluate all baselines
(strictly walk-forward) and the full 31-agent sandbox, and record the
outcome.  The Poisson baseline's parameters are fitted ONCE per test season
on the training window that ENDS before the season starts - in-season data
never touches its parameters.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.backtest.baselines import make_baselines
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.schema import HistoricalMatch, HistoricalPreMatchSnapshot
from football_simulation.data.historical.snapshot import SnapshotBuilder


class WalkForwardBacktester:
    def __init__(
        self,
        dataset: HistoricalDataset,
        runs: int = 1000,
        seed: int = 12345,
        include_system: bool = True,
        cache_dir: Optional[Path] = None,
        exclude_models: Optional[set] = None,
        extended_features: bool = False,
        expose_odds: bool = True,
        refit_every: int = 20,
    ):
        self.dataset = dataset
        self.runs = runs
        self.seed = seed
        self.include_system = include_system
        self.builder = SnapshotBuilder(dataset.matches, strict=True)
        self.baselines = make_baselines()
        for name in (exclude_models or set()):
            self.baselines.pop(name, None)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.extended_features = extended_features
        self.expose_odds = expose_odds
        self.refit_every = refit_every
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def run_season(
        self,
        season: str,
        progress: Optional[Callable[[int, int], None]] = None,
        resume: bool = True,
        match_ids: Optional[set] = None,
    ) -> List[PredictionRecord]:
        matches = self.dataset.matches_in_season(season)
        if match_ids is not None:
            matches = [m for m in matches if m.match_id in match_ids]
        if not matches:
            raise ValueError(f"season {season!r} not in dataset "
                             f"{self.dataset.summary()['seasons']}")
        # walk-forward refit: Poisson MLE uses ONLY matches before the
        # current match (refit every ``refit_every`` matches)
        poisson_params = self.baselines["poisson"].fit(self.dataset, matches[0].date)
        records: List[PredictionRecord] = []
        for i, match in enumerate(matches):
            if i > 0 and i % self.refit_every == 0:
                poisson_params = self.baselines["poisson"].fit(self.dataset, match.date)
            cached = self._load_cache(match.match_id) if resume else None
            if cached is not None:
                records.append(cached)
            else:
                record = self.predict_one(match, poisson_params)
                self._save_cache(record)
                records.append(record)
            if progress is not None and (i + 1) % max(1, len(matches) // 10) == 0:
                progress(i + 1, len(matches))
        return records

    # ------------------------------------------------------------------
    def predict_one(self, match: HistoricalMatch, poisson_params: Optional[Dict] = None) -> PredictionRecord:
        snapshot = self.builder.build(match)
        predictions: Dict[str, ModelPrediction] = {}
        for name, baseline in self.baselines.items():
            if name == "poisson":
                prediction = baseline.predict(self.dataset, match, poisson_params)
            else:
                prediction = baseline.predict(self.dataset, match)
            if prediction is not None:
                predictions[name] = prediction
        if self.include_system:
            predictions["full_system"] = self._run_full_system(match, snapshot)
        record = PredictionRecord(
            match_id=match.match_id,
            kickoff=match.date,
            home_team=match.home_team,
            away_team=match.away_team,
            actual_home_goals=match.home_goals,
            actual_away_goals=match.away_goals,
            actual_ht_home_goals=match.half_time_home_goals,
            actual_ht_away_goals=match.half_time_away_goals,
            predictions=predictions,
            unknowns=snapshot.unknowns,
            no_signal=snapshot.no_signal,
            top_scenario=None,
            seed=self.seed,
            runs=self.runs,
            synthetic=match.is_synthetic,
        )
        if "full_system" in predictions:
            record.top_scenario = getattr(self, "_last_top_scenario", None)
        return record

    # ------------------------------------------------------------------
    def _run_full_system(self, match: HistoricalMatch,
                         snapshot: HistoricalPreMatchSnapshot) -> ModelPrediction:
        provider = HistoricalDataProvider(
            self.dataset, snapshot,
            use_extended_features=self.extended_features,
            expose_odds=self.expose_odds,
        )
        director = DirectorAgent(
            provider,
            DirectorConfig(simulation_runs=self.runs, seed=self.seed, freeze=True),
        )
        report = director.analyze(match.match_id)
        r = report.result_probability
        scenarios = report.scenarios
        self._last_top_scenario = scenarios[0].name if scenarios else None
        return ModelPrediction(
            model="full_system",
            home_win=r.home_win,
            draw=r.draw,
            away_win=r.away_win,
            expected_goals=report.goals_probability.expected_total_goals,
            over25=report.goals_probability.over.get("2.5"),
            over35=report.goals_probability.over.get("3.5"),
            btts_yes=report.btts.yes,
            score_matrix=dict(report.score_probability.matrix),
        )

    # ------------------------------------------------------------------
    def _cache_path(self, match_id: str) -> Path:
        return self.cache_dir / f"{match_id}.json"

    def _save_cache(self, record: PredictionRecord) -> None:
        if self.cache_dir is None:
            return
        self._cache_path(record.match_id).write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")

    def _load_cache(self, match_id: str) -> Optional[PredictionRecord]:
        if self.cache_dir is None:
            return None
        path = self._cache_path(match_id)
        if not path.exists():
            return None
        return PredictionRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def run_backtest(
    dataset: HistoricalDataset,
    seasons: List[str],
    runs: int = 1000,
    seed: int = 12345,
    cache_dir: Optional[Path] = None,
    include_system: bool = True,
) -> Dict[str, List[PredictionRecord]]:
    runner = WalkForwardBacktester(dataset, runs=runs, seed=seed,
                                   include_system=include_system, cache_dir=cache_dir)
    out: Dict[str, List[PredictionRecord]] = {}
    for season in seasons:
        t0 = time.time()
        records = runner.run_season(season)
        out[season] = records
        print(f"season {season}: {len(records)} matches in {time.time() - t0:.0f}s")
    return out
