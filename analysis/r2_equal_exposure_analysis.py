"""
analysis/r2_equal_exposure_analysis.py

The pre-registered R2 analysis (docs/paper/r2-equal-exposure-plan.md, frozen at commit
9964211), followed in the exact order the plan specifies. Report-only: never writes to
decision-log.md, hypotheses.md, or any paper file -- that write (D29) is a separate,
later step for whoever drafts it.

Reuses rather than reimplements: stratified_cluster_permutation_test (exact_tests.py,
§5's named test) and check_run/load_poll/parse_ts (gateway_poll_verify.py, the
independent gateway witness Phase 4B already built and self-tested) -- a second,
parallel implementation of either would be exactly the kind of drift this project's own
decision log keeps finding.

Usage:
    python3 analysis/r2_equal_exposure_analysis.py
    python3 analysis/r2_equal_exposure_analysis.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exact_tests import stratified_cluster_permutation_test
from gateway_poll_verify import check_run, load_poll, parse_ts

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATASET_PATH = DATA_DIR / "r2_equal_exposure.csv"
TRANSITIONS_PATH = DATA_DIR / "r2_cb_transitions.jsonl"
POLL_PATH = DATA_DIR / "audit" / "r2_sweep_poll.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "out" / "r2_equal_exposure_analysis.json"

STRATA = (5.0, 15.0, 30.0)
P2_THRESHOLD_S = 1.0
E_FAIL_PHASE4B = 3.5
E_OK_PHASE4B = 3.0

# Phase 4B's own COUNT_BASED bounce finding (D22/decision-log.md), quoted here for the
# explicit §4-style comparison STEP 4 requires -- not recomputed, since it's a fact
# about a different, already-closed dataset.
PHASE4B_COUNT_BOUNCE_OBSERVATIONS = "0/18"


def _key(experiment_id, replicate):
    return (experiment_id, str(replicate))


def load_rows(path=DATASET_PATH):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_sidecar(path=TRANSITIONS_PATH):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# =============================================================================
# STEP 1 -- exclusions (§6), rules 1-5, in order, before any outcome column is read.
# =============================================================================

def apply_exclusions(rows, sidecar_records):
    """Returns (kept_rows, table) where table is an ORDERED list of
    {"rule": name, "removed_by_arm": {window_type: n}, "removed_ids": [...]}, one
    entry per rule, applied in sequence (each rule operates on what the previous one
    left). No field from recovery_event_s/bounce_count/time_to_recover is read here --
    only precondition_ok, the sidecar's own transitions, the horizon verdict,
    fault_on_after_open_s (a setup-timing diagnostic, not a recovery outcome), and
    lambda_deviation_flag.
    """
    sidecar_by_key = {_key(r["experiment_id"], r["replicate"]): r for r in sidecar_records}
    gw_tripped_keys = {
        _key(r["experiment_id"], r["replicate"])
        for r in sidecar_records
        if any(t.get("service") == "gateway" and t.get("state_transition") == "CLOSED_TO_OPEN"
               for t in r.get("transitions", []))
    }

    poll_ticks, poll_start, poll_stop = load_poll(POLL_PATH)
    verified_clean_keys = set()
    horizon_verdicts = {}
    for r in rows:
        k = _key(r["experiment_id"], r["replicate"])
        side = sidecar_by_key.get(k)
        if side is None:
            horizon_verdicts[k] = {"verdict": "NOT_VERIFIED", "issues": ["NO_SIDECAR_RECORD"]}
            continue
        lo = parse_ts(side.get("fault_injected_at"))
        hi = parse_ts(r.get("run_timestamp"))  # DEVIATION 02: end = run_timestamp
        if lo is None or hi is None:
            horizon_verdicts[k] = {"verdict": "NOT_VERIFIED", "issues": ["UNPARSEABLE_TIMESTAMP"]}
            continue
        sidecar_trips = k in gw_tripped_keys
        verdict = check_run(poll_ticks, poll_start, poll_stop, lo, hi, sidecar_trips)
        horizon_verdicts[k] = verdict
        if verdict["verdict"] == "VERIFIED_CLEAN":
            verified_clean_keys.add(k)

    table = []
    current = rows

    def record_rule(name, survivors):
        nonlocal current
        removed = [r for r in current if r not in survivors]
        by_arm = defaultdict(int)
        for r in removed:
            by_arm[r["window_type"]] += 1
        table.append({
            "rule": name,
            "n_removed": len(removed),
            "removed_by_arm": dict(by_arm),
            "removed_ids": [f'{r["experiment_id"]}#{r["replicate"]}' for r in removed],
        })
        current = survivors

    record_rule("1_aborted_runs", [r for r in current if r["precondition_ok"] == "True"])
    record_rule("2_gateway_trip", [r for r in current
                                    if _key(r["experiment_id"], r["replicate"]) not in gw_tripped_keys])
    record_rule("3_not_verified_clean", [r for r in current
                                          if _key(r["experiment_id"], r["replicate"]) in verified_clean_keys])

    def implausible_duration(r):
        dw = float(r["wait_duration"])
        expected = dw + 5.0
        fault_on = r.get("fault_on_after_open_s")
        if not fault_on:
            return True  # no setup-timing diagnostic at all is itself implausible/unusable
        return float(fault_on) > 10 * expected  # Phase 4B's host-sleep records were ~70-250x expected

    record_rule("4_implausible_duration", [r for r in current if not implausible_duration(r)])
    record_rule("5_lambda_deviation_flag", [r for r in current if r["lambda_deviation_flag"] != "True"])

    return current, table, horizon_verdicts, poll_ticks, poll_start, poll_stop, gw_tripped_keys


# =============================================================================
# STEP 2 -- verification horizon (§7): report by arm/stratum, plus the poller summary.
# =============================================================================

def summarize_horizon(rows, horizon_verdicts):
    by_arm_stratum = defaultdict(lambda: {"VERIFIED_CLEAN": 0, "NOT_VERIFIED": 0, "FAILED": 0})
    for r in rows:
        k = _key(r["experiment_id"], r["replicate"])
        v = horizon_verdicts.get(k, {"verdict": "NOT_VERIFIED"})["verdict"]
        by_arm_stratum[(r["window_type"], r["wait_duration"])][v] += 1
    return {f"{wt}|D{dw}": counts for (wt, dw), counts in sorted(by_arm_stratum.items())}


def summarize_poller(poll_ticks, poll_start, poll_stop, rows, sidecar_records):
    sidecar_by_key = {_key(r["experiment_id"], r["replicate"]): r for r in sidecar_records}
    non_closed_ticks = sum(
        1 for t in poll_ticks
        for st in (t.get("states") or {}).values() if st and st != "CLOSED"
    )
    no_state_ticks = sum(1 for t in poll_ticks if not (t.get("states") or {}))

    windows = []
    for r in rows:
        side = sidecar_by_key.get(_key(r["experiment_id"], r["replicate"]))
        if side is None:
            continue
        lo = parse_ts(side.get("fault_injected_at"))
        hi = parse_ts(r.get("run_timestamp"))
        if lo is not None and hi is not None:
            windows.append((lo, hi))

    def inside_any_window(t):
        return any(lo <= t <= hi for lo, hi in windows)

    no_state_inside_window = sum(
        1 for t in poll_ticks if not (t.get("states") or {}) and inside_any_window(t["t"])
    )

    return {
        "total_ticks": len(poll_ticks),
        "poll_start": poll_start,
        "poll_stop": poll_stop,
        "non_closed_state_ticks": non_closed_ticks,
        "no_state_ticks": no_state_ticks,
        "no_state_ticks_inside_a_run_window": no_state_inside_window,
    }


# =============================================================================
# STEP 3 -- config-level values (§5): configuration is the unit, mean of replicates.
# =============================================================================

def config_level_values(rows, value_col="recovery_event_s"):
    """-> {(window_type, wait_duration): {config_id: mean_value}}, plus a report dict
    covering censored replicates, excluded configs, and exact ties -- config_id here is
    experiment_id with the replicate suffix stripped (R2's experiment_ids already omit
    replicate, so experiment_id itself IS the config id)."""
    by_stratum_config = defaultdict(lambda: defaultdict(list))
    censored = []
    for r in rows:
        stratum_key = (r["window_type"], r["wait_duration"])
        val = r.get(value_col)
        if r.get("recovery_censored") == "True" or not val:
            censored.append(f'{r["experiment_id"]}#{r["replicate"]}')
            continue
        by_stratum_config[stratum_key][r["experiment_id"]].append(float(val))

    means = {}
    config_counts = {}
    for stratum_key, configs in by_stratum_config.items():
        means[stratum_key] = {cid: statistics.mean(vals) for cid, vals in configs.items()}
        config_counts[stratum_key] = {cid: len(vals) for cid, vals in configs.items()}

    ties = []
    for stratum_key, cfg_means in means.items():
        vals = list(cfg_means.values())
        if len(vals) != len(set(vals)):
            dupes = [v for v in vals if vals.count(v) > 1]
            ties.append({"stratum": stratum_key, "tied_values": sorted(set(dupes))})

    n_configs_by_arm_stratum = {
        f"{wt}|D{dw}": len(cfg_means) for (wt, dw), cfg_means in means.items()
    }

    return {
        "means": means,
        "config_counts": config_counts,
        "censored_replicates": censored,
        "n_configs_by_arm_stratum": n_configs_by_arm_stratum,
        "ties": ties,
    }


# =============================================================================
# STEP 4 -- P1, the bounce prediction (§3).
# =============================================================================

def bounce_report(rows):
    by_arm_stratum = defaultdict(list)
    for r in rows:
        by_arm_stratum[(r["window_type"], r["wait_duration"])].append(int(r["bounce_count"]))

    report = {}
    all_exactly_one = True
    for (wt, dw), vals in sorted(by_arm_stratum.items()):
        exactly_one = all(v == 1 for v in vals)
        all_exactly_one = all_exactly_one and exactly_one
        report[f"{wt}|D{dw}"] = {
            "n": len(vals), "min": min(vals), "max": max(vals),
            "all_exactly_1": exactly_one,
        }
    return report, all_exactly_one


# =============================================================================
# STEP 5 -- P2, the arm-difference equivalence test (§3, §5).
# =============================================================================

def p2_primary(means_by_stratum):
    """(a) PRIMARY: per-stratum median recovery for each arm, absolute difference vs
    the 1s threshold."""
    report = {}
    for dw in STRATA:
        time_key = ("TIME_BASED", str(int(dw)))
        count_key = ("COUNT_BASED", str(int(dw)))
        time_vals = list(means_by_stratum.get(time_key, {}).values())
        count_vals = list(means_by_stratum.get(count_key, {}).values())
        if not time_vals or not count_vals:
            report[f"D{int(dw)}"] = {"error": "missing arm", "time_n": len(time_vals),
                                      "count_n": len(count_vals)}
            continue
        time_median = statistics.median(time_vals)
        count_median = statistics.median(count_vals)
        diff = abs(time_median - count_median)
        report[f"D{int(dw)}"] = {
            "time_median": time_median, "count_median": count_median,
            "abs_diff": diff, "threshold_s": P2_THRESHOLD_S,
            "passes_equivalence": diff < P2_THRESHOLD_S,
        }
    return report


def p2_direction_consistency(means_by_stratum):
    """(b) Direction (sign of TIME - COUNT median) per stratum, reported before any
    pooled p-value."""
    signs = {}
    for dw in STRATA:
        time_key = ("TIME_BASED", str(int(dw)))
        count_key = ("COUNT_BASED", str(int(dw)))
        time_vals = list(means_by_stratum.get(time_key, {}).values())
        count_vals = list(means_by_stratum.get(count_key, {}).values())
        if not time_vals or not count_vals:
            signs[f"D{int(dw)}"] = None
            continue
        d = statistics.median(time_vals) - statistics.median(count_vals)
        signs[f"D{int(dw)}"] = "TIME_higher" if d > 0 else ("COUNT_higher" if d < 0 else "tied")
    consistent = len({s for s in signs.values() if s is not None}) <= 1
    return signs, consistent


def p2_secondary_test(means_by_stratum):
    """(c) SECONDARY: stratified_cluster_permutation_test, strata {5,15,30}."""
    strata_input = {}
    for dw in STRATA:
        time_vals = means_by_stratum.get(("TIME_BASED", str(int(dw))), {})
        count_vals = means_by_stratum.get(("COUNT_BASED", str(int(dw))), {})
        if not time_vals or not count_vals:
            continue
        # group1 = COUNT, group2 = TIME -- matches this project's established convention
        # (canary_readout.py / order_leg_containment.py / window_type_recovery_leak.py all
        # order COUNT first).
        strata_input[f"D{int(dw)}"] = (dict(count_vals), dict(time_vals))

    if not strata_input:
        return {"error": "no usable strata"}

    result = stratified_cluster_permutation_test(strata_input, two_sided=True)
    return {
        "statistic": result.statistic,
        "p_value": result.p_value,
        "p_value_one_sided": result.p_value_one_sided,
        "p_floor_two_sided": result.p_floor_two_sided,
        "p_floor_one_sided": result.p_floor_one_sided,
        "total_assignments": result.total_assignments,
        "strata": [{"name": s.name, "n1": s.n1, "n2": s.n2,
                    "n_assignments": s.n_assignments,
                    "observed_statistic": s.observed_statistic} for s in result.strata],
        "note": "A non-significant result does NOT by itself establish equivalence (§5). "
                "The primary evidence for P2 is the per-stratum median-difference check "
                "above, not this p-value.",
    }


# =============================================================================
# STEP 6 -- secondary descriptive prediction (§4): NOT a test of D28.
# =============================================================================

def descriptive_model_fit(means_by_stratum):
    report = {}
    for dw in STRATA:
        predicted = 2 * dw + (E_FAIL_PHASE4B + E_OK_PHASE4B)
        all_vals = []
        for wt in ("TIME_BASED", "COUNT_BASED"):
            all_vals.extend(means_by_stratum.get((wt, str(int(dw))), {}).values())
        if not all_vals:
            continue
        observed_median = statistics.median(all_vals)
        gap = observed_median - predicted
        # What E_FAIL + E_OK would have to sum to, to fit jay-mac exactly at this D_w
        # (same "one bounce, D_w, episode-sum" model, solved for the episode-sum term):
        implied_episode_sum = observed_median - 2 * dw
        report[f"D{int(dw)}"] = {
            "predicted_phase4b_constants_s": predicted,
            "observed_median_s": observed_median,
            "gap_s": gap,
            "implied_episode_sum_for_jay_mac_s": implied_episode_sum,
        }
    return report


# =============================================================================
# STEP 7 -- falsification check (§3).
# =============================================================================

def falsification_check(bounce_report_result, p2_primary_result):
    bounce_differs_systematically = not all(
        v["all_exactly_1"] for v in bounce_report_result.values()
    )
    gap_over_1s_same_direction = False
    directions = set()
    for dw_key, v in p2_primary_result.items():
        if "error" in v:
            continue
        if v["abs_diff"] > 1.0:
            sign = "TIME_higher" if v["time_median"] > v["count_median"] else "COUNT_higher"
            directions.add((dw_key, sign))
    strata_over_1s = {d for d, _ in directions}
    signs_over_1s = {s for _, s in directions}
    if len(strata_over_1s) == len(STRATA) and len(signs_over_1s) == 1:
        gap_over_1s_same_direction = True

    return {
        "bounce_counts_differ_systematically_by_window_type": bounce_differs_systematically,
        "recovery_gap_over_1s_same_direction_all_strata": gap_over_1s_same_direction,
        "falsified": bounce_differs_systematically or gap_over_1s_same_direction,
    }


# =============================================================================
# Orchestration / report printing
# =============================================================================

def run_analysis():
    rows = load_rows()
    sidecar = load_sidecar()

    kept, exclusion_table, horizon_verdicts, poll_ticks, poll_start, poll_stop, gw_keys = \
        apply_exclusions(rows, sidecar)

    horizon_summary = summarize_horizon(rows, horizon_verdicts)
    poller_summary = summarize_poller(poll_ticks, poll_start, poll_stop, rows, sidecar)

    cfg = config_level_values(kept, "recovery_event_s")
    means_flat = cfg["means"]  # {(window_type, wait_duration_str): {config_id: mean}}

    bounces, p1_all_one = bounce_report(kept)
    p2a = p2_primary(means_flat)
    p2b_signs, p2b_consistent = p2_direction_consistency(means_flat)
    p2c = p2_secondary_test(means_flat)
    step6 = descriptive_model_fit(means_flat)
    step7 = falsification_check(bounces, p2a)

    # JSON can't key a dict by tuple -- means/config_counts are tuple-keyed internally
    # (convenient for STEP 4-6's lookups above); stringify only for the written report.
    cfg_json_safe = {
        **cfg,
        "means": {f"{wt}|D{dw}": m for (wt, dw), m in cfg["means"].items()},
        "config_counts": {f"{wt}|D{dw}": c for (wt, dw), c in cfg["config_counts"].items()},
        "ties": [{"stratum": f"{s[0]}|D{s[1]}", "tied_values": t["tied_values"]}
                 for t in cfg["ties"] for s in [t["stratum"]]],
    }

    return {
        "n_rows_total": len(rows),
        "n_rows_kept": len(kept),
        "step1_exclusions": exclusion_table,
        "step2_horizon_by_arm_stratum": horizon_summary,
        "step2_poller_summary": poller_summary,
        "step3_config_level": cfg_json_safe,
        "step4_bounce_report": bounces,
        "step4_p1_all_exactly_one": p1_all_one,
        "step4_phase4b_count_bounce_comparison": PHASE4B_COUNT_BOUNCE_OBSERVATIONS,
        "step5a_p2_primary": p2a,
        "step5b_direction_signs": p2b_signs,
        "step5b_direction_consistent": p2b_consistent,
        "step5c_p2_secondary_test": p2c,
        "step6_descriptive_model_fit": step6,
        "step7_falsification": step7,
    }


def print_report(result):
    print(f"\nR2 equal-exposure analysis -- {result['n_rows_total']} rows loaded, "
          f"{result['n_rows_kept']} kept after exclusions\n")

    print("STEP 1 -- exclusions (§6), applied in order, BEFORE any outcome column was read")
    for entry in result["step1_exclusions"]:
        print(f"  {entry['rule']}: removed {entry['n_removed']} "
              f"(by arm: {entry['removed_by_arm']})")

    print("\nSTEP 2 -- verification horizon (§7), end = run_timestamp (DEVIATION 02)")
    for key, counts in result["step2_horizon_by_arm_stratum"].items():
        print(f"  {key}: {counts}")
    ps = result["step2_poller_summary"]
    print(f"  poller: {ps['total_ticks']} ticks, {ps['non_closed_state_ticks']} "
          f"non-CLOSED observed, {ps['no_state_ticks']} ticks with no state "
          f"({ps['no_state_ticks_inside_a_run_window']} of those inside a run's window)")

    print("\nSTEP 3 -- config-level values (§5)")
    print(f"  configs per arm per stratum: {result['step3_config_level']['n_configs_by_arm_stratum']}")
    print(f"  censored replicates: {result['step3_config_level']['censored_replicates']}")
    print(f"  exact ties: {result['step3_config_level']['ties']}")

    print("\nSTEP 4 -- P1, the bounce prediction (§3)")
    for key, v in result["step4_bounce_report"].items():
        print(f"  {key}: n={v['n']} min={v['min']} max={v['max']} "
              f"all_exactly_1={v['all_exactly_1']}")
    print(f"  P1 holds across every arm/stratum: {result['step4_p1_all_exactly_one']}")
    print(f"  Phase 4B comparison: COUNT_BASED bounced in "
          f"{result['step4_phase4b_count_bounce_comparison']} observations there")

    print("\nSTEP 5 -- P2, the arm-difference equivalence test (§3, §5)")
    print("  (a) PRIMARY -- per-stratum median recovery, vs 1s threshold:")
    for key, v in result["step5a_p2_primary"].items():
        if "error" in v:
            print(f"    {key}: {v}")
            continue
        print(f"    {key}: TIME={v['time_median']:.3f}s COUNT={v['count_median']:.3f}s "
              f"|diff|={v['abs_diff']:.3f}s passes(<1s)={v['passes_equivalence']}")
    print(f"  (b) direction signs (before any pooled p-value): "
          f"{result['step5b_direction_signs']} -- consistent: "
          f"{result['step5b_direction_consistent']}")
    print("  (c) SECONDARY -- stratified_cluster_permutation_test:")
    p2c = result["step5c_p2_secondary_test"]
    if "error" in p2c:
        print(f"    {p2c}")
    else:
        print(f"    statistic={p2c['statistic']:.4f} p={p2c['p_value']:.6f} "
              f"(floor={p2c['p_floor_two_sided']:.6f}, "
              f"total_assignments={p2c['total_assignments']})")
        print(f"    {p2c['note']}")

    print("\nSTEP 6 -- secondary descriptive prediction (§4), NOT a test of D28")
    for key, v in result["step6_descriptive_model_fit"].items():
        print(f"  {key}: predicted(Phase4B consts)={v['predicted_phase4b_constants_s']:.1f}s "
              f"observed_median={v['observed_median_s']:.3f}s gap={v['gap_s']:+.3f}s "
              f"implied_E_FAIL+E_OK_for_jay_mac={v['implied_episode_sum_for_jay_mac_s']:.3f}s")

    print("\nSTEP 7 -- falsification check (§3)")
    f = result["step7_falsification"]
    print(f"  bounce counts differ systematically by window type: "
          f"{f['bounce_counts_differ_systematically_by_window_type']}")
    print(f"  recovery gap > 1s, same direction, all three strata: "
          f"{f['recovery_gap_over_1s_same_direction_all_strata']}")
    print(f"  D28 FALSIFIED: {f['falsified']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1

    result = run_analysis()
    print_report(result)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nWrote {OUT_PATH}")
    return 0


# --------------------------------------------------------------------------- self-test

def self_test():
    ok = True

    def check(name, cond):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    print("apply_exclusions: rule 1 (aborted runs)")
    rows = [
        {"experiment_id": "A", "replicate": "1", "window_type": "COUNT_BASED",
         "wait_duration": "5", "precondition_ok": "True", "lambda_deviation_flag": "",
         "fault_on_after_open_s": "10.1", "recovery_event_s": "14.0",
         "recovery_censored": "False", "run_timestamp": "2026-01-01T00:00:20Z"},
        {"experiment_id": "B", "replicate": "1", "window_type": "COUNT_BASED",
         "wait_duration": "5", "precondition_ok": "False", "lambda_deviation_flag": "",
         "fault_on_after_open_s": "", "recovery_event_s": "", "recovery_censored": "",
         "run_timestamp": "2026-01-01T00:00:20Z"},
    ]
    sidecar = [
        {"experiment_id": "A", "replicate": 1, "fault_injected_at": "2026-01-01T00:00:00Z",
         "fault_cleared_at": "2026-01-01T00:00:10Z", "transitions": []},
        {"experiment_id": "B", "replicate": 1, "fault_injected_at": "2026-01-01T00:00:00Z",
         "fault_cleared_at": "2026-01-01T00:00:10Z", "transitions": []},
    ]
    import tempfile
    # 2026-01-01T00:00:00Z == 1767225600.0 -- poll ticks must actually cover the
    # fixtures' ISO timestamps, not an arbitrary unrelated epoch range.
    EPOCH_BASE = 1767225600.0
    with tempfile.TemporaryDirectory() as tmpdir:
        poll_path = Path(tmpdir) / "poll.jsonl"
        with open(poll_path, "w") as f:
            f.write(json.dumps({"_meta": "poller_start", "t": EPOCH_BASE - 5.0}) + "\n")
            t = EPOCH_BASE - 5.0
            while t < EPOCH_BASE + 100.0:
                f.write(json.dumps({"states": {"orderServiceCB": "CLOSED",
                                                "inventoryServiceCB": "CLOSED",
                                                "paymentServiceCB": "CLOSED"},
                                     "buffered": {}, "errors": [], "ok": True, "t": t}) + "\n")
                t += 1.0

        global POLL_PATH
        original_poll_path = POLL_PATH
        POLL_PATH = poll_path
        try:
            kept, table, verdicts, *_ = apply_exclusions(rows, sidecar)
        finally:
            POLL_PATH = original_poll_path

    check("rule 1 removes exactly the aborted row", table[0]["n_removed"] == 1
          and table[0]["removed_ids"] == ["B#1"])
    check("the clean row A survives through exclusions", len(kept) == 1 and kept[0]["experiment_id"] == "A")

    print("apply_exclusions: rule 4 (implausible duration, host-sleep shape)")
    bad_rows = [
        {"experiment_id": "C", "replicate": "1", "window_type": "TIME_BASED",
         "wait_duration": "5", "precondition_ok": "True", "lambda_deviation_flag": "",
         "fault_on_after_open_s": "701.0", "recovery_event_s": "710.0",
         "recovery_censored": "False", "run_timestamp": "2026-01-01T00:00:20Z"},
    ]
    bad_sidecar = [
        {"experiment_id": "C", "replicate": 1, "fault_injected_at": "2026-01-01T00:00:00Z",
         "fault_cleared_at": "2026-01-01T00:00:10Z", "transitions": []},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        poll_path = Path(tmpdir) / "poll.jsonl"
        with open(poll_path, "w") as f:
            f.write(json.dumps({"_meta": "poller_start", "t": EPOCH_BASE - 5.0}) + "\n")
            t = EPOCH_BASE - 5.0
            while t < EPOCH_BASE + 100.0:
                f.write(json.dumps({"states": {"orderServiceCB": "CLOSED",
                                                "inventoryServiceCB": "CLOSED",
                                                "paymentServiceCB": "CLOSED"},
                                     "buffered": {}, "errors": [], "ok": True, "t": t}) + "\n")
                t += 1.0
        POLL_PATH = poll_path
        kept_bad, table_bad, *_ = apply_exclusions(bad_rows, bad_sidecar)
    check("a Phase-4B-host-sleep-shaped fault_on_after_open_s (701s against D_w=5's "
          "expected 10s) is caught by rule 4", len(kept_bad) == 0
          and table_bad[3]["n_removed"] == 1)

    print("config_level_values: mean-of-replicates, censored replicates excluded")
    rows2 = [
        {"experiment_id": "X", "replicate": "1", "window_type": "COUNT_BASED",
         "wait_duration": "5", "recovery_event_s": "10.0", "recovery_censored": "False"},
        {"experiment_id": "X", "replicate": "2", "window_type": "COUNT_BASED",
         "wait_duration": "5", "recovery_event_s": "12.0", "recovery_censored": "False"},
        {"experiment_id": "X", "replicate": "3", "window_type": "COUNT_BASED",
         "wait_duration": "5", "recovery_event_s": "", "recovery_censored": "True"},
    ]
    cfg = config_level_values(rows2, "recovery_event_s")
    check("config X's mean is 11.0 (two clean replicates, one censored excluded)",
          cfg["means"][("COUNT_BASED", "5")]["X"] == 11.0)
    check("the censored replicate is reported, not silently dropped",
          cfg["censored_replicates"] == ["X#3"])

    print("bounce_report: P1 all-exactly-1 detection")
    rows3 = [
        {"window_type": "COUNT_BASED", "wait_duration": "5", "bounce_count": "1"},
        {"window_type": "COUNT_BASED", "wait_duration": "5", "bounce_count": "1"},
        {"window_type": "TIME_BASED", "wait_duration": "5", "bounce_count": "2"},
    ]
    report, all_one = bounce_report(rows3)
    check("mixed bounce counts correctly flagged as NOT all-exactly-1", all_one is False)
    check("the COUNT_BASED|D5 cell itself is still correctly all-exactly-1",
          report["COUNT_BASED|D5"]["all_exactly_1"] is True)

    print("p2_primary / p2_direction_consistency")
    means = {
        ("TIME_BASED", "5"): {"c1": 14.0, "c2": 14.5, "c3": 13.8, "c4": 14.2},
        ("COUNT_BASED", "5"): {"c5": 14.1, "c6": 13.9, "c7": 14.0, "c8": 14.3},
    }
    p2a = p2_primary(means)
    check("D5 passes equivalence (medians nearly identical, well under 1s)",
          p2a["D5"]["passes_equivalence"] is True)
    signs, consistent = p2_direction_consistency(means)
    check("direction sign is recorded for D5", signs["D5"] in ("TIME_higher", "COUNT_higher", "tied"))

    print("falsification_check")
    bounces_bad = {"COUNT_BASED|5": {"all_exactly_1": False}, "TIME_BASED|5": {"all_exactly_1": True}}
    p2_bad = {"D5": {"time_median": 20.0, "count_median": 10.0, "abs_diff": 10.0},
              "D15": {"time_median": 30.0, "count_median": 20.0, "abs_diff": 10.0},
              "D30": {"time_median": 45.0, "count_median": 35.0, "abs_diff": 10.0}}
    f_bad = falsification_check(bounces_bad, p2_bad)
    check("a bounce-count mismatch alone triggers falsification",
          f_bad["bounce_counts_differ_systematically_by_window_type"] is True
          and f_bad["falsified"] is True)
    f_gap = falsification_check(
        {"COUNT_BASED|5": {"all_exactly_1": True}, "TIME_BASED|5": {"all_exactly_1": True}},
        p2_bad)
    check(">1s gap, same direction, in all three strata triggers falsification on its own",
          f_gap["recovery_gap_over_1s_same_direction_all_strata"] is True
          and f_gap["falsified"] is True)
    p2_clean = {"D5": {"time_median": 14.0, "count_median": 13.9, "abs_diff": 0.1},
                "D15": {"time_median": 24.0, "count_median": 23.9, "abs_diff": 0.1},
                "D30": {"time_median": 39.0, "count_median": 38.9, "abs_diff": 0.1}}
    f_clean = falsification_check(
        {"COUNT_BASED|5": {"all_exactly_1": True}, "TIME_BASED|5": {"all_exactly_1": True}},
        p2_clean)
    check("clean bounces + small gaps -> not falsified", f_clean["falsified"] is False)

    return ok


if __name__ == "__main__":
    sys.exit(main())
