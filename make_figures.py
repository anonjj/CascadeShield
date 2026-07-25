"""
CascadeShield — paper-ready figures + summary stats from master_dataset.csv

Outputs (into ./figures/):
  fig1_blast_heatmap_median_mean.{png,pdf}  — headline: fault x window, median AND mean side by side
  fig2_trip_rate_heatmap.{png,pdf}          — fraction of runs where the breaker opened (blast > 0)
  fig3_count_blast_distribution.{png,pdf}    — COUNT_BASED blast-radius distribution by fault (shows the bimodality)
  summary_stats.csv                          — per fault x window: n, median, mean, std, min, max, trip_rate

Run from the repo root:  python make_figures.py
Requires: pandas, matplotlib  (pip install pandas matplotlib)
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt

DATA = "data/master_dataset.csv"
OUT = "figures"
os.makedirs(OUT, exist_ok=True)

# ---- IEEE-ish styling -------------------------------------------------------
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "savefig.dpi": 300,
    "figure.dpi": 300,
    "savefig.bbox": "tight",
    "axes.linewidth": 0.6,
})

FAULT_ORDER = ["LATENCY", "CRASH", "THROTTLE"]
WIN_ORDER = ["COUNT_BASED", "TIME_BASED"]
WIN_LABEL = {"COUNT_BASED": "COUNT", "TIME_BASED": "TIME"}

# ---- load & sanity ----------------------------------------------------------
df = pd.read_csv(DATA)
df["blast_radius"] = pd.to_numeric(df["blast_radius"], errors="coerce")
df = df.dropna(subset=["blast_radius"])
present_faults = [f for f in FAULT_ORDER if f in set(df["fault_type"])]
print(f"Loaded {len(df)} rows | faults present: {present_faults}")


def grid(series_reducer):
    """Return a (fault x window) matrix applying reducer to blast_radius groups."""
    m = np.full((len(present_faults), len(WIN_ORDER)), np.nan)
    for i, f in enumerate(present_faults):
        for j, w in enumerate(WIN_ORDER):
            sub = df[(df.fault_type == f) & (df.window_type == w)]["blast_radius"]
            if len(sub):
                m[i, j] = series_reducer(sub)
    return m


def draw_heatmap(ax, mat, title, vmax, cbar_label=None, fmt="{:.1f}"):
    im = ax.imshow(mat, cmap="YlOrRd", vmin=0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(WIN_ORDER)))
    ax.set_xticklabels([WIN_LABEL[w] for w in WIN_ORDER])
    ax.set_yticks(range(len(present_faults)))
    ax.set_yticklabels(present_faults)
    ax.set_title(title)
    ax.set_xlabel("Sliding-window type")
    # annotate
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if np.isnan(v):
                continue
            # dark text on light cells, white on dark
            frac = v / vmax if vmax else 0
            ax.text(j, i, fmt.format(v), ha="center", va="center",
                    color="white" if frac > 0.55 else "black", fontsize=9)
    return im


# ---- FIG 1: median + mean side by side -------------------------------------
med = grid(np.median)
mean = grid(np.mean)
vmax = np.nanmax([np.nanmax(med), np.nanmax(mean)])
fig, axes = plt.subplots(1, 2, figsize=(6.5, 2.8))
draw_heatmap(axes[0], med, "Median blast radius", vmax)
axes[0].set_ylabel("Fault type")
im = draw_heatmap(axes[1], mean, "Mean blast radius", vmax)
axes[1].set_yticklabels([])
cbar = fig.colorbar(im, ax=axes, fraction=0.046, pad=0.04)
cbar.set_label("Blast radius (% of mesh)")
for ext in ("png", "pdf"):
    fig.savefig(f"{OUT}/fig1_blast_heatmap_median_mean.{ext}")
plt.close(fig)

# ---- FIG 2: trip rate (fraction blast > 0) ---------------------------------
trip = grid(lambda s: (s > 0).mean() * 100.0)
fig, ax = plt.subplots(figsize=(3.4, 2.8))
im = draw_heatmap(ax, trip, "Breaker trip rate", 100.0, fmt="{:.0f}%")
ax.set_ylabel("Fault type")
cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
cbar.set_label("Runs with CB open (%)")
for ext in ("png", "pdf"):
    fig.savefig(f"{OUT}/fig2_trip_rate_heatmap.{ext}")
plt.close(fig)

# ---- FIG 3: COUNT_BASED blast distribution by fault ------------------------
fig, ax = plt.subplots(figsize=(3.4, 2.8))
data_by_fault = [df[(df.fault_type == f) & (df.window_type == "COUNT_BASED")]["blast_radius"].values
                 for f in present_faults]
parts = ax.boxplot(data_by_fault, labels=present_faults, showmeans=True, widths=0.5,
                   medianprops=dict(color="firebrick", linewidth=1.4),
                   meanprops=dict(marker="D", markerfacecolor="black", markersize=4))
# jittered points for visibility of the discrete structure
for i, vals in enumerate(data_by_fault, start=1):
    x = np.random.normal(i, 0.05, size=len(vals))
    ax.scatter(x, vals, s=6, alpha=0.35, color="steelblue", zorder=3)
ax.set_ylabel("Blast radius (% of mesh)")
ax.set_xlabel("Fault type (COUNT_BASED only)")
ax.set_title("COUNT_BASED containment by fault")
for ext in ("png", "pdf"):
    fig.savefig(f"{OUT}/fig3_count_blast_distribution.{ext}")
plt.close(fig)

# ---- summary stats CSV ------------------------------------------------------
recs = []
for f in present_faults:
    for w in WIN_ORDER:
        s = df[(df.fault_type == f) & (df.window_type == w)]["blast_radius"]
        if not len(s):
            continue
        recs.append({
            "fault_type": f, "window_type": w, "n": len(s),
            "median": round(s.median(), 4), "mean": round(s.mean(), 4),
            "std": round(s.std(ddof=1), 4) if len(s) > 1 else 0.0,
            "min": round(s.min(), 4), "max": round(s.max(), 4),
            "trip_rate_pct": round((s > 0).mean() * 100, 2),
        })
summary = pd.DataFrame(recs)
summary.to_csv(f"{OUT}/summary_stats.csv", index=False)

print("\n=== summary_stats.csv ===")
print(summary.to_string(index=False))
print(f"\nWrote figures + summary_stats.csv to ./{OUT}/")
