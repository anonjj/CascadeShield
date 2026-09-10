"""Generates the exploratory lambda canary run matrix across base,
matched-horizon, and null-fault control arms.

Outputs to data/canary_matrix.csv.
"""
import argparse
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LAMBDAS = [5, 20, 80, 320]           # req/s at the gateway's protected call site
WINDOW_TYPES = ["COUNT_BASED", "TIME_BASED"]
WINDOW_SIZES = [5, 10, 20]
REPLICATES = 5
THRESHOLD = 50                       # theta, fixed
WAIT_DURATION = 15                   # D_w seconds, fixed
TOPOLOGY = "LINEAR"
FAULT_TYPE = "LATENCY"

N_MIN = 5                            # minimumNumberOfCalls, pinned in runner.py
RESOLUTION_S = 1                     # Resilience4j takes whole seconds for a TIME window
MAX_COUNT_WINDOW = 1000              # documented slidingWindowSize ceiling (DATA_DICTIONARY)

NULL_ARM_LAMBDAS = [20, 80]
NULL_ARM_REPLICATES = 10

# Seeded so the run order is reproducible from the dataset alone. runner.py persists this
# as run_order_seed; anyone re-deriving the order from the artifact gets the same sequence.
RUN_ORDER_SEED = 20260811


def experiment_id(window_type, window_size, lam, fault_type=FAULT_TYPE, horizon=None):
    """Deterministic id. The matched arm appends the horizon it is matched at, because two
    different W can round to the same T and would otherwise collide onto one id."""
    wt = {"COUNT_BASED": "CNT", "TIME_BASED": "TIM"}[window_type]
    ft = {"LATENCY": "LAT", "NONE": "NUL"}[fault_type]
    tag = "" if horizon is None else "-MH{}".format(int(horizon))
    return "LIN-{}-{}-T{}-W{}-D{}-L{}{}".format(
        ft, wt, THRESHOLD, window_size, WAIT_DURATION, lam, tag)


def effective_horizon(window_type, window_size, lam):
    """H = W under COUNT, lambda * T under TIME. The quantity the two estimators must share
    before their detection latencies can be compared at all."""
    return float(window_size) if window_type == "COUNT_BASED" else float(lam) * window_size


def base_arm():
    for lam in LAMBDAS:
        for wt in WINDOW_TYPES:
            for w in WINDOW_SIZES:
                for rep in range(1, REPLICATES + 1):
                    yield {
                        "arm": "base",
                        "experiment_id": experiment_id(wt, w, lam),
                        "topology": TOPOLOGY,
                        "fault_type": FAULT_TYPE,
                        "window_type": wt,
                        "threshold": THRESHOLD,
                        "window_size": w,
                        "wait_duration": WAIT_DURATION,
                        "lambda_target": lam,
                        "replicate": rep,
                        "effective_horizon_nominal": effective_horizon(wt, w, lam),
                        "matched_to_count_w": "",
                        "feasible": 1,
                        "infeasible_reason": "",
                    }


def _matched_row(arm_direction, wt, size, lam, horizon, partner, feasible, reason, rep):
    return {
        "arm": "matched_horizon",
        "direction": arm_direction,
        "experiment_id": experiment_id(wt, size, lam, horizon=horizon),
        "topology": TOPOLOGY,
        "fault_type": FAULT_TYPE,
        "window_type": wt,
        "threshold": THRESHOLD,
        "window_size": size,
        "wait_duration": WAIT_DURATION,
        "lambda_target": lam,
        "replicate": rep,
        "effective_horizon_nominal": float(horizon),
        "matched_to_count_w": partner,
        "feasible": feasible,
        "infeasible_reason": reason,
    }


def matched_horizon_arm():
    """Pairs of settings that put COUNT and TIME on the same horizon H at a given lambda."""
    for lam in LAMBDAS:
        # Direction 1: hold the COUNT window, derive the TIME window.
        for w in WINDOW_SIZES:
            exact = w / lam
            t = int(round(exact / RESOLUTION_S) * RESOLUTION_S)
            feasible, reason = 1, ""
            if t < RESOLUTION_S:
                # At 320 req/s a 5-call horizon is 16 ms; the breaker cannot be configured
                # that finely, so this half of the plane is simply unreachable.
                feasible, reason = 0, ("T = W/lambda = {:.3f}s rounds below the {}s "
                                       "configuration resolution".format(exact, RESOLUTION_S))
            elif lam * t < N_MIN:
                # Fewer than minimumNumberOfCalls arrive inside the window, so the breaker
                # never evaluates and t_open is null by construction, not by measurement.
                feasible, reason = 0, ("only {:.1f} calls arrive in T = {}s at lambda = {}, "
                                       "below n_min = {}".format(lam * t, t, lam, N_MIN))
            for rep in range(1, REPLICATES + 1):
                yield _matched_row("T_from_W", "TIME_BASED", t, lam, w, w, feasible, reason, rep)

        # Direction 2: hold the TIME window, derive the COUNT window. This is the direction
        # that actually reaches high lambda, until W outruns the configurable ceiling.
        for t in WINDOW_SIZES:
            w = int(round(lam * t))
            feasible, reason = 1, ""
            if w > MAX_COUNT_WINDOW:
                feasible, reason = 0, ("W = lambda*T = {} calls exceeds the {}-call "
                                       "slidingWindowSize ceiling".format(w, MAX_COUNT_WINDOW))
            elif w < N_MIN:
                feasible, reason = 0, ("W = lambda*T = {} calls is below n_min = {}".format(w, N_MIN))
            for rep in range(1, REPLICATES + 1):
                yield _matched_row("W_from_T", "COUNT_BASED", w, lam, w, t, feasible, reason, rep)


