"""
analysis/recovery_fault_timing_check.py

Does a HALF_OPEN episode's outcome depend on whether the injected fault was still active
when the episode began?

Why this exists. `experiments/runner.py` keeps the Toxiproxy fault active for the whole
load plan and clears it only afterwards (`toxiproxy.reset_all()` after `generate_load`).
`compute_load_plan()` sizes that plan differently per window type: TIME_BASED runs for
`window + wait_duration + TIME_BASED_MARGIN_S` seconds, COUNT_BASED for
`max(3*window, 3*n_min, 40)` calls at 10 req/s (4-6 s). `time_to_recover` is anchored at
the breaker's OPEN time, not at fault clearance. Separately, Resilience4j 2.2.0 builds every
HALF_OPEN state's metrics with `CircuitBreakerMetrics.forHalfOpen(...)`, which is always a
fresh COUNT_BASED buffer of `permittedNumberOfCallsInHalfOpenState` calls (checked with
`javap` against the 2.2.0 jar) -- the configured window type is not consulted there.

So if every failed HALF_OPEN episode (HALF_OPEN_TO_OPEN, a "bounce") began before the fault
was cleared, and every successful one (HALF_OPEN_TO_CLOSED) began after, the window-type
difference in recovery time is explained by how long the harness kept the fault on, not by
the breaker. This script counts exactly that, from the transition sidecar.

Scope: the order-service `inventoryServiceCB` breaker (the one LATENCY faults exercise on
LINEAR). `fault_cleared_at` has 1 s resolution; the script reports the margins so a reader
can see whether that resolution could matter.

Usage:
    python analysis/recovery_fault_timing_check.py [path/to/cb_transitions.jsonl ...]
    python analysis/recovery_fault_timing_check.py --self-test

Default path: data/cb_transitions.jsonl. The Phase 4B (post-D25) sidecar lives on branch
`h3-evidence-audit`: `git show origin/h3-evidence-audit:data/cb_transitions.jsonl > f.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cb_transitions.jsonl"
SERVICE, BREAKER = "order", "inventoryServiceCB"


def _ts(value: str) -> float:
    """Parse the sidecar's ISO timestamps ('...Z' or '...Z[Etc/UTC]', up to ns precision).

    Zero-pads the fractional-second component to 6 digits (not just truncates) before
    handing it to fromisoformat -- Python's fromisoformat (this project's Python 3.9)
    only accepts an exactly-3 or exactly-6-digit fraction, and a short fraction like the
    single-digit ".0" real Resilience4j timestamps and this file's own self-test fixtures
    both use is neither. Truncating alone (frac[:6]) leaves a 1-2 digit fraction
    unchanged and still invalid; padding first makes any 1-9-digit input work.
    """
    s = value.split("[")[0].rstrip("Z")
    if "." in s:
        head, frac = s.split(".")
        s = head + "." + (frac + "000000")[:6]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def classify(records):
    """Return (counts, margins). counts[(window_type, started, outcome)] -> n, where started is
    'fault_active' or 'fault_cleared' at the OPEN_TO_HALF_OPEN timestamp, and outcome is the
    next transition of the same breaker ('NONE' if the record ends in HALF_OPEN)."""
    counts, margins = Counter(), defaultdict(list)
    for rec in records:
        if not rec.get("fault_cleared_at"):
            counts[(rec.get("window_type"), "no_fault_cleared_at", "-")] += 1
            continue
        cleared = _ts(rec["fault_cleared_at"])
        events = [e for e in rec.get("transitions", [])
                  if e.get("service") == SERVICE and e.get("breaker") == BREAKER]
        for i, ev in enumerate(events):
            if ev.get("state_transition") != "OPEN_TO_HALF_OPEN":
                continue
            start = _ts(ev["creation_time"])
            outcome = events[i + 1]["state_transition"] if i + 1 < len(events) else "NONE"
            started = "fault_active" if start < cleared else "fault_cleared"
            counts[(rec.get("window_type"), started, outcome)] += 1
            margins[(rec.get("window_type"), outcome)].append(start - cleared)
    return counts, margins


def report(path: Path) -> dict:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    counts, margins = classify(records)
    print(f"\n{path}  ({len(records)} records)")
    print("  window_type   HALF_OPEN began with   next transition        n")
    for (wt, started, outcome), n in sorted(counts.items(), key=str):
        print(f"  {str(wt):12s}  {started:21s}  {outcome:21s}  {n}")
    print("  HALF_OPEN start minus fault_cleared_at (s), by outcome:")
    for (wt, outcome), vals in sorted(margins.items(), key=str):
        print(f"    {wt:12s} {outcome:21s} min {min(vals):7.1f}  max {max(vals):7.1f}")
    bounces_after_clear = sum(n for (_, s, o), n in counts.items()
                              if s == "fault_cleared" and o == "HALF_OPEN_TO_OPEN")
    closes_before_clear = sum(n for (_, s, o), n in counts.items()
                              if s == "fault_active" and o == "HALF_OPEN_TO_CLOSED")
    verdict = ("SEPARATES_BY_FAULT_STATE" if bounces_after_clear == 0 and closes_before_clear == 0
               else "DOES_NOT_SEPARATE")
    print(f"  bounces that began after clearance: {bounces_after_clear}; "
          f"closes that began before clearance: {closes_before_clear} -> {verdict}")
    return {"verdict": verdict, "counts": {"|".join(map(str, k)): v for k, v in counts.items()}}


def self_test() -> None:
    def rec(wt, cleared, events):
        return {"window_type": wt, "fault_cleared_at": cleared,
                "transitions": [{"service": SERVICE, "breaker": BREAKER,
                                 "state_transition": t, "creation_time": c} for t, c in events]}
    records = [
        rec("TIME_BASED", "2026-01-01T00:00:30Z", [
            ("CLOSED_TO_OPEN", "2026-01-01T00:00:05.0Z"),
            ("OPEN_TO_HALF_OPEN", "2026-01-01T00:00:20.0Z"),    # fault still on
            ("HALF_OPEN_TO_OPEN", "2026-01-01T00:00:23.0Z"),
            ("OPEN_TO_HALF_OPEN", "2026-01-01T00:00:38.0Z[Etc/UTC]"),  # fault cleared
            ("HALF_OPEN_TO_CLOSED", "2026-01-01T00:00:40.0Z")]),
        rec("COUNT_BASED", "2026-01-01T00:00:07Z", [
            ("CLOSED_TO_OPEN", "2026-01-01T00:00:04.0Z"),
            ("OPEN_TO_HALF_OPEN", "2026-01-01T00:00:19.0Z"),
            ("HALF_OPEN_TO_CLOSED", "2026-01-01T00:00:21.0Z")]),
    ]
    counts, _ = classify(records)
    assert counts[("TIME_BASED", "fault_active", "HALF_OPEN_TO_OPEN")] == 1, counts
    assert counts[("TIME_BASED", "fault_cleared", "HALF_OPEN_TO_CLOSED")] == 1, counts
    assert counts[("COUNT_BASED", "fault_cleared", "HALF_OPEN_TO_CLOSED")] == 1, counts
    assert sum(counts.values()) == 3, counts
    print("self-test OK")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", type=Path, default=[DEFAULT_PATH])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    for path in args.paths:
        report(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
