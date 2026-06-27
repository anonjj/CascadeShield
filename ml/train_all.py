#!/usr/bin/env python3
"""
train_all.py -- CascadeShield ML pipeline orchestrator (Soham)

One command to reproduce every ML artifact from scratch:

    python train_all.py                 # synthetic data -> both models
    python train_all.py --no-generate   # reuse existing data/master_dataset.csv
                                        # (use this once the REAL sweep output is in place)

Steps:
  1. generate_synthetic_data  -> data/master_dataset.csv  (skipped with --no-generate)
  2. decision_tree            -> models/decision_tree.pkl, rules, feature_importance.csv
  3. isolation_forest         -> models/isolation_forest.pkl, data/anomalies.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import decision_tree  # noqa: E402
import generate_synthetic_data  # noqa: E402
import isolation_forest  # noqa: E402


def _banner(text: str) -> None:
    print("\n" + "=" * 70 + f"\n {text}\n" + "=" * 70)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run the full CascadeShield ML pipeline.")
    p.add_argument("--no-generate", action="store_true",
                   help="skip synthetic generation; use the existing master_dataset.csv "
                        "(set this when the real sweep output is in place)")
    args = p.parse_args(argv)

    if not args.no_generate:
        _banner("STEP 1/3  generate synthetic dataset")
        generate_synthetic_data.main([])
    else:
        _banner("STEP 1/3  SKIPPED (using existing data/master_dataset.csv)")

    _banner("STEP 2/3  train Decision Tree recommender")
    decision_tree.main([])

    _banner("STEP 3/3  train Isolation Forest anomaly detector")
    isolation_forest.main([])

    _banner("DONE")
    print("artifacts:")
    print("  data/master_dataset.csv        (15-col dataset; swap for real sweep output)")
    print("  data/feature_importance.csv    (recommender feature ranking)")
    print("  data/anomalies.csv             (flagged runs)")
    print("  ml/models/decision_tree.pkl    (recommender bundle -> Lambda)")
    print("  ml/models/decision_tree_rules.txt")
    print("  ml/models/isolation_forest.pkl (anomaly detector bundle)")
    print("\nnext:  python lambda_handler.py --topology FAN_OUT --fault-type CRASH")
    print("       python closed_loop_demo.py --topology SHARED_DEP_MESH --fault LATENCY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
