#!/usr/bin/env python3
"""Diagnostic: confirms or refutes the leg_failure_rate blending hypothesis.

Finding this investigates: a canary_matrix.py smoke-test row (LIN-LAT-TIM-T50-W20-D15-L320)
recorded order-service's leg_failure_rate at 0.4870 -- suspiciously close to 0.50, and
matching docs/paper/hypotheses.md's unrelated archive dataset's 0.4867 almost exactly.

Hypothesis: runner.py's _get_cb_metric_count() sums a metric ACROSS ALL of a service's
circuit breakers -- its actuator query filters only by `tag=kind:{outcome}`, never by which
CB. order-service has TWO breakers (inventoryServiceCB, guarding the call that actually hits
the injected fault; sharedDbCB, guarding a call to shared-db-service that's completely
unaffected by this fault). OrderController.order() calls both once per request, unconditionally
-- so the "leg" reading compute_leg_failure_rates() produces is really an unweighted blend of
"near-100%-failed" (inventory side) and "~0%-failed" (shared-db side), landing near 50% BY
CONSTRUCTION, regardless of how severe the real fault is. Order/inventory/payment all have
this same 2-breaker shape (a "next hop" + shared-db); notification has only one breaker
(sharedDbCB alone) and should NOT show this artifact.

This script polls order-service's two breakers SEPARATELY, via a name-filtered actuator query
neither snapshot_cb_calls() nor compute_leg_failure_rates() uses, alongside the harness's own
blended reading -- across several replicates of the same config -- to check whether the
individual breakers actually sit near 0%/100% while the blend sits near 50% (confirming the
mechanism) or something else is going on.

Reuses runner.py's existing machinery end to end (write_env_file, update_containers,
wait_for_readiness, reset_all_breakers, warmup_phase, generate_load, compute_load_plan,
inject_fault, snapshot_cb_calls, compute_leg_failure_rates) -- no new execution logic, only
new measurement (the name-filtered per-breaker query) layered alongside the existing one.
Skips the recovery-wait phase deliberately -- this is a diagnostic about failure-rate
measurement, not a timing measurement, and doesn't need it.

Usage: python3 experiments/diagnose_leg_blend.py [--replicates N] [--target-rps R]
Default config matches the canary_matrix.py smoke-test row that surfaced this
(TIME_BASED, threshold=50, window_size=20, wait_duration=15, n_min=5, lambda=320).
"""
import argparse
import statistics
import sys
import time
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import (  # noqa: E402
    CB_METRIC_TARGETS, check_breaker_precondition, compute_leg_failure_rates,
    compute_load_plan, generate_load, inject_fault, reset_all_breakers, snapshot_cb_calls,
    toxiproxy, update_containers, wait_for_readiness, warmup_phase, write_env_file,
)

TOPOLOGY = "linear"
ENDPOINT = f"http://localhost:8080/api/v1/{TOPOLOGY}"
# order-service's own two breakers -- the ones this script isolates.
FAULTED_CB = "inventoryServiceCB"     # guards order -> inventory, which the fault hits directly
UNAFFECTED_CB = "sharedDbCB"          # guards order -> shared-db, untouched by this fault


def get_cb_metric_by_name(base_url, metric, kind, cb_name):
    """Like runner.py's _get_cb_metric_count, but filtered to ONE circuit breaker by name --
    the query that's missing from the existing harness and the reason this diagnostic exists."""
    url = f"{base_url}/actuator/metrics/{metric}?tag=kind:{kind}&tag=name:{cb_name}"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                for m in data.get("measurements", []):
                    if m.get("statistic") == "COUNT":
                        return float(m.get("value", 0.0))
    except Exception:
        pass
    return None


def snapshot_cb_by_name(base_url, cb_name):
    success = get_cb_metric_by_name(base_url, "resilience4j.circuitbreaker.calls", "successful", cb_name)
    failed = get_cb_metric_by_name(base_url, "resilience4j.circuitbreaker.calls", "failed", cb_name)
    rejected = get_cb_metric_by_name(base_url, "resilience4j.circuitbreaker.not.permitted.calls",
                                     "not_permitted", cb_name)
    if success is None and failed is None and rejected is None:
        return None
    return {"success": success or 0.0, "failed": failed or 0.0, "rejected": rejected or 0.0}


def rate_from_snapshot(before, after):
    if not before or not after:
        return None
    d_success = max(after["success"] - before["success"], 0.0)
    d_failed = max(after["failed"] - before["failed"], 0.0)
    d_rejected = max(after["rejected"] - before["rejected"], 0.0)
    total = d_success + d_failed + d_rejected
    if total <= 0:
        return None
    return (d_failed + d_rejected) / total


