#!/usr/bin/env python3
"""
preprocessing.py -- CascadeShield ML pipeline (Soham)

The single, shared source of truth for turning the 17-column master dataset into
model-ready matrices. BOTH models and the Lambda import this module, so a config
is encoded identically at training time and at serving time (no train/serve skew).

Design decisions are inherited from data/DATA_DICTIONARY.md and
ml/feature_engineering.md:

  * Features (Decision Tree inputs) = the 6 swept independent variables only.
    Provenance columns (experiment_id, permitted_calls_half_open, environment,
    mode, replicate, run_timestamp) are NEVER features -- the recommender must not
    learn LOCAL-vs-AWS shortcuts or fixed-knob values.
  * topology, fault_type    -> one-hot (all categories kept, fixed order). The real
    sweep so far only contains LINEAR; FAN_OUT / SHARED_DEP_MESH stay in the category
    list so the encoded matrix (and the Lambda contract) is stable once they land.
  * window_type             -> single binary column window_type_is_time.
  * threshold/window_size/wait_duration -> numeric, untouched (trees split, no scaling).
  * blast_radius is emitted directly as a 0.0-1.0 fraction by runner.py /
    generate_synthetic_data.py (no rescale needed here; BLAST_RADIUS_SCALE=1.0).
    A drift guard still warns if a value exceeds 1.0, which would mean the
    source scale changed again.
  * Outcomes feed the Isolation Forest. time_to_open / time_to_recover have
    MEANINGFUL nulls (breaker never opened / never recovered) -- per the data
    dictionary we do NOT mean-impute. We encode the *event* via companion booleans
    (cb_opened, recovered) and fit the IF on the three never-null fractions plus
    those flags, instead of imputing a magnitude we do not have.
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---- schema contract ----------------------------------------------------------
# TOPOLOGIES: the real sweep so far only emits "LINEAR". FAN_OUT / SHARED_DEP_MESH
# are retained so the one-hot stays multi-category (not a degenerate single column)
# and the encoded matrix / Lambda contract does not shift when they are swept later.
TOPOLOGIES = ["LINEAR", "FAN_OUT", "SHARED_DEP_MESH"]
FAULT_TYPES = ["LATENCY", "CRASH", "THROTTLE"]
WINDOW_TYPES = ["COUNT_BASED", "TIME_BASED"]
THRESHOLDS = [30, 50, 70]
WINDOW_SIZES = [5, 10, 20]      # matches the real sweep (was the planned [10, 50, 100])
WAIT_DURATIONS = [5, 15, 30]    # matches the real sweep (was the planned [5, 10, 30])

# blast_radius is already a 0.0-1.0 fraction in this branch: runner.py's
# get_blast_radius() normalises the Java endpoint's 0-100 range at the source
# (raw / 100.0) before writing to the CSV, and generate_synthetic_data.py emits
# the same 0.0-1.0 scale directly -- so no further rescale happens here. (main's
# preprocessing.py still divides by 100 because main's own runner.py writes the
# raw 0-100 value; this constant stays 1.0 to match THIS branch's convention,
# not main's, or every value would be silently divided by 100 twice.)
BLAST_RADIUS_SCALE = 1.0

FEATURE_COLUMNS = ["topology", "fault_type", "window_type",
                   "threshold", "window_size", "wait_duration"]
OUTCOME_COLUMNS = ["blast_radius", "time_to_open", "time_to_recover",
                   "error_rate", "throughput_loss"]
# Non-feature columns carried for provenance/analysis only. permitted_calls_half_open
# and mode are fixed operational knobs in this sweep (const 5 / "full"), not features.
PROVENANCE_COLUMNS = ["experiment_id", "permitted_calls_half_open",
                      "environment", "mode", "replicate", "run_timestamp"]
# 17-column real contract, in file order.
SCHEMA_COLUMNS = (["experiment_id"] + FEATURE_COLUMNS
                  + ["permitted_calls_half_open", "environment", "mode",
                     "replicate", "run_timestamp"] + OUTCOME_COLUMNS)

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

# blast_radius > tau => "unsafe". main's DEFAULT_TAU=0.1 is calibrated for its
# discrete real-data distribution (values cluster at {0.0, 0.2, 0.4}, with many
# rows genuinely at 0.0 -- "zero blast = safe" is a meaningful, common case
# there). THIS branch's synthetic generator produces a continuous distribution
# with a hard floor around 0.03-0.06 (see generate_synthetic_data.py's
# simulate_outcomes: `np.clip(latent + noise, 0.03, 0.99)`) -- almost no row is
# ever near true zero. Applying main's tau=0.1 here collapsed the label to 19
# safe / 2897 unsafe (near-constant, cv_f1_macro dropped to 0.45) -- the same
# degenerate-split failure mode this whole harness-fix effort exists to catch.
# tau=0.5 is this branch's own calibrated value against its own distribution
# (743 safe / 2173 unsafe, cv_f1_macro=0.86) and is kept for that reason, not
# reverted to main's. Tunable; documented in README.
DEFAULT_TAU = 0.5


def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load master_dataset.csv and assert the 17-column contract holds."""
    df = pd.read_csv(path)
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: dataset missing required columns: {missing}")
    check_data_quality(df, source=str(path))
    return df


