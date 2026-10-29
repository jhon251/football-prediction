"""Configuration system.

Loads ``config/default.json`` (bundled) and merges an optional user JSON or
YAML file.  Simulation counts / thresholds / weights are config, never
hardcoded (spec section 74).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULTS: Dict[str, Any] = {}


def _load_defaults() -> Dict[str, Any]:
    global _DEFAULTS
    if _DEFAULTS:
        return _DEFAULTS
    path = Path(__file__).resolve().parent.parent.parent / "config" / "default.json"
    if not path.exists():
        # fall back to a bundled copy inside the package if installed as a wheel
        data = resources.files("football_simulation").joinpath("default_config.json").read_text(encoding="utf-8")
        _DEFAULTS = json.loads(data)
    else:
        _DEFAULTS = json.loads(path.read_text(encoding="utf-8"))
    return _DEFAULTS


def _load_user(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore

            return yaml.safe_load(text) or {}
        except ImportError:
            raise RuntimeError("YAML config requires PyYAML; use JSON config instead.")
    return json.loads(text)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(user_path: Optional[str] = None) -> Dict[str, Any]:
    """Full merged configuration dict."""
    config = _deep_merge(_load_defaults(), {})
    if user_path:
        config = _deep_merge(config, _load_user(Path(user_path)))
    return config


def simulation_config(config: Optional[Dict[str, Any]] = None) -> Any:
    from football_simulation.core.simulation_engine import SimulationConfig

    config = config or load_config()
    return SimulationConfig(**config.get("simulation", {}))


def director_config(config: Optional[Dict[str, Any]] = None) -> Any:
    from football_simulation.agents.director import DirectorConfig

    config = config or load_config()
    sim = config.get("simulation", {})
    d = config.get("director", {})
    return DirectorConfig(
        simulation_runs=sim.get("default_runs", 10000),
        seed=sim.get("seed", 12345),
        keep_events=sim.get("keep_events", False),
        run_convergence=d.get("run_convergence", False),
        run_counterfactuals=d.get("run_counterfactuals", False),
        counterfactual_runs=d.get("counterfactual_runs", 2000),
        freeze=d.get("freeze", True),
        convergence_threshold=sim.get("convergence_threshold", 0.005),
    )
