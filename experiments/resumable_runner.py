"""
Resumable, append-only result writer for the CascadeShield harness (D9).

Turns a mid-grid crash from "lose the night" into "lose the current row":
on restart, every (experiment_id, replicate) already in the output file is
skipped. Also fixes the silent-header-refuse bug (the lost occupancy run) by
failing LOUDLY on a header mismatch instead of quietly writing nothing.

Integrate with 3 hooks in your existing loop:

    from resumable_runner import load_completed, is_done, append_row

    completed = load_completed(out_path, DATASET_HEADERS)          # once, before the loop
    for cfg in grid:
        for rep in range(1, replicates + 1):
            if is_done(cfg.experiment_id, rep, completed):         # top of each cell
                continue
            row = run_one(cfg, rep)                                # your existing work
            append_row(out_path, row, DATASET_HEADERS)             # replaces log_results write
            completed.add((cfg.experiment_id, str(rep)))           # keep the set current
"""

import csv
import os


def load_completed(path, header):
    """Return the set of (experiment_id, replicate) already written.

    Fails loudly if the file's header != the header this run will write —
    that mismatch is the silent-refuse bug (36-col occupancy pointed at the
    34-col master). Better to stop than to "succeed" writing nothing.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        file_header = reader.fieldnames or []
        if file_header != list(header):
            raise SystemExit(
                f"[resume] header mismatch on {path}\n"
                f"  file: {file_header}\n"
                f"  run : {list(header)}\n"
                "This mode must write its OWN file, or reconcile to the "
                "canonical schema (D8)."
            )
        return {
            (row.get("experiment_id"), str(row.get("replicate")))
            for row in reader
        }


def is_done(experiment_id, replicate, completed):
    """True if this (experiment_id, replicate) cell is already in the file."""
    return (experiment_id, str(replicate)) in completed


def append_row(path, row, header):
    """Append one row, creating the file with `header` if absent.

    Flush + fsync per row, so a crash loses at most the row being written.
    restval="" lets a mode-specific (nullable) column be omitted from `row`
    and written blank; extrasaction="ignore" drops stray keys. Together these
    let every mode share one canonical superset header (D8).
    """
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(header), restval="", extrasaction="ignore"
        )
        if new_file:
            writer.writeheader()
        writer.writerow(row)
        f.flush()
        os.fsync(f.fileno())
