"""Day 1 (Soham) -- recompute real_blast_radius as a function of the per-leg threshold.

`real_blast_radius` reads 0.0 in all 80 rows of the current dataset. That is not a property
of the system; it is a calibration failure. tau_leg was pinned at 0.50 back when the legs
were bimodal (a leg either sat near 0 or near 1), and after the rebuild the only leg that
fires at all -- order-service -- tops out at 0.4867. The threshold now sits just above the
entire support of the data, so the metric is constant by construction.

`leg_failure_rates` was persisted precisely so this could be fixed without re-running a
single experiment. This script recomputes B_real over tau in [0.05, 0.95] and reports the
metric AS A FUNCTION OF TAU, which is what belongs in the paper: a threshold that has to be
chosen is a researcher degree of freedom, and showing the whole curve converts a
calibration failure into a sensitivity analysis. It also feeds H4 directly -- if config
rankings under different tau disagree, competing containment definitions are not
interchangeable.

Usage:  python analysis/tau_sweep.py
Output: analysis/out/tau_sweep.json, analysis/out/tau_sweep.csv, figures/fig7_tau_sweep.png
"""

import numpy as np
import pandas as pd
from scipy import stats

from common import FIG_DIR, OUT_DIR, load, real_blast_radius_from_rates, write_json

TAUS = np.round(np.arange(0.05, 0.9501, 0.05), 2)
RUNNER_TAU = 0.50   # REAL_BLAST_LEG_ERROR_THRESHOLD in experiments/runner.py


def sweep(df):
    """B_real at every tau, per row. Returns a long frame: one row per (run, tau)."""
    records = []
    for i, row in df.iterrows():
        legs = row["legs"]
        for tau in TAUS:
            records.append({
                "row": i,
                "experiment_id": row["experiment_id"],
                "window_type": row["window_type"],
                "replicate": row["replicate"],
                "tau": float(tau),
                # None (not 0.0) when no leg was observable -- a measurement gap must never
                # be laundered into a containment reading of zero.
                "real_blast_radius": real_blast_radius_from_rates(legs, tau),
            })
    return pd.DataFrame(records)


def _kendall(a, b):
    """Kendall's tau-b, or an explicit reason it is undefined. Never a bare NaN."""
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 3:
        return {"kendall_tau": None, "p": None, "n_configs": int(len(pair)),
                "reason": "fewer than 3 configurations in common"}
    if pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return {"kendall_tau": None, "p": None, "n_configs": int(len(pair)),
                "reason": "constant ranking vector at one of the two thresholds"}
    k = stats.kendalltau(pair.iloc[:, 0], pair.iloc[:, 1])
    return {"kendall_tau": float(k.statistic), "p": float(k.pvalue),
            "n_configs": int(len(pair)), "reason": None}


def rank_agreement(long_df):
    """H4: do competing containment definitions rank configurations differently?

    Two views, because the obvious one is currently uninformative:

      vs_runner_tau -- every threshold against the pinned 0.50. This is the comparison the
        sprint plan asks for, and it is undefined at every tau, because the reference
        itself ranks all 26 configurations identically at zero. Reported rather than
        hidden: "the shipped metric cannot rank anything" is the finding.

      pairwise -- all pairs of thresholds whose ranking is non-degenerate. This is where H4
        can actually be tested: tau < 1 between two live thresholds means the threshold,
        not the system, decides which configuration looks safer.
    """
    per_config = (long_df.dropna(subset=["real_blast_radius"])
                  .groupby(["tau", "experiment_id"])["real_blast_radius"].mean().unstack("tau"))
    vs_runner = []
    if RUNNER_TAU in per_config.columns:
        for tau in per_config.columns:
            entry = {"tau": float(tau)}
            entry.update(_kendall(per_config[RUNNER_TAU], per_config[tau]))
            vs_runner.append(entry)

    live = [t for t in per_config.columns if per_config[t].nunique() >= 2]
    pairwise = []
    for i, t1 in enumerate(live):
        for t2 in live[i + 1:]:
            entry = {"tau_a": float(t1), "tau_b": float(t2)}
            entry.update(_kendall(per_config[t1], per_config[t2]))
            pairwise.append(entry)

    taus_with_agreement = [p for p in pairwise if p["kendall_tau"] is not None]
    return {
        "vs_runner_tau": vs_runner,
        "non_degenerate_taus": [float(t) for t in live],
        "pairwise": pairwise,
        "min_pairwise_kendall_tau": (min(p["kendall_tau"] for p in taus_with_agreement)
                                     if taus_with_agreement else None),
        "n_pairs_below_1": sum(1 for p in taus_with_agreement if p["kendall_tau"] < 1.0),
        "n_pairs_compared": len(taus_with_agreement),
    }


