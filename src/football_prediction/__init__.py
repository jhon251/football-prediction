# -*- coding: utf-8 -*-
"""football_prediction — minimal time-safe market-baseline prediction module.

Scope (PREDICTION_MATRIX.md): only Market Baseline M4 (FTR) / O2 (OU25) emits
probabilities. External signals are status-managed, never blended. No betting,
no ROI/EV/stake, no Agent, no ML models.
"""
from football_prediction.predictor import MODEL_VERSION, SCHEMA_VERSION, predict_match

__all__ = ["predict_match", "MODEL_VERSION", "SCHEMA_VERSION"]
__version__ = "0.1.0"