def null_arm():
    """fault_type = NONE. Supplies phi, the false-trip rate."""
    for lam in NULL_ARM_LAMBDAS:
        for wt in WINDOW_TYPES:
            for w in WINDOW_SIZES:
                for rep in range(1, NULL_ARM_REPLICATES + 1):
                    yield {
                        "arm": "null_control",
                        "experiment_id": experiment_id(wt, w, lam, fault_type="NONE"),
                        "topology": TOPOLOGY,
                        "fault_type": "NONE",
                        "window_type": wt,
                        "threshold": THRESHOLD,
                        "window_size": w,
                        "wait_duration": WAIT_DURATION,
                        "lambda_target": lam,
                        "replicate": rep,
                        "effective_horizon_nominal": effective_horizon(wt, w, lam),
                        "matched_to_count_w": "",
                        "feasible": 1,
                        "infeasible_reason": "",
                    }


FIELDS = ["run_index", "run_order_seed", "arm", "direction", "experiment_id", "topology",
          "fault_type", "window_type", "threshold", "window_size", "wait_duration",
          "lambda_target", "replicate", "effective_horizon_nominal", "matched_to_count_w",
          "feasible", "infeasible_reason"]


ARMS = {"base": base_arm, "matched_horizon": matched_horizon_arm, "null_control": null_arm}

# What each arm buys, printed with the time estimate so the arm that gets cut when the day
# runs short is cut deliberately rather than by whatever the sweep happened to reach.
ARM_PURPOSE = {
    "base": "the Day-2 gate itself: trip-rate vs lambda (H2). Cutting this cancels the gate.",
    "matched_horizon": "H1 -- mean and variance of t_open at equal horizon H.",
    "null_control": "phi, the false-trip rate. Without it no configuration can be called safe.",
}

SECONDS_PER_RUN = 90   # includes breaker reset, warmup, fault window and recovery


def build(arms=None):
    arms = arms or list(ARMS)
    rows = []
    for name in arms:
        rows.extend(ARMS[name]())
    # Seeded shuffle: sequential execution of a long sweep on one host confounds treatment
    # with thermal and memory drift, so the order is randomised and the seed persisted.
    import random
    rng = random.Random(RUN_ORDER_SEED)
    runnable = [r for r in rows if r["feasible"]]
    rng.shuffle(runnable)
    for i, row in enumerate(runnable, start=1):
        row["run_index"] = i
        row["run_order_seed"] = RUN_ORDER_SEED
    for row in rows:
        row.setdefault("run_index", "")
        row.setdefault("run_order_seed", RUN_ORDER_SEED)
        row.setdefault("direction", "")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE_DIR / "data" / "canary_matrix.csv"))
    ap.add_argument("--arms", nargs="*", choices=list(ARMS), default=list(ARMS),
                    help="arms to emit; drop one only after reading what it buys, below")
    args = ap.parse_args()

    rows = build(args.arms)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r["arm"], r["experiment_id"], r["replicate"])):
            writer.writerow({k: row[k] for k in FIELDS})

    runnable = [r for r in rows if r["feasible"]]
    print("wrote {}\n".format(out))
    print("  {:<16} {:>5} {:>8} {:>7}   {}".format("ARM", "RUNS", "CONFIGS", "HOURS", "WHAT IT BUYS"))
    for arm in args.arms:
        a = [r for r in rows if r["arm"] == arm]
        ok = [r for r in a if r["feasible"]]
        print("  {:<16} {:>5} {:>8} {:>7.1f}   {}".format(
            arm, len(ok), len({r["experiment_id"] for r in ok}),
            len(ok) * SECONDS_PER_RUN / 3600, ARM_PURPOSE[arm]))
        if len(ok) != len(a):
            print("  {:<16} {:>5} infeasible cells retained with a stated reason".format(
                "", len(a) - len(ok)))
    print("  {:<16} {:>5} {:>8} {:>7.1f}".format(
        "TOTAL", len(runnable), len({r["experiment_id"] for r in runnable}),
        len(runnable) * SECONDS_PER_RUN / 3600))

    infeasible = {r["experiment_id"]: r["infeasible_reason"] for r in rows if not r["feasible"]}
    if infeasible:
        print("\ninfeasible cells (emitted with feasible=0, not silently dropped):")
        for eid, reason in sorted(infeasible.items()):
            print("  {:<38} {}".format(eid, reason))

    # The plan budgets "~3 h, start it before lunch". Say so plainly when the design does
    # not fit that, rather than letting the sweep discover it at 22:00.
    hours = len(runnable) * SECONDS_PER_RUN / 3600
    if hours > 4:
        print("\nNOTE: {:.1f} h does not fit the plan's single-afternoon budget. The gate needs "
              "only `base` ({:.1f} h); run `--arms base matched_horizon` before lunch and the "
              "null arm overnight.".format(
                  hours, sum(1 for r in runnable if r["arm"] == "base") * SECONDS_PER_RUN / 3600))
    print("\nrun_order_seed = {} (persist it to every dataset row)".format(RUN_ORDER_SEED))


if __name__ == "__main__":
    main()
