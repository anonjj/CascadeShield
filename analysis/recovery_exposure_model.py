"""
analysis/recovery_exposure_model.py

A window-type-BLIND simulation: does a model that knows only t_open, fault_cleared_at,
and wait_duration (D) -- and is structurally incapable of reading window_type or
window_size -- reproduce each HALF_OPEN episode's real outcome (bounce vs close) and
the real total recovery time? If it does, the window-type difference
recovery_fault_timing_check.py found is explained by fault-exposure timing alone, not
by any property of the breaker's configured window type.

Model (simulate_recovery): HALF_OPEN fires D seconds after each (re)open. If that
HALF_OPEN begins before fault_cleared_at, it bounces (reopens) after a fixed
E_FAIL=3.5s; otherwise it closes after a fixed E_OK=3.0s. Both constants are shared
across both arms. The enforcement that the model never reads window_type/window_size
is simulate_recovery's own signature: (t_open, fault_cleared_at, D[, e_fail, e_ok])
only -- there is no parameter to pass a window type through even by mistake.

Scope: order-service inventoryServiceCB, same as recovery_fault_timing_check.py, whose
_ts/SERVICE/BREAKER this module reuses directly rather than reimplementing.

Usage:
    python analysis/recovery_exposure_model.py [path/to/cb_transitions.jsonl]
    python analysis/recovery_exposure_model.py --self-test
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_fault_timing_check import _ts, SERVICE, BREAKER

E_FAIL = 3.5
E_OK = 3.0

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cb_transitions.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "out" / "recovery_exposure_model.json"

_D_RE = re.compile(r"-D(\d+)(?:-|$)")


def parse_wait_duration(experiment_id: str) -> int:
    """experiment_id format: {topo}-{fault}-{wtype}-T{threshold}-W{window}-D{wait}
    [-M{n_min}][-L{lambda}] (make_experiment_id, runner.py) -- D always immediately
    follows W and is itself followed by either another '-<letter>...' token or the
    string's end, so a single anchored regex is unambiguous against this fixed shape."""
    m = _D_RE.search(experiment_id)
    if not m:
        raise ValueError(f"no wait_duration found in experiment_id: {experiment_id!r}")
    return int(m.group(1))


def simulate_recovery(t_open: float, fault_cleared_at: float, D: float,
                       e_fail: float = E_FAIL, e_ok: float = E_OK):
    """Pure simulation. Takes ONLY (t_open, fault_cleared_at, D[, e_fail, e_ok]) -- no
    config dict, no window_type, no window_size, nothing this signature doesn't name.
    That is the whole enforcement mechanism: a caller cannot pass window information
    through by accident because there is no parameter for it.

    Returns (bounce_count, recovery_s): bounce_count is how many HALF_OPEN_TO_OPEN
    bounces the model predicts before the first successful close; recovery_s is the
    model's predicted t_open -> HALF_OPEN_TO_CLOSED duration."""
    t = t_open
    bounces = 0
    while True:
        half_open_at = t + D
        if half_open_at < fault_cleared_at:
            bounces += 1
            t = half_open_at + e_fail
        else:
            return bounces, (half_open_at + e_ok) - t_open


def gateway_tripped(rec: dict) -> bool:
    """Same D24 rule reused verbatim: a real gateway CLOSED_TO_OPEN anywhere in this
    record's transitions. Only meaningful for COUNT_BASED (D23's confound is
    COUNT-specific) -- see gateway_clean below."""
    return any(t.get("service") == "gateway" and t.get("state_transition") == "CLOSED_TO_OPEN"
               for t in rec.get("transitions", []))


def gateway_clean(rec: dict) -> bool:
    """D24's cleaning rule: TIME_BASED rows kept regardless (the confound is
    COUNT-specific); COUNT_BASED rows kept only if the gateway did not trip."""
    return rec.get("window_type") == "TIME_BASED" or not gateway_tripped(rec)


