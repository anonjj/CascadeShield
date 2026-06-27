#!/usr/bin/env python3
"""
preprocessing.py -- CascadeShield ML pipeline (Soham)

The single, shared source of truth for turning the 15-column master dataset into
model-ready matrices. BOTH models and the Lambda import this module, so a config
is encoded identically at training time and at serving time (no train/serve skew).

Design decisions are inherited from data/DATA_DICTIONARY.md and
ml/feature_engineering.md:

  * Features (Decision Tree inputs) = the 6 swept independent variables only.
    Provenance columns (experiment_id, environment, replicate, run_timestamp) are
    NEVER features -- the recommender must not learn LOCAL-vs-AWS shortcuts.
  * topology, fault_type    -> one-hot (all categories kept, fixed order).
  * window_type             -> single binary column window_type_is_time.
  * threshold/window_size/wait_duration -> numeric, untouched (trees split, no scaling).
  * Outcomes feed the Isolation Forest. time_to_open / time_to_recover have
    MEANINGFUL nulls (breaker never opened / never recovered) -- per the data
    dictionary we do NOT mean-impute. We encode the *event* via companion booleans
    (cb_opened, recovered) and fit the IF on the three never-null fractions plus
    those flags, instead of imputing a magnitude we do not have.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---- schema contract ----------------------------------------------------------
TOPOLOGIES = ["LINEAR_CHAIN", "FAN_OUT", "SHARED_DEP_MESH"]
FAULT_TYPES = ["LATENCY", "CRASH", "THROTTLE"]
WINDOW_TYPES = ["COUNT_BASED", "TIME_BASED"]
THRESHOLDS = [30, 50, 70]
WINDOW_SIZES = [10, 50, 100]
WAIT_DURATIONS = [5, 10, 30]

FEATURE_COLUMNS = ["topology", "fault_type", "window_type",
                   "threshold", "window_size", "wait_duration"]
OUTCOME_COLUMNS = ["blast_radius", "time_to_open", "time_to_recover",
                   "error_rate", "throughput_loss"]
PROVENANCE_COLUMNS = ["experiment_id", "environment", "replicate", "run_timestamp"]
SCHEMA_COLUMNS = (["experiment_id"] + FEATURE_COLUMNS
                  + ["environment", "replicate", "run_timestamp"] + OUTCOME_COLUMNS)

# Stable encoded-feature order. The Lambda relies on this exact order.
ENCODED_FEATURE_NAMES = (
    [f"topology={t}" for t in TOPOLOGIES]
    + [f"fault_type={f}" for f in FAULT_TYPES]
    + ["window_type_is_time", "threshold", "window_size", "wait_duration"]
)
# Outcome features the Isolation Forest is fit on (see module docstring).
IF_NUMERIC_FEATURES = ["blast_radius", "error_rate", "throughput_loss"]
IF_FLAG_FEATURES = ["cb_opened", "recovered"]
IF_FEATURE_NAMES = IF_NUMERIC_FEATURES + IF_FLAG_FEATURES

DEFAULT_TAU = 0.5  # blast_radius > tau  => "unsafe". Tunable; documented in README.


def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load master_dataset.csv and assert the 15-column contract holds."""
    df = pd.read_csv(path)
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: dataset missing required columns: {missing}")
    return df


def encode_features(df: pd.DataFrame) -> pd.DataFrame:
    """Encode the 6 independent variables into the fixed ENCODED_FEATURE_NAMES matrix.

    Works for the full training frame or a single-row serving request, producing
    identical columns in identical order either way.
    """
    out = pd.DataFrame(index=df.index)
    for t in TOPOLOGIES:
        out[f"topology={t}"] = (df["topology"] == t).astype(int)
    for f in FAULT_TYPES:
        out[f"fault_type={f}"] = (df["fault_type"] == f).astype(int)
    out["window_type_is_time"] = (df["window_type"] == "TIME_BASED").astype(int)
    out["threshold"] = pd.to_numeric(df["threshold"])
    out["window_size"] = pd.to_numeric(df["window_size"])
    out["wait_duration"] = pd.to_numeric(df["wait_duration"])
    return out[ENCODED_FEATURE_NAMES]


def featurize_config(topology: str, fault_type: str, window_type: str,
                     threshold: int, window_size: int, wait_duration: int) -> pd.DataFrame:
    """Encode a single config (used by the recommender / Lambda). Validates inputs."""
    _validate("topology", topology, TOPOLOGIES)
    _validate("fault_type", fault_type, FAULT_TYPES)
    _validate("window_type", window_type, WINDOW_TYPES)
    row = pd.DataFrame([{
        "topology": topology, "fault_type": fault_type, "window_type": window_type,
        "threshold": int(threshold), "window_size": int(window_size),
        "wait_duration": int(wait_duration),
    }])
    return encode_features(row)


def make_labels(df: pd.DataFrame, tau: float = DEFAULT_TAU) -> pd.Series:
    """Binary recommender target: 'safe' if blast_radius <= tau else 'unsafe'."""
    return np.where(df["blast_radius"] <= tau, "safe", "unsafe")


def build_outcome_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Outcome matrix for the Isolation Forest, with meaningful-null handling.

    Companion booleans encode whether the breaker opened / the system recovered;
    the null timing magnitudes themselves are deliberately NOT imputed or fed in.
    """
    out = pd.DataFrame(index=df.index)
    out["blast_radius"] = df["blast_radius"].astype(float)
    out["error_rate"] = df["error_rate"].astype(float)
    out["throughput_loss"] = df["throughput_loss"].astype(float)
    out["cb_opened"] = df["time_to_open"].notna().astype(int)
    out["recovered"] = df["time_to_recover"].notna().astype(int)
    return out[IF_FEATURE_NAMES]


def config_grid():
    """All 54 circuit-breaker parameter combinations (window_type x 3 numeric knobs).

    Topology and fault_type are *context* the operator supplies; the recommender
    searches this grid for the safest config given that context.
    """
    for wt in WINDOW_TYPES:
        for thr in THRESHOLDS:
            for ws in WINDOW_SIZES:
                for wd in WAIT_DURATIONS:
                    yield {"window_type": wt, "threshold": thr,
                           "window_size": ws, "wait_duration": wd}


def _validate(name: str, value, allowed) -> None:
    if value not in allowed:
        raise ValueError(f"{name}={value!r} is not one of {allowed}")
