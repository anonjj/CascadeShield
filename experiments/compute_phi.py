#!/usr/bin/env python3
"""compute_phi.py -- CascadeShield no-fault false-trip rate (phi).

See DATA_DICTIONARY.md's "fault_type=NONE" note and ml/preprocessing.py's
load_dataset() docstring: a config reading blast_radius=0 under a REAL fault is
not distinguishable from a config that would read 0 regardless of whether
anything happened at all, unless there is a baseline to compare against.
fault_type=NONE runs (runner.py --fault none) exercise the mesh with NO fault
injected -- Toxiproxy stays clean for the whole window -- so ANY circuit breaker
that still opens during one of those runs is, by construction, a false trip:
there is no fault to justify it. phi is the fraction of valid NONE runs where
that happened. It is deliberately computed here, from the raw CSV, rather than
through ml/preprocessing.py's load_dataset(): that function filters
fault_type=NONE rows OUT before returning, since they are control data, not
training data for the recommender.

Unlike validate_gate.py's is_unsafe() (blast_radius > TAU, an SLO-breach
tolerance meant for judging REAL fault damage), there is no meaningful
tolerance here -- under NONE, zero trips is the only correct outcome, so
"tripped" is blast_radius > 0 (strictly), not > TAU.

Usage:
    python experiments/compute_phi.py [path/to/dataset.csv]
Always exits 0 on a successful read (this is a report, not a pass/fail gate --
see validate_gate.py for that). Exits 2 if the dataset file itself is missing,
1 if it has no usable fault_type=NONE rows at all.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "data" / "master_dataset.csv"

# Mirrors runner.py's MIN_NONE_FAULT_REPLICATES. Duplicated (not imported) so this
# stays a standalone stdlib script, same convention as validate_gate.py duplicating
# ml/preprocessing.py's DEFAULT_TAU with a comment instead of importing it -- keep
# these two in sync if the floor ever changes.
MIN_NONE_FAULT_REPLICATES = 10


def load_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def is_valid_none_row(row):
    """A usable no-fault control row: fault_type=NONE and the run actually
    cleared its precondition. precondition_ok=False rows were aborted before
    fault injection (or non-injection, here) even started -- they measured
    nothing, and counting them as "no trip" would silently deflate phi."""
    if row.get("fault_type") != "NONE":
        return False
    return row.get("precondition_ok", "") in ("True", "true", "1")


def tripped(row):
    """True if this run's blast_radius (the CB-state fraction of CB-bearing
    services that opened) was strictly greater than zero -- ANY breaker
    opening under a no-fault run is a false trip. Blank (a measurement gap,
    e.g. the gateway was unreachable) is treated as not tripped, matching
    validate_gate.py's is_unsafe() convention for blank blast_radius."""
    raw = row.get("blast_radius", "")
    if raw in ("", "None"):
        return False
    try:
        return float(raw) > 0.0
    except ValueError:
        return False


def compute_phi(rows):
    """(phi, trips, total) over already-filtered rows. phi is None when
    total == 0 -- nothing to compute, not a false claim of phi=0."""
    total = len(rows)
    trips = sum(1 for r in rows if tripped(r))
    phi = (trips / total) if total else None
    return phi, trips, total


def config_key(row):
    """The 6-tuple that identifies a swept config (topology + the 5 CB knobs).
    Matches the independent variables in DATA_DICTIONARY.md."""
    return (
        row.get("topology", ""), row.get("window_type", ""),
        row.get("threshold", ""), row.get("window_size", ""),
        row.get("wait_duration", ""),
    )


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not path.exists():
        print(f"Dataset not found: {path}", file=sys.stderr)
        sys.exit(2)

    all_rows = load_rows(path)
    none_rows = [r for r in all_rows if r.get("fault_type") == "NONE"]
    valid_rows = [r for r in none_rows if is_valid_none_row(r)]
    aborted = len(none_rows) - len(valid_rows)

    print(f"Dataset: {path}  ({len(all_rows)} total rows)")
    print(f"fault_type=NONE rows: {len(none_rows)} ({aborted} aborted by "
          f"precondition_ok=False, excluded)")
    print("-" * 72)

    if not valid_rows:
        print("No valid fault_type=NONE rows -- phi cannot be computed. "
              "Run `runner.py --fault none --replicates 10` first.")
        sys.exit(1)

    overall_phi, overall_trips, overall_total = compute_phi(valid_rows)
    print(f"Overall phi (baseline false-trip rate): {overall_phi:.4f} "
          f"({overall_trips}/{overall_total} runs tripped with no fault injected)")
    print()

    by_topology = defaultdict(list)
    for r in valid_rows:
        by_topology[r.get("topology", "")].append(r)
    print("By topology:")
    for topo in sorted(by_topology):
        phi, trips, total = compute_phi(by_topology[topo])
        print(f"  {topo:<20} phi={phi:.4f}  ({trips}/{total})")
    print()

    by_config = defaultdict(list)
    for r in valid_rows:
        by_config[config_key(r)].append(r)
    print(f"By config ({len(by_config)} distinct configs among the NONE runs), "
          "worst (highest phi) first:")
    rows_out = []
    for key, rows in by_config.items():
        phi, trips, total = compute_phi(rows)
        rows_out.append((phi, trips, total, key))
    rows_out.sort(key=lambda t: (-t[0], -t[2]))
    for phi, trips, total, (topo, wt, thr, ws, wd) in rows_out:
        thin = " [THIN SAMPLE]" if total < MIN_NONE_FAULT_REPLICATES else ""
        flag = " <-- false trips observed" if trips > 0 else ""
        print(f"  {topo:<12} {wt:<12} T={thr:<4} W={ws:<4} D={wd:<4} "
              f"phi={phi:.4f} ({trips}/{total}){thin}{flag}")

    sys.exit(0)


if __name__ == "__main__":
    main()
