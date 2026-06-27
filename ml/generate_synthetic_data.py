#!/usr/bin/env python3
"""
generate_synthetic_data.py -- CascadeShield ML pipeline (Soham)

Produces a SCHEMA-CONFORMANT synthetic dataset so the ML pipeline (Isolation
Forest + Decision Tree recommender) can be developed, tested, and demonstrated
BEFORE the real 486-config chaos sweep has run on the mesh.

    *** THIS DATA IS SIMULATED -- NOT MEASURED. ***
    Replace data/master_dataset.csv with the real runner.py output once the
    canary / full sweep lands. The 15-column schema is identical, so nothing
    downstream (preprocessing, both models, the Lambda) changes.

How it works
------------
Reads the 486 planned configurations from data/experiment_matrix.csv and, for
each (config x environment x replicate), simulates the 5 measured outcomes with
a documented response model that encodes the study's working hypotheses:

  * Fault contagion:   CRASH > LATENCY > THROTTLE.
  * Topology blast:    SHARED_DEP_MESH > FAN_OUT > LINEAR_CHAIN (shared deps
                       cause common-mode failure).
  * Breaker tightness: looser breakers (higher threshold, larger window) contain
                       less, so blast radius goes up.
  * NOVELTY:           the better window_type DEPENDS on the fault. TIME_BASED
                       wins under LATENCY (sustained degradation accumulates over
                       time); COUNT_BASED wins under CRASH/THROTTLE (discrete
                       failures are counted immediately). This interaction is the
                       structure the Decision Tree should recover and the paper
                       should report.
  * Environment:       AWS runs are slightly worse than LOCAL (within ~15%),
                       which feeds the LOCAL-vs-AWS divergence analysis.

A small fraction of rows are injected anomalies (outcomes that defy the model).
Their ground truth is written to data/_synthetic_truth.csv so the Isolation
Forest's detection can be scored. That truth file is NOT part of the 15-column
schema; it exists only for evaluation and is ignored by every other module.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"

# ---- the 15-column master schema (must stay identical to runner.py output) ----
SCHEMA_COLUMNS = [
    "experiment_id", "topology", "fault_type", "window_type",
    "threshold", "window_size", "wait_duration",
    "environment", "replicate", "run_timestamp",
    "blast_radius", "time_to_open", "time_to_recover",
    "error_rate", "throughput_loss",
]
FEATURE_COLUMNS = ["topology", "fault_type", "window_type",
                   "threshold", "window_size", "wait_duration"]

# ---- response-model coefficients (all documented in README.md) ----------------
FAULT_BASE = {"CRASH": 0.55, "LATENCY": 0.45, "THROTTLE": 0.30}
TOPO_MULT = {"SHARED_DEP_MESH": 1.30, "FAN_OUT": 1.05, "LINEAR_CHAIN": 0.82}
# (fault_type, window_type) -> additive effect on blast radius. The sign flip
# across fault types is the empirical novelty the study is built to surface.
WT_INTERACTION = {
    ("LATENCY", "TIME_BASED"): -0.07, ("LATENCY", "COUNT_BASED"): +0.05,
    ("CRASH", "TIME_BASED"): +0.05, ("CRASH", "COUNT_BASED"): -0.06,
    ("THROTTLE", "TIME_BASED"): +0.03, ("THROTTLE", "COUNT_BASED"): -0.04,
}
FAULT_ERROR_ADJ = {"CRASH": 0.08, "LATENCY": 0.02, "THROTTLE": -0.03}

THRESHOLD_RANGE = (30, 70)
WINDOW_RANGE = (10, 100)
WAIT_RANGE = (5, 30)
OBSERVATION_WINDOW_S = 120.0  # past this, "not recovered" -> meaningful null

ANOMALY_KINDS = ("blast_spike", "error_blast_decouple", "recover_flip")


def _norm(value: float, lo: float, hi: float) -> float:
    """Min-max normalise a swept knob to [0, 1] using its known grid bounds."""
    return (value - lo) / (hi - lo)


def simulate_outcomes(cfg, environment: str, rng: np.random.Generator) -> dict:
    """Simulate the 5 measured outcomes for one (config, environment) draw.

    cfg is a namedtuple/Row exposing topology, fault_type, window_type,
    threshold, window_size, wait_duration.
    """
    thr_n = _norm(cfg.threshold, *THRESHOLD_RANGE)
    win_n = _norm(cfg.window_size, *WINDOW_RANGE)
    wait_n = _norm(cfg.wait_duration, *WAIT_RANGE)

    # --- blast radius: the primary outcome -----------------------------------
    latent = (
        FAULT_BASE[cfg.fault_type] * TOPO_MULT[cfg.topology]
        + 0.18 * thr_n            # looser trip threshold -> contains later
        + 0.12 * win_n            # bigger window -> slower to accumulate -> later
        + 0.03 * wait_n           # longer open state -> degraded a touch longer
        + WT_INTERACTION[(cfg.fault_type, cfg.window_type)]
    )
    env_mult = 1.0 if environment == "LOCAL" else float(rng.uniform(1.03, 1.14))
    latent *= env_mult
    blast = float(np.clip(latent + rng.normal(0.0, 0.045), 0.03, 0.99))

    # --- correlated secondary outcomes ---------------------------------------
    error_rate = float(np.clip(
        0.12 + 0.75 * blast + FAULT_ERROR_ADJ[cfg.fault_type] + rng.normal(0.0, 0.04),
        0.0, 1.0))
    throughput_loss = float(np.clip(
        0.05 + 0.70 * blast + 0.10 * wait_n + rng.normal(0.0, 0.04),
        0.0, 1.0))

    # --- time_to_open: NULL is meaningful (breaker never tripped) -------------
    open_signal = (
        FAULT_BASE[cfg.fault_type] * TOPO_MULT[cfg.topology]
        - 0.20 * thr_n - 0.10 * win_n + rng.normal(0.0, 0.03)
    )
    if open_signal > 0.26:
        # TIME_BASED needs to fill a seconds window; COUNT_BASED a calls window.
        if cfg.window_type == "COUNT_BASED":
            tto = cfg.window_size * (0.20 + 0.15 * thr_n)
        else:
            tto = cfg.window_size * (0.35 + 0.25 * thr_n)
        time_to_open = float(max(0.2, tto + rng.normal(0.0, max(0.2, tto * 0.12))))
    else:
        time_to_open = np.nan  # breaker never opened -> documented meaningful null

    # --- time_to_recover: NULL when not back to baseline within the window ---
    if not np.isnan(time_to_open):
        ttr = cfg.wait_duration * (1.0 + 0.6 * blast) + rng.normal(0.0, 1.5)
        ttr = max(cfg.wait_duration * 0.8, ttr)
        never_recovered = (
            (blast > 0.85 and cfg.wait_duration >= 10 and rng.random() < 0.6)
            or ttr > OBSERVATION_WINDOW_S
        )
        time_to_recover = np.nan if never_recovered else float(ttr)
    else:
        # never opened -> mild fault, system stays near baseline -> trivial recovery
        time_to_recover = float(max(0.0, rng.normal(2.0, 0.5)))

    return {
        "blast_radius": round(blast, 4),
        "time_to_open": (np.nan if np.isnan(time_to_open) else round(time_to_open, 3)),
        "time_to_recover": (np.nan if (isinstance(time_to_recover, float) and np.isnan(time_to_recover))
                            else round(time_to_recover, 3)),
        "error_rate": round(error_rate, 4),
        "throughput_loss": round(throughput_loss, 4),
    }


def inject_anomaly(out: dict, rng: np.random.Generator) -> tuple[dict, str]:
    """Perturb one row's outcomes into a multivariate outlier the IF should catch."""
    kind = str(rng.choice(ANOMALY_KINDS))
    if kind == "blast_spike":
        # Blast jumps to near-total while errors DON'T surge -> the usual
        # blast<->error coupling breaks (e.g. a GC pause / latent resource leak
        # degrades services without a matching error spike). The contradiction,
        # not the high blast alone (blast is often high), is what makes it odd.
        out["blast_radius"] = round(float(rng.uniform(0.85, 0.99)), 4)
        out["error_rate"] = round(float(rng.uniform(0.10, 0.30)), 4)
        out["throughput_loss"] = round(float(np.clip(
            out["blast_radius"] * 0.8 + rng.normal(0.0, 0.03), 0.0, 1.0)), 4)
    elif kind == "error_blast_decouple":
        # Errors near saturation but blast tiny -> errors did not propagate.
        out["error_rate"] = round(float(rng.uniform(0.90, 1.0)), 4)
        out["blast_radius"] = round(float(rng.uniform(0.05, 0.20)), 4)
    elif kind == "recover_flip":
        # An otherwise unremarkable row that simply never recovers.
        out["time_to_recover"] = np.nan
    return out, kind


