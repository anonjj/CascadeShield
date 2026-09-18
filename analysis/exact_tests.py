"""Exact permutation-test floors and exact permutation tests -- row-level and
stratified-cluster.

A permutation test's p-value is a count of "as-or-more-extreme" label
reassignments over the total number of possible assignments. No permutation
p-value can be smaller than 1/(that total) -- the observed assignment is
always one of them, so the smallest possible "extreme" bucket is the single
observed one. An asymptotic (chi-square) approximation doesn't know about
this floor and can report values below it; when it does, that's an
approximation artifact, not a real result.

**Read this before calling anything below.** Every count in this module --
`exact_p_floor`'s n1/n2, `exact_logrank_test`'s group sizes -- must be a count
of INDEPENDENT, EXCHANGEABLE UNITS, not raw rows. If your data has replicates
(the same configuration run more than once), a row-level count silently
inflates n and produces a floor -- and a p-value -- that is not attainable
from the actual design. This module's own first version (2026-09-18) made
exactly that mistake: it fed `exact_logrank_test` 6 COUNT_BASED / 5 TIME_BASED
*rows* at decision-log.md's D24 D_w=5/15 comparisons, without checking that
those rows were replicates of only 3 (D_w=5) and 1 (D_w=15) distinct
configurations. Both row-level results were retracted -- see D24's
2026-09-18 update in decision-log.md for the full account -- and replaced
with `stratified_cluster_permutation_test` below, which treats a
configuration (not a replicate row) as the unit, uses the mean of each
configuration's replicates as its value, and holds D_w fixed as a blocking
stratum rather than testing each D_w separately (H3's claim is "TIME_BASED
recovers slower than COUNT_BASED," one claim, not one per D_w).

`exact_p_floor`/`exact_logrank_test` are kept for genuinely unclustered data
(distinct configurations, one observation each) -- they are not wrong, they
were misapplied. Use `stratified_cluster_permutation_test` whenever your
units carry replicates.
"""
from __future__ import annotations

import argparse
import itertools
import math
import random
import sys
from dataclasses import dataclass, field
from itertools import combinations

EXACT_ENUMERATION_MAX_N = 22
DEFAULT_RESAMPLES = 20000


def exact_p_floor(n1_clusters: int, n2_clusters: int) -> float:
    """Smallest attainable p-value from a permutation test at these group
    sizes. n1_clusters/n2_clusters MUST be counts of independent units
    (e.g. distinct configurations) -- never raw replicate rows. See module
    docstring."""
    if n1_clusters < 1 or n2_clusters < 1:
        return 1.0
    return 1.0 / math.comb(n1_clusters + n2_clusters, n1_clusters)


@dataclass
class PFloorVerdict:
    p_reported: float
    p_floor: float
    n1_clusters: int
    n2_clusters: int
    below_floor: bool
    message: str


def check_p_floor(p: float, n1_clusters: int, n2_clusters: int) -> PFloorVerdict:
    floor = exact_p_floor(n1_clusters, n2_clusters)
    below = p < floor
    if below:
        msg = (f"p={p:g} is below the exact permutation floor "
               f"1/C({n1_clusters + n2_clusters},{n1_clusters})={floor:.4g} for "
               f"n1={n1_clusters}, n2={n2_clusters} clusters -- not attainable "
               "from a real permutation test at this sample size; likely an "
               "asymptotic-approximation artifact (or a row-count-vs-cluster-"
               "count mixup -- check that n1/n2 are independent units).")
    else:
        msg = f"p={p:g} is at or above the floor {floor:.4g}; not flagged."
    return PFloorVerdict(p, floor, n1_clusters, n2_clusters, below, msg)


def guard_p(p: float, n1_clusters: int, n2_clusters: int,
            clamp: bool = True) -> tuple[float, PFloorVerdict]:
    """Reported p, clamped to the floor when it's below it (unless clamp=False)."""
    verdict = check_p_floor(p, n1_clusters, n2_clusters)
    return (verdict.p_floor if (clamp and verdict.below_floor) else p, verdict)


