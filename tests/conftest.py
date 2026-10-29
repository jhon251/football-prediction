"""Make the src layout importable for bare `pytest tests` runs.

Mirrors tests/helpers.py's sys.path handling so prediction tests (which
import football_prediction directly, without helpers) also resolve without
a prior `pip install -e .`.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