def make_figure(summary, leg_support, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(6.0, 5.6), sharex=True,
                                  gridspec_kw={"height_ratios": [2, 1]})

    ax.plot(summary["tau"], summary["mean_real_blast_radius"], marker="o", ms=4,
            color="#1f3b73", lw=1.6, label=r"mean $B_{\mathrm{real}}$")
    ax.fill_between(summary["tau"], summary["ci_lo"], summary["ci_hi"],
                    color="#1f3b73", alpha=0.18, lw=0, label="95% CI (cluster bootstrap)")
    ax.axvline(RUNNER_TAU, color="#b3261e", ls="--", lw=1.2)
    # Label rides the line itself, rotated, so it cannot collide with the legend.
    ax.text(RUNNER_TAU + 0.012, ax.get_ylim()[1] * 0.55, r"pinned $\tau_{\mathrm{leg}}=0.50$",
            color="#b3261e", fontsize=8, rotation=90, va="center")
    ax.set_ylabel(r"$B_{\mathrm{real}}$ (fraction of legs)")
    ax.legend(frameon=False, fontsize=8, loc="upper right", bbox_to_anchor=(0.98, 0.98))
    ax.set_title(r"Containment as a function of the per-leg threshold $\tau_{\mathrm{leg}}$",
                 fontsize=10)

    # The rug underneath is the point of the whole figure: every observed leg failure rate
    # lies to the LEFT of the pinned threshold, so the metric could only ever read zero.
    ax2.eventplot([leg_support], colors="#444444", lineoffsets=0.5, linelengths=0.8, lw=0.7)
    ax2.axvline(RUNNER_TAU, color="#b3261e", ls="--", lw=1.2)
    ax2.set_yticks([])
    ax2.set_xlabel(r"$\tau_{\mathrm{leg}}$")
    ax2.set_ylabel("observed\nleg rates", fontsize=8)
    ax2.set_xlim(0, 1)

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    fig.savefig(str(path).replace(".png", ".pdf"))  # vector copy for the IEEE submission
    plt.close(fig)


def main(dataset="current"):
    from common import bootstrap_ci_grouped

    df = load(dataset)
    long_df = sweep(df)

    rows = []
    for tau, group in long_df.groupby("tau"):
        observed = group.dropna(subset=["real_blast_radius"])
        ci = bootstrap_ci_grouped(observed, "real_blast_radius")
        rows.append({
            "tau": float(tau),
            "n_runs_with_observable_legs": int(len(observed)),
            "n_runs_missing_legs": int(group["real_blast_radius"].isna().sum()),
            "mean_real_blast_radius": ci["point"],
            "ci_lo": ci["lo"],
            "ci_hi": ci["hi"],
            "n_distinct_values": int(observed["real_blast_radius"].nunique()),
            "share_nonzero": float((observed["real_blast_radius"] > 0).mean()) if len(observed) else 0.0,
        })
    summary = pd.DataFrame(rows)

    all_rates = sorted(r for legs in df["legs"] for r in legs.values())
    firing = [r for r in all_rates if r > 0]
    support = {
        "n_leg_observations": len(all_rates),
        "n_nonzero": len(firing),
        "max_leg_failure_rate": float(max(all_rates)) if all_rates else None,
        "max_nonzero_leg_rate": float(max(firing)) if firing else None,
        "services_that_ever_fire": sorted({svc for legs in df["legs"]
                                           for svc, r in legs.items() if r > 0}),
    }
    # The threshold above which the metric is dead: no leg anywhere in the dataset exceeds
    # it, so B_real is identically zero and carries no information.
    ceiling = support["max_leg_failure_rate"]
    informative = summary[summary["share_nonzero"] > 0]["tau"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_DIR / "tau_sweep.csv", index=False)
    fig_path = FIG_DIR / "fig7_tau_sweep.png"
    make_figure(summary, all_rates, fig_path)

    payload = {
        "dataset": dataset,
        "n_runs": int(len(df)),
        "n_configs": int(df["experiment_id"].nunique()),
        "runner_tau": RUNNER_TAU,
        "leg_support": support,
        "informative_tau_range": {
            "lo": float(informative.min()) if len(informative) else None,
            "hi": float(informative.max()) if len(informative) else None,
            "comment": ("B_real is identically 0 for every tau above the largest observed "
                        "leg failure rate ({}), which is why the pinned 0.50 produced a "
                        "constant column.".format(ceiling)),
        },
        "curve": summary.to_dict("records"),
        "h4_rank_agreement": rank_agreement(long_df),
        "figure": str(fig_path.relative_to(fig_path.parents[1])),
    }
    write_json("tau_sweep.json", payload)

    print("\nleg support: {} observations, {} non-zero, max = {:.4f}".format(
        support["n_leg_observations"], support["n_nonzero"], ceiling))
    print("services that ever fire: {}".format(", ".join(support["services_that_ever_fire"]) or "none"))
    print("\ntau  mean B_real   95% CI            share>0")
    for r in payload["curve"]:
        print("{:.2f}  {:>9.4f}   [{:.4f}, {:.4f}]   {:.1%}".format(
            r["tau"], r["mean_real_blast_radius"], r["ci_lo"], r["ci_hi"], r["share_nonzero"]))

    h4 = payload["h4_rank_agreement"]
    print("\nH4 rank agreement: {} of {} threshold pairs rank configurations differently "
          "(min Kendall tau = {})".format(
              h4["n_pairs_below_1"], h4["n_pairs_compared"],
              "n/a" if h4["min_pairwise_kendall_tau"] is None
              else "{:.3f}".format(h4["min_pairwise_kendall_tau"])))
    print("     every comparison against the pinned tau=0.50 is undefined: that threshold "
          "ranks all {} configurations identically at zero.".format(payload["n_configs"]))
    return payload


if __name__ == "__main__":
    main()
