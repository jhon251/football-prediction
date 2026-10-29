# -*- coding: utf-8 -*-
"""CLI for the minimal prediction module.

Usage:
  python -m football_prediction.cli predict --input match.json [--pretty]
  python -m football_prediction.cli self-check
  python -m football_prediction.cli serve [--host 127.0.0.1] [--port 8600]

Exit codes for `predict`: 0 VALID/CONDITIONAL, 1 INSUFFICIENT_DATA/UNKNOWN,
2 REJECTED, 3 STOP, 4 internal error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from football_prediction.predictor import predict_match
from football_prediction.provenance import frozen_fingerprint

_EXIT = {"VALID": 0, "CONDITIONAL": 0, "INSUFFICIENT_DATA": 1, "UNKNOWN": 1,
         "REJECTED": 2, "STOP": 3}


def _cmd_predict(args) -> int:
    try:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except Exception as e:  # unreadable input is an operator error, not a prediction status
        print(json.dumps({"error": f"cannot read input: {e}"}), file=sys.stderr)
        return 4
    out = predict_match(raw)
    print(json.dumps(out, indent=2 if args.pretty else None, ensure_ascii=False))
    return _EXIT.get(out.get("overall_status"), 4)


def _cmd_self_check(_) -> int:
    prov = frozen_fingerprint()
    print(json.dumps(prov, indent=2, ensure_ascii=False))
    return 0 if prov["verified"] else 3


def _cmd_serve(args) -> int:
    from football_prediction.webapp import run_server
    run_server(host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="football_prediction",
                                 description="minimal time-safe market-baseline prediction "
                                             "(M4/O2; research use only; no betting)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict", help="predict one match from a prediction_input.v1 JSON file")
    p.add_argument("--input", required=True, help="path to prediction_input.v1 JSON")
    p.add_argument("--pretty", action="store_true")
    p.set_defaults(fn=_cmd_predict)
    sc = sub.add_parser("self-check", help="verify frozen v1.1.0 dataset fingerprint")
    sc.set_defaults(fn=_cmd_self_check)
    srv = sub.add_parser("serve", help="run the one-click prediction webapp")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8600)
    srv.set_defaults(fn=_cmd_serve)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
