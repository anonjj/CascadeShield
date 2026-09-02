"""Day 2 (Soham) -- the lambda canary read-out, and with it the Day-2 gate.

Run this the moment the canary finishes. It answers H2 and H1 and prints the gate
recommendation, so the decision that picks the paper is made from numbers rather than from
whoever is still awake.

  H2  Is there a crossover lambda* below which TIME_BASED cannot trip inside the fault
      window? Measured as trip rate -- the share of runs with a non-null time_to_open --
      per (window_type, lambda). A null t_open here is the measurement, not a gap.

  H1  At MATCHED horizon H, is E[t_open] indistinguishable between window types while
      Var(t_open) differs? Mean by Welch's t (unequal variances, which is the whole point),
      variance by Brown-Forsythe (Levene centred on the median -- robust, and it tests
      variance directly, because H1 is a variance claim). Both with 95% bootstrap CIs and
      Cliff's delta, because a bare p-value is a rejection reason.

      This runs on the matched arm only. Running it on the base arm reproduces the
      comparison the paper argues is invalid, so it is refused there rather than reported
      with a caveat.

  phi The false-trip rate, from the null-fault arm: P(breaker opens | no fault injected).

Gate logic follows the sprint plan's table exactly:

  crossover AND variance gap significant   -> Paper A  ("The Window Is an Estimator")
  crossover, no variance gap               -> Paper A' (H2 alone)
  no lambda effect                         -> Paper B  (construct validity)

Usage:
  python analysis/canary_readout.py --dataset data/canary_runs.csv
  python analysis/canary_readout.py --self-test     # synthetic data, verifies the pipeline

Output: analysis/out/canary_readout.json, figures/fig4_trip_rate_vs_lambda.png,
        figures/fig4b_topen_vs_lambda.png
"""

import argparse

import numpy as np
import pandas as pd
from scipy import stats

from common import FIG_DIR, bootstrap_ci, cliffs_delta, drop_excluded, holm_bonferroni, write_json

ALPHA = 0.05
# A window type "reliably trips" above this share of runs, and "cannot trip" below it. The
# crossover lambda* is the first lambda where TIME_BASED clears the upper bar.
TRIP_RELIABLE = 0.80
TRIP_FAILING = 0.20
# |achieved - target| / target above this flags a run. Read from experiments/constants.py
# rather than redeclared, so the analysis layer cannot quietly disagree with the runner
# about what counts as off-target. constants.py is stdlib-only (unlike runner.py, which
# imports Toxiproxy at module scope), so no try/except fallback is needed here.
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "experiments"))
from constants import LAMBDA_DEVIATION_THRESHOLD as LAMBDA_TOLERANCE


# ------------------------------------------------------------------------------ loading

