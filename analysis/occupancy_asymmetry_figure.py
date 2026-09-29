"""H2b figure (D18): the occupancy ratio's asymmetry between window types.

TIME_BASED shows a clean crossover at rho=1 -- every inert run at rho <= 0.4996, every
tripping run at rho >= 0.9967, nothing between. COUNT_BASED shows no such structure: every
run tripped, including at rho = 0.025 (2.5% of its required occupancy). The figure's job is
to make a reader see that gap and its absence without reading the caption -- see D18,
docs/paper/decision-log.md.

time_to_open is plotted on y rather than the binary trip outcome: 162 points on a binary axis
overplots badly, and time_to_open already carries the trip/no-trip distinction (null means
inert) plus the timing information a bare binary axis would discard. Inert runs are plotted
at a fixed sentinel level below an axis break rather than dropped -- they are an outcome, not
a missing value (the same point Sec IV-E makes about right-censored timing DVs generally).

Usage:  python analysis/occupancy_asymmetry_figure.py
Output: analysis/out/occupancy_asymmetry.json, figures/fig8_occupancy_asymmetry.{png,pdf}
"""

from common import FIG_DIR, OUT_DIR, load, write_json

WINDOW_STYLE = {
    "TIME_BASED": {"color": "#1f3b73", "marker": "o", "label": "TIME_BASED"},
    "COUNT_BASED": {"color": "#d97706", "marker": "^", "label": "COUNT_BASED"},
}
INERT_SENTINEL = -3.0   # below the real time_to_open floor (min observed: 3.16s)
BREAK_Y = -1.0          # where the axis-break marks sit, between the sentinel row and y=0


def summarize(df):
    """Per-window-type occupancy_ratio bounds for inert vs tripped runs -- the numbers the
    figure visualizes, reported so nothing in the plot is unverifiable from the JSON."""
    out = {}
    for wt, g in df.groupby("window_type"):
        inert = g[g["inert"]]
        tripped = g[~g["inert"]]
        out[wt] = {
            "n": int(len(g)),
            "n_inert": int(len(inert)),
            "n_tripped": int(len(tripped)),
            "inert_occupancy_ratio_range": (
                [float(inert["occupancy_ratio"].min()), float(inert["occupancy_ratio"].max())]
                if len(inert) else None
            ),
            "tripped_occupancy_ratio_range": (
                [float(tripped["occupancy_ratio"].min()), float(tripped["occupancy_ratio"].max())]
                if len(tripped) else None
            ),
        }
    return out


def make_figure(df, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.6))

    for wt, style in WINDOW_STYLE.items():
        g = df[df["window_type"] == wt]
        tripped = g[~g["inert"]]
        inert = g[g["inert"]]
        ax.scatter(tripped["occupancy_ratio"], tripped["time_to_open"],
                   color=style["color"], marker=style["marker"], s=26, alpha=0.75,
                   edgecolors="none", label=style["label"])
        if len(inert):
            ax.scatter(inert["occupancy_ratio"], [INERT_SENTINEL] * len(inert),
                       color=style["color"], marker=style["marker"], s=26, alpha=0.75,
                       edgecolors="none")

    ax.set_xscale("log")
    ax.axvline(1.0, color="#666666", ls="--", lw=1.2, zorder=0)
    ax.text(1.15, 0.97, r"$\rho=1$", transform=ax.get_xaxis_transform(),
            color="#666666", fontsize=8, ha="left", va="top")

    # Axis break between the real time_to_open range and the inert sentinel row: a dashed
    # divider plus offset "//" tick marks, the standard broken-axis idiom.
    ax.axhline(BREAK_Y, color="#999999", ls=":", lw=0.9, zorder=0)
    for x_frac in (0.0, 1.0):
        ax.plot([x_frac], [BREAK_Y], transform=ax.get_yaxis_transform(), clip_on=False,
                marker=[(-1, -0.6), (1, 0.6)], markersize=9, color="#999999", mew=1.2)

    yticks = list(range(0, 30, 5))
    ax.set_yticks([INERT_SENTINEL] + yticks)
    ax.set_yticklabels(["inert\n(never opened)"] + [str(t) for t in yticks])
    ax.set_ylim(INERT_SENTINEL - 1.5, None)

    ax.set_xlabel(r"Occupancy ratio $\rho = H_{\mathrm{eff}} / n_{\min}$"
                  "\n(effective horizon over minimum-calls, log scale)")
    ax.set_ylabel(r"time to open (s)")
    ax.set_title("Occupancy ratio predicts inertness for TIME_BASED, not COUNT_BASED",
                 fontsize=9.5)
    ax.legend(frameon=False, fontsize=8, loc="lower right")

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    fig.savefig(str(path).replace(".png", ".pdf"))  # vector copy for the IEEE submission
    plt.close(fig)


def main(dataset="d7_occupancy_ratio"):
    df = load(dataset)

    summary = summarize(df)
    fig_path = FIG_DIR / "fig8_occupancy_asymmetry.png"
    make_figure(df, fig_path)

    payload = {
        "dataset": dataset,
        "n_runs": int(len(df)),
        "occupancy_ratio_range": [float(df["occupancy_ratio"].min()),
                                   float(df["occupancy_ratio"].max())],
        "by_window_type": summary,
        "figure": str(fig_path.relative_to(fig_path.parents[1])),
    }
    write_json("occupancy_asymmetry.json", payload)

    for wt, s in summary.items():
        print("{}: n={} (inert={}, tripped={})".format(wt, s["n"], s["n_inert"], s["n_tripped"]))
        print("  inert rho range:    {}".format(s["inert_occupancy_ratio_range"]))
        print("  tripped rho range:  {}".format(s["tripped_occupancy_ratio_range"]))
    return payload


if __name__ == "__main__":
    main()
