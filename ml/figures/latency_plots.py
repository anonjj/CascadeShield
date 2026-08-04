#!/usr/bin/env python3
"""latency_plots.py -- CascadeShield publication-ready latency figures.

Generates two IEEE-column-width figures (300 DPI) into ml/figures/:

  1. detection_heatmap.png -- mean time_to_open by window_type x window_size
  2. recovery_barplot.png  -- mean time_to_recover by wait_duration (+/- std)

Values are recomputed from the raw sweep CSV when available (so the figures can be
regenerated after a re-sweep); otherwise the literals below -- taken from the
162-run LATENCY sweep (master_dataset_v2_latency_5svc.csv) -- are used as a fallback.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless-safe: render to file, never require a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_CANDIDATES = [
    HERE / ".." / ".." / "data" / "master_dataset_v2_latency_5svc.csv",
    HERE / ".." / ".." / "data" / "master_dataset.csv",
]

WINDOW_TYPES = ["COUNT_BASED", "TIME_BASED"]   # x-axis order
WINDOW_SIZES = [5, 10, 20]                     # y-axis order
WAIT_DURATIONS = [5, 15, 30]

# ---- Fallback literals (from the 162-run LATENCY sweep) -----------------------
# detection[window_size][window_type] = mean time_to_open (s)
DETECTION_FALLBACK = {
    5:  {"COUNT_BASED": 3.52, "TIME_BASED": 5.33},
    10: {"COUNT_BASED": 4.58, "TIME_BASED": 9.16},
    20: {"COUNT_BASED": 7.88, "TIME_BASED": 13.80},
}
# recovery[wait_duration] = (mean, std) of time_to_recover (s)
RECOVERY_FALLBACK = {5: (16.95, 10.83), 15: (27.85, 12.77), 30: (49.31, 16.94)}
RECOVERY_OVERALL_MEAN_FALLBACK = 31.4
RECOVER_OUTLIER_S = 1000.0  # harness-hang guard, matches train_latency_models.py

# IEEE single-column width ~3.5in
FIGSIZE = (3.5, 2.9)
DPI = 300


def find_dataset():
    for p in DATA_CANDIDATES:
        if p.exists():
            return p.resolve()
    return None


def compute_from_data(path):
    """Return (detection_matrix, recovery_stats, overall_recover_mean) from the CSV,
    or None if the expected columns aren't present."""
    df = pd.read_csv(path)
    needed = {"window_type", "window_size", "wait_duration", "time_to_open", "time_to_recover"}
    if not needed.issubset(df.columns):
        return None
    for c in ["window_size", "wait_duration", "time_to_open", "time_to_recover"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Detection: mean time_to_open per (window_size, window_type)
    det = {}
    do = df[df["time_to_open"].notna()]
    for ws in WINDOW_SIZES:
        det[ws] = {}
        for wt in WINDOW_TYPES:
            sub = do[(do["window_size"] == ws) & (do["window_type"] == wt)]["time_to_open"]
            det[ws][wt] = float(sub.mean()) if len(sub) else np.nan

    # Recovery: mean/std time_to_recover per wait_duration (outliers excluded)
    dr = df[(df["time_to_recover"].notna()) & (df["time_to_recover"] <= RECOVER_OUTLIER_S)]
    rec = {}
    for wd in WAIT_DURATIONS:
        sub = dr[dr["wait_duration"] == wd]["time_to_recover"]
        rec[wd] = (float(sub.mean()), float(sub.std())) if len(sub) else (np.nan, np.nan)
    # Reference line = mean of the plotted bar heights (per-wait_duration means), which is
    # the "overall mean" consistent with the chart (~31.4s), not the row-level mean.
    grp_means = [rec[wd][0] for wd in WAIT_DURATIONS if not np.isnan(rec[wd][0])]
    overall = float(np.mean(grp_means)) if grp_means else RECOVERY_OVERALL_MEAN_FALLBACK
    return det, rec, overall


def make_detection_heatmap(detection, outpath):
    # matrix rows = window sizes (top->bottom), cols = window types
    matrix = np.array([[detection[ws][wt] for wt in WINDOW_TYPES] for ws in WINDOW_SIZES])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    im = ax.imshow(matrix, cmap="viridis", aspect="auto")

    ax.set_xticks(range(len(WINDOW_TYPES)))
    ax.set_xticklabels(WINDOW_TYPES)
    ax.set_yticks(range(len(WINDOW_SIZES)))
    ax.set_yticklabels(WINDOW_SIZES)
    ax.set_xlabel("Window Type")
    ax.set_ylabel("Window Size")
    ax.set_title("Mean Detection Latency (s) by\nWindow Type and Window Size", fontsize=9)

    # Annotate each cell; pick text colour for contrast against the colormap.
    vmax = np.nanmax(matrix)
    for i in range(len(WINDOW_SIZES)):
        for j in range(len(WINDOW_TYPES)):
            val = matrix[i, j]
            if np.isnan(val):
                continue
            colour = "white" if val < 0.6 * vmax else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    color=colour, fontsize=9, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Mean time_to_open (s)", fontsize=8)
    fig.tight_layout()
    fig.savefig(outpath, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {outpath.relative_to(HERE.parent.parent)}")


def make_recovery_barplot(recovery, overall_mean, outpath):
    means = [recovery[wd][0] for wd in WAIT_DURATIONS]
    stds = [recovery[wd][1] for wd in WAIT_DURATIONS]
    x = np.arange(len(WAIT_DURATIONS))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(x, means, yerr=stds, capsize=5, color="#4C72B0",
           edgecolor="black", linewidth=0.6, error_kw={"elinewidth": 1.0})

    ax.axhline(overall_mean, linestyle="--", color="firebrick", linewidth=1.2,
               label=f"Overall mean ({overall_mean:.1f}s)")

    ax.set_xticks(x)
    ax.set_xticklabels(WAIT_DURATIONS)
    ax.set_xlabel("Wait Duration in Open State (s)")
    ax.set_ylabel("Mean Recovery Latency (s)")
    ax.set_title("Recovery Latency Increases\nMonotonically with Wait Duration", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")

    # value labels above each bar
    for xi, m in zip(x, means):
        ax.text(xi, m, f"{m:.1f}", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(outpath, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {outpath.relative_to(HERE.parent.parent)}")


def main():
    path = find_dataset()
    if path is not None:
        computed = compute_from_data(path)
        if computed is not None:
            detection, recovery, overall = computed
            print(f"Data source: {path} (recomputed from raw)")
        else:
            detection, recovery, overall = (DETECTION_FALLBACK, RECOVERY_FALLBACK,
                                            RECOVERY_OVERALL_MEAN_FALLBACK)
            print(f"Data source: {path} found but missing expected columns -- using fallback literals")
    else:
        detection, recovery, overall = (DETECTION_FALLBACK, RECOVERY_FALLBACK,
                                        RECOVERY_OVERALL_MEAN_FALLBACK)
        print("Data source: no CSV found -- using fallback literals from the 162-run sweep")

    make_detection_heatmap(detection, HERE / "detection_heatmap.png")
    make_recovery_barplot(recovery, overall, HERE / "recovery_barplot.png")
    print("Done.")


if __name__ == "__main__":
    main()