def load_canary(path):
    df = pd.read_csv(path)
    for col in ("time_to_open", "time_to_recover", "lambda_achieved", "lambda_target",
                "effective_horizon", "lambda_cv"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = drop_excluded(df)
    df["tripped"] = df["time_to_open"].notna()
    return df.reset_index(drop=True)


def check_lambda_fidelity(df):
    """H1 and H2 are both claims about lambda. If the harness did not deliver the lambda it
    was asked for, every result downstream is about an unknown independent variable, so this
    runs first and its verdict is reported next to the hypotheses rather than buried."""
    if "lambda_achieved" not in df.columns or df["lambda_achieved"].isna().all():
        return {"available": False,
                "verdict": "lambda_achieved was never recorded -- H1/H2 cannot be claimed, "
                           "because the independent variable is unmeasured. This is Jay's "
                           "Day-2 instrumentation task and it is a hard blocker, not a caveat."}
    rel = (df["lambda_achieved"] - df["lambda_target"]).abs() / df["lambda_target"]
    # Prefer the harness's own verdict where it exists. runner.py computes the deviation
    # from per-request dispatch timestamps it can see and this layer cannot, so recomputing
    # from the two rounded CSV columns is strictly the weaker measurement -- fall back to it
    # only for older files written before lambda_deviation_flag existed.
    if "lambda_deviation_flag" in df.columns and df["lambda_deviation_flag"].notna().any():
        off = df["lambda_deviation_flag"].astype(str).str.strip().str.lower().isin(["true", "1"])
        flag_source = "runner.lambda_deviation_flag"
    else:
        off = rel > LAMBDA_TOLERANCE
        flag_source = "recomputed from lambda_achieved vs lambda_target"
    return {
        "deviation_flag_source": flag_source,
        "deviation_threshold": LAMBDA_TOLERANCE,
        "available": True,
        "n_runs": int(len(df)),
        "n_off_target": int(off.sum()),
        "share_off_target": float(off.mean()),
        "worst_relative_deviation": float(rel.max()),
        "median_lambda_cv": (float(df["lambda_cv"].median())
                             if "lambda_cv" in df.columns else None),
        "by_target": {str(k): {"achieved_mean": float(g["lambda_achieved"].mean()),
                               "n_off_target": int((rel.loc[g.index] > LAMBDA_TOLERANCE).sum())}
                      for k, g in df.groupby("lambda_target")},
        "verdict": ("OK" if not off.any() else
                    "{} of {} runs missed their target lambda by more than {:.0%} -- report "
                    "results against lambda_achieved, never lambda_target".format(
                        int(off.sum()), len(df), LAMBDA_TOLERANCE)),
    }


# ----------------------------------------------------------------------------------- H2

def h2_base_arm(df):
    """The rows H2 is about: fault injected, nominal window sizes.

    Filtering matters more than it looks. Pooling the null arm in drags every trip rate
    toward phi, and pooling the matched arm in mixes window sizes chosen per-lambda into a
    curve that is supposed to hold window size fixed -- either one can manufacture or erase
    a crossover on its own.
    """
    out = df[df["fault_type"].astype(str).str.upper() != "NONE"]
    if "arm" in out.columns and "base" in set(out["arm"]):
        out = out[out["arm"] == "base"]
    return out


def h2_trip_rate(df):
    """Trip rate vs lambda per window type, and the crossover if there is one."""
    df = h2_base_arm(df)
    rows = []
    for (wt, lam), g in df.groupby(["window_type", "lambda_target"]):
        k, n = int(g["tripped"].sum()), int(len(g))
        # Wilson interval: at n = 15 per cell a Wald interval on a proportion near 0 or 1
        # is nonsense, and these cells sit near 0 and 1 by design.
        lo, hi = _wilson(k, n)
        rows.append({"window_type": wt, "lambda_target": float(lam), "n": n, "n_tripped": k,
                     "trip_rate": k / n if n else None, "ci_lo": lo, "ci_hi": hi,
                     "mean_t_open": float(g["time_to_open"].mean()) if k else None})
    table = pd.DataFrame(rows).sort_values(["window_type", "lambda_target"])

    crossover = {}
    for wt, g in table.groupby("window_type"):
        g = g.sort_values("lambda_target")
        failing = g[g["trip_rate"] <= TRIP_FAILING]["lambda_target"]
        reliable = g[g["trip_rate"] >= TRIP_RELIABLE]["lambda_target"]
        # A crossover means the failing region lies ENTIRELY below the reliable one. Merely
        # overlapping regions describe a non-monotone trip rate, which is a broken
        # measurement rather than a load threshold, and must not be reported as lambda*.
        has = (len(failing) > 0 and len(reliable) > 0
               and failing.max() < reliable.min())
        crossover[wt] = {
            "crossover_present": bool(has),
            # lambda* is bracketed, not point-estimated: the design samples lambda on a
            # geometric grid, so the transition is known only to lie between two rungs.
            "lambda_star_lower": float(failing.max()) if has else None,
            "lambda_star_upper": float(reliable.min()) if has else None,
            "max_trip_rate": float(g["trip_rate"].max()),
            "min_trip_rate": float(g["trip_rate"].min()),
        }

    # H2 as stated is specifically about TIME_BASED failing where COUNT_BASED does not.
    time_cross = crossover.get("TIME_BASED", {}).get("crossover_present", False)
    count_cross = crossover.get("COUNT_BASED", {}).get("crossover_present", False)

    non_monotone = [wt for wt, g in table.groupby("window_type")
                    if not crossover[wt]["crossover_present"]
                    and (g.sort_values("lambda_target")["trip_rate"].diff().dropna() < -0.2).any()]

    # Does window type actually interact with lambda, or do both just trip less at low load?
    contingency = pd.crosstab(df["window_type"], df["tripped"])
    chi2 = None
    if contingency.shape == (2, 2) and contingency.values.min() >= 0:
        c = stats.chi2_contingency(contingency)
        chi2 = {"chi2": float(c.statistic), "p": float(c.pvalue), "dof": int(c.dof),
                "cramers_v": float(np.sqrt(c.statistic / (contingency.values.sum() * 1)))}

    return {
        "n_rows_used": int(len(df)),
        "table": table.to_dict("records"),
        "per_window_type": crossover,
        # Trip rate falling as load rises has no mechanism behind it. If this is non-empty,
        # stop and diagnose the harness before reading anything else on this page.
        "non_monotone_window_types": non_monotone,
        "h2_supported": bool(time_cross and not count_cross),
        "h2_verdict": (
            "TIME_BASED shows a crossover and COUNT_BASED does not -- H2 supported"
            if time_cross and not count_cross else
            "both window types show a crossover -- this is a load effect, not a window-type "
            "effect; H2 as stated is not supported" if time_cross and count_cross else
            "no crossover in TIME_BASED -- H2 not supported"),
        "trip_by_window_type_overall": chi2,
    }


def _wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denom
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


# ----------------------------------------------------------------------------------- H1

def h1_matched_horizon(df, horizon_col="effective_horizon"):
    """Mean and variance of t_open by window type, within each matched horizon bucket."""
    if "arm" not in df.columns or "matched_horizon" not in set(df["arm"]):
        return {"testable": False,
                "reason": "no matched_horizon arm in the dataset. H1 must not be tested on "
                          "the base arm -- at nominal window size COUNT and TIME sit on "
                          "different horizons and the contrast is the invalid one the paper "
                          "argues against."}
    matched = df[(df["arm"] == "matched_horizon") & df["time_to_open"].notna()].copy()

    # Group by the horizon the runs were DESIGNED at, not the one they achieved. Jay's
    # effective_horizon is derived from lambda_achieved, so it is continuous -- grouping on
    # it directly puts every run in a bucket of one and the contrast silently evaporates.
    # The achieved value is still reported per bucket, because a design horizon of 100 that
    # actually delivered 60 is a finding, not a rounding detail.
    if "effective_horizon_nominal" in matched.columns:
        matched["_bucket"] = matched["effective_horizon_nominal"].astype(float)
    elif horizon_col in matched.columns:
        matched["_bucket"] = matched[horizon_col].astype(float).round()
    else:
        return {"testable": False, "reason": "no horizon column to group on"}

    results, pvals = [], {}
    for h, g in matched.groupby("_bucket"):
        count = g[g["window_type"] == "COUNT_BASED"]["time_to_open"].dropna()
        time = g[g["window_type"] == "TIME_BASED"]["time_to_open"].dropna()
        if len(count) < 3 or len(time) < 3:
            results.append({"horizon": float(h), "n_count": len(count), "n_time": len(time),
                            "testable": False,
                            "reason": "fewer than 3 tripped runs on one side"})
            continue
        welch = stats.ttest_ind(count, time, equal_var=False)
        bf = stats.levene(count, time, center="median")   # Brown-Forsythe
        diff = float(count.mean() - time.mean())
        entry = {
            "horizon": float(h),
            "horizon_achieved_mean": (float(g[horizon_col].mean())
                                      if horizon_col in g.columns else None),
            "n_count": int(len(count)), "n_time": int(len(time)),
            "mean_count": bootstrap_ci(count), "mean_time": bootstrap_ci(time),
            "sd_count": float(count.std(ddof=1)), "sd_time": float(time.std(ddof=1)),
            "var_ratio_time_over_count": float(time.var(ddof=1) / count.var(ddof=1))
                                          if count.var(ddof=1) > 0 else None,
            "welch_t": float(welch.statistic), "welch_p": float(welch.pvalue),
            "welch_df": float(welch.df) if hasattr(welch, "df") else None,
            "mean_difference": diff,
            "mean_difference_ci": _diff_ci(count.to_numpy(), time.to_numpy()),
            "brown_forsythe_W": float(bf.statistic), "brown_forsythe_p": float(bf.pvalue),
            "cliffs_delta": cliffs_delta(count, time),
            "testable": True,
        }
        results.append(entry)
        pvals["welch_H{}".format(int(h))] = entry["welch_p"]
        pvals["bf_H{}".format(int(h))] = entry["brown_forsythe_p"]

    adjusted = holm_bonferroni(pvals)
    for entry in results:
        if entry.get("testable"):
            h = int(entry["horizon"])
            entry["welch_p_holm"] = adjusted.get("welch_H{}".format(h))
            entry["brown_forsythe_p_holm"] = adjusted.get("bf_H{}".format(h))

    live = [r for r in results if r.get("testable")]
    means_indistinguishable = all(r["welch_p_holm"] > ALPHA for r in live) if live else False
    variance_differs = any(r["brown_forsythe_p_holm"] <= ALPHA for r in live) if live else False
    return {
        "testable": bool(live),
        "n_horizons_tested": len(live),
        "by_horizon": results,
        "means_indistinguishable": bool(means_indistinguishable),
        "variance_differs": bool(variance_differs),
        "h1_supported": bool(means_indistinguishable and variance_differs),
        "h1_verdict": (
            "means indistinguishable and variance differs -- H1 supported"
            if means_indistinguishable and variance_differs else
            "variance differs but means also differ -- the estimators differ in level too, "
            "which is a stronger claim than H1 but not H1"
            if variance_differs else
            "no variance gap survives Holm correction -- H1 not supported"),
        "note": "Non-significant Welch p does NOT prove equal means; it fails to reject. "
                "Report the CI on the difference and say the data are consistent with "
                "equality, never that equality is established.",
    }


def _diff_ci(a, b, n_resamples=10000, seed=20260811):
    """Bootstrap CI on the difference in means. Reported because a non-significant Welch
    test is only meaningful alongside the interval it failed to exclude zero from."""
    rng = np.random.default_rng(seed)
    draws = (rng.choice(a, (n_resamples, len(a)), replace=True).mean(axis=1)
             - rng.choice(b, (n_resamples, len(b)), replace=True).mean(axis=1))
    return {"point": float(a.mean() - b.mean()),
            "lo": float(np.percentile(draws, 2.5)), "hi": float(np.percentile(draws, 97.5))}


# ---------------------------------------------------------------------------------- phi

def false_trip_rate(df):
    """phi = P(breaker opens | no fault injected), from the null-fault arm."""
    null = df[df["fault_type"].astype(str).str.upper() == "NONE"]
    if null.empty:
        return {"available": False,
                "reason": "no fault_type = NONE rows. Without phi, no configuration in this "
                          "paper can be described as safe, and its absence is a guaranteed "
                          "reviewer catch."}
    rows = []
    for (wt, lam), g in null.groupby(["window_type", "lambda_target"]):
        k, n = int(g["tripped"].sum()), int(len(g))
        lo, hi = _wilson(k, n)
        rows.append({"window_type": wt, "lambda_target": float(lam), "n": n,
                     "n_false_trips": k, "phi": k / n, "ci_lo": lo, "ci_hi": hi})
    overall_k, overall_n = int(null["tripped"].sum()), int(len(null))
    lo, hi = _wilson(overall_k, overall_n)
    return {"available": True, "phi_overall": overall_k / overall_n, "n": overall_n,
            "ci_lo": lo, "ci_hi": hi, "by_cell": rows}


# --------------------------------------------------------------------------------- gate

def gate(h2, h1):
    if h2["h2_supported"] and h1.get("variance_differs"):
        paper, pivot = "A", ("Full sweep includes lambda. Target ICPE / IEEE Access. "
                             "H1/H2 are the core, H3/H5 supporting.")
    elif h2["h2_supported"]:
        paper, pivot = "A-prime", ("Same sweep, narrower claim: lead on H2 alone -- static "
                                   "window configuration is correct at exactly one traffic "
                                   "level.")
    else:
        paper, pivot = "B", ("Drop lambda from the sweep. Spend Days 3-4 on FAN_OUT + TREE "
                             "breadth. H3 + H5 + H4 + the metric-evolution narrative.")
    return {"paper": paper, "days_3_7_pivot": pivot,
            "h2_supported": h2["h2_supported"],
            "variance_gap_significant": bool(h1.get("variance_differs")),
            "reminder": "Write this into docs/paper/decision-log.md with the supporting "
                        "numbers tonight. Do not revisit it on Day 4."}


# ------------------------------------------------------------------------------ figures

def make_figures(h2, df, prefix="", watermark=False):
    """Writes fig4 (trip rate) and fig4b (latency) vs lambda.

    `prefix` and `watermark` exist so self-test output can never be mistaken for results: a
    synthetic figure sitting at the real figure's path is one drag-and-drop away from the
    paper.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    table = pd.DataFrame(h2["table"])
    colours = {"COUNT_BASED": "#1f3b73", "TIME_BASED": "#b3261e"}
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    def stamp(ax):
        if watermark:
            ax.text(0.5, 0.5, "SYNTHETIC\nNOT RESULTS", transform=ax.transAxes,
                    fontsize=22, color="#d32f2f", alpha=0.25, rotation=30,
                    ha="center", va="center", zorder=10)

    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    for wt, g in table.groupby("window_type"):
        g = g.sort_values("lambda_target")
        ax.errorbar(g["lambda_target"], g["trip_rate"],
                    yerr=[g["trip_rate"] - g["ci_lo"], g["ci_hi"] - g["trip_rate"]],
                    marker="o", ms=5, capsize=3, lw=1.6, color=colours.get(wt), label=wt)
    ax.axhline(TRIP_RELIABLE, color="#888", ls=":", lw=0.9)
    ax.axhline(TRIP_FAILING, color="#888", ls=":", lw=0.9)
    ax.set_xscale("log")
    ax.set_xlabel(r"arrival rate $\lambda$ (req/s, achieved)")
    ax.set_ylabel("trip rate  P(breaker opens)")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Detection reliability against arrival rate", fontsize=10)
    stamp(ax)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "{}fig4_trip_rate_vs_lambda.png".format(prefix), dpi=300)
    fig.savefig(FIG_DIR / "{}fig4_trip_rate_vs_lambda.pdf".format(prefix))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    tripped = df[df["time_to_open"].notna()]
    for wt, g in tripped.groupby("window_type"):
        stat = g.groupby("lambda_target")["time_to_open"].agg(["mean", "std", "count"])
        ax.errorbar(stat.index, stat["mean"], yerr=stat["std"], marker="s", ms=5, capsize=3,
                    lw=1.6, color=colours.get(wt), label=wt)
    ax.set_xscale("log")
    ax.set_xlabel(r"arrival rate $\lambda$ (req/s, achieved)")
    ax.set_ylabel(r"$t_{\mathrm{open}}$ (s)")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(r"Detection latency against arrival rate (tripped runs only)", fontsize=10)
    stamp(ax)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "{}fig4b_topen_vs_lambda.png".format(prefix), dpi=300)
    fig.savefig(FIG_DIR / "{}fig4b_topen_vs_lambda.pdf".format(prefix))
    plt.close(fig)


# --------------------------------------------------------------------------------- main

def synthesise(seed=7, h2_effect=True, variance_gap=True):
    """Synthetic canary data, used only by --self-test.

    Exists so the read-out is known to work before the sweep runs -- discovering a crash in
    this script at 23:00 on Day 2 costs the gate. NEVER written to a dataset path.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for lam in [5, 20, 80, 320]:
        for wt in ["COUNT_BASED", "TIME_BASED"]:
            for w in [5, 10, 20]:
                for rep in range(5):
                    if wt == "TIME_BASED" and h2_effect:
                        p_trip = {5: 0.0, 20: 0.35, 80: 0.95, 320: 1.0}[lam]
                    else:
                        p_trip = 0.95
                    tripped = rng.random() < p_trip
                    rows.append({
                        "arm": "base", "experiment_id": "SYN-{}-{}-{}".format(wt, w, lam),
                        "window_type": wt, "window_size": w, "lambda_target": lam,
                        "lambda_achieved": lam * rng.normal(1.0, 0.03), "lambda_cv": 0.05,
                        "fault_type": "LATENCY", "replicate": rep + 1,
                        "effective_horizon": w if wt == "COUNT_BASED" else lam * w,
                        "time_to_open": float(rng.normal(6.0, 1.2)) if tripped else np.nan,
                        "time_to_recover": float(rng.normal(20, 3)) if tripped else np.nan,
                    })
    for h in [25, 50, 100]:
        for wt in ["COUNT_BASED", "TIME_BASED"]:
            sd = 5.4 if (wt == "TIME_BASED" and variance_gap) else 2.2
            for rep in range(15):
                rows.append({
                    "arm": "matched_horizon", "experiment_id": "SYN-MH-{}-{}".format(wt, h),
                    "window_type": wt, "window_size": h, "lambda_target": 20,
                    "lambda_achieved": 20 * rng.normal(1.0, 0.03), "lambda_cv": 0.05,
                    "fault_type": "LATENCY", "replicate": rep + 1, "effective_horizon": h,
                    "time_to_open": float(rng.normal(6.0, sd)),
                    "time_to_recover": float(rng.normal(20, 3)),
                })
    for lam in [20, 80]:
        for wt in ["COUNT_BASED", "TIME_BASED"]:
            for rep in range(10):
                false_trip = rng.random() < 0.05
                rows.append({
                    "arm": "null_control", "experiment_id": "SYN-NULL-{}-{}".format(wt, lam),
                    "window_type": wt, "window_size": 10, "lambda_target": lam,
                    "lambda_achieved": lam * rng.normal(1.0, 0.03), "lambda_cv": 0.05,
                    "fault_type": "NONE", "replicate": rep + 1, "effective_horizon": 10,
                    "time_to_open": float(rng.normal(6.0, 1.2)) if false_trip else np.nan,
                    "time_to_recover": np.nan,
                })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/canary_runs.csv")
    ap.add_argument("--self-test", action="store_true",
                    help="run against synthetic data to verify the pipeline before the sweep")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        df = synthesise()
        df["tripped"] = df["time_to_open"].notna()
        print("SELF-TEST: synthetic data, {} rows. Numbers below are NOT results.\n".format(len(df)))
    else:
        df = load_canary(args.dataset)
        print("loaded {} rows from {}\n".format(len(df), args.dataset))

    fidelity = check_lambda_fidelity(df)
    h2 = h2_trip_rate(df)
    h1 = h1_matched_horizon(df)
    phi = false_trip_rate(df)
    decision = gate(h2, h1)

    print("lambda fidelity: {}".format(fidelity["verdict"]))

    print("\nH2 -- trip rate vs lambda")
    print("  {:<12} {:>8} {:>12} {:>18}".format("window", "lambda", "trip rate", "95% CI"))
    for r in h2["table"]:
        print("  {:<12} {:>8.0f} {:>11.2f} {:>18}".format(
            r["window_type"], r["lambda_target"], r["trip_rate"],
            "[{:.2f}, {:.2f}]".format(r["ci_lo"], r["ci_hi"])))
    for wt, c in h2["per_window_type"].items():
        if c["crossover_present"]:
            print("  {}: crossover between lambda = {:.0f} and {:.0f} req/s".format(
                wt, c["lambda_star_lower"], c["lambda_star_upper"]))
    for wt in h2["non_monotone_window_types"]:
        print("  !! {}: trip rate FALLS as lambda rises. No mechanism produces that -- "
              "diagnose the harness before reading further.".format(wt))
    print("  => {}".format(h2["h2_verdict"]))

    print("\nH1 -- matched horizon")
    if not h1["testable"]:
        print("  NOT TESTABLE: {}".format(h1.get("reason", "no usable horizon buckets")))
    else:
        for r in h1["by_horizon"]:
            if not r.get("testable"):
                print("  H={:.0f}: skipped ({})".format(r["horizon"], r["reason"]))
                continue
            print("  H={:.0f}  mean COUNT {:.2f} [{:.2f}, {:.2f}] vs TIME {:.2f} "
                  "[{:.2f}, {:.2f}]".format(
                      r["horizon"], r["mean_count"]["point"], r["mean_count"]["lo"],
                      r["mean_count"]["hi"], r["mean_time"]["point"], r["mean_time"]["lo"],
                      r["mean_time"]["hi"]))
            print("        Welch p={:.4f} (Holm {:.4f}), diff {:.2f} [{:.2f}, {:.2f}], "
                  "Cliff's d={:.3f} ({})".format(
                      r["welch_p"], r["welch_p_holm"], r["mean_difference_ci"]["point"],
                      r["mean_difference_ci"]["lo"], r["mean_difference_ci"]["hi"],
                      r["cliffs_delta"]["delta"], r["cliffs_delta"]["magnitude"]))
            print("        Brown-Forsythe W={:.3f} p={:.4f} (Holm {:.4f}); sd {:.2f} vs "
                  "{:.2f}".format(r["brown_forsythe_W"], r["brown_forsythe_p"],
                                  r["brown_forsythe_p_holm"], r["sd_count"], r["sd_time"]))
        print("  => {}".format(h1["h1_verdict"]))

    print("\nphi -- false-trip rate")
    if phi["available"]:
        print("  overall {:.3f} [{:.3f}, {:.3f}] over {} null-fault runs".format(
            phi["phi_overall"], phi["ci_lo"], phi["ci_hi"], phi["n"]))
    else:
        print("  UNAVAILABLE: {}".format(phi["reason"]))

    print("\n" + "=" * 70)
    print("DAY-2 GATE -> Paper {}".format(decision["paper"]))
    print("  {}".format(decision["days_3_7_pivot"]))
    print("  {}".format(decision["reminder"]))
    print("=" * 70)

    # Self-test artifacts get their own names and a watermark. A synthetic figure sitting at
    # the real figure's path is one drag-and-drop away from ending up in the paper.
    prefix = "SELFTEST_" if args.self_test else ""
    if not args.no_figures:
        make_figures(h2, df, prefix=prefix, watermark=args.self_test)
        print("\nwrote figures/{p}fig4_trip_rate_vs_lambda.{{png,pdf}} and "
              "{p}fig4b_topen_vs_lambda.{{png,pdf}}".format(p=prefix))

    write_json("{}canary_readout.json".format(prefix.lower()), {
        "self_test": bool(args.self_test),
        "n_rows": int(len(df)),
        "lambda_fidelity": fidelity,
        "H2": h2,
        "H1": h1,
        "phi": phi,
        "gate": decision,
    })


if __name__ == "__main__":
    main()
