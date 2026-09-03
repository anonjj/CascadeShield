"""
analysis/verify_calibration_run.py  (D6 support)

Sanity-checks ONE machine's canary/calibration output right after a run finishes,
before it's renamed and sent to the other person. Catches a bad run early (wrong
topology, wrong machine_id, a precondition failure that silently blanked outcome
columns, etc.) instead of discovering it after both files are already merged.

Usage:
  python analysis/verify_calibration_run.py data/master_dataset_calibration_soham_fanout_overlap.csv \
      --machine-id soham-local --topology FANOUT --expected-rows 18
"""

import argparse
import sys

import pandas as pd


def verify(df, machine_id, topology, expected_rows):
    problems = []
    warnings = []

    n = len(df)
    if expected_rows is not None and n != expected_rows:
        warnings.append(f"expected {expected_rows} rows, got {n} "
                         f"(fine if a precondition retry changed the count, but check why)")

    topos = df["topology"].unique().tolist()
    if len(topos) != 1:
        problems.append(f"topology is not uniform: {topos}")
    elif topology and topos[0].upper() != topology.upper():
        problems.append(f"topology is {topos[0]}, expected {topology}")

    machines = df["machine_id"].unique().tolist()
    if len(machines) != 1:
        problems.append(f"machine_id is not uniform: {machines}")
    elif machine_id and str(machines[0]) != machine_id:
        problems.append(f"machine_id is '{machines[0]}', expected '{machine_id}'")

    ok_col = df["precondition_ok"].astype(str)
    n_bad_precond = int((ok_col != "True").sum())
    if n_bad_precond:
        reasons = df.loc[ok_col != "True", "precondition_fail_reason"].value_counts().to_dict()
        problems.append(f"{n_bad_precond}/{n} rows have precondition_ok=False -- these rows "
                         f"measured nothing. Reasons: {reasons}. Re-run to replace them.")

    tto = pd.to_numeric(df["time_to_open"], errors="coerce")
    trip_rate = tto.notna().mean() if n else float("nan")
    if n and trip_rate == 0.0:
        warnings.append("time_to_open is null on every row -- nothing tripped. Check "
                         "that fault_injector.py's proxies were actually up before this ran.")
    elif n and trip_rate < 0.5:
        warnings.append(f"only {trip_rate:.0%} of runs tripped -- worth a look")

    if "lambda_deviation_flag" in df.columns:
        dev = df["lambda_deviation_flag"].astype(str).str.strip().str.lower().isin(["true", "1"])
        if dev.any():
            warnings.append(f"{int(dev.sum())}/{n} rows flagged lambda_deviation_flag=True")

    wtypes = df["window_type"].value_counts().to_dict()
    if len(wtypes) < 2:
        warnings.append(f"only window_type(s) {list(wtypes.keys())} present -- expected both "
                         f"COUNT_BASED and TIME_BASED")

    return {"n_rows": n, "topologies": topos, "machines": machines,
            "n_precondition_fail": n_bad_precond, "trip_rate": trip_rate,
            "window_type_counts": wtypes, "problems": problems, "warnings": warnings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--machine-id", default=None)
    ap.add_argument("--topology", default="LINEAR")
    ap.add_argument("--expected-rows", type=int, default=10)
    args = ap.parse_args()

    df = pd.read_csv(args.csv_path)
    result = verify(df, args.machine_id, args.topology, args.expected_rows)

    print(f"file: {args.csv_path}")
    print(f"rows: {result['n_rows']}  |  topology: {result['topologies']}  |  "
          f"machine_id: {result['machines']}")
    if result['n_rows']:
        print(f"precondition failures: {result['n_precondition_fail']}  |  "
              f"trip rate: {result['trip_rate']:.0%}")
    print(f"window_type coverage: {result['window_type_counts']}")

    if result["warnings"]:
        print("\nWARNINGS (worth a look, not necessarily wrong):")
        for w in result["warnings"]:
            print(f"  - {w}")

    if result["problems"]:
        print("\nPROBLEMS (fix before using this file):")
        for p in result["problems"]:
            print(f"  - {p}")
        print("\nRESULT: FAIL")
        sys.exit(1)
    else:
        print("\nRESULT: PASS")


if __name__ == "__main__":
    main()
