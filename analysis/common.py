"""Shared loaders and statistics helpers for the CascadeShield analysis layer.

Everything under analysis/ obeys one rule from the sprint contract: **no number that
appears in the paper is typed by hand.** Each script writes its results to
analysis/out/*.json (machine-readable, the single source of truth for LaTeX) and
optionally a .csv/.png alongside it.

Python 3.9 compatible; depends only on pandas / numpy / scipy (+ matplotlib for the
figure-emitting scripts). statsmodels is NOT required here -- it becomes a dependency on
Day 3 (MixedLM, power analysis), not on Days 1-2.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = Path(__file__).resolve().parent / "out"
FIG_DIR = BASE_DIR / "figures"

# The datasets this project has produced, newest last. Each entry records the metric
# regime it was collected under, because blast_radius is NOT comparable across them --
# the subject denominator and the leg node set both changed. Pooling these files is the
# single most likely way to produce a wrong number in the paper.
DATASETS = {
    "v1_prefix": {
        "path": DATA_DIR / "master_dataset_v1_prefix.csv",
        "n_expected": 486,
        "blast_scale": 100.0,      # raw percent, never normalised by the old runner
        "blast_denominator": 5,    # 5 downstream services
        "leg_node_set": None,      # leg_failure_rates column did not exist yet
        "note": "Pre-timing-collector archive. time_to_open/time_to_recover are 100% null "
                "(the collector was a TODO stub), so this file cannot support H3 at all.",
    },
    "v2_latency_5svc": {
        "path": DATA_DIR / "master_dataset_v2_latency_5svc.csv",
        "n_expected": 162,
        "blast_scale": 1.0,
        "blast_denominator": 5,
        "leg_node_set": "gateway+4",   # legs INCLUDE gateway; blast subjects EXCLUDE it
        "note": "First sweep with timing. Legacy blast_radius and the leg vector range over "
                "DISJOINT node sets -- cross-metric checks on this file are heuristic only.",
    },
    "v3_gateway_not_rebuilt": {
        "path": DATA_DIR / "master_dataset_v3_gateway_not_rebuilt.csv",
        "n_expected": 92,
        "blast_scale": 1.0,
        "blast_denominator": 5,
        "leg_node_set": "4",
        "note": "Gateway container was not rebuilt for this batch; treat as a transitional "
                "archive, not a result set.",
    },
    "v4_flat_concurrency": {
        "path": DATA_DIR / "master_dataset_v4_flat_concurrency.csv",
        "n_expected": 798,
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "Full pre-fix snapshot of 'current', kept for audit before the LATENCY rows "
                "were removed from the live file and re-collected. LOAD_CONCURRENCY was a flat "
                "constant (5) regardless of fault type, so every FANOUT+LATENCY row here (214/214, "
                "100%) and 28/204 LINEAR+LATENCY rows carry lambda_deviation_flag=True -- see "
                "LAMBDA_DEVIATION in the quarantine exclusion-codes table, DATA_DICTIONARY.md. "
                "The 380 CRASH rows (192 FANOUT + 188 LINEAR) are NOT affected (crash's own "
                "worst-case latency is ~0s, so the flat concurrency=5 happened to already be "
                "correct for it) and were carried forward into 'current' unchanged, with "
                "load_concurrency backfilled to 5 (the true, known value) rather than left blank.",
    },
    "v5_soham_linear_presweep": {
        "path": DATA_DIR / "master_dataset_v5_soham_linear_presweep.csv",
        "n_expected": 324,
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "Soham's independent full LINEAR sweep (commit a957e5a, 2026-08-30, machine_id "
                "'soham-codespace') -- 162 CRASH + 162 LATENCY rows, collected on the Stage 4 "
                "branch before the LOAD_CONCURRENCY fix or DATASET_PATH_OVERRIDE existed, merged "
                "back into main only as this archive (PR #32's own version of master_dataset.csv "
                "was superseded during the merge, not silently dropped -- see git history). "
                "26/162 LATENCY rows already carry lambda_deviation_flag=True (16%, consistent "
                "with v4_flat_concurrency's ~14% on the same cell). Superseded by the D6 "
                "calibration LINEAR+LATENCY redo and 'current''s own retained CRASH rows -- kept "
                "for audit/history, not intended as a live analysis input.",
    },
    "current": {
        "path": DATA_DIR / "master_dataset.csv",
        "n_expected": 704,   # 380 retained CRASH rows + 324 re-collected LATENCY rows (162/topology)
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "Post-metric-change rebuild. blast_radius and the leg vector finally range "
                "over the SAME four CB-bearing subjects, so cross-metric checks are exact. "
                "LATENCY rows were fully re-collected (both topologies) after the "
                "LOAD_CONCURRENCY fix -- see v4_flat_concurrency above for the pre-fix archive. "
                "Complete as of 2026-09-03: 704/704 rows, 0 quarantined by analysis/quarantine.py "
                "(no STATE_LEAK/RECOVERY_TIMEOUT_HANG/LAMBDA_DEVIATION hits). LINEAR+LATENCY "
                "collected on soham-local, FANOUT+LATENCY on codespace -- see "
                "master_dataset_calibration_*_overlap.csv for the cross-machine calibration "
                "subset (6 configs x 3 replicates each direction) used to bound the host effect "
                "before trusting a LINEAR-vs-FANOUT comparison across these two collectors.",
    },
}

# The design factors that, together, identify a configuration. Replicates of one
# configuration differ only in `replicate`.
CONFIG_KEYS = ["experiment_id", "environment"]


# --------------------------------------------------------------------------- loading

def load(name, apply_exclusions=True):
    """Load one of the DATASETS by key. Returns a DataFrame with two derived columns:

      * `legs`          -- dict {service: failure_rate} parsed from leg_failure_rates
      * `blast_frac`    -- blast_radius normalised to 0-1 regardless of the file's scale

    When `apply_exclusions` is True (default) and an `excluded_reason` column is present,
    quarantined rows are dropped. Analyses that need to *count* exclusions pass False.
    """
    spec = DATASETS[name]
    df = pd.read_csv(spec["path"])
    df["dataset"] = name
    df["legs"] = df.get("leg_failure_rates", pd.Series([""] * len(df))).map(parse_legs)
    df["blast_frac"] = pd.to_numeric(df["blast_radius"], errors="coerce") / spec["blast_scale"]
    if apply_exclusions:
        df = drop_excluded(df)
    return df.reset_index(drop=True)


def drop_excluded(df):
    """Drop quarantined rows (a non-empty `excluded_reason`). A no-op if the column
    isn't present. Shared so every caller agrees on what "excluded" means -- see
    canary_readout.py::load_canary, which loads a differently-shaped CSV than the
    DATASETS this module owns and so can't just call load() itself."""
    if "excluded_reason" not in df.columns:
        return df
    return df[df["excluded_reason"].isna() | (df["excluded_reason"].astype(str).str.strip() == "")]


