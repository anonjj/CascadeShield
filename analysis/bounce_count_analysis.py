#!/usr/bin/env python3
"""H3 mechanism candidate: does the HALF_OPEN->OPEN bounce count explain why TIME_BASED
recovers slower than COUNT_BASED?

Background (decision-log.md D13/D22): HALF_OPEN->CLOSED is gated by
permittedNumberOfCallsInHalfOpenState (3 calls admitted, evaluated the instant they
complete), not minimumNumberOfCalls -- confirmed live. 3 probes at ~0.3s should take about
a second, yet TIME_BASED recovery runs 19-40s. Candidate mechanism: the observed time is
mostly repeated HALF_OPEN -> OPEN -> wait_duration -> HALF_OPEN bounces before one episode
finally closes, driven by a TIME_BASED window still holding failure records from the last
`window_size` seconds on re-evaluation (a COUNT_BASED ring buffer gets overwritten by fresh
successes almost immediately instead). Larger window_size means longer residual fault
memory, hence more bounces -- which would produce exactly the window_size correlation
found in decision-log.md's D13 2026-09-17 update.

Reuses half_open_survival.py's extract_observations() (same n_failed_probes field -- the
actual HALF_OPEN_TO_OPEN bounce count per run; NOT n_half_open_entries, which is bounded by
len(BREAKER_WATCH) and carries no bounce information at all, see that file's comment).

Usage:
    python3 analysis/bounce_count_analysis.py --since 2026-09-16
    python3 analysis/bounce_count_analysis.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from half_open_survival import extract_observations  # noqa: E402


def load_records(jsonl_path: str, since: str | None) -> list[dict]:
    records = []
    for line in Path(jsonl_path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if since:
        records = [r for r in records if r.get("fault_injected_at", "") >= since]
    return records


def bounce_by_window_size(obs: list[dict]) -> dict:
    """{(window_type, window_size): [bounce_count, ...]} -- one entry per observation."""
    table = defaultdict(list)
    for o in obs:
        table[(o["window_type"], o["window_size"])].append(o["n_failed_probes"])
    return dict(table)


def ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Plain OLS via numpy.linalg.lstsq -- no statsmodels dependency, matching
    half_open_survival.py's own numpy-only, scipy-only-when-needed convention.
    Returns (coefficients, R^2). Descriptive on this sample size (n<=34), not a
    claim of inferential significance -- no p-values reported here."""
    beta, _residuals, _rank, _sv = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2