def one_replicate(config, rep):
    print(f"\n--- replicate {rep} ---")
    write_env_file(config)
    if not update_containers():
        print("Container recreate failed, skipping replicate.", file=sys.stderr)
        return None
    all_ready, _ = wait_for_readiness()
    if not all_ready:
        print("Readiness timeout, skipping replicate.", file=sys.stderr)
        return None
    reset_all_breakers()
    precondition = check_breaker_precondition()
    if not precondition["ok"]:
        print(f"Precondition failed ({precondition['fail_reason']}), skipping replicate.",
              file=sys.stderr)
        return None

    warmup_phase(ENDPOINT)

    order_base = CB_METRIC_TARGETS["order-service"]
    before_blended = snapshot_cb_calls()
    before_faulted = snapshot_cb_by_name(order_base, FAULTED_CB)
    before_unaffected = snapshot_cb_by_name(order_base, UNAFFECTED_CB)

    try:
        inject_fault("latency")
    except Exception as e:
        print(f"Fault injection failed: {e}", file=sys.stderr)
        return None

    plan = compute_load_plan(config, target_rps=config["targetRps"], mode="diagnostic",
                              fault_type="latency")
    print(f"Load plan: {plan['requests_count']} requests, concurrency={plan['concurrency']}, "
          f"~{plan['duration_s']:.0f}s @ {plan['target_rps']} req/s")
    throughput, error_rate, avg_latency, lambda_achieved, lambda_cv = generate_load(
        ENDPOINT, requests_count=plan["requests_count"], concurrency=plan["concurrency"],
        interval_s=plan["interval_s"])

    after_blended = snapshot_cb_calls()
    after_faulted = snapshot_cb_by_name(order_base, FAULTED_CB)
    after_unaffected = snapshot_cb_by_name(order_base, UNAFFECTED_CB)

    toxiproxy.reset_all()

    blended_rates = compute_leg_failure_rates(before_blended, after_blended)
    blended = blended_rates.get("order-service")
    faulted_rate = rate_from_snapshot(before_faulted, after_faulted)
    unaffected_rate = rate_from_snapshot(before_unaffected, after_unaffected)

    print(f"  lambda_achieved={lambda_achieved}  error_rate={error_rate:.2f}%")
    print(f"  blended order-service leg (existing harness metric): "
          f"{blended if blended is not None else 'n/a'}")
    print(f"  {FAULTED_CB} alone (hits the fault directly):        "
          f"{faulted_rate if faulted_rate is not None else 'n/a'}")
    print(f"  {UNAFFECTED_CB} alone (untouched by this fault):     "
          f"{unaffected_rate if unaffected_rate is not None else 'n/a'}")

    return {"blended": blended, "faulted": faulted_rate, "unaffected": unaffected_rate}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replicates", type=int, default=5,
                     help="how many times to repeat the same config (default 5, matching "
                          "canary_matrix.py's own REPLICATES for this cell)")
    ap.add_argument("--target-rps", type=int, default=320)
    ap.add_argument("--window-size", type=int, default=20)
    ap.add_argument("--threshold", type=int, default=50)
    ap.add_argument("--wait-duration", type=int, default=15)
    args = ap.parse_args()

    config = {
        "failureRateThreshold": args.threshold,
        "slidingWindowSize": args.window_size,
        "waitDurationInOpenState": args.wait_duration,
        "slidingWindowType": "TIME_BASED",
        "minimumNumberOfCalls": 5,
        "targetRps": args.target_rps,
    }
    print(f"Config: {config}")
    print(f"Running {args.replicates} replicates to check whether the blended order-service "
          f"leg reading is a stable ~50% structural artifact or something else.")

    try:
        toxiproxy.setup_default_proxies()
        toxiproxy.reset_all()
    except Exception:
        print("Toxiproxy unreachable -- is the mesh up? (docker compose up -d)", file=sys.stderr)
        sys.exit(1)

    results = []
    for rep in range(1, args.replicates + 1):
        r = one_replicate(config, rep)
        if r is not None:
            results.append(r)

    print("\n" + "=" * 70)
    print(f"SUMMARY ({len(results)}/{args.replicates} replicates completed)")
    print("=" * 70)
    for label, key in [("blended order-service leg", "blended"),
                        (f"{FAULTED_CB} alone", "faulted"),
                        (f"{UNAFFECTED_CB} alone", "unaffected")]:
        vals = [r[key] for r in results if r[key] is not None]
        if vals:
            print(f"  {label:32} n={len(vals)}  mean={statistics.mean(vals):.4f}  "
                  f"stdev={statistics.stdev(vals) if len(vals) > 1 else 0.0:.4f}  "
                  f"values={[round(v, 4) for v in vals]}")
        else:
            print(f"  {label:32} no measurable values")

    print("\nExpected if the blending hypothesis is correct: blended clusters near 0.5,")
    print(f"{FAULTED_CB} alone clusters near 1.0, {UNAFFECTED_CB} alone clusters near 0.0.")
    print("If blended instead tracks close to one of the individual breakers, or all three")
    print("vary together, the blending explanation is wrong and needs rethinking.")


if __name__ == "__main__":
    main()