def parse_legs(raw):
    """`"order-service:0.2692;inventory-service:0.0000"` -> {"order-service": 0.2692, ...}.

    An empty / missing cell means no leg was observable during the run (a measurement gap,
    which is a meaningful null) and yields {} -- never a fabricated set of zeros.
    """
    out = {}
    if not isinstance(raw, str):
        return out
    for part in raw.split(";"):
        if not part.strip():
            continue
        svc, _, val = part.partition(":")
        try:
            out[svc.strip()] = float(val)
        except ValueError:
            continue
    return out


def real_blast_radius_from_rates(rates, tau):
    """Fraction of *observed* legs whose failure rate exceeds tau.

    Mirrors runner.real_blast_radius_from_rates exactly so a post-hoc recomputation from
    the CSV cannot silently disagree with what the harness wrote. Returns None when no leg
    was observable -- a meaningful null, never 0.0.
    """
    if not rates:
        return None
    return sum(1 for r in rates.values() if r > tau) / len(rates)


# ------------------------------------------------------------------------ statistics

def bootstrap_ci(values, statistic=np.mean, n_resamples=10000, alpha=0.05, seed=20260810):
    """Percentile bootstrap CI. Returned on every mean the paper prints, no exceptions.

    NOTE: this resamples *rows*. Where the unit of independence is the configuration and
    not the run, use bootstrap_ci_grouped instead -- runs within one experiment_id are not
    independent and row-level resampling will understate the interval.
    """
    v = np.asarray([x for x in values if x is not None and not pd.isna(x)], dtype=float)
    if len(v) == 0:
        return {"n": 0, "point": None, "lo": None, "hi": None}
    rng = np.random.default_rng(seed)
    draws = statistic(rng.choice(v, size=(n_resamples, len(v)), replace=True), axis=1)
    return {
        "n": int(len(v)),
        "point": float(statistic(v)),
        "lo": float(np.percentile(draws, 100 * alpha / 2)),
        "hi": float(np.percentile(draws, 100 * (1 - alpha / 2))),
    }