def generate(matrix_path: Path, out_path: Path, truth_path: Path,
             environments, replicates: int, anomaly_rate: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    matrix = pd.read_csv(matrix_path)
    missing = [c for c in (["experiment_id"] + FEATURE_COLUMNS) if c not in matrix.columns]
    if missing:
        raise SystemExit(f"experiment_matrix.csv missing columns: {missing}")

    base_ts = datetime(2026, 6, 21, 9, 0, 0, tzinfo=timezone.utc)
    rows, truth_rows = [], []
    tick = 0
    for cfg in matrix.itertuples(index=False):
        for environment in environments:
            for replicate in range(1, replicates + 1):
                out = simulate_outcomes(cfg, environment, rng)
                is_anom, kind = False, ""
                if rng.random() < anomaly_rate:
                    out, kind = inject_anomaly(out, rng)
                    is_anom = True
                ts = (base_ts + timedelta(seconds=37 * tick)).strftime("%Y-%m-%dT%H:%M:%SZ")
                tick += 1
                rows.append({
                    "experiment_id": cfg.experiment_id,
                    "topology": cfg.topology,
                    "fault_type": cfg.fault_type,
                    "window_type": cfg.window_type,
                    "threshold": cfg.threshold,
                    "window_size": cfg.window_size,
                    "wait_duration": cfg.wait_duration,
                    "environment": environment,
                    "replicate": replicate,
                    "run_timestamp": ts,
                    **out,
                })
                truth_rows.append({
                    "experiment_id": cfg.experiment_id,
                    "environment": environment,
                    "replicate": replicate,
                    "is_anomaly": int(is_anom),
                    "anomaly_type": kind,
                })

    df = pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    truth = pd.DataFrame(truth_rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    truth.to_csv(truth_path, index=False)
    return df


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generate a synthetic, schema-conformant CascadeShield dataset.")
    p.add_argument("--matrix", type=Path, default=DATA_DIR / "experiment_matrix.csv")
    p.add_argument("--out", type=Path, default=DATA_DIR / "master_dataset.csv")
    p.add_argument("--truth-out", type=Path, default=DATA_DIR / "_synthetic_truth.csv")
    p.add_argument("--environments", default="LOCAL,AWS",
                   help="comma-separated; subset of {LOCAL,AWS}")
    p.add_argument("--replicates", type=int, default=3)
    p.add_argument("--anomaly-rate", type=float, default=0.04)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    environments = [e.strip().upper() for e in args.environments.split(",") if e.strip()]
    df = generate(args.matrix, args.out, args.truth_out,
                  environments, args.replicates, args.anomaly_rate, args.seed)

    n_open_null = df["time_to_open"].isna().sum()
    n_rec_null = df["time_to_recover"].isna().sum()
    print("[generate] SYNTHETIC dataset written (replace with real sweep output later)")
    print(f"  out      : {args.out}")
    print(f"  rows     : {len(df)}  ({df['experiment_id'].nunique()} configs"
          f" x {len(environments)} env x {args.replicates} replicates)")
    print(f"  blast    : mean={df['blast_radius'].mean():.3f} "
          f"min={df['blast_radius'].min():.3f} max={df['blast_radius'].max():.3f}")
    print(f"  meaningful nulls: time_to_open={n_open_null}  time_to_recover={n_rec_null}")
    print(f"  truth    : {args.truth_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
