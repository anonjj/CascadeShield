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
from scipy import stats

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
    "v6_pre_d17_leg_blend_crash": {
        "path": DATA_DIR / "master_dataset_v6_pre_d17_leg_blend_crash.csv",
        "n_expected": 704,
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "Full pre-D17-fix snapshot of 'current' (704 rows: 380 CRASH + 324 LATENCY), "
                "kept for audit before the 380 CRASH rows were removed from the live file and "
                "re-collected under the corrected compute_leg_failure_rates() (max-of-breakers, "
                "commit 723863d, PR #45). Every CRASH row here reads order-service's AND "
                "inventory-service's leg_failure_rates at exactly 0.5000 (zero variance, "
                "380/380, confirmed in PR #44) -- the D17 leg-blending bug saturating at a "
                "deterministic ceiling (CRASH drives one breaker to ~100% failure, its sibling "
                "reads 0%, average is exactly 50%). The 324 LATENCY rows here are ALSO computed "
                "through the same pre-fix blending path and are technically diluted too, just "
                "not to a hard ceiling (LATENCY's partial/probabilistic failure doesn't collapse "
                "the average the way CRASH's near-total failure does) -- they were carried "
                "forward into 'current' UNCHANGED because D15's LATENCY-only separation claim "
                "already held on this data and a LATENCY re-collection is a separate, later "
                "decision, not because they're unaffected. Superseded once CRASH re-collection "
                "lands in 'current'.",
    },
    "d21_poll_until_transition_verification": {
        "path": DATA_DIR / "master_dataset_d21_recollect.csv",
        "n_expected": 36,
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "Standalone, NOT merged into 'current' (D21, 2026-09-16). 18 LINEAR/LATENCY "
                "configs x 2 window types x 2 replicates, run under the post-D21 harness "
                "(BreakerObserver._drive_half_open_probes now polls until a real transition "
                "instead of a fixed ~4.1s window) to verify the fix against real_data before "
                "trusting analysis/half_open_survival.py's KM read. Deliberately used fresh "
                "replicates 1-2 for these 18 experiment_ids -- which already exist in "
                "'current' from the original main sweep + the D13 top-up (PR #54) -- so every "
                "(experiment_id, replicate) key here COLLIDES with 'current' and this file "
                "must never be appended to it. Not needed there anyway: the coarse "
                "time_to_recover metric was never actually censored (0/360 nulls in "
                "'current', confirmed independently of this run), so there is nothing here "
                "that improves 'current''s own numbers -- the entire payload of this "
                "re-collection is the precise_half_open_to_closed evidence, already fully "
                "captured in data/cb_transitions.jsonl (the sidecar half_open_survival.py "
                "reads directly). Two rows (LIN-LAT-TIM-T50-W20-D5 rep 2,  "
                "LIN-LAT-TIM-T50-W20-D15 rep 1) have a coarse time_to_recover inflated by a "
                "real-world system-sleep event mid-poll (704.6s / 2657.1s, run_timestamps "
                "hours apart from the rest of the sweep) -- caught by the EXISTING "
                "RECOVERY_TIMEOUT_HANG rule (RECOVERY_CAP_S=120.0) once quarantine.py runs "
                "against this dataset, no new detection logic needed. Their "
                "half_open_probe_timed_out is still correctly False -- the sleep happened "
                "during _poll_for_recovery's own loop, not during _drive_half_open_probes' "
                "separate, much shorter poll-until-transition window that runs after it.",
    },
    "current": {
        "path": DATA_DIR / "master_dataset.csv",
        "n_expected": 360,   # 324 retained LATENCY rows; CRASH rows removed pending re-collection (v6 above)
        "blast_scale": 1.0,
        "blast_denominator": 4,
        "leg_node_set": "4",
        "note": "TEMPORARILY LATENCY-ONLY (2026-09-06): the 380 CRASH rows were removed and "
                "archived to v6_pre_d17_leg_blend_crash above, pending re-collection under "
                "D17's fix (max-of-breakers). Update n_expected again once fresh CRASH rows "
                "land -- see decision-log D17/D15 for the re-collection plan. "
                "Pre-2026-09-06 history: post-metric-change rebuild, blast_radius and the leg "
                "vector range over the SAME four CB-bearing subjects, so cross-metric checks are "
                "exact. LATENCY rows were fully re-collected (both topologies) after the "
                "LOAD_CONCURRENCY fix -- see v4_flat_concurrency above for that pre-fix archive. "
                "LINEAR+LATENCY collected on soham-local, FANOUT+LATENCY on codespace -- see "
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


def mann_whitney(a, b):
    """Two-sided Mann-Whitney U test -- the paper's default significance test for any
    two-group timing/count comparison (B5, docs/paper/statistical-treatment.md). Rank-based
    and distribution-free: it makes no normality assumption, which a parametric test (Welch's
    t) is not entitled to here -- per-cell replicate counts are small (often n < 15) and the
    timing DVs are heavy-tailed, bounded at 0, and carry a documented TIME_BASED bimodality
    (hypotheses.md Sec 4). Always report alongside cliffs_delta() (see compare_groups below)
    -- a bare p-value is a rejection reason at empirical-SE venues, per the metrics contract.

    NaNs are dropped before the test, mirroring cliffs_delta's own handling. This does NOT
    make it safe to call directly on a raw column that may still hold right-censored nulls
    (time_to_open/time_to_recover) -- for those, go through compare_censored_groups below so
    the censored rows are accounted for as a rate, not silently discarded.
    """
    a = np.asarray([x for x in a if not pd.isna(x)], dtype=float)
    b = np.asarray([x for x in b if not pd.isna(x)], dtype=float)
    if len(a) == 0 or len(b) == 0:
        return {"U": None, "p": None, "n_a": int(len(a)), "n_b": int(len(b))}
    result = stats.mannwhitneyu(a, b, alternative="two-sided")
    return {"U": float(result.statistic), "p": float(result.pvalue),
            "n_a": int(len(a)), "n_b": int(len(b))}


def compare_groups(a, b):
    """THE standard two-group comparison (B5): Mann-Whitney U for significance, Cliff's delta
    for effect size, reported together so a caller can never emit one without the other.
    Every H1-H5 two-group contrast on an uncensored quantity should call this rather than
    reaching for scipy.stats directly -- see docs/paper/statistical-treatment.md."""
    return {"mann_whitney": mann_whitney(a, b), "cliffs_delta": cliffs_delta(a, b)}


def censored_timing_summary(df, value_col, group_col="experiment_id",
                             n_resamples=10000, alpha=0.05, seed=20260810):
    """The mandatory report shape for a right-censored timing DV (B5: time_to_open,
    time_to_recover). A null in value_col means the event never happened within the
    observation window -- "breaker never opened" / "never recovered" -- and is an outcome,
    not a missing value (metrics contract Sec 6, DATA_DICTIONARY.md). It is NEVER
    mean-imputed and never silently dropped before averaging: doing either conditions the
    remaining rows on the event having occurred and biases the timing comparison up or down
    depending on how the cell's own rate compares to the other cell's -- exactly the failure
    mode B5 exists to close off.

    Returns the rate at which the event was observed at all (e.g. trip rate / recovery rate)
    and, SEPARATELY, the timing distribution conditional on it having happened. Report both
    numbers together, always -- never one alone.

    `df` must already be restricted to the population this rate is computed over (e.g. one
    window_type x horizon cell); this function only splits on null/non-null in value_col.
    Both the rate and the conditional-timing CI use the cluster bootstrap over group_col
    (bootstrap_ci_grouped) -- the same configs-not-rows unit as every other pooled quantity
    in this paper.
    """
    total = df[[group_col, value_col]].copy()
    observed_mask = total[value_col].notna()
    rate = bootstrap_ci_grouped(
        total.assign(_observed=observed_mask.astype(float)),
        "_observed", group_col=group_col, n_resamples=n_resamples, alpha=alpha, seed=seed,
    )
    conditional = bootstrap_ci_grouped(
        total[observed_mask], value_col, group_col=group_col,
        n_resamples=n_resamples, alpha=alpha, seed=seed,
    )
    return {
        "n_total": int(len(total)),
        "n_observed": int(observed_mask.sum()),
        "n_censored": int((~observed_mask).sum()),
        "rate": rate,                       # P(event observed) -- e.g. trip rate, recovery rate
        "conditional_timing": conditional,  # value_col | event observed. Never imputed.
    }


def compare_censored_groups(df_a, df_b, value_col, group_col="experiment_id"):
    """The full two-group protocol for a right-censored timing DV (B5): compares the RATE at
    which the event occurred (e.g. did group B trip more often than group A) and, separately,
    compares timing conditional on the event having occurred (Mann-Whitney + Cliff's delta,
    via compare_groups). Call this instead of hand-rolling a mean-of-non-null-rows comparison
    -- see censored_timing_summary above and docs/paper/statistical-treatment.md."""
    summary_a = censored_timing_summary(df_a, value_col, group_col=group_col)
    summary_b = censored_timing_summary(df_b, value_col, group_col=group_col)
    return {
        "a": summary_a,
        "b": summary_b,
        "conditional_timing_comparison": compare_groups(
            df_a[value_col].dropna(), df_b[value_col].dropna()),
    }


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
