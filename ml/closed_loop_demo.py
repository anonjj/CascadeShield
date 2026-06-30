#!/usr/bin/env python3
"""
closed_loop_demo.py -- CascadeShield Adaptive Reconfiguration demo (Soham)

Closes the loop the paper proposes: observe the live situation -> ask the
recommender for a safer circuit-breaker config -> emit that config in the exact
CB_* environment-variable form the compose stack and experiments/runner.py
already consume, so it can be hot-applied with `docker compose up -d`.

This is a DEMONSTRATION of the control loop, not an autonomous controller: it
prints the before/after predicted blast radius and writes a .env file. Wiring it
to actually redeploy is a one-line `subprocess` call left to the operator.

    python closed_loop_demo.py --topology SHARED_DEP_MESH --fault LATENCY \\
        --current-window TIME_BASED --current-threshold 70 --current-window-size 100 \\
        --current-wait 30

Maps recommender output -> Jay's env knobs:
    window_type   -> CB_SLIDING_WINDOW_TYPE
    window_size   -> CB_SLIDING_WINDOW_SIZE
    threshold     -> CB_FAILURE_RATE_THRESHOLD
    wait_duration -> CB_WAIT_DURATION_OPEN   (seconds, 's' suffix)
    (CB_PERMITTED_CALLS_HALF_OPEN is not swept by the 486-config matrix; a fixed
     default is emitted and flagged as such.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import joblib  # noqa: E402
from decision_tree import recommend  # noqa: E402
from preprocessing import FAULT_TYPES, TOPOLOGIES, featurize_config  # noqa: E402

MODEL_PATH = SCRIPT_DIR / "models" / "decision_tree.pkl"
DEFAULT_PERMITTED_HALF_OPEN = 5  # not swept by the matrix; documented default


def to_env(cfg: dict, permitted_half_open: int = DEFAULT_PERMITTED_HALF_OPEN) -> dict:
    """Translate a recommended config into the CB_* env vars compose/runner read."""
    return {
        "CB_SLIDING_WINDOW_TYPE": cfg["window_type"],
        "CB_SLIDING_WINDOW_SIZE": str(cfg["window_size"]),
        "CB_FAILURE_RATE_THRESHOLD": str(cfg["threshold"]),
        "CB_WAIT_DURATION_OPEN": f"{cfg['wait_duration']}s",
        "CB_PERMITTED_CALLS_HALF_OPEN": str(permitted_half_open),  # fixed default
    }


def predict_blast(bundle: dict, topology: str, fault_type: str, cfg: dict) -> float:
    x = featurize_config(topology=topology, fault_type=fault_type, **cfg)
    return float(bundle["regressor"].predict(x)[0])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="CascadeShield adaptive reconfiguration demo.")
    p.add_argument("--topology", choices=TOPOLOGIES, default="SHARED_DEP_MESH")
    p.add_argument("--fault", choices=FAULT_TYPES, default="LATENCY")
    p.add_argument("--current-window", choices=["COUNT_BASED", "TIME_BASED"], default="TIME_BASED")
    p.add_argument("--current-threshold", type=int, default=70)
    p.add_argument("--current-window-size", type=int, default=100)
    p.add_argument("--current-wait", type=int, default=30)
    p.add_argument("--env-out", type=Path, default=SCRIPT_DIR / "recommended.env")
    args = p.parse_args(argv)

    if not MODEL_PATH.exists():
        print(f"[closed_loop] {MODEL_PATH} not found -- run train_all.py first.", file=sys.stderr)
        return 1
    bundle = joblib.load(MODEL_PATH)

    current = {"window_type": args.current_window, "threshold": args.current_threshold,
               "window_size": args.current_window_size, "wait_duration": args.current_wait}
    cur_blast = predict_blast(bundle, args.topology, args.fault, current)

    rec = recommend(bundle, args.topology, args.fault)
    new = rec["recommended_config"]
    new_blast = rec["predicted_blast_radius"]

    print(f"[closed_loop] context: topology={args.topology} fault={args.fault}")
    print(f"  observed config : {current}")
    print(f"      predicted blast radius = {cur_blast:.3f}")
    print(f"  recommended     : {new}")
    print(f"      predicted blast radius = {new_blast:.3f}   ({rec['predicted_label']})")
    delta = cur_blast - new_blast
    verdict = (f"-> projected blast radius reduction of {delta:.3f} "
               f"({100*delta/max(cur_blast,1e-9):.0f}%)") if delta > 0 else \
              "-> current config already at/under the recommendation"
    print(f"  {verdict}")
    print(f"  why: {' AND '.join(rec['decision_path']) or '(root)'}")

    env = to_env(new)
    lines = [f"# CascadeShield adaptive recommendation",
             f"# context: topology={args.topology} fault={args.fault}",
             f"# CB_PERMITTED_CALLS_HALF_OPEN is a fixed default (not swept by the matrix)"]
    lines += [f"{k}={v}" for k, v in env.items()]
    args.env_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {args.env_out.name}: " + " ".join(f"{k}={v}" for k, v in env.items()))
    print(f"  apply with:  docker compose --env-file {args.env_out.name} up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