def _logrank_components(d1, e1, d2, e2) -> tuple[float, float, float]:
    """(O1, E1, V) for a two-sample log-rank test -- same math as
    half_open_survival.logrank(), split out so an exact null can be built
    from the raw observed/expected/variance instead of the asymptotic p."""
    d1, e1, d2, e2 = list(d1), list(e1), list(d2), list(e2)
    event_times = sorted({t for t, ev in zip(d1, e1) if ev} | {t for t, ev in zip(d2, e2) if ev})
    O1 = E1 = V = 0.0
    for t in event_times:
        n1 = sum(1 for x in d1 if x >= t)
        n2 = sum(1 for x in d2 if x >= t)
        n = n1 + n2
        o1 = sum(1 for x, ev in zip(d1, e1) if x == t and ev)
        o2 = sum(1 for x, ev in zip(d2, e2) if x == t and ev)
        o = o1 + o2
        if n <= 1 or o == 0:
            continue
        O1 += o1
        E1 += o * n1 / n
        V += (o * (n1 / n) * (1 - n1 / n) * (n - o)) / (n - 1)
    return O1, E1, V


@dataclass
class ExactTestResult:
    test: str
    statistic: float
    p_value: float
    p_floor: float
    n1: int
    n2: int
    method: str  # "exact-enumeration" or "monte-carlo"
    n_permutations: int
    note: str = ""


def exact_logrank_test(d1, e1, d2, e2, resamples: int = DEFAULT_RESAMPLES,
                        seed: int = 0) -> ExactTestResult:
    """Two-sided exact (full-enumeration for n1+n2<=22) or Monte Carlo
    two-sample log-rank permutation test: the fraction of the C(n,n1) label
    assignments whose |O1-E1|/sqrt(V) is >= the observed value.

    d1/d2 must be independent units -- one row per configuration, not one row
    per replicate. If your data has replicates, aggregate to one value per
    configuration first, or use stratified_cluster_permutation_test."""
    d1, e1, d2, e2 = list(d1), list(e1), list(d2), list(e2)
    n1, n2 = len(d1), len(d2)
    n = n1 + n2
    floor = exact_p_floor(n1, n2)

    O1, E1, V = _logrank_components(d1, e1, d2, e2)
    if V <= 0:
        return ExactTestResult("logrank", 0.0, 1.0, floor, n1, n2, "undefined", 0,
                                note="zero variance; test undefined")
    observed = abs(O1 - E1) / math.sqrt(V)

    all_d, all_e = d1 + d2, e1 + e2

    def stat_for(idx1: set[int]) -> float:
        g1d = [all_d[i] for i in idx1]
        g1e = [all_e[i] for i in idx1]
        g2d = [all_d[i] for i in range(n) if i not in idx1]
        g2e = [all_e[i] for i in range(n) if i not in idx1]
        o1, e1v, v = _logrank_components(g1d, g1e, g2d, g2e)
        return abs(o1 - e1v) / math.sqrt(v) if v > 0 else 0.0

    if n <= EXACT_ENUMERATION_MAX_N:
        total = math.comb(n, n1)
        extreme = sum(1 for idx1 in combinations(range(n), n1)
                      if stat_for(set(idx1)) >= observed - 1e-9)
        return ExactTestResult("logrank", observed, extreme / total, floor, n1, n2,
                                "exact-enumeration", total)

    rng = random.Random(seed)
    idx_all = list(range(n))
    extreme = sum(1 for _ in range(resamples)
                  if stat_for(set(rng.sample(idx_all, n1))) >= observed - 1e-9)
    p = (extreme + 1) / (resamples + 1)
    return ExactTestResult("logrank", observed, p, floor, n1, n2,
                            "monte-carlo", resamples,
                            note="Monte Carlo estimate; +1/+1 correction so p is never exactly 0")