def extract_record(rec: dict):
    """-> dict with t_open, fault_cleared_at, D, observed_bounces,
    observed_recovery_s, window_type, experiment_id, fault_on_after_open_s -- or None
    when this record has no modelable order:inventoryServiceCB CLOSED_TO_OPEN event or
    no fault_cleared_at (nothing to anchor the model on)."""
    events = [t for t in rec.get("transitions", [])
              if t.get("service") == SERVICE and t.get("breaker") == BREAKER]
    t_open_str = next((e["creation_time"] for e in events
                        if e.get("state_transition") == "CLOSED_TO_OPEN"), None)
    if t_open_str is None or not rec.get("fault_cleared_at"):
        return None

    t_open = _ts(t_open_str)
    fault_cleared_at = _ts(rec["fault_cleared_at"])
    D = parse_wait_duration(rec["experiment_id"])

    observed_bounces = sum(1 for e in events if e.get("state_transition") == "HALF_OPEN_TO_OPEN")
    t_closed_str = None
    for e in events:
        if e.get("state_transition") == "HALF_OPEN_TO_CLOSED":
            t_closed_str = e["creation_time"]  # keep overwriting: the FINAL close
    observed_recovery_s = (_ts(t_closed_str) - t_open) if t_closed_str is not None else None

    return {
        "experiment_id": rec["experiment_id"],
        "window_type": rec.get("window_type"),
        "t_open": t_open,
        "fault_cleared_at": fault_cleared_at,
        "D": D,
        "observed_bounces": observed_bounces,
        "observed_recovery_s": observed_recovery_s,
        "fault_on_after_open_s": fault_cleared_at - t_open,
    }


def run_model(records, e_fail: float = E_FAIL, e_ok: float = E_OK):
    results = []
    for rec in records:
        extracted = extract_record(rec)
        if extracted is None:
            continue
        pred_bounces, pred_recovery = simulate_recovery(
            extracted["t_open"], extracted["fault_cleared_at"], extracted["D"], e_fail, e_ok)
        results.append({**extracted, "predicted_bounces": pred_bounces,
                         "predicted_recovery_s": pred_recovery})
    return results


def summarize(results):
    n = len(results)
    bounce_exact = sum(1 for r in results if r["predicted_bounces"] == r["observed_bounces"])
    diffs = [abs(r["observed_recovery_s"] - r["predicted_recovery_s"])
             for r in results if r["observed_recovery_s"] is not None]
    misses = [r for r in results if r["predicted_bounces"] != r["observed_bounces"]]
    return {
        "n": n,
        "bounce_exact": bounce_exact,
        "bounce_exact_fraction": f"{bounce_exact}/{n}",
        "recovery_abs_diff_median": statistics.median(diffs) if diffs else None,
        "recovery_abs_diff_max": max(diffs) if diffs else None,
        "n_with_observed_recovery": len(diffs),
        "bounce_misses": [
            {"experiment_id": r["experiment_id"], "window_type": r["window_type"],
             "fault_on_after_open_s": round(r["fault_on_after_open_s"], 1),
             "observed_bounces": r["observed_bounces"], "predicted_bounces": r["predicted_bounces"]}
            for r in misses
        ],
    }


def per_arm_dw_table(results):
    groups = defaultdict(list)
    for r in results:
        groups[(r["window_type"], r["D"])].append(r)
    table = []
    for (wt, D), rs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        fault_on = [r["fault_on_after_open_s"] for r in rs]
        obs_rec = [r["observed_recovery_s"] for r in rs if r["observed_recovery_s"] is not None]
        pred_rec = [r["predicted_recovery_s"] for r in rs]
        table.append({
            "window_type": wt, "wait_duration": D, "n": len(rs),
            "median_fault_on_after_open_s": statistics.median(fault_on),
            "mean_bounces": statistics.mean(r["observed_bounces"] for r in rs),
            "median_observed_recovery_s": statistics.median(obs_rec) if obs_rec else None,
            "median_predicted_recovery_s": statistics.median(pred_rec),
        })
    return table


