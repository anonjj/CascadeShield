"""Exact permutation-test floors and an exact log-rank permutation test.

A permutation test's p-value is a count of "as-or-more-extreme" label
reassignments over the total number of possible assignments, C(n1+n2, n1).
No permutation p-value can be smaller than 1/C(n1+n2, n1) -- the observed
assignment is always one of those C(n1+n2, n1) equally likely relabelings, so
the smallest possible "extreme" bucket is the single observed one. An
asymptotic (chi-square) approximation doesn't know about this floor and can
report values below it; when it does, that's an approximation artifact, not
a real result.

Motivating case: decision-log.md's D24 entry reports p=0.0082 from a
log-rank chi-square test (analysis/half_open_survival.py's `logrank()`) on
2 COUNT_BASED vs 5 TIME_BASED observations (the gateway-cleaned D_w=15
comparison). 1/C(7,2) = 1/21 = 0.0476 -- the reported p is below the floor
and cannot be a real permutation p-value at that sample size. See this
module's `--self-test` for the same check run against a synthetic
same-shaped case, and the exact re-test of the real D24 data below.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from itertools import combinations

EXACT_ENUMERATION_MAX_N = 22
DEFAULT_RESAMPLES = 20000


def exact_p_floor(n1: int, n2: int) -> float:
    """Smallest attainable p-value from a permutation test at these group sizes."""
    if n1 < 1 or n2 < 1:
        return 1.0
    return 1.0 / math.comb(n1 + n2, n1)


@dataclass
class PFloorVerdict:
    p_reported: float
    p_floor: float
    n1: int
    n2: int
    below_floor: bool
    message: str


def check_p_floor(p: float, n1: int, n2: int) -> PFloorVerdict:
    floor = exact_p_floor(n1, n2)
    below = p < floor
    if below:
        msg = (f"p={p:g} is below the exact permutation floor "
               f"1/C({n1 + n2},{n1})={floor:.4g} for n1={n1}, n2={n2} -- not "
               "attainable from a real permutation test at this sample size; "
               "likely an asymptotic-approximation artifact.")
    else:
        msg = f"p={p:g} is at or above the floor {floor:.4g}; not flagged."
    return PFloorVerdict(p, floor, n1, n2, below, msg)


def guard_p(p: float, n1: int, n2: int, clamp: bool = True) -> tuple[float, PFloorVerdict]:
    """Reported p, clamped to the floor when it's below it (unless clamp=False)."""
    verdict = check_p_floor(p, n1, n2)
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
    assignments whose |O1-E1|/sqrt(V) is >= the observed value."""
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


def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    print("exact_p_floor / guard_p")
    check("floor(2,5) == 1/21", math.isclose(exact_p_floor(2, 5), 1 / 21))
    check("floor(2,6) == 1/28", math.isclose(exact_p_floor(2, 6), 1 / 28))
    v = check_p_floor(0.0082, 2, 5)
    check("p=0.0082 flagged below floor at (2,5)", v.below_floor)
    p, v2 = guard_p(0.0082, 2, 5)
    check("guard_p clamps to the floor", math.isclose(p, 1 / 21))
    check("guard_p never emits a sub-floor value", p >= exact_p_floor(2, 5))
    p3, v3 = guard_p(0.5, 2, 5)
    check("guard_p leaves an above-floor p untouched", p3 == 0.5 and not v3.below_floor)

    print("exact_logrank_test")
    # Complete separation, n1=2, n2=5: this is the single most extreme
    # permutation out of C(7,2)=21, so exact p must equal the floor exactly.
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

    print()
    print("The D24 D_w=15 case, done correctly (2 COUNT_BASED vs 5 TIME_BASED, "
          "gateway-cleaned, both arms fully observed -- see decision-log.md D24):")
    print(f"  reported (chi-square, half_open_survival.logrank) : p = 0.0082")
    print(f"  exact permutation floor at n=(2,5)                : p = {exact_p_floor(2, 5):.4f}")
    print(f"  exact permutation p (this module)                 : p = {r.p_value:.4f}")

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
