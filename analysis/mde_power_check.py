"""
analysis/mde_power_check.py

Post-sweep per-cell MDE (minimum detectable effect) power-check, run once against the
completed full sweep (data/master_dataset.csv, 216 cells x n=3 replicates) rather than at
runtime. Answers one question: at n=3 replicates/cell, how big does a true difference have
to be before we could reliably see it -- and which of the sweep's actual matched comparisons
fall short of that bar and would need a replicate top-up before being trusted?

Two parts:

  (a) HEADLINE MDE -- for each primary DV (time_to_open, time_to_recover; blast_radius
      included as secondary per the LINEAR/FAN_OUT decision), pool the within-cell variance
      across every n=3 cell to get the best available noise estimate at this replicate
      depth, then solve for the Cohen's d (and raw-unit) effect size a two-sample t-test
      (n=3 vs n=3, df=4, alpha=0.05 two-sided) needs to hit 80% power. This is the
      resolution floor of the whole sweep, independent of which comparison you run.

  (b) MATCHED-COMPARISON AUDIT -- the sweep's grid lets cells be paired/grouped so that
      exactly one factor differs (window_type, fault_type, topology, or wait_duration) and
      everything else (topology/fault_type/threshold/window_size/wait_duration as
      applicable) is held fixed. For every such matched family this script computes the
      observed effect and its ratio to the DV's MDE from (a), and labels it:
        POWERED       observed effect >= 1.5x MDE   -- trust this comparison as-is
        BORDERLINE    observed effect in [0.75, 1.5)x MDE -- the "close comparisons" this
                       check exists to catch; a modest replicate top-up would firm it up
        UNDERPOWERED  observed effect < 0.75x MDE    -- cannot distinguish from noise at
                       n=3; do not claim a direction without more reps

  Window_type pairs are the NOMINAL grid pairing (same T/W/D suffix), not matched-H per
  hypotheses.md S2.1 -- that requires lambda-based matching outside a fixed grid cell and
  is out of scope here. Reported as an instrument-resolution check, not an H1 verdict.

Usage:  python analysis/mde_power_check.py [dataset]   (default "current")
Output: analysis/out/mde_power_check.json
        analysis/out/mde_power_check_matched_pairs.csv
"""

import re
import sys

import numpy as np
import pandas as pd
from scipy import stats, optimize

from common import DATA_DIR, OUT_DIR, load, write_json

DVS = ["time_to_open", "time_to_recover", "blast_radius"]

ALPHA = 0.05
TARGET_POWER = 0.80
N_PER_CELL = 3  # design replicate depth; cells with fewer are excluded from pooling

ID_RE = re.compile(
    r"^(?P<topology>LIN|FAN)-(?P<fault>LAT|CRS)-(?P<window_type>CNT|TIM)"
    r"-T(?P<threshold>\d+)-W(?P<window_size>\d+)-D(?P<wait>\d+)$"
)

FACTOR_COLS = ["topology", "fault", "window_type", "threshold", "window_size", "wait"]


def parse_experiment_id(exp_id):
    m = ID_RE.match(exp_id)
    if not m:
        return None
    return m.groupdict()


# --------------------------------------------------------------- (a) headline MDE

def is_tim_w5(exp_id):
    """TIME_BASED sliding window with a 5s window (window_size=5) shows systematically
    higher run-to-run variance than every other config (see decision log) -- window-
    boundary timing sensitivity is much larger relative to a short window. Pooling its
    variance into one blended per-DV estimate contaminates the noise floor used to judge
    every OTHER comparison, so it gets its own stratum rather than joining the main pool."""
    parsed = parse_experiment_id(exp_id)
    return parsed is not None and parsed["window_type"] == "TIM" and parsed["window_size"] == "5"


def pooled_within_cell_sd(df, dv, subset_ids=None):
    """Pool within-cell variance across every experiment_id with >=2 non-null observations
    of `dv`, weighting each cell's variance by its own degrees of freedom (n-1). Cells with
    only 1 observation contribute no variance info and are excluded; everything else is
    included regardless of whether it has the original n=3 or a topped-up n=5 -- a fixed
    n==3 filter here would silently drop exactly the cells a replicate top-up improved,
    which is the opposite of what this check is for.

    subset_ids, if given, restricts pooling to that set of experiment_ids -- used to keep
    the TIM-W5 stratum (see is_tim_w5) from contaminating the noise floor for every other
    comparison with its much higher variance."""
    sub = df[["experiment_id", dv]].dropna()
    if subset_ids is not None:
        sub = sub[sub["experiment_id"].isin(subset_ids)]
    counts = sub.groupby("experiment_id")[dv].count()
    usable_cells = counts[counts >= 2].index
    if len(usable_cells) == 0:
        return {"pooled_sd": None, "n_cells": 0, "df_total": 0}
    g = sub[sub["experiment_id"].isin(usable_cells)].groupby("experiment_id")[dv]
    variances = g.var(ddof=1).dropna()
    dfs = (g.count() - 1).loc[variances.index]
    if dfs.sum() == 0:
        return {"pooled_sd": None, "n_cells": 0, "df_total": 0}
    pooled_var = (variances * dfs).sum() / dfs.sum()
    return {
        "pooled_sd": float(np.sqrt(pooled_var)),
        "n_cells": int(len(variances)),
        "df_total": int(dfs.sum()),
    }


