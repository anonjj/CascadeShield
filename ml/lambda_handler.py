#!/usr/bin/env python3
"""
lambda_handler.py -- CascadeShield Recommender Lambda (Soham)

AWS Lambda entrypoint backing `POST /recommend`. Given an operational context
(topology + fault_type), it loads the trained Decision Tree bundle and returns
the circuit-breaker configuration with the lowest predicted blast radius, plus
the readable decision path that justifies it.

The same file runs locally for the demo / smoke test:

    python lambda_handler.py '{"topology": "FAN_OUT", "fault_type": "CRASH"}'

Deployment note: package this module together with preprocessing.py,
decision_tree.py, models/decision_tree.pkl and the scikit-learn/joblib layer;
set the handler to `lambda_handler.handler`. The bundle is loaded once per warm
container (module scope), so only cold starts pay the unpickle cost.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import joblib  # noqa: E402
from decision_tree import recommend  # noqa: E402
from preprocessing import FAULT_TYPES, TOPOLOGIES  # noqa: E402

MODEL_PATH = SCRIPT_DIR / "models" / "decision_tree.pkl"
_BUNDLE = None  # warm-container cache


def _bundle():
    global _BUNDLE
    if _BUNDLE is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"{MODEL_PATH} not found -- run `python decision_tree.py` (or train_all.py) first.")
        _BUNDLE = joblib.load(MODEL_PATH)
    return _BUNDLE


def _parse_event(event) -> dict:
    """Accept an API Gateway proxy event (body is a JSON string) or a direct dict."""
    if isinstance(event, str):
        return json.loads(event or "{}")
    if isinstance(event, dict) and "body" in event and not ("topology" in event):
        body = event["body"]
        return json.loads(body) if isinstance(body, str) else (body or {})
    return event or {}


def _response(status: int, payload: dict) -> dict:
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload)}


def handler(event, context=None):
    try:
        req = _parse_event(event)
    except (ValueError, TypeError) as exc:
        return _response(400, {"error": f"invalid request body: {exc}"})

    topology = req.get("topology")
    fault_type = req.get("fault_type")
    top_k = int(req.get("top_k", 3))

    if topology not in TOPOLOGIES:
        return _response(400, {"error": "missing/invalid 'topology'",
                               "allowed": TOPOLOGIES})
    if fault_type not in FAULT_TYPES:
        return _response(400, {"error": "missing/invalid 'fault_type'",
                               "allowed": FAULT_TYPES})

    try:
        rec = recommend(_bundle(), topology, fault_type, top_k=top_k)
    except FileNotFoundError as exc:
        return _response(503, {"error": str(exc)})

    rec["model"] = {"tau": _bundle()["tau"],
                    "trained_at": _bundle().get("trained_at"),
                    "is_synthetic": _bundle().get("is_synthetic", None)}
    return _response(200, rec)


def main(argv=None) -> int:
    """Local CLI. Uses plain flags (no JSON quoting headaches on PowerShell);
    --event is available for exercising the raw Lambda event path."""
    import argparse
    p = argparse.ArgumentParser(description="CascadeShield recommender -- POST /recommend, locally.")
    p.add_argument("--topology", choices=TOPOLOGIES, help="deployment topology")
    p.add_argument("--fault-type", dest="fault_type", choices=FAULT_TYPES, help="fault class to defend against")
    p.add_argument("--top-k", dest="top_k", type=int, default=3, help="how many configs to return")
    p.add_argument("--event", help="raw JSON event string (tests the Lambda code path)")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    if args.event:
        event = json.loads(args.event)
    elif args.topology and args.fault_type:
        event = {"topology": args.topology, "fault_type": args.fault_type, "top_k": args.top_k}
    else:
        event = {"topology": "FAN_OUT", "fault_type": "CRASH"}  # default demo
    resp = handler(event, None)
    print(f"HTTP {resp['statusCode']}")
    print(json.dumps(json.loads(resp["body"]), indent=2))
    return 0 if resp["statusCode"] == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
