#!/usr/bin/env python3
"""validate_gate.py -- CascadeShield LINEAR re-run validation gate.

Codifies the quantitative pass criteria for the harness-fix validation gate
(see the "Validity Findings" note, section 6.3). Run this against the LINEAR
re-run CSV before scaling to FAN_OUT / SHARED_DEP_MESH or training the
recommender. The gate passes only if BOTH criteria hold:

  1. Coverage: > 15% of TIME_BASED runs register "unsafe". If time-based
     breakers still never trip, blast_radius stays 0 and this stays at 0% --
     the original window-fill artifact would still be present.

  2. Independence: Cramer's V between window_type and is_safe is < 0.30, i.e.
     the safe/unsafe label is no longer (near-)perfectly collinear with
     window_type. The pre-fix data had V = 1.0 (every unsafe run COUNT_BASED).

A run is "unsafe" when blast_radius > TAU (default 0.1 -> any SLO breach).
Stdlib only (csv + math): no pandas/scipy, matching the runner's constraints.

Usage:
    python experiments/validate_gate.py [path/to/dataset.csv]
Exit code 0 if the gate passes, 1 if it fails (usable in CI).
"""
import math
import sys
from pathlib import Path

from csv_gate_utils import load_rows, safe_float

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "data" / "master_dataset.csv"

TAU = 0.1                       # blast_radius > TAU => "unsafe" (matches ml/preprocessing DEFAULT_TAU)
MIN_TIME_BASED_UNSAFE = 0.15    # criterion 1: > 15% of TIME_BASED runs unsafe
MAX_CRAMERS_V = 0.30            # criterion 2: window_type vs is_safe association below this


def is_unsafe(row):
    """A run is unsafe if it recorded a blast_radius strictly above TAU.
    Blank blast_radius (a skipped/failed run) is treated as not-unsafe."""
    val = safe_float(row.get("blast_radius", ""))
    return val is not None and val > TAU


def cramers_v(rows):
    """Cramer's V for the 2x2 (window_type x is_safe) contingency table.
    For 2x2, V = sqrt(chi2 / n). Returns (v, n, table) or (None, n, table)
    when the table is degenerate (a whole row/column is zero)."""
    # table[window_type][safe_bool] = count
    table = {}
    for r in rows:
        wt = r.get("window_type", "")
        if not wt:
            continue
        safe = not is_unsafe(r)
        table.setdefault(wt, {True: 0, False: 0})
        table[wt][safe] += 1

    window_types = list(table)
    n = sum(table[wt][s] for wt in window_types for s in (True, False))
    if n == 0 or len(window_types) < 2:
        return None, n, table

    row_tot = {wt: table[wt][True] + table[wt][False] for wt in window_types}
    col_tot = {s: sum(table[wt][s] for wt in window_types) for s in (True, False)}
    if any(v == 0 for v in row_tot.values()) or any(v == 0 for v in col_tot.values()):
        # A constant row or column => no variation => association undefined (treat as 0).
        return 0.0, n, table

    chi2 = 0.0
    for wt in window_types:
        for s in (True, False):
            expected = row_tot[wt] * col_tot[s] / n
            observed = table[wt][s]
            chi2 += (observed - expected) ** 2 / expected
    k = min(len(window_types) - 1, 1)  # min(r-1, c-1); c=2 here
    return math.sqrt(chi2 / (n * k)), n, table


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not path.exists():
        print(f"Dataset not found: {path}", file=sys.stderr)
        sys.exit(2)

    rows = load_rows(path)
    time_based = [r for r in rows if r.get("window_type") == "TIME_BASED"]
    tb_unsafe = sum(1 for r in time_based if is_unsafe(r))
    tb_frac = tb_unsafe / len(time_based) if time_based else 0.0
    v, n, _ = cramers_v(rows)

    print(f"Dataset: {path}  ({len(rows)} rows, {n} usable for association)")
    print("-" * 60)

    c1_pass = tb_frac > MIN_TIME_BASED_UNSAFE
    print(f"[{'PASS' if c1_pass else 'FAIL'}] Criterion 1 — TIME_BASED unsafe coverage")
    print(f"        {tb_unsafe}/{len(time_based)} = {tb_frac:.1%}  (need > {MIN_TIME_BASED_UNSAFE:.0%})")

    if v is None:
        c2_pass = False
        print(f"[FAIL] Criterion 2 — Cramer's V: not computable (degenerate table)")
    else:
        c2_pass = v < MAX_CRAMERS_V
        print(f"[{'PASS' if c2_pass else 'FAIL'}] Criterion 2 — window_type vs is_safe independence")
        print(f"        Cramer's V = {v:.3f}  (need < {MAX_CRAMERS_V:.2f})")

    print("-" * 60)
    gate_pass = c1_pass and c2_pass
    print(f"GATE: {'PASS — cleared to scale to all topologies' if gate_pass else 'FAIL — do not scale yet'}")
    sys.exit(0 if gate_pass else 1)


if __name__ == "__main__":
    main()