def mde_cohens_d(n_a, n_b=None, alpha=ALPHA, power=TARGET_POWER):
    """Exact two-sample t-test MDE in Cohen's d, via the noncentral t distribution, for
    (possibly unequal) group sizes n_a, n_b. df = n_a+n_b-2. Solves for the noncentrality
    delta such that the two-sided test rejects with probability `power`, then converts
    delta -> d (unequal-n formula: delta = d / sqrt(1/n_a + 1/n_b))."""
    if n_b is None:
        n_b = n_a
    df = n_a + n_b - 2
    t_crit = stats.t.ppf(1 - alpha / 2, df)

    def power_at(delta):
        return stats.nct.sf(t_crit, df, delta) + stats.nct.cdf(-t_crit, df, delta)

    lo, hi = 0.0, 1.0
    while power_at(hi) < power:
        hi *= 2
        if hi > 1000:
            raise RuntimeError("MDE search did not converge")
    delta = optimize.brentq(lambda d: power_at(d) - power, lo, hi, xtol=1e-6)
    d = delta / np.sqrt(1.0 / n_a + 1.0 / n_b)
    return float(d)


def headline_mde(df):
    d_at_n3 = mde_cohens_d(N_PER_CELL)  # reference figure: MDE at the ORIGINAL design depth
    out = {"cohens_d_mde_n3": d_at_n3, "alpha": ALPHA, "target_power": TARGET_POWER, "by_dv": {}}
    all_ids = df["experiment_id"].unique()
    tim_w5_ids = {e for e in all_ids if is_tim_w5(e)}
    rest_ids = set(all_ids) - tim_w5_ids
    for dv in DVS:
        pooled_main = pooled_within_cell_sd(df, dv, subset_ids=rest_ids)
        pooled_tim_w5 = pooled_within_cell_sd(df, dv, subset_ids=tim_w5_ids)
        raw_mde = None if pooled_main["pooled_sd"] is None else pooled_main["pooled_sd"] * d_at_n3
        out["by_dv"][dv] = {
            **pooled_main, "raw_unit_mde": raw_mde,
            "tim_w5_stratum": pooled_tim_w5,  # reported separately, not blended into raw_mde
        }
    return out


# --------------------------------------------------------- (b) matched-comparison audit

def build_cell_stats(df, dv):
    """Per-experiment_id n/mean/sd for one DV, plus parsed factors."""
    rows = []
    for exp_id, g in df.groupby("experiment_id"):
        vals = g[dv].dropna().to_numpy(dtype=float)
        parsed = parse_experiment_id(exp_id)
        if parsed is None:
            continue
        rows.append({
            "experiment_id": exp_id,
            **parsed,
            "n": len(vals),
            "mean": float(np.mean(vals)) if len(vals) else None,
            "sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else None,
        })
    return pd.DataFrame(rows)


def label_comparison(observed_effect, mde):
    if mde is None or mde == 0:
        return "UNSCORABLE"
    ratio = abs(observed_effect) / mde
    if ratio >= 1.5:
        return "POWERED"
    if ratio >= 0.75:
        return "BORDERLINE"
    return "UNDERPOWERED"


def matched_family_comparisons(cell_df, varying_factor, dv, pooled_sd_main, pooled_sd_tim_w5):
    """Group cells by every factor EXCEPT `varying_factor`; within each group, every pair
    of distinct levels of `varying_factor` is one matched comparison (everything else held
    fixed). Two-level factors (window_type CNT/TIM, fault LAT/CRS, topology LIN/FAN) yield
    exactly one pair per group; this also handles factors with >2 levels generically.

    The MDE for each pair is computed from THAT pair's own n_a/n_b (via mde_cohens_d),
    not a blanket design-wide value -- necessary once a replicate top-up gives some cells
    n=5 while others stay at n=3, so two cells being compared can have different power.
    The noise (pooled_sd) used is also picked per pair: if EITHER side is a TIM-W5 cell
    (see is_tim_w5), the higher TIM-W5-stratum SD applies to the whole comparison, since
    that side's noise dominates; otherwise the main-stratum SD applies."""
    hold_cols = [c for c in FACTOR_COLS if c != varying_factor]
    results = []
    for hold_vals, g in cell_df.groupby(hold_cols):
        g = g.dropna(subset=["mean"])
        levels = g[varying_factor].unique()
        if len(levels) < 2:
            continue
        for i in range(len(levels)):
            for j in range(i + 1, len(levels)):
                a = g[g[varying_factor] == levels[i]].iloc[0]
                b = g[g[varying_factor] == levels[j]].iloc[0]
                if a["mean"] is None or b["mean"] is None or a["n"] < 2 or b["n"] < 2:
                    continue
                observed = a["mean"] - b["mean"]
                pair_d_mde = mde_cohens_d(int(a["n"]), int(b["n"]))
                either_tim_w5 = is_tim_w5(a["experiment_id"]) or is_tim_w5(b["experiment_id"])
                pooled_sd = pooled_sd_tim_w5 if either_tim_w5 else pooled_sd_main
                pair_raw_mde = None if pooled_sd is None else pooled_sd * pair_d_mde
                results.append({
                    "dv": dv,
                    "varying_factor": varying_factor,
                    "held": dict(zip(hold_cols, hold_vals if isinstance(hold_vals, tuple) else (hold_vals,))),
                    "level_a": f"{varying_factor}={levels[i]}", "mean_a": a["mean"], "sd_a": a["sd"], "n_a": int(a["n"]),
                    "level_b": f"{varying_factor}={levels[j]}", "mean_b": b["mean"], "sd_b": b["sd"], "n_b": int(b["n"]),
                    "experiment_id_a": a["experiment_id"], "experiment_id_b": b["experiment_id"],
                    "noise_stratum": "tim_w5" if either_tim_w5 else "main",
                    "observed_effect": observed,
                    "raw_mde": pair_raw_mde,
                    "effect_to_mde_ratio": None if not pair_raw_mde else abs(observed) / pair_raw_mde,
                    "status": label_comparison(observed, pair_raw_mde),
                })
    return results


