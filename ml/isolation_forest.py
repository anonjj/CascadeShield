#!/usr/bin/env python3
"""
isolation_forest.py -- CascadeShield Anomaly Detector (Soham)

Fits the Isolation Forest from the README ML layer on the measured OUTCOMES of
each run and flags config/outcome combinations that behave unexpectedly -- e.g.
a "safe-looking" config that nonetheless produced a large blast radius, or a run
whose errors saturated while blast stayed tiny. These are the rows worth a human
second look before they pollute the recommender's training signal.

Feature set (see preprocessing.build_outcome_frame and its docstring):
    blast_radius, error_rate, throughput_loss  (scaled)
  + cb_opened, recovered                       (companion booleans for the
                                                meaningful nulls -- we encode the
                                                event, never an imputed magnitude)

When run on the synthetic dataset, detection is scored against the injected
ground truth in data/_synthetic_truth.csv. On real data that file is absent and
the script simply reports the flagged rows.

Run:  python isolation_forest.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from preprocessing import (  # noqa: E402
    IF_FLAG_FEATURES, IF_NUMERIC_FEATURES, build_outcome_frame, load_dataset,
)

DATA_DIR = SCRIPT_DIR.parent / "data"
MODELS_DIR = SCRIPT_DIR / "models"
RANDOM_STATE = 42
DEFAULT_CONTAMINATION = 0.05  # ~ the injected anomaly rate; tune on real data


def _transform(outcomes: pd.DataFrame, scaler: StandardScaler, fit: bool) -> np.ndarray:
    num = outcomes[IF_NUMERIC_FEATURES].to_numpy(dtype=float)
    num = scaler.fit_transform(num) if fit else scaler.transform(num)
    flags = outcomes[IF_FLAG_FEATURES].to_numpy(dtype=float)
    return np.hstack([num, flags])


def fit(dataset_path: Path, contamination: float):
    df = load_dataset(dataset_path)
    outcomes = build_outcome_frame(df)
    scaler = StandardScaler()
    X = _transform(outcomes, scaler, fit=True)

    model = IsolationForest(n_estimators=300, contamination=contamination,
                            random_state=RANDOM_STATE)
    model.fit(X)

    # higher score => more anomalous (invert sklearn's "higher = more normal")
    scores = -model.score_samples(X)
    is_flagged = (model.predict(X) == -1).astype(int)

    flagged = df.copy()
    flagged["anomaly_score"] = np.round(scores, 4)
    flagged["flagged"] = is_flagged
    return df, flagged, model, scaler


def evaluate(flagged: pd.DataFrame, truth_path: Path) -> dict | None:
    if not truth_path.exists():
        return None
    truth = pd.read_csv(truth_path)
    key = ["experiment_id", "environment", "replicate"]
    merged = flagged.merge(truth[key + ["is_anomaly", "anomaly_type"]], on=key, how="left")
    y_true = merged["is_anomaly"].fillna(0).astype(int)
    y_pred = merged["flagged"].astype(int)
    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0)
    by_kind = (merged[merged.is_anomaly == 1]
               .groupby("anomaly_type")["flagged"]
               .agg(["sum", "count"]))
    return {
        "n_injected": int(y_true.sum()), "n_flagged": int(y_pred.sum()),
        "precision": round(float(p), 4), "recall": round(float(r), 4),
        "f1": round(float(f1), 4),
        "recall_by_kind": {k: f"{int(row['sum'])}/{int(row['count'])}"
                           for k, row in by_kind.iterrows()},
    }


def save_bundle(model, scaler, contamination: float, metrics) -> Path:
    import sklearn
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model, "scaler": scaler,
        "numeric_features": IF_NUMERIC_FEATURES, "flag_features": IF_FLAG_FEATURES,
        "contamination": contamination, "metrics": metrics,
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = MODELS_DIR / "isolation_forest.pkl"
    joblib.dump(bundle, path)
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Train the CascadeShield Isolation Forest anomaly detector.")
    p.add_argument("--data", type=Path, default=DATA_DIR / "master_dataset.csv")
    p.add_argument("--truth", type=Path, default=DATA_DIR / "_synthetic_truth.csv")
    p.add_argument("--contamination", type=float, default=DEFAULT_CONTAMINATION)
    args = p.parse_args(argv)

    df, flagged, model, scaler = fit(args.data, args.contamination)
    metrics = evaluate(flagged, args.truth)

    out_cols = (["experiment_id", "environment", "replicate", "topology", "fault_type",
                 "window_type", "threshold", "window_size", "wait_duration",
                 "blast_radius", "error_rate", "throughput_loss",
                 "time_to_open", "time_to_recover", "anomaly_score"])
    anomalies = (flagged[flagged.flagged == 1]
                 .sort_values("anomaly_score", ascending=False))[out_cols]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    anomalies.to_csv(DATA_DIR / "anomalies.csv", index=False)

    bundle_path = save_bundle(model, scaler, args.contamination, metrics)

    print(f"[isolation_forest] fit on {len(df)} rows  (contamination={args.contamination})")
    print(f"  flagged {int(flagged.flagged.sum())} anomalies -> data/anomalies.csv")
    if metrics:
        print(f"  detection vs injected truth: precision={metrics['precision']}"
              f"  recall={metrics['recall']}  f1={metrics['f1']}"
              f"  ({metrics['n_injected']} injected, {metrics['n_flagged']} flagged)")
        print(f"  recall by anomaly kind: {metrics['recall_by_kind']}")
    print("  top 3 anomalies:")
    for row in anomalies.head(3).itertuples():
        print(f"    {row.experiment_id} [{row.environment}] score={row.anomaly_score}"
              f"  blast={row.blast_radius} err={row.error_rate}")
    print("  saved:", bundle_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
