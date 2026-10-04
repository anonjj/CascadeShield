"""Paper Fig. 2 (IEEE single column): occupancy-ratio boundary, from data/occupancy_dataset.csv.

Outcome (opened / inert) against rho on a log axis; vertical jitter only, to separate
overplotted points. Markers differ in shape and fill so the two window types read in
greyscale. Plots committed data as-is; computes nothing new.

Usage:  python analysis/fig_paper_rho.py
Output: figures/fig2_rho_boundary.{pdf,png}
"""
import numpy as np

from common import FIG_DIR, load

STYLE = {
    "TIME_BASED": {"marker": "o", "face": "black", "edge": "black", "label": "TIME_BASED"},
    "COUNT_BASED": {"marker": "^", "face": "white", "edge": "black", "label": "COUNT_BASED"},
}
JITTER = 0.09
SEED = 0


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 8,
                         "ytick.labelsize": 8, "legend.fontsize": 8,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "font.family": "serif", "mathtext.fontset": "stix"})
    df = load("d7_occupancy_ratio")
    rng = np.random.default_rng(SEED)

    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    counts = {}
    for wt, s in STYLE.items():
        g = df[df["window_type"] == wt]
        y = np.where(g["inert"], 0.0, 1.0) + rng.uniform(-JITTER, JITTER, len(g))
        ax.scatter(g["occupancy_ratio"], y, marker=s["marker"], s=16, linewidths=0.7,
                   facecolors=s["face"], edgecolors=s["edge"], alpha=0.8, label=s["label"])
        counts[wt] = int(len(g))

    ax.set_xscale("log")
    ax.axvline(1.0, color="black", ls="--", lw=0.9, zorder=0)
    ax.text(1.08, 0.38, r"$\rho=1$", transform=ax.get_xaxis_transform(), fontsize=8,
            ha="left", va="center")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["inert", "opened"])
    ax.set_ylim(-0.4, 1.4)
    ax.set_xlabel(r"occupancy ratio $\rho$")
    ax.legend(frameon=False, loc="lower right", handletextpad=0.2, borderaxespad=0.3)
    fig.tight_layout(pad=0.3)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "fig2_rho_boundary.pdf")
    fig.savefig(FIG_DIR / "fig2_rho_boundary.png", dpi=300)
    plt.close(fig)
    print("points plotted:", counts)


if __name__ == "__main__":
    main()
