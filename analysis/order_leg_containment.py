"""
analysis/order_leg_containment.py  (D3 -- the user's own working label; NOT a
docs/paper/decision-log.md D-00X entry by itself, though it backs decision D15.)

blast_radius / real_blast_radius: fix, replace, or retire?

Both are quartized -- {0, 0.25, 0.5, 0.75, 1.0} -- because they binarize per-leg failure
against a threshold (the legacy metric implicitly, real_blast_radius explicitly via
tau_leg) before counting legs. On every archive collected so far (LINEAR topology only,
see below), exactly one leg -- order-service -- ever fires at all (hypotheses.md S5.3), so
the quartized metric has only TWO attainable values on this data: {0, 0.25}. tau_sweep.py
already showed the shipped tau=0.50 sits above the entire support (D-001).

The raw signal behind that binarization -- leg_failure_rates["order-service"], "order_leg"
below -- is continuous and has never been thresholded. This script checks whether it is
worth reporting on its own merits: does it have real resolution, does it move sensibly with
a swept parameter, does it separate window_type cleanly? If yes, binarizing it into a
4-point denominator and then defending a knife-edge tau (D-001's whole problem) is throwing
away information to manufacture a problem -- the quartized metric should be retired to
threats-to-validity (D15), not fixed.

Also reports topology counts, because the reason only one leg ever fires is structural, not
a calibration accident: a chain topology (LINEAR) exposes exactly one subject downstream of
the injection point. Cascade (>1 leg degraded) is only observable where a topology gives
failure more than one place to go -- FAN_OUT. `--topology fanout` is implemented in
experiments/runner.py but has never been swept: every row in every archive checked here is
LINEAR. That is the tension D15 states explicitly rather than leaving for a reviewer.

Usage:  python analysis/order_leg_containment.py --self-test (fixture only, no I/O)
        python analysis/order_leg_containment.py [dataset]    (default: current)
Output: analysis/out/order_leg_containment.json
"""

import sys

import pandas as pd

from common import load, bootstrap_ci_grouped, cliffs_delta, write_json


def order_leg_stats(df):
    """Everything D15 cites, in one place, from real data -- no number typed by hand."""
    df = df.copy()
    df["order_leg"] = df["legs"].apply(lambda d: d.get("order-service"))
    df = df.dropna(subset=["order_leg"])

    by_cell = (df.groupby(["window_type", "window_size"])["order_leg"]
                 .agg(["mean", "count"]).reset_index()
                 .sort_values(["window_type", "window_size"]))

    ci_by_wt = {
        wt: bootstrap_ci_grouped(g, "order_leg", group_col="experiment_id")
        for wt, g in df.groupby("window_type")
    }

    count_vals = df.loc[df["window_type"] == "COUNT_BASED", "order_leg"]
    time_vals = df.loc[df["window_type"] == "TIME_BASED", "order_leg"]
    delta = cliffs_delta(count_vals, time_vals)

    return {
        "n_rows": int(len(df)),
        "n_distinct_order_leg": int(df["order_leg"].nunique()),
        "by_cell": by_cell.to_dict("records"),
        "ci_by_window_type": ci_by_wt,
        "count_time_separation": {
            "count_max": float(count_vals.max()) if len(count_vals) else None,
            "time_min": float(time_vals.min()) if len(time_vals) else None,
            "cliffs_delta": delta,
        },
    }


def main(dataset="current"):
    df = load(dataset)
    stats = order_leg_stats(df)

    payload = {
        "dataset": dataset,
        "topology_counts": df["topology"].value_counts().to_dict(),
        **stats,
    }
    write_json("order_leg_containment.json", payload)

    print("dataset: {} ({} rows, {} with an order-service leg observed)".format(
        dataset, len(df), stats["n_rows"]))
    print("topology counts: {}".format(payload["topology_counts"]))
    print("n distinct order_leg values: {}".format(stats["n_distinct_order_leg"]))
    print("\nwindow_type   window_size   n    mean order_leg")
    for r in stats["by_cell"]:
        print("{:<13} {:<13} {:<4} {:.4f}".format(
            r["window_type"], r["window_size"], r["count"], r["mean"]))
    sep = stats["count_time_separation"]
    print("\nCOUNT_BASED max = {:.4f}, TIME_BASED min = {:.4f}, gap = {}".format(
        sep["count_max"], sep["time_min"],
        "no overlap" if sep["count_max"] < sep["time_min"] else "OVERLAPS"))
    print("Cliff's delta (COUNT vs TIME): {}".format(sep["cliffs_delta"]))
    return payload


# --------------------------------------------------------------------------- self-test

def self_test():
    """Hand-built fixture: does the pipeline get nunique/monotonicity/separation right,
    and does it skip rows with no order-service leg observed instead of crashing on them?"""
    rows = [
        # COUNT_BASED, window_size grows -> order_leg should grow too (monotonic check).
        {"window_type": "COUNT_BASED", "window_size": 5, "experiment_id": "C5",
         "legs": {"order-service": 0.20}},
        {"window_type": "COUNT_BASED", "window_size": 5, "experiment_id": "C5",
         "legs": {"order-service": 0.22}},
        {"window_type": "COUNT_BASED", "window_size": 10, "experiment_id": "C10",
         "legs": {"order-service": 0.30}},
        {"window_type": "COUNT_BASED", "window_size": 20, "experiment_id": "C20",
         "legs": {"order-service": 0.40}},
        # TIME_BASED, tightly banded above every COUNT_BASED value -> clean separation.
        {"window_type": "TIME_BASED", "window_size": 5, "experiment_id": "T5",
         "legs": {"order-service": 0.46}},
        {"window_type": "TIME_BASED", "window_size": 10, "experiment_id": "T10",
         "legs": {"order-service": 0.47}},
        # No order-service leg observed this run (e.g. never exercised) -> must be
        # dropped, not treated as a 0.0.
        {"window_type": "TIME_BASED", "window_size": 20, "experiment_id": "T20",
         "legs": {"inventory-service": 0.10}},
    ]
    df = pd.DataFrame(rows)
    stats = order_leg_stats(df)

    assert stats["n_rows"] == 6, "the no-order-leg row must be dropped, got n_rows={}".format(
        stats["n_rows"])
    assert stats["n_distinct_order_leg"] == 6

    means = {(r["window_type"], r["window_size"]): r["mean"] for r in stats["by_cell"]}
    assert means[("COUNT_BASED", 5)] < means[("COUNT_BASED", 10)] < means[("COUNT_BASED", 20)], \
        "COUNT_BASED means should be monotonic in window_size"

    sep = stats["count_time_separation"]
    assert sep["count_max"] < sep["time_min"], "fixture is constructed to not overlap"
    assert sep["cliffs_delta"]["delta"] == -1.0, "fixture is a fully-separated case"

    print("self-test: 4/4 checks OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        arg = sys.argv[1] if len(sys.argv) > 1 else "current"
        main(arg)