def report(path: Path, label: str, filter_fn=None):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if filter_fn is not None:
        records = [r for r in records if filter_fn(r)]
    results = run_model(records)
    summary = summarize(results)
    table = per_arm_dw_table(results)

    print(f"\n{label}: {path} -- {summary['n']} modelable records")
    print(f"  bounce_count exact: {summary['bounce_exact_fraction']}")
    if summary["recovery_abs_diff_median"] is not None:
        print(f"  |observed - predicted| recovery_s: median {summary['recovery_abs_diff_median']:.3f}, "
              f"max {summary['recovery_abs_diff_max']:.3f}  (n={summary['n_with_observed_recovery']})")
    if summary["bounce_misses"]:
        print("  bounce_count misses:")
        for m in summary["bounce_misses"]:
            print(f"    {m['experiment_id']:32s} {str(m['window_type']):12s} "
                  f"fault_on_after_open={m['fault_on_after_open_s']:>8.1f}s  "
                  f"observed={m['observed_bounces']} predicted={m['predicted_bounces']}")
    print("  window_type   D_w    n   median_fault_on   mean_bounces   obs_median_rec   pred_median_rec")
    for row in table:
        obs = f"{row['median_observed_recovery_s']:.2f}" if row["median_observed_recovery_s"] is not None else "   -  "
        print(f"  {str(row['window_type']):12s}  {row['wait_duration']:4d}  {row['n']:3d}  "
              f"{row['median_fault_on_after_open_s']:15.2f}  {row['mean_bounces']:12.2f}  "
              f"{obs:>14s}  {row['median_predicted_recovery_s']:15.2f}")
    return summary, table


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1

    records = [json.loads(line) for line in Path(args.path).read_text().splitlines() if line.strip()]

    phase4b_summary, phase4b_table = report(
        args.path, "Phase 4B (machine_id=soham-local)",
        filter_fn=lambda r: r.get("machine_id") == "soham-local")

    older_summary, older_table = report(
        args.path, "Older, gateway-clean (D24 rule; machine_id != soham-local)",
        filter_fn=lambda r: r.get("machine_id") != "soham-local" and gateway_clean(r))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "e_fail": E_FAIL, "e_ok": E_OK,
        "phase4b": {"summary": phase4b_summary, "table": phase4b_table},
        "older_gateway_clean": {"summary": older_summary, "table": older_table},
    }, indent=2, default=str))
    print(f"\nWrote {OUT_PATH}")
    return 0


