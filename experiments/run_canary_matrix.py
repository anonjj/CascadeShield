#!/usr/bin/env python3
"""Executes experiments/canary_matrix.py's design (data/canary_matrix.csv) against a live
Docker/Toxiproxy mesh, driving runner.py's existing run_experiment_run()/log_results()
machinery per row.

This is the actual "Day-2 canary" run that docs/paper/decision-log.md's D-004 gate reads
(via analysis/canary_readout.py) -- distinct from runner.py's own `--mode canary`, which is
an unrelated 5-config smoke test.

Output routing: uses runner.py's DATASET_PATH_OVERRIDE env var, same as any other mode --
set it before invoking this script so results land in their own file, not master_dataset.csv
(canary_matrix's design -- lambda up to 320 req/s, arm/direction-labeled rows -- doesn't
belong mixed into the standard 54-config full-sweep schema):

    export DATASET_PATH_OVERRIDE=data/canary_matrix_runs.csv
    python3 experiments/run_canary_matrix.py --arms base

Resumability matches runner.py main()'s own pattern exactly: load_completed() once up
front (fails loudly on a header mismatch, same guard as every other mode), skip any
(experiment_id, replicate) already recorded, so a killed/resumed run never re-executes
completed cells or duplicates rows.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import (  # noqa: E402
    DATASET_HEADERS, make_experiment_id, run_experiment_run, toxiproxy,
)
from resumable_runner import is_done, load_completed  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MATRIX = BASE_DIR / "data" / "canary_matrix.csv"
DEFAULT_OUT = BASE_DIR / "data" / "canary_matrix_runs.csv"

MODE = "canary_matrix"

# canary_matrix.py pins this for every row (N_MIN = 5); not swept, so a single constant
# here is correct, not a simplification. compute_load_plan accesses
# config["minimumNumberOfCalls"] unconditionally, so it must be present on every config.
N_MIN = 5


def row_to_config(row):
    return {
        "failureRateThreshold": int(row["threshold"]),
        "slidingWindowSize": int(row["window_size"]),
        "waitDurationInOpenState": int(row["wait_duration"]),
        "slidingWindowType": row["window_type"],
        "minimumNumberOfCalls": N_MIN,
        "targetRps": int(float(row["lambda_target"])),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX),
                     help=f"canary_matrix.csv to read (default: {DEFAULT_MATRIX})")
    ap.add_argument("--out", default=None,
                     help="Output CSV path, ONLY used to check for pre-existing completed "
                          "rows (resumability) -- does not itself redirect where "
                          "run_experiment_run writes. Set DATASET_PATH_OVERRIDE (env var) "
                          "to actually control the write path; pass the same path here so "
                          "resumability reads the file runs are really landing in. Defaults "
                          "to DATASET_PATH_OVERRIDE's value if set, else "
                          f"{DEFAULT_OUT}.")
    ap.add_argument("--arms", nargs="*", default=None,
                     choices=["base", "matched_horizon", "null_control"],
                     help="restrict to these arms; default all three")
    ap.add_argument("--machine-id", default="",
                     help="Same as runner.py's --machine-id -- falls back to MACHINE_ID's "
                          "own auto-detection if omitted.")
    ap.add_argument("--limit", type=int, default=None,
                     help="Cap to the first N new (non-already-completed) runs, in "
                          "canary_matrix.csv's own pre-shuffled run_index order.")
    args = ap.parse_args()

    import os
    out_path = Path(args.out or os.environ.get("DATASET_PATH_OVERRIDE", str(DEFAULT_OUT)))

    with open(args.matrix, newline="") as f:
        rows = list(csv.DictReader(f))

    runnable = [r for r in rows if r["feasible"] == "1"]
    if args.arms:
        runnable = [r for r in runnable if r["arm"] in args.arms]
    runnable.sort(key=lambda r: int(r["run_index"]))

    print(f"Loaded {len(rows)} total rows from {args.matrix}, "
          f"{len(runnable)} feasible+selected before resumability filtering.")

    completed = load_completed(out_path, DATASET_HEADERS)
    print(f"{len(completed)} (experiment_id, replicate) cells already in {out_path}.")

    pending = []
    skipped = 0
    for row in runnable:
        topology = row["topology"].lower()
        fault_type = row["fault_type"].lower()
        config = row_to_config(row)
        experiment_id = make_experiment_id(topology, fault_type, config, mode=MODE)
        if is_done(experiment_id, row["replicate"], completed):
            skipped += 1
        else:
            pending.append((row, topology, fault_type, config, experiment_id))

    if args.limit is not None:
        pending = pending[:args.limit]

    print(f"{skipped} already done, {len(pending)} to run this invocation.")

    try:
        toxiproxy.setup_default_proxies()
        toxiproxy.reset_all()
    except Exception:
        print("Toxiproxy unreachable -- is the mesh up? (docker compose up -d)",
              file=sys.stderr)
        sys.exit(1)

    success_runs = 0
    failed_runs = 0
    for i, (row, topology, fault_type, config, experiment_id) in enumerate(pending, start=1):
        replicate = int(row["replicate"])
        run_index = int(row["run_index"])
        run_order_seed = int(row["run_order_seed"])
        print(f"\nProgress: {i}/{len(pending)}  arm={row['arm']}"
              f"{'/' + row['direction'] if row.get('direction') else ''}  "
              f"{experiment_id} replicate {replicate}")
        success = run_experiment_run(
            config, fault_type, MODE, topology, replicate=replicate,
            run_order_seed=run_order_seed, run_index=run_index,
            machine_id=args.machine_id)
        if success:
            success_runs += 1
        else:
            failed_runs += 1

    print("\n" + "=" * 60)
    print(f"CANARY MATRIX RUN COMPLETE: {success_runs}/{len(pending)} succeeded, "
          f"{failed_runs} failed, {skipped} skipped as already-recorded.")
    print(f"Output: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
