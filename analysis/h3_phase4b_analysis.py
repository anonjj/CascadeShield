"""H3 primary analysis on the Phase 4B dataset, per the pre-registration at 3e4ad1e.

    python analysis/h3_phase4b_analysis.py
    python analysis/h3_phase4b_analysis.py --horizon literal     # the frozen rule
    python analysis/h3_phase4b_analysis.py --self-test

VERIFICATION RULE
-----------------
The primary analysis set is the runs VERIFIED_CLEAN under **DEVIATION 02**
(`docs/paper/deviation-02-horizon-simplification.md`): horizon = fault_injected_at ..
run_timestamp, which reads no measurement column at all.

DEVIATION 01 (`docs/paper/deviation-01-verification-horizon.md`) is the superseded
intermediate step. It diagnosed the defect -- the §5 horizon over-covers past each run's own
end by an amount proportional to `time_to_recover`, the dependent variable, and so reaches
into the next run's `update_containers()` window where the gateway is down on purpose -- and
its `min(§5 horizon, run_timestamp)` produces verdicts identical to DEVIATION 02's on all 72
runs. DEVIATION 02 supersedes it only because it needs no argument about circularity.

Under the **literal** pre-registered rule the TIME arm is empty in two strata and 1-of-4 in
the third, so §3's zero-configuration clause excludes all three strata, fewer than two
survive, and **the stratified test is not run at all**. That is reported as "insufficient
clean data in stratum D_w=N", never as a null result. `--horizon literal` reproduces it.

The pre-registration itself is NOT edited and is byte-identical to
3e4ad1e5d0596883bbd35604828d0d2db39a9eb2.

WHAT IS PRE-REGISTERED AND WHAT IS NOT
--------------------------------------
Pre-registered and followed exactly: the §3 config-level value rule, the §3.1 applicability
test, the §4 exclusion rules and their order, the §7 same-sign validity condition checked
BEFORE any pooled p-value is quoted, the §2 primary test and its secondary, and §8's claim
scope. Deviating: the verification horizon only (§5/§6), per DEVIATION 01/02.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exact_tests as et  # noqa: E402
import gateway_poll_verify as gpv  # noqa: E402
from phase4b_postsweep_check import (HORIZONS, gateway_trips,  # noqa: E402
                                     verdict_diff, verdicts_by_horizon)

PREREG_SHA = "3e4ad1e5d0596883bbd35604828d0d2db39a9eb2"
BASELINE_RECORDS = 73
STRATA = (5, 15, 30)
DATASET = os.path.join("data", "phase4b_postd25.csv")
SIDECAR = os.path.join("data", "cb_transitions.jsonl")
POLL_LOG = os.path.join("data", "audit", "phase4b_poll.jsonl")

# GROUP1 = COUNT, GROUP2 = TIME. The statistic is group1's within-stratum rank-sum
# minus its null expectation, summed across strata, so NEGATIVE means COUNT ranks
# lower, i.e. COUNT recovers FASTER.
ARM1, ARM2 = "COUNT", "TIME"


def arm(eid):
    return "COUNT" if "-CNT-" in eid else "TIME"


def stratum(eid):
    return int(eid.rsplit("-D", 1)[1])


# --------------------------------------------------------------------- §4 + §3

def exclusion_table(rows, records, ticks, pstart, pstop, horizon):
    """§4 rules applied in order. Returns (kept_rows, counts_by_arm)."""
    by = {(r.get("experiment_id"), str(r.get("replicate"))): r for r in records}
    fn = HORIZONS[horizon]
    counts = {a: collections.Counter() for a in (ARM1, ARM2)}
    kept = []
    for row in rows:
        eid = row["experiment_id"]
        a = arm(eid)
        rec = by.get((eid, str(row["replicate"])))
        reasons = []
        if str(row.get("precondition_ok")) != "True":
            reasons.append("1_aborted")
        trips = gateway_trips(rec) if rec else []
        if trips:
            reasons.append("2_gateway_trip")
        if rec is None:
            reasons.append("3_not_verified")
        else:
            lo, hi = fn(rec, row)
            v = ("NOT_VERIFIED" if lo is None else
                 gpv.check_run(ticks, pstart, pstop, lo, hi, trips)["verdict"])
            if v != "VERIFIED_CLEAN":
                reasons.append("3_not_verified")
        try:
            if float(row["time_to_recover"]) > 3.0 * float(row["wait_duration"]) + 60.0:
                reasons.append("4_implausible")
        except (TypeError, ValueError):
            pass
        flag = str(row.get("lambda_deviation_flag"))
        if flag == "True":
            reasons.append("5_lambda")
        elif flag != "False":
            counts[a]["5_lambda_None_flagged_not_excluded"] += 1
        for r_ in reasons:
            counts[a][r_] += 1
        if not reasons:
            kept.append(row)
            counts[a]["RETAINED"] += 1
    return kept, counts


def config_values(kept):
    """§3 config-level value rule. Returns (values, case_counts, censored_rows)."""
    per = collections.defaultdict(list)
    for r in kept:
        per[r["experiment_id"]].append(r)
    values, cases, censored = {}, collections.Counter(), []
    for eid, rs in per.items():
        unc = []
        for r in rs:
            if str(r.get("half_open_probe_timed_out")) == "True":
                censored.append(r)
            else:
                unc.append(float(r["time_to_recover"]))
        if not unc:
            cases["0/N uncensored -> config EXCLUDED"] += 1
            continue
        if len(rs) == 3 and len(unc) == 3:
            cases["3/3 uncensored -> mean of 3"] += 1
        else:
            cases[f"{len(unc)}/{len(rs)} uncensored -> mean of uncensored "
                  f"(censored-partial)"] += 1
        values[eid] = sum(unc) / len(unc)
    return values, cases, censored


def imputed_values(kept):
    """§3.2 sensitivity: each censored replicate takes 3*wait+60, mean of all 3."""
    per = collections.defaultdict(list)
    for r in kept:
        per[r["experiment_id"]].append(r)
    out = {}
    for eid, rs in per.items():
        vals = []
        for r in rs:
            if str(r.get("half_open_probe_timed_out")) == "True":
                vals.append(3.0 * float(r["wait_duration"]) + 60.0)
            else:
                vals.append(float(r["time_to_recover"]))
        out[eid] = sum(vals) / len(vals)
    return out


# ------------------------------------------------------------------------ main

def load(dataset=DATASET, sidecar=SIDECAR, poll=POLL_LOG):
    rows = list(csv.DictReader(open(dataset, newline="", encoding="utf-8-sig")))
    recs = [json.loads(l) for l in open(sidecar, encoding="utf-8")
            if l.strip()][BASELINE_RECORDS:]
    ticks, ps, pe = gpv.load_poll(poll)
    return rows, recs, ticks, ps, pe


def analyse(horizon="dev02", out=print):
    rows, recs, ticks, ps, pe = load()
    out("=" * 78)
    out(f"H3 PRIMARY ANALYSIS -- pre-registration {PREREG_SHA[:7]}, horizon = {horizon}")
    if horizon == "dev02":
        out("Verification: DEVIATION 02 (supersedes DEVIATION 01, identical verdicts).")
        out("  docs/paper/deviation-02-horizon-simplification.md")
        out("  docs/paper/deviation-01-verification-horizon.md  (superseded)")
    elif horizon == "literal":
        out("Verification: the LITERAL pre-registered §5/§6 rule.")
    out("=" * 78)

    kept, counts = exclusion_table(rows, recs, ticks, ps, pe, horizon)
    out("\n§4 EXCLUSIONS, by arm (36 runs per arm), applied in order")
    keys = ["1_aborted", "2_gateway_trip", "3_not_verified", "4_implausible",
            "5_lambda", "5_lambda_None_flagged_not_excluded", "RETAINED"]
    out(f"  {'rule':40s} {ARM1:>8s} {ARM2:>8s}")
    for k in keys:
        out(f"  {k:40s} {counts[ARM1][k]:>8d} {counts[ARM2][k]:>8d}")

    values, cases, censored = config_values(kept)
    out("\n§3 CONFIG-LEVEL VALUE RULE")
    for k, v in sorted(cases.items()):
        out(f"  {k:58s} {v}")
    out(f"  censored replicates (half_open_probe_timed_out is True) : {len(censored)}")
    out(f"  configurations with a value                             : {len(values)}")
    tie_counts = collections.Counter(round(v, 12) for v in values.values())
    ties = [v for v, n in tie_counts.items() if n > 1]
    out(f"  exact ties between config values                        : {len(ties)}")

    out("\n§3.1 POWER SIMULATION APPLICABILITY")
    applicable = (cases.get("3/3 uncensored -> mean of 3", 0) == len(values)
                  and cases.get("0/N uncensored -> config EXCLUDED", 0) == 0
                  and not ties)
    out(f"  -> {'simulated scenarios apply as written' if applicable else 'NOT ESTABLISHED'}")

    out("\n§3.2 CENSORING SENSITIVITY (impute each censored replicate at 3*wait+60)")
    if not censored:
        out("  no censored replicate exists, so the imputed values are IDENTICAL to the")
        out("  primary ones. The sensitivity is not applicable rather than a second result.")
        assert imputed_values(kept) == values, "imputation must be a no-op with no censoring"
        out("  verified: imputed value map == primary value map")
    else:
        out(f"  {len(censored)} censored replicate(s); the sensitivity IS a second analysis")

    # strata for the test
    strata = {}
    for d in STRATA:
        g1 = {e: v for e, v in values.items() if arm(e) == ARM1 and stratum(e) == d}
        g2 = {e: v for e, v in values.items() if arm(e) == ARM2 and stratum(e) == d}
        strata[f"D_w={d}"] = (g1, g2)
    empty = [k for k, (a_, b_) in strata.items() if not a_ or not b_]
    out("\nPER-STRATUM CONFIGURATION COUNTS (the analysis unit)")
    for d in STRATA:
        g1, g2 = strata[f"D_w={d}"]
        out(f"  D_w={d:<3d} {ARM1}={len(g1)}  {ARM2}={len(g2)}"
            + ("   <- EMPTY ARM, stratum excluded by §3" if (not g1 or not g2) else ""))
    if empty:
        out(f"\n  §3: {len(empty)} stratum/strata carry no label information and are EXCLUDED:")
        for k in empty:
            out(f"    insufficient clean data in stratum {k}")
        for k in empty:
            del strata[k]
    if len(strata) < 2:
        out("\n  §3: fewer than two strata survive -> THE STRATIFIED TEST IS NOT RUN.")
        out("  Only descriptives are reported. This is 'insufficient clean data',")
        out("  NEVER a null result and never evidence about H3.")
        return {"test_run": False, "strata_surviving": len(strata), "values": values}

    res = et.stratified_cluster_permutation_test(strata, two_sided=True)

    out("\n§7 VALIDITY CONDITION -- checked BEFORE any pooled p-value is quoted")
    signs = []
    for s in res.strata:
        sg = "+" if s.observed_statistic > 0 else ("-" if s.observed_statistic < 0 else "0")
        signs.append(sg)
        out(f"  {s.name:8s} n1={s.n1} n2={s.n2}  observed_statistic="
            f"{s.observed_statistic:+8.2f}  [{sg}]  "
            f"{'COUNT slower' if sg == '+' else 'TIME slower' if sg == '-' else 'tied'}")
    all_same = len(set(signs)) == 1 and signs[0] != "0"
    out(f"  signs: {signs}   ALL THE SAME WAY: {all_same}")
    if not all_same:
        out("  *** §7 FAILS -- the pooled p-value is NOT quoted. Per-stratum results are")
        out("  *** reported instead and the inconsistency IS the finding.")

    out("\n§2 PRIMARY TEST -- stratified_cluster_permutation_test, two-sided")
    out(f"  statistic         : {res.statistic:+.4f}")
    out(f"  total_assignments : {res.total_assignments:,}")
    out(f"  exact floor (2-s) : {res.p_floor_two_sided:.6g}")
    if all_same:
        out(f"  p_value (2-sided) : {res.p_value:.6g}")
        out(f"  p_value (1-sided) : {res.p_value_one_sided:.6g}")
        at_floor = abs(res.p_value - res.p_floor_two_sided) < 1e-15
        out(f"  p IS the floor    : {at_floor}")
        if at_floor:
            out("  *** The test is SATURATED. §2: 'The floor is the exact test's resolution,")
            out("  *** not power or evidence.' This p cannot distinguish a small effect from")
            out("  *** a large one; it says only that no relabeling is more extreme.")
    else:
        out("  p_value           : WITHHELD (§7 failed)")

    out("\n§2 SECONDARY -- cluster_permutation_rank_test, per stratum (no stratification)")
    raw = collections.defaultdict(list)
    for r in kept:
        raw[r["experiment_id"]].append(float(r["time_to_recover"]))
    sec = {}
    for d in STRATA:
        if f"D_w={d}" not in strata:
            continue
        g1 = {e: raw[e] for e in values if arm(e) == ARM1 and stratum(e) == d}
        g2 = {e: raw[e] for e in values if arm(e) == ARM2 and stratum(e) == d}
        r2 = et.cluster_permutation_rank_test(g1, g2, two_sided=True)
        sec[d] = r2
        sg = "+" if r2.statistic > 0 else ("-" if r2.statistic < 0 else "0")
        out(f"  D_w={d:<3d} stat={r2.statistic:+9.2f} [{sg}]  p={r2.p_value:.6g}  "
            f"floor={et.exact_p_floor(r2.n1_clusters, r2.n2_clusters) * 2:.6g}")
    disagree = [d for i, d in enumerate([x for x in STRATA if f"D_w={x}" in strata])
                if (("+" if sec[d].statistic > 0 else "-") != signs[i])]
    out(f"  direction disagreement with the primary: "
        f"{disagree if disagree else 'none'}")

    out("\nDESCRIPTIVE ONLY -- per-stratum Kaplan-Meier medians (§8: no inferential claim)")
    from half_open_survival import kaplan_meier
    import numpy as np
    km_out = {}
    out(f"  {'stratum':9s} {'arm':6s} {'n':>4s} {'KM median':>11s} {'mean':>9s} "
        f"{'min':>8s} {'max':>8s}")
    for d in STRATA:
        for a in (ARM1, ARM2):
            vs = [float(r["time_to_recover"]) for r in kept
                  if arm(r["experiment_id"]) == a and stratum(r["experiment_id"]) == d]
            if not vs:
                continue
            km = kaplan_meier(np.array(vs), np.ones(len(vs), dtype=int))
            km_out[(a, d)] = km["median_s"]
            out(f"  D_w={d:<5d} {a:6s} {len(vs):>4d} {km['median_s']:>11.3f} "
                f"{statistics.mean(vs):>9.3f} {min(vs):>8.3f} {max(vs):>8.3f}")

    out("\n§8 CLAIM SCOPE -- restated, because it bounds everything above")
    for line in [
        "LINEAR topology and LATENCY fault ONLY. Nothing here speaks to FANOUT or CRASH.",
        "ONE machine (soham-local). No cross-machine generalisation.",
        "Database state is NOT reset between runs; DB and pool state persist across all 72.",
        "Coverage is T50 at W=5/10/20 plus a single T70/W10 probe per stratum. No threshold",
        "  effect is claimed from that one probe.",
        "Window size is NOT matched across arms: slidingWindowSize is CALLS under COUNT_BASED",
        "  and SECONDS under TIME_BASED. Arms are matched on threshold, D_w, topology, fault",
        "  type and load only. This is NOT 'COUNT beats TIME at matched window size'.",
        "KM medians are descriptive only; no per-cell p-value is a result.",
        "Post-D25 only; never pooled with pre-D25 rows.",
    ]:
        out(f"  - {line}")

    return {"test_run": True, "statistic": res.statistic, "p_value": res.p_value,
            "p_floor": res.p_floor_two_sided, "signs": signs, "all_same": all_same,
            "total_assignments": res.total_assignments, "values": values,
            "km": km_out, "secondary": {d: sec[d].p_value for d in sec},
            "counts": counts, "cases": dict(cases), "n_censored": len(censored)}


# -------------------------------------------------------------------- self-test

# Pinned so a refactor that silently changes a number fails loudly. p and its floor
# are written as the exact rationals the enumeration produces -- 2 extreme
# assignments out of 343,000 -- rather than transcribed decimals, so the comparison
# is exact and self-documenting rather than brittle at the last float digit.
TOTAL_ASSIGNMENTS = 343_000
EXPECTED = {
    "statistic": -24.0,
    "p_value": 2 / TOTAL_ASSIGNMENTS,
    "p_floor": 2 / TOTAL_ASSIGNMENTS,
    "total_assignments": TOTAL_ASSIGNMENTS,
    "signs": ["-", "-", "-"],
    "n_censored": 0,
    # Kaplan-Meier medians are observed event times, not interpolated midpoints.
    "km": {("COUNT", 5): 6.732, ("TIME", 5): 23.613, ("COUNT", 15): 16.332,
           ("TIME", 15): 35.085, ("COUNT", 30): 31.435, ("TIME", 30): 65.165},
}


def self_test():
    ok = True

    def expect(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))

    if not all(os.path.exists(p) for p in (DATASET, SIDECAR, POLL_LOG)):
        print("  [skip] Phase 4B data not present")
        return True

    quiet = lambda *a, **k: None

    print("1. DEVIATION 02 is the primary rule and matches DEVIATION 01 exactly")
    rows, recs, ticks, ps, pe = load()
    v1 = verdicts_by_horizon(rows, recs, ticks, ps, pe, "dev01")
    v2 = verdicts_by_horizon(rows, recs, ticks, ps, pe, "dev02")
    expect("verdict_diff(dev01, dev02) empty", verdict_diff(v1, v2), {})
    expect("all 72 VERIFIED_CLEAN under dev02", set(v2.values()), {"VERIFIED_CLEAN"})

    print("2. the headline numbers are reproduced bit-for-bit")
    r = analyse("dev02", out=quiet)
    expect("test was run", r["test_run"], True)
    expect("statistic", r["statistic"], EXPECTED["statistic"])
    expect("p_value", r["p_value"], EXPECTED["p_value"])
    expect("p_floor", r["p_floor"], EXPECTED["p_floor"])
    expect("p IS the floor", r["p_value"] == r["p_floor"], True)
    expect("total_assignments", r["total_assignments"], EXPECTED["total_assignments"])
    expect("§7 signs", r["signs"], EXPECTED["signs"])
    expect("§7 all same way", r["all_same"], True)
    expect("no censored replicate", r["n_censored"], EXPECTED["n_censored"])
    expect("24 config values", len(r["values"]), 24)
    expect("zero exclusions, both arms",
           [r["counts"][a][k] for a in (ARM1, ARM2)
            for k in ("1_aborted", "2_gateway_trip", "3_not_verified",
                      "4_implausible", "5_lambda")], [0] * 10)
    expect("36 retained per arm",
           (r["counts"][ARM1]["RETAINED"], r["counts"][ARM2]["RETAINED"]), (36, 36))
    for k, want in EXPECTED["km"].items():
        expect(f"KM median {k}", round(r["km"][k], 4), want)

    print("3. dev01 gives the identical analysis, as the verdict diff implies")
    r1 = analyse("dev01", out=quiet)
    for k in ("statistic", "p_value", "p_floor", "signs", "total_assignments"):
        expect(f"dev01 == dev02 on {k}", r1[k], r[k])
    expect("dev01 == dev02 on the config values", r1["values"], r["values"])
    expect("dev01 == dev02 on the KM medians", r1["km"], r["km"])

    print("4. the LITERAL pre-registered rule does NOT run the test (§3)")
    rl = analyse("literal", out=quiet)
    expect("literal: test not run", rl["test_run"], False)
    expect("literal: fewer than two strata survive", rl["strata_surviving"] < 2, True)

    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horizon", choices=("dev02", "dev01", "literal"), default="dev02")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return 0 if self_test() else 1
    analyse(a.horizon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