# --------------------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    print("parse_wait_duration")
    check("plain ID", parse_wait_duration("LIN-LAT-CNT-T50-W10-D15") == 15)
    check("with -M/-L suffix", parse_wait_duration("LIN-LAT-TIM-T50-W20-D15-M5-L10") == 15)
    check("D30 at the end", parse_wait_duration("FAN-LAT-CNT-T30-W20-D30") == 30)

    print("simulate_recovery: pure logic, hand-computed")
    # t_open=0, fault_cleared_at=10, D=5 -> HALF_OPEN at 5 (before clear=10) -> bounce,
    # reopens at 5+3.5=8.5 -> next HALF_OPEN at 8.5+5=13.5 (after clear=10) -> closes
    # at 13.5+3.0=16.5.
    bounces, recovery = simulate_recovery(0.0, 10.0, 5)
    check("one bounce then close", bounces == 1)
    check("recovery_s == 16.5", math.isclose(recovery, 16.5))
    # t_open=0, fault_cleared_at=2, D=5 -> HALF_OPEN at 5, already after clear=2 ->
    # closes immediately, recovery = 5+3.0 = 8.0, zero bounces.
    bounces2, recovery2 = simulate_recovery(0.0, 2.0, 5)
    check("zero bounces when D alone outlasts clearance", bounces2 == 0)
    check("recovery_s == 8.0", math.isclose(recovery2, 8.0))

    print("simulate_recovery's signature enforces window-type-blindness")
    sig = inspect.signature(simulate_recovery)
    check("no window_type/window_size parameter exists anywhere in the signature",
          set(sig.parameters) <= {"t_open", "fault_cleared_at", "D", "e_fail", "e_ok"})

    print("synthetic TIME trace: fault stays on past the first HALF_OPEN -> one bounce, "
          "then close (timestamps hand-derived from the model's own recursion: "
          "t_open=0, D=15 -> half_open_1=15 (before fault_cleared_at=20 -> bounce) -> "
          "reopen=15+3.5=18.5 -> half_open_2=18.5+15=33.5 (after clear=20 -> close) "
          "-> close=33.5+3.0=36.5)")
    time_rec = {
        "experiment_id": "LIN-LAT-TIM-T50-W20-D15", "window_type": "TIME_BASED",
        "fault_cleared_at": "2026-01-01T00:00:20Z",
        "transitions": [
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "CLOSED_TO_OPEN",
             "creation_time": "2026-01-01T00:00:00.0Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "OPEN_TO_HALF_OPEN",
             "creation_time": "2026-01-01T00:00:15.0Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "HALF_OPEN_TO_OPEN",
             "creation_time": "2026-01-01T00:00:18.5Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "OPEN_TO_HALF_OPEN",
             "creation_time": "2026-01-01T00:00:33.5Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "HALF_OPEN_TO_CLOSED",
             "creation_time": "2026-01-01T00:00:36.5Z"},
        ],
    }
    ex1 = extract_record(time_rec)
    check("extracted D == 15", ex1["D"] == 15)
    check("extracted observed_bounces == 1", ex1["observed_bounces"] == 1)
    pb1, pr1 = simulate_recovery(ex1["t_open"], ex1["fault_cleared_at"], ex1["D"])
    check("predicted bounces == observed bounces", pb1 == ex1["observed_bounces"] == 1)
    check("predicted recovery matches the real trace within 0.1s",
          abs(pr1 - ex1["observed_recovery_s"]) < 0.1)

    print("synthetic COUNT trace: fault clears well before D elapses -> zero bounces, "
          "immediate close")
    count_rec = {
        "experiment_id": "LIN-LAT-CNT-T50-W10-D15", "window_type": "COUNT_BASED",
        "fault_cleared_at": "2026-01-01T00:00:05Z",
        "transitions": [
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "CLOSED_TO_OPEN",
             "creation_time": "2026-01-01T00:00:00.0Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "OPEN_TO_HALF_OPEN",
             "creation_time": "2026-01-01T00:00:15.0Z"},
            {"service": SERVICE, "breaker": BREAKER, "state_transition": "HALF_OPEN_TO_CLOSED",
             "creation_time": "2026-01-01T00:00:18.0Z"},
        ],
    }
    ex2 = extract_record(count_rec)
    pb2, pr2 = simulate_recovery(ex2["t_open"], ex2["fault_cleared_at"], ex2["D"])
    check("zero predicted bounces, matches zero observed", pb2 == ex2["observed_bounces"] == 0)
    check("predicted recovery matches the real trace within 0.1s",
          abs(pr2 - ex2["observed_recovery_s"]) < 0.1)

    print("extract_record returns None when there's nothing to model")
    check("no fault_cleared_at -> None",
          extract_record({"experiment_id": "X-D5", "transitions": []}) is None)
    check("no order:inventoryServiceCB CLOSED_TO_OPEN -> None",
          extract_record({"experiment_id": "X-D5", "fault_cleared_at": "2026-01-01T00:00:05Z",
                           "transitions": []}) is None)

    return ok


if __name__ == "__main__":
    sys.exit(main())