# ---------------------------------------------------------------------------
# Stratified cluster permutation -- the corrected tool for replicated designs
# ---------------------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    """Average ranks (1-indexed), ties split evenly -- standard rank-sum
    tie-handling."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def stratified_p_floor(strata_clusters) -> dict:
    """strata_clusters: iterable of (n1, n2) DISTINCT-CONFIGURATION counts,
    one pair per stratum (e.g. per D_w). Every stratum must already have at
    least 1 configuration on each side -- a stratum with an empty arm (e.g.
    every configuration in that D_w gateway-tripped on one side) carries no
    label information to permute and must be excluded by the caller before
    calling this, not silently zeroed here.

    Strata are independent, so the total number of joint label assignments
    is the PRODUCT of each stratum's C(n1+n2, n1), and the floor is
    1/that product (one-sided) or min(1, 2/that product) (two-sided, valid
    whenever the statistic's null distribution is symmetric under swapping
    which label is "group 1" in every stratum simultaneously -- true for the
    rank-sum statistic stratified_cluster_permutation_test uses)."""
    strata_clusters = list(strata_clusters)
    per_stratum = []
    total = 1
    for n1, n2 in strata_clusters:
        if n1 < 1 or n2 < 1:
            raise ValueError(f"stratum with n1={n1}, n2={n2} has an empty arm; "
                              "exclude it before calling stratified_p_floor")
        c = math.comb(n1 + n2, n1)
        per_stratum.append(c)
        total *= c
    return {
        "total_assignments": total,
        "per_stratum_assignments": per_stratum,
        "one_sided_floor": 1.0 / total,
        "two_sided_floor": min(1.0, 2.0 / total),
    }


@dataclass
class StratumInfo:
    name: str
    n1: int
    n2: int
    n_assignments: int
    observed_statistic: float


@dataclass
class StratifiedClusterTestResult:
    statistic: float
    p_value: float
    p_value_one_sided: float
    p_floor_one_sided: float
    p_floor_two_sided: float
    total_assignments: int
    two_sided: bool
    strata: list = field(default_factory=list)
    method: str = "exact-enumeration"
    note: str = ""


def stratified_cluster_permutation_test(strata: dict, two_sided: bool = True
                                         ) -> StratifiedClusterTestResult:
    """strata: {stratum_name: (group1_configs, group2_configs)}, each a dict
    {config_id: value}. value is the config-level summary (mean of that
    config's replicates) -- ONE value per configuration, never one per
    replicate row. Every stratum must have >=1 config in EACH group; a
    stratum where one arm is entirely absent (e.g. gateway-tripped it all
    away) carries no label information and must be excluded by the caller
    before calling this.

    Statistic: an unweighted stratified rank-sum (van-Elteren-style). Within
    each stratum, rank the pooled group1+group2 config values (average rank
    for ties), take group1's rank-sum minus its null expectation
    n1*(n1+n2+1)/2, and sum that signed quantity across strata -- this holds
    the stratifying variable (e.g. D_w) fixed as a blocking factor rather
    than pooling raw rows across it, which is what let clustered replicates
    masquerade as independent units in the first place.

    The null is exact, not asymptotic or Monte Carlo: each stratum's label
    assignment is enumerated over its own C(n1+n2, n1) configuration
    relabelings, and because strata are independent, the joint null is the
    full Cartesian product across strata -- enumerated directly. Intended for
    small designs (this project's largest case is 20 x 4 = 80 total
    assignments); there is no Monte Carlo fallback here because nothing in
    this project's replicated designs needs one yet.
    """
    names = list(strata.keys())
    strata_meta = []
    per_stratum_stat_values = []  # list[list[float]], index 0 is ALWAYS the observed labeling

    for name in names:
        g1, g2 = strata[name]
        n1, n2 = len(g1), len(g2)
        if n1 < 1 or n2 < 1:
            raise ValueError(f"stratum {name!r} has an empty arm (n1={n1}, n2={n2}); "
                              "exclude it before calling stratified_cluster_permutation_test")
        pooled_vals = [g1[k] for k in g1] + [g2[k] for k in g2]
        n = n1 + n2
        ranks = _ranks(pooled_vals)
        e1 = n1 * (n + 1) / 2.0
        # itertools.combinations(range(n), n1) yields (0,...,n1-1) FIRST
        # (lexicographic order) -- and since pooled_vals/ranks are built as
        # "group1 items, then group2 items", that first combination IS the
        # actual observed group1 assignment. Verified in self_test().
        stat_values = [sum(ranks[i] for i in combo) - e1
                       for combo in combinations(range(n), n1)]
        strata_meta.append({"name": name, "n1": n1, "n2": n2})
        per_stratum_stat_values.append(stat_values)

    observed = sum(vals[0] for vals in per_stratum_stat_values)

    total_assignments = 1
    for vals in per_stratum_stat_values:
        total_assignments *= len(vals)

    two_sided_extreme = 0
    one_sided_extreme = 0
    for combo in itertools.product(*per_stratum_stat_values):
        joint = sum(combo)
        if abs(joint) >= abs(observed) - 1e-9:
            two_sided_extreme += 1
        if joint <= observed + 1e-9:
            one_sided_extreme += 1

    p_two_sided = two_sided_extreme / total_assignments
    p_one_sided = one_sided_extreme / total_assignments

    floor = stratified_p_floor([(m["n1"], m["n2"]) for m in strata_meta])

    strata_info = [
        StratumInfo(name=m["name"], n1=m["n1"], n2=m["n2"],
                    n_assignments=len(per_stratum_stat_values[i]),
                    observed_statistic=per_stratum_stat_values[i][0])
        for i, m in enumerate(strata_meta)
    ]

    return StratifiedClusterTestResult(
        statistic=observed,
        p_value=(p_two_sided if two_sided else p_one_sided),
        p_value_one_sided=p_one_sided,
        p_floor_one_sided=floor["one_sided_floor"],
        p_floor_two_sided=floor["two_sided_floor"],
        total_assignments=total_assignments,
        two_sided=two_sided,
        strata=strata_info,
    )


