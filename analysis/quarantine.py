"""Day 1 (Soham) -- add and populate the `excluded_reason` column.

Rows that cannot be trusted are marked, never deleted. A silently dropped row is
indistinguishable from a row that was never collected, and the difference is exactly what a
reviewer checking the artifact will look for. Every exclusion here carries a machine-readable
code, is counted in analysis/out/quarantine.json, and gets stated in the paper.

Exclusion codes
---------------
STATE_LEAK_EARLY_OPEN    breaker entered the run already OPEN (leak_audit S1, SEVERE tier)
STATE_LEAK_BLAST         more subjects OPEN than legs with any observed failure (S2)
RECOVERY_TIMEOUT_HANG    time_to_recover far outside the physical range of the protocol --
                         the 7540.5 s (2.1 h) row, where every other run in the file tops
                         out at 65.7 s. Step 8 of the run protocol now caps this at 120 s.
LAMBDA_DEVIATION         runner.py's own lambda_deviation_flag fired (achieved arrival rate
                         missed target by more than LAMBDA_DEVIATION_THRESHOLD) -- the
                         detector was already correct, it just had no downstream effect: a
                         flagged row was written to the dataset the same as any other and
                         nothing here ever promoted the flag into an exclusion, so 242
                         contaminated rows passed straight into analysis silently.

Rows carrying a RECURRENT_MODE label from the audit are deliberately NOT excluded: a
displacement that reproduces across configurations is a property of the instrument being
measured, and dropping it would delete a finding.

Neither is a dataset whose S2 verdict came back CONSTANT_OFFSET. On
`v3_gateway_not_rebuilt` the contradiction holds for 95.7% of rows, which is not 88 leaked
breakers -- it is one subject reading degraded in every single run, so blast_radius carries
a fixed offset. Quarantining the file row by row would throw away 88 usable timing
measurements to fix a column that timing analyses never touch. The whole *column* is marked
unusable instead, and the rows stay.

Usage:  python analysis/quarantine.py [--apply]
        Default is a dry run that prints the diff. --apply rewrites the CSV in place.
Output: analysis/out/quarantine.json
"""

import argparse
import shutil

import pandas as pd

from common import DATASETS, load, write_json
from leak_audit import (CONSTANT_OFFSET_SHARE, early_open_flags, impossible_blast_flags,
                        screen_recurrent_modes)

# Step 8 of the run protocol sustains load until CLOSED or timeout, capped at 120 s. Any
# recorded recovery beyond that cap is a hang the old harness failed to bound, not a
# measurement of recovery latency.
RECOVERY_CAP_S = 120.0

EXCLUSION_COLUMN = "excluded_reason"


def classify(df):
    """Returns (exclusion-code Series, dataset-level notes).

    Codes accumulate, so a row hit by two signatures reports both.
    """
    parts = pd.Series([[] for _ in range(len(df))], index=df.index)
    notes = {}

    s1, s1_diag, _ = early_open_flags(df)
    s1, _ = screen_recurrent_modes(df, s1, s1_diag)
    s2, _ = impossible_blast_flags(df, DATASETS[df["dataset"].iloc[0]]["blast_denominator"])

    # Only the SEVERE tier is excluded. A MODERATE hit that survived the recurrence screen
    # is suspicious but not demonstrably contaminated, and excluding on suspicion alone
    # biases the very DV the exclusion is meant to protect.
    for idx in df.index[s1 & (s1_diag["severity"] == "SEVERE")]:
        parts[idx].append("STATE_LEAK_EARLY_OPEN")

    # A contradiction that holds for most of a file is a property of the metric, not of the
    # runs. Mark the column, keep the rows -- see the module docstring.
    if len(df) and s2.mean() >= CONSTANT_OFFSET_SHARE:
        notes["blast_radius_column_unusable"] = (
            "S2 fires on {:.1%} of rows: blast_radius carries a constant offset from a "
            "subject that reads degraded in every run. Rows are retained -- their timing "
            "measurements are unaffected -- but blast_radius and real_blast_radius from "
            "this file must not be used as outcomes.".format(s2.mean()))
    else:
        for idx in df.index[s2]:
            parts[idx].append("STATE_LEAK_BLAST")

    t_rec = pd.to_numeric(df.get("time_to_recover"), errors="coerce")
    for idx in df.index[t_rec > RECOVERY_CAP_S]:
        parts[idx].append("RECOVERY_TIMEOUT_HANG")

    # runner.py already computes and writes this per row (see DATASET_HEADERS); it was never
    # wired into an exclusion, so a flagged run's numbers entered analysis unmarked. Matches
    # canary_readout.py's own str/lower/isin(["true", "1"]) parse of the same column.
    if "lambda_deviation_flag" in df.columns:
        flagged = df["lambda_deviation_flag"].astype(str).str.strip().str.lower().isin(["true", "1"])
        for idx in df.index[flagged]:
            parts[idx].append("LAMBDA_DEVIATION")

    return parts.map(lambda codes: "+".join(codes)), notes


