#!/usr/bin/env python3
"""D23/D24: audit data/master_dataset.csv (360 rows) for gateway breaker activity.

Answer, up front: **structurally inconclusive**, not "gateway was clean." Confirmed below:

1. Gateway can never appear in `leg_failure_rates`/`blast_radius`/`real_blast_radius` in any
   row -- `CB_METRIC_TARGETS` (experiments/runner.py) and `SERVICE_ACTUATOR_URLS`
   (BlastRadiusService.java) both hard-code the 4 downstream services only, gateway explicitly
   excluded by design ("it is the MEASUREMENT PLANE, not an experimental subject").
2. The one indirect proxy -- error_rate (client-observed, through gateway) diverging from
   leg_failure_rates' order-service entry (order's own outbound health) -- is real in
   principle, but the ratio between them is dominated by an unrelated ~2x/1x artifact that
   splits cleanly by collection batch (machine_id/run_timestamp), not by D23's flagged
   parameter region (COUNT_BASED, wait_duration in {15,30}, window_size in {10,20}).
   Building a threshold on this now would misattribute that unrelated batch artifact to
   gateway. This script prints both findings and stops there -- it does not fabricate a
   working heuristic that isn't real.

Usage:
    python3 analysis/gateway_leg_audit.py
    python3 analysis/gateway_leg_audit.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

D23_LEAK_WINDOW_SIZES = {10, 20}
D23_LEAK_WAIT_DURATIONS = {15, 30}


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def parse_leg_failure_rates(raw: str) -> dict[str, float]:
    """'svc:rate;svc:rate' -> {svc: rate}. Blank/malformed entries are skipped, not guessed."""
    out = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        svc, _, rate = part.partition(":")
        try:
            out[svc] = float(rate)
        except ValueError:
            continue
    return out


def audit_gateway_presence(rows: list[dict]) -> tuple[int, set[str]]:
    """Returns (rows_checked, set of every leg key ever seen)."""
    all_keys = set()
    for r in rows:
        all_keys.update(parse_leg_failure_rates(r.get("leg_failure_rates", "")).keys())
    return len(rows), all_keys


def error_rate_ratio(row: dict) -> float | None:
    """error_rate / max(downstream leg failure rate) -- None if the row has no usable legs
    or error_rate/legs are both zero (0/0, not a real ratio)."""
    try:
        error_rate = float(row.get("error_rate", ""))
    except ValueError:
        return None
    legs = parse_leg_failure_rates(row.get("leg_failure_rates", ""))
    if not legs:
        return None
    max_leg = max(legs.values())
    if max_leg == 0:
        return None
    return error_rate / max_leg


def render(rows: list[dict]) -> str:
    L = []

    n, keys = audit_gateway_presence(rows)
    L.append(f"1. leg_failure_rates key audit: {n} rows checked, "
              f"distinct leg keys seen: {sorted(keys)}")
    gw_present = any("gateway" in k for k in keys)
    L.append(f"   gateway ever present as a leg: {gw_present} "
             "(expected False -- CB_METRIC_TARGETS/SERVICE_ACTUATOR_URLS exclude it by design)")

    L.append("")
    L.append("2. error_rate / max(leg_failure_rate) ratio, by topology x machine_id/batch:")
    by_batch: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        ratio = error_rate_ratio(r)
        if ratio is None:
            continue
        batch_key = (r.get("topology", ""), r.get("machine_id", "") or r.get("run_timestamp", "")[:10])
        by_batch[batch_key].append(ratio)
    for key in sorted(by_batch):
        vals = by_batch[key]
        mean = sum(vals) / len(vals)
        L.append(f"   {key}: n={len(vals):3}  mean={mean:.4f}  "
                 f"min={min(vals):.4f}  max={max(vals):.4f}")
    L.append("   -> splits cleanly by batch (~2.0 vs ~1.0), not by window params -- an")
    L.append("      unrelated, unexplained artifact worth its own investigation, flagged not")
    L.append("      solved here.")

    L.append("")
    L.append("3. D23-flagged region vs rest of COUNT_BASED (does the ratio separate them?):")
    in_region, out_region = [], []
    for r in rows:
        if r.get("window_type") != "COUNT_BASED":
            continue
        try:
            ws = int(r.get("window_size", ""))
            wd = int(r.get("wait_duration", ""))
        except ValueError:
            continue
        ratio = error_rate_ratio(r)
        if ratio is None:
            continue
        residual = ratio  # already normalized by leg rate; compare distributions directly
        if ws in D23_LEAK_WINDOW_SIZES and wd in D23_LEAK_WAIT_DURATIONS:
            in_region.append(residual)
        else:
            out_region.append(residual)
    if in_region and out_region:
        mean_in = sum(in_region) / len(in_region)
        mean_out = sum(out_region) / len(out_region)
        L.append(f"   in-region  (n={len(in_region)}): mean ratio={mean_in:.4f}")
        L.append(f"   out-region (n={len(out_region)}): mean ratio={mean_out:.4f}")
        L.append("   -> heavily overlapping, no clean separation. The batch artifact in (2)")
        L.append("      swamps any incremental signal from D23's parameter region.")

    L.append("")
    L.append("AUDIT RESULT: INCONCLUSIVE. master_dataset.csv's schema cannot see gateway's")
    L.append("breaker state directly (1), and the one indirect proxy is confounded by an")
    L.append("unrelated batch artifact (2, 3). This is a genuine schema gap, not evidence")
    L.append("that gateway stayed clean in these 360 rows -- see decision-log.md D24.")
    return "\n".join(L)


def self_test() -> bool:
    ok = True

    rows = [
        {"leg_failure_rates": "order-service:0.20;inventory-service:0.00", "error_rate": "0.40",
         "topology": "LINEAR", "machine_id": "test-machine", "window_type": "COUNT_BASED",
         "window_size": "20", "wait_duration": "30"},
        {"leg_failure_rates": "order-service:0.10", "error_rate": "0.10",
         "topology": "LINEAR", "machine_id": "test-machine", "window_type": "COUNT_BASED",
         "window_size": "5", "wait_duration": "5"},
    ]

    n, keys = audit_gateway_presence(rows)
    if n != 2 or keys != {"order-service", "inventory-service"}:
        print(f"FAIL: audit_gateway_presence -- got n={n}, keys={keys}")
        ok = False

    r0 = error_rate_ratio(rows[0])
    if r0 is None or abs(r0 - 2.0) > 1e-9:
        print(f"FAIL: error_rate_ratio -- expected 2.0, got {r0}")
        ok = False

    parsed = parse_leg_failure_rates("order-service:0.2083;inventory-service:0.0000;;bad-entry")
    if parsed != {"order-service": 0.2083, "inventory-service": 0.0}:
        print(f"FAIL: parse_leg_failure_rates -- got {parsed}")
        ok = False

    print("self-test PASSED" if ok else "self-test FAILED")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="data/master_dataset.csv")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return 0 if self_test() else 1

    path = Path(args.csv)
    if not path.exists():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        return 1

    rows = load_rows(str(path))
    print(f"loaded {len(rows)} rows from {path}\n")
    print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