def bootstrap_ci_grouped(df, value_col, group_col="experiment_id", statistic=np.mean,
                         n_resamples=10000, alpha=0.05, seed=20260810):
    """Cluster bootstrap: resample whole configurations with replacement, then pool their
    rows. This is the interval the paper reports, because the effective sample size is the
    number of configurations, not the number of runs.
    """
    sub = df[[group_col, value_col]].dropna()
    groups = [g[value_col].to_numpy(dtype=float) for _, g in sub.groupby(group_col)]
    if not groups:
        return {"n_rows": 0, "n_groups": 0, "point": None, "lo": None, "hi": None}
    rng = np.random.default_rng(seed)
    idx = np.arange(len(groups))
    draws = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        pick = rng.choice(idx, size=len(idx), replace=True)
        draws[i] = statistic(np.concatenate([groups[j] for j in pick]))
    pooled = np.concatenate(groups)
    return {
        "n_rows": int(len(pooled)),
        "n_groups": int(len(groups)),
        "point": float(statistic(pooled)),
        "lo": float(np.percentile(draws, 100 * alpha / 2)),
        "hi": float(np.percentile(draws, 100 * (1 - alpha / 2))),
    }


# Cliff's delta's magnitude labels, ordered mildest-to-strongest. Shared so a caller
# needing "which of these magnitudes is worst" (e.g. machine_calibration.py comparing
# several DVs) imports this instead of re-typing the same ordering locally -- one
# definition, so a future tier addition here can't silently desync a second copy.
# Deliberately excludes "undefined" (cliffs_delta below returns it when a group has
# zero observations) -- that's not a magnitude, it's "never actually compared," and a
# caller doing a worst-of walk must handle it as its own case, not rank it at all.
MAGNITUDE_RANK = {"negligible": 0, "small": 1, "medium": 2, "large": 3}


def cliffs_delta(a, b):
    """Cliff's delta with the conventional magnitude label. Reported next to every
    p-value -- a bare p-value is a rejection reason at empirical-SE venues."""
    a = np.asarray([x for x in a if not pd.isna(x)], dtype=float)
    b = np.asarray([x for x in b if not pd.isna(x)], dtype=float)
    if len(a) == 0 or len(b) == 0:
        return {"delta": None, "magnitude": "undefined", "n_a": int(len(a)), "n_b": int(len(b))}
    diff = np.sign(a[:, None] - b[None, :])
    d = float(diff.mean())
    m = abs(d)
    label = "negligible" if m < 0.147 else "small" if m < 0.33 else "medium" if m < 0.474 else "large"
    return {"delta": d, "magnitude": label, "n_a": int(len(a)), "n_b": int(len(b))}


def holm_bonferroni(pvalues):
    """Holm-Bonferroni step-down adjustment across the H1-H6 family.

    `pvalues` is a dict {label: p}; returns {label: adjusted_p}. Nones pass through.
    """
    items = [(k, v) for k, v in pvalues.items() if v is not None]
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    adjusted = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))  # enforce monotonicity
        adjusted[k] = running
    for k, v in pvalues.items():
        adjusted.setdefault(k, None)
    return adjusted


# ---------------------------------------------------------------------------- output

def write_json(name, payload):
    """Write analysis/out/<name>.json and echo the path. Every reported number lands here."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=_jsonable)
    print("wrote {}".format(os.path.relpath(path, BASE_DIR)))
    return path


def _jsonable(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError("not JSON serialisable: {!r}".format(type(obj)))