def main():
    dataset = sys.argv[1] if len(sys.argv) > 1 else "current"
    df = load(dataset)

    headline = headline_mde(df)

    all_pairs = []
    for dv in ["time_to_open", "time_to_recover"]:  # primary DVs only for the family audit
        pooled_sd_main = headline["by_dv"][dv]["pooled_sd"]
        pooled_sd_tim_w5 = headline["by_dv"][dv]["tim_w5_stratum"]["pooled_sd"]
        cell_df = build_cell_stats(df, dv)
        for factor in ["window_type", "fault", "topology", "wait"]:
            all_pairs.extend(matched_family_comparisons(cell_df, factor, dv, pooled_sd_main, pooled_sd_tim_w5))

    pairs_df = pd.DataFrame(all_pairs)
    status_counts = pairs_df["status"].value_counts().to_dict() if len(pairs_df) else {}

    # "Close comparisons needing more reps" means observed effects sitting NEAR the n=3
    # detection floor (ratio approaching 1 from either side) -- those could plausibly
    # firm up into POWERED with a modest top-up. Sorted DESCENDING by ratio so the
    # comparisons closest to significance (most worth topping up) lead the list; a
    # near-zero observed effect (ratio ~0, e.g. H3's wait_duration-on-t_open negative
    # control) is confidently null already and sinks to the bottom on purpose.
    borderline_or_worse = pairs_df[pairs_df["status"].isin(["BORDERLINE", "UNDERPOWERED"])].copy()
    if len(borderline_or_worse):
        borderline_or_worse = borderline_or_worse.sort_values("effect_to_mde_ratio", ascending=False)

    payload = {
        "dataset": dataset,
        "n_rows": int(len(df)),
        "n_cells": int(df["experiment_id"].nunique()),
        "design_n_per_cell": N_PER_CELL,
        "headline_mde": headline,
        "matched_comparisons_total": int(len(pairs_df)),
        "status_counts": status_counts,
        "priority_topup_list": borderline_or_worse.head(25).to_dict("records"),
    }
    write_json("mde_power_check.json", payload)

    out_csv = OUT_DIR / "mde_power_check_matched_pairs.csv"
    pairs_df.to_csv(out_csv, index=False)
    print(f"wrote {out_csv.relative_to(DATA_DIR.parent)}")

    print(f"\ndataset={dataset}  rows={len(df)}  cells={df['experiment_id'].nunique()}")
    print(f"Cohen's d MDE at n=3/group (alpha=.05, power=.80): {headline['cohens_d_mde_n3']:.2f}  "
          f"(a LARGE effect by conventional labels — n=3 can only reliably catch big differences)")
    for dv in DVS:
        info = headline["by_dv"][dv]
        if info["pooled_sd"] is None:
            print(f"  {dv}: no full n=3 cells available, MDE not computable")
        else:
            print(f"  {dv}: pooled within-cell SD={info['pooled_sd']:.3f} over {info['n_cells']} cells "
                  f"-> raw MDE={info['raw_unit_mde']:.3f}")
    print(f"\nmatched comparisons: {len(pairs_df)} total -> {status_counts}")
    if len(borderline_or_worse):
        print(f"\ntop close comparisons (highest effect/MDE ratio first -- most worth a top-up):")
        for _, r in borderline_or_worse.head(10).iterrows():
            print(f"  [{r['status']:12s}] {r['dv']:16s} {r['varying_factor']:12s} "
                  f"{r['level_a']} vs {r['level_b']}  held={r['held']}  "
                  f"observed={r['observed_effect']:+.3f}  ratio={r['effect_to_mde_ratio']:.2f}")


if __name__ == "__main__":
    main()