def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    print("exact_p_floor / guard_p (row-level, unclustered)")
    check("floor(2,5) == 1/21", math.isclose(exact_p_floor(2, 5), 1 / 21))
    check("floor(2,6) == 1/28", math.isclose(exact_p_floor(2, 6), 1 / 28))
    v = check_p_floor(0.0082, 2, 5)
    check("p=0.0082 flagged below floor at (2,5)", v.below_floor)
    p, v2 = guard_p(0.0082, 2, 5)
    check("guard_p clamps to the floor", math.isclose(p, 1 / 21))
    check("guard_p never emits a sub-floor value", p >= exact_p_floor(2, 5))
    p3, v3 = guard_p(0.5, 2, 5)
    check("guard_p leaves an above-floor p untouched", p3 == 0.5 and not v3.below_floor)

    print("exact_logrank_test (row-level, unclustered)")
    r = exact_logrank_test([1.0, 1.1], [True, True],
                            [10.0, 10.1, 10.2, 10.3, 10.4], [True] * 5)
    check("(2,5) complete separation: exact-enumeration, 21 permutations",
          r.method == "exact-enumeration" and r.n_permutations == 21)
    check("(2,5) complete separation: p == floor == 1/21",
          math.isclose(r.p_value, 1 / 21) and math.isclose(r.p_value, r.p_floor))
    r_same = exact_logrank_test([5.0, 6.0], [True, True],
                                 [5.1, 5.2, 5.3, 5.4, 5.5], [True] * 5)
    check("indistinguishable groups are not falsely significant (p >= 0.2)",
          r_same.p_value >= 0.2)
    r_cens = exact_logrank_test([1.0, 1.1], [True, False],
                                 [10.0, 10.1, 10.2, 10.3, 10.4], [True] * 5)
    check("censored input still returns a p-value", r_cens.p_value is not None)
    big1 = [float(i) for i in range(15)]
    big2 = [float(i) + 0.5 for i in range(15)]
    r_big = exact_logrank_test(big1, [True] * 15, big2, [True] * 15, resamples=2000)
    check("n=30 falls through to Monte Carlo", r_big.method == "monte-carlo")
    check("Monte Carlo p is never exactly 0", r_big.p_value > 0)

    print("stratified_p_floor")
    # The exact worked example this module was built to reproduce: D_w=5 has
    # 3 configs/arm (C(6,3)=20), D_w=15 has 1 COUNT config vs 3 TIME configs
    # (C(4,1)=4), D_w=30 excluded (COUNT arm empty) -- 20*4=80 total.
    floor = stratified_p_floor([(3, 3), (1, 3)])
    check("total_assignments == 80", floor["total_assignments"] == 80)
    check("one-sided floor == 1/80 == 0.0125", math.isclose(floor["one_sided_floor"], 0.0125))
    check("two-sided floor == 2/80 == 0.025", math.isclose(floor["two_sided_floor"], 0.025))
    try:
        stratified_p_floor([(3, 3), (0, 3)])
        check("empty-arm stratum raises", False)
    except ValueError:
        check("empty-arm stratum raises", True)

    print("stratified_cluster_permutation_test")
    # Complete separation in both strata (every group1 config beats every
    # group2 config) -> the observed labeling must be the single most extreme
    # of all 80 joint assignments, so p should equal the floor exactly.
    strata = {
        "D5": ({"c1": 2.0, "c2": 2.1, "c3": 2.2}, {"t1": 19.0, "t2": 19.3, "t3": 28.7}),
        "D15": ({"c1": 2.5}, {"t1": 20.9, "t2": 30.5, "t3": 39.6}),
    }
    res = stratified_cluster_permutation_test(strata, two_sided=True)
    check("total_assignments == 80", res.total_assignments == 80)
    check("complete separation: p == two-sided floor == 0.025",
          math.isclose(res.p_value, 0.025) and math.isclose(res.p_value, res.p_floor_two_sided))
    check("one-sided p == 1/80 == 0.0125", math.isclose(res.p_value_one_sided, 0.0125))
    check("observed statistic is negative (group1/COUNT ranks below group2/TIME)",
          res.statistic < 0)

    # index-0-is-observed invariant, checked directly rather than trusted.
    g1 = {"a": 1.0, "b": 2.0}
    g2 = {"c": 10.0, "d": 11.0}
    single = stratified_cluster_permutation_test({"only": (g1, g2)}, two_sided=True)
    # ranks of [1,2,10,11] = [1,2,3,4]; group1 (a,b) rank-sum=3, e1=2*5/2=5 -> -2
    check("observed statistic matches hand-computed rank-sum (-2.0)",
          math.isclose(single.strata[0].observed_statistic, -2.0))

    # No real separation -> p should sit well above the floor, not near it.
    strata_null = {
        "D5": ({"c1": 20.5, "c2": 19.8, "c3": 21.0}, {"t1": 19.0, "t2": 20.9, "t3": 20.2}),
        "D15": ({"c1": 25.0}, {"t1": 24.0, "t2": 26.0, "t3": 22.0}),
    }
    res_null = stratified_cluster_permutation_test(strata_null, two_sided=True)
    check("no real separation is not spuriously significant (p >= 0.2)",
          res_null.p_value >= 0.2)

    # Ties: shouldn't crash, ranks should average.
    tie_ranks = _ranks([1.0, 1.0, 2.0])
    check("tied values get averaged ranks ([1.5, 1.5, 3.0])",
          tie_ranks == [1.5, 1.5, 3.0])

    try:
        stratified_cluster_permutation_test({"D30": ({}, {"t1": 1.0})})
        check("empty-arm stratum in the test itself raises", False)
    except ValueError:
        check("empty-arm stratum in the test itself raises", True)

    print()
    print("D24's D_w=5/15 comparison, done correctly at the configuration level")
    print("(retracts this module's own first version -- see decision-log.md D24, "
          "2026-09-18 update):")
    print(f"  row-level 'exact' p (RETRACTED)      : D_w=5 p=0.0043, D_w=15 p=0.0476")
    print(f"  stratified cluster floor (2 strata)  : one-sided={floor['one_sided_floor']:.4f}, "
          f"two-sided={floor['two_sided_floor']:.4f}")

    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return 0 if self_test() else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