def render(obs: list[dict]) -> str:
    lines = []
    bt = bounce_by_window_size(obs)

    lines.append("bounce count (n_failed_probes) by (window_type, window_size):")
    lines.append(f"  {'window_type':12} {'W':>3} {'n':>3} {'mean bounces':>13}  raw")
    for key in sorted(bt, key=lambda k: (str(k[0]), k[1])):
        vals = bt[key]
        lines.append(f"  {key[0]:12} {key[1]!s:>3} {len(vals):>3} "
                      f"{np.mean(vals):>13.3f}  {vals}")

    counts_flat = [b for (wtype, _), vals in bt.items() if wtype == "COUNT_BASED" for b in vals]
    times_flat = [b for (wtype, _), vals in bt.items() if wtype == "TIME_BASED" for b in vals]
    lines.append("")
    lines.append(f"COUNT_BASED: {len(counts_flat)} obs, "
                  f"bounces all zero: {all(b == 0 for b in counts_flat)}")
    lines.append(f"TIME_BASED: {len(times_flat)} obs, "
                  f"mean bounces {np.mean(times_flat):.3f}, range "
                  f"{min(times_flat)}-{max(times_flat)}")

    # Joint regression: duration_s ~ bounce_count + wait_duration + is_time_based
    # A naive two-term decomposition (bounce_count * wait_duration) was checked ad hoc and
    # found to over-explain the gap at Dw=15/30 -- COUNT_BASED's own zero-bounce "final
    # episode" duration ALSO scales with window params, which that decomposition can't
    # represent. A joint regression at least puts all three covariates on equal footing
    # instead of assuming COUNT's baseline is a flat ~1s.
    rows = [o for o in obs]
    y = np.array([o["duration_s"] for o in rows], dtype=float)
    bounce = np.array([o["n_failed_probes"] for o in rows], dtype=float)
    wait = np.array([o["wait_duration"] for o in rows], dtype=float)
    is_time = np.array([1.0 if o["window_type"] == "TIME_BASED" else 0.0 for o in rows])
    X = np.column_stack([np.ones_like(y), bounce, wait, is_time])
    beta, r2 = ols(X, y)

    lines.append("")
    lines.append(f"OLS: duration_s ~ 1 + bounce_count + wait_duration + is_time_based  (n={len(rows)})")
    lines.append(f"  intercept        = {beta[0]:8.3f}")
    lines.append(f"  bounce_count     = {beta[1]:8.3f}  (s per additional bounce)")
    lines.append(f"  wait_duration    = {beta[2]:8.3f}  (s per additional second of D_w)")
    lines.append(f"  is_time_based    = {beta[3]:8.3f}  (s, TIME vs COUNT at bounce=0, "
                  "same D_w -- the part bounce_count alone doesn't explain)")
    lines.append(f"  R^2              = {r2:8.3f}")
    lines.append("  Descriptive only (n<=34, unbalanced cells after exclusions) -- no")
    lines.append("  p-values reported. A nonzero is_time_based coefficient at bounce=0 means")
    lines.append("  bounce count is not a complete explanation on its own.")

    # The specific outlier flagged in decision-log.md's D13/D22 entries: a 0-bounce
    # COUNT_BASED run that still took far longer than its sibling cells.
    outliers = [o for o in obs if o["window_type"] == "COUNT_BASED" and o["n_failed_probes"] == 0
                and o["duration_s"] > 20]
    if outliers:
        lines.append("")
        lines.append("Unexplained: 0-bounce COUNT_BASED runs with duration_s > 20s "
                      "(bounce model predicts these should be fast, like other COUNT cells):")
        for o in outliers:
            lines.append(f"  {o['experiment_id']} rep{o['replicate']}: "
                          f"duration_s={o['duration_s']:.2f}, W={o['window_size']}, "
                          f"D_w={o['wait_duration']}")

    return "\n".join(lines)


def self_test() -> bool:
    """Synthetic sanity check: bounce_count should dominate the regression coefficient
    for a dataset constructed so duration_s = 5 * bounce_count + noise, independent of
    window_type/wait_duration."""
    ok = True
    rng = np.random.default_rng(0)
    obs = []
    for i in range(20):
        bounces = i % 4
        obs.append({
            "experiment_id": f"synthetic-{i}", "replicate": i,
            "window_type": "TIME_BASED" if i % 2 else "COUNT_BASED",
            "window_size": 10, "wait_duration": 15,
            "duration_s": 5.0 * bounces + 2.0 + float(rng.normal(0, 0.1)),
            "n_failed_probes": bounces,
        })
    y = np.array([o["duration_s"] for o in obs])
    bounce = np.array([o["n_failed_probes"] for o in obs], dtype=float)
    wait = np.array([o["wait_duration"] for o in obs], dtype=float)
    is_time = np.array([1.0 if o["window_type"] == "TIME_BASED" else 0.0 for o in obs])
    X = np.column_stack([np.ones_like(y), bounce, wait, is_time])
    beta, r2 = ols(X, y)
    if abs(beta[1] - 5.0) > 0.5:
        print(f"FAIL: expected bounce_count coefficient ~5.0, got {beta[1]:.3f}")
        ok = False
    if r2 < 0.95:
        print(f"FAIL: expected near-perfect fit on synthetic data, got R^2={r2:.3f}")
        ok = False

    bt = bounce_by_window_size(obs)
    if len(bt) != 2:
        print(f"FAIL: expected 2 (window_type, window_size) cells, got {len(bt)}")
        ok = False

    print("self-test PASSED" if ok else "self-test FAILED")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", default="data/cb_transitions.jsonl")
    ap.add_argument("--since", default="2026-09-16",
                     help="YYYY-MM-DD -- default matches the post-D21-fix slice the "
                          "published H3 KM table uses, so this analysis is directly "
                          "comparable to it.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return 0 if self_test() else 1

    path = Path(args.jsonl)
    if not path.exists():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        return 1

    records = load_records(str(path), args.since)
    obs = extract_observations(records)
    if not obs:
        print("ERROR: zero observations extracted.", file=sys.stderr)
        return 1
    print(f"{len(obs)} observations ({args.since or 'all time'})\n")
    print(render(obs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