def check_data_quality(df: pd.DataFrame, source: str = "<dataframe>") -> None:
    """Surface silent data-quality problems that the encoders would otherwise mask.

    In particular: time_to_open / time_to_recover legitimately carry meaningful nulls,
    but an *entirely* null column across a full dataset means the companion booleans
    (cb_opened / recovered) collapse to a constant 0 -- a dead feature. That usually
    signals a real question ("are the breakers opening at all?"), not clean data, so we
    log it loudly rather than let the degenerate column slip through.
    """
    if len(df) == 0:
        return
    for col in ("time_to_open", "time_to_recover"):
        if col in df.columns and df[col].isna().all():
            logger.warning(
                "DATA QUALITY: %s is 100%% null across all %d rows of %s -- the "
                "companion flag will be a constant 0 (dead feature). Confirm whether "
                "the circuit breaker actually opened/recovered during these runs.",
                col, len(df), source,
            )


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


def blast_radius_fraction(df: pd.DataFrame) -> pd.Series:
    """blast_radius as a 0-1 fraction. Already stored that way in this branch
    (BLAST_RADIUS_SCALE=1.0, a no-op division) -- kept as a function so every
    consumer routes through one place if the source scale ever changes again.

    A drift guard warns if any value exceeds 1.0, which would mean the incoming
    scale changed (e.g. back to a raw percent) and DEFAULT_TAU no longer applies.
    """
    frac = df["blast_radius"].astype(float) / BLAST_RADIUS_SCALE
    over = frac > 1.0
    if over.any():
        warnings.warn(
            f"blast_radius exceeds 1.0 after /{BLAST_RADIUS_SCALE:g} scaling for "
            f"{int(over.sum())} row(s) (max={frac.max():.4f}); the source scale may have "
            "drifted -- DEFAULT_TAU and the safe/unsafe label may be wrong.",
            RuntimeWarning,
            stacklevel=2,
        )
    return frac


def make_labels(df: pd.DataFrame, tau: float = DEFAULT_TAU) -> pd.Series:
    """Binary recommender target: 'safe' if blast_radius (fraction) <= tau else 'unsafe'."""
    return np.where(blast_radius_fraction(df) <= tau, "safe", "unsafe")


def build_outcome_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Outcome matrix for the Isolation Forest, with meaningful-null handling.

    Companion booleans encode whether the breaker opened / the system recovered;
    the null timing magnitudes themselves are deliberately NOT imputed or fed in.
    """
    out = pd.DataFrame(index=df.index)
    out["blast_radius"] = blast_radius_fraction(df)
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