def process(name, apply_changes):
    spec = DATASETS[name]
    df = load(name, apply_exclusions=False)
    reasons, notes = classify(df)

    raw = pd.read_csv(spec["path"])
    if EXCLUSION_COLUMN in raw.columns:
        # Preserve any reason a human wrote in by hand; only fill the blanks.
        existing = raw[EXCLUSION_COLUMN].fillna("").astype(str)
        merged = existing.where(existing.str.strip() != "", reasons)
    else:
        merged = reasons
    raw[EXCLUSION_COLUMN] = merged

    excluded = raw[raw[EXCLUSION_COLUMN].astype(str).str.strip() != ""]
    detail = excluded[["experiment_id", "replicate", "time_to_open", "time_to_recover",
                       EXCLUSION_COLUMN]].to_dict("records")

    if apply_changes and len(raw):
        backup = spec["path"].with_suffix(".csv.pre_quarantine")
        if not backup.exists():
            shutil.copy2(spec["path"], backup)
            print("  backed up -> {}".format(backup.name))
        raw.to_csv(spec["path"], index=False)
        print("  wrote {} with {} column".format(spec["path"].name, EXCLUSION_COLUMN))

    return {
        "dataset": name,
        "n_rows": int(len(raw)),
        "n_excluded": int(len(excluded)),
        "share_excluded": float(len(excluded) / len(raw)) if len(raw) else 0.0,
        "n_analysable": int(len(raw) - len(excluded)),
        "by_reason": excluded[EXCLUSION_COLUMN].value_counts().to_dict(),
        "column_level_notes": notes,
        "rows": detail,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the CSVs in place (a .pre_quarantine backup is kept)")
    ap.add_argument("--datasets", nargs="*", default=["current", "v2_latency_5svc",
                                                      "v3_gateway_not_rebuilt"])
    args = ap.parse_args()

    results = []
    for name in args.datasets:
        print("\n=== {} ===".format(name))
        r = process(name, args.apply)
        results.append(r)
        print("  {} / {} rows quarantined ({:.1%})".format(
            r["n_excluded"], r["n_rows"], r["share_excluded"]))
        for reason, n in r["by_reason"].items():
            print("    {:<45} {}".format(reason, n))
        for key, msg in r["column_level_notes"].items():
            print("    ! {}: {}".format(key, msg))
        for row in r["rows"]:
            print("    - {} rep {}: t_open={} t_rec={}".format(
                row["experiment_id"], row["replicate"],
                row["time_to_open"], row["time_to_recover"]))

    if not args.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply to persist.")

    write_json("quarantine.json", {
        "recovery_cap_s": RECOVERY_CAP_S,
        "applied": bool(args.apply),
        "per_dataset": results,
    })


if __name__ == "__main__":
    main()
