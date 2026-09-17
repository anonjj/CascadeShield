#!/usr/bin/env python3
"""
D13 — Kaplan-Meier estimator for precise_half_open_to_closed.

Closes the open item left by PR #55: `window_type_recovery_leak.py` now *reports*
censoring correctly (LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING) but still cannot
produce a verdict, because a fully-censored bucket (COUNT at D_w=30, 0/6 recovered)
has no median to fold into a ratio.

Kaplan-Meier handles this directly: a censored observation contributes its
"survived at least this long" information to the risk set without requiring an
event time. Where a median is unreachable (survival never drops to 0.5), that is
reported as ">= t_max", never as NaN and never dropped.

No new dependencies. KM, Greenwood variance and the log-rank test are implemented
here against numpy/pandas only -- deliberately, given PR #52's undeclared-scipy
incident. scipy is used only for the log-rank p-value and is imported lazily; the
estimator itself runs without it.

Usage:
    python3 analysis/half_open_survival.py
    python3 analysis/half_open_survival.py --jsonl data/cb_transitions.jsonl
    python3 analysis/half_open_survival.py --self-test

Outputs analysis/out/half_open_survival.json and a readable table on stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# half_open_probe_deadline_s is stdlib-only (breaker_observer.py's only imports are
# json/os/socket/sys/time/urllib.request), so no try/except fallback is needed here --
# same reasoning canary_readout.py already uses for its own experiments/ import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))
from breaker_observer import half_open_probe_deadline_s  # noqa: E402

# --------------------------------------------------------------------------
# Schema tolerance
#
# cb_transitions.jsonl has been written by more than one version of the harness
# (pre-D14 records carry no machine_id at all). Rather than pin one spelling,
# every field is looked up through an alias list. If a record shape shows up that
# none of these match, the loader says so loudly instead of silently yielding
# zero rows -- that failure mode has already cost this project one sweep.
# --------------------------------------------------------------------------

RUN_ID_KEYS = ("experiment_id", "experimentId", "exp_id", "id")
REPLICATE_KEYS = ("replicate", "rep", "replicate_index")
MACHINE_KEYS = ("machine_id", "machineId", "machine", "host")
TRANSITIONS_KEYS = ("transitions", "events", "state_transitions", "records")

NAME_KEYS = ("state_transition", "stateTransition", "transition", "name", "event", "type")
TIME_KEYS = ("creation_time", "creationTime", "timestamp", "time", "at", "ts")
BREAKER_KEYS = ("circuit_breaker_name", "circuitBreakerName", "breaker", "cb", "name_cb", "circuitBreaker")
SERVICE_KEYS = ("service", "service_name", "serviceName", "source", "app")

HALF_OPEN_ENTRY = "OPEN_TO_HALF_OPEN"
HALF_OPEN_SUCCESS = "HALF_OPEN_TO_CLOSED"
HALF_OPEN_FAILURE = "HALF_OPEN_TO_OPEN"


def _get(d: dict, keys: Iterable[str], default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_timestamp(raw: Any) -> float | None:
    """Seconds since epoch from whatever the harness wrote.

    Resilience4j's ZonedDateTime.toString() emits e.g.
        2026-09-14T11:02:31.417538+05:30[Asia/Kolkata]
    The bracketed zone id is not ISO-8601 and is what broke pd.Timestamp() in the
    bug fixed on the worktree-session-handoff branch. Strip it, then parse.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # Epoch millis vs seconds: anything past ~2001 in seconds is < 1e12.
        return float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
    s = str(raw).strip()
    s = re.sub(r"\[[^\]]+\]$", "", s)          # drop [Asia/Kolkata]
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)      # clamp to microseconds
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# experiment_id parsing
#
# Authoritative per the repo: n_min lives only in the id, and so do window_type
# and D_w. e.g. LIN-LAT-CNT-T50-W5-D30 -> COUNT_BASED, theta=50, W=5, D_w=30.
# --------------------------------------------------------------------------

WINDOW_TOKEN = {"CNT": "COUNT_BASED", "TIM": "TIME_BASED"}


def parse_experiment_id(exp_id: str) -> dict:
    out = {"window_type": None, "threshold": None, "window_size": None,
           "wait_duration": None, "topology": None, "fault_type": None}
    if not exp_id:
        return out
    parts = str(exp_id).split("-")
    for p in parts:
        if p in ("LIN", "FAN", "TREE"):
            out["topology"] = {"LIN": "LINEAR", "FAN": "FANOUT", "TREE": "TREE"}[p]
        elif p in ("LAT", "CRS", "THR"):
            out["fault_type"] = {"LAT": "LATENCY", "CRS": "CRASH", "THR": "THROTTLE"}[p]
        elif p in WINDOW_TOKEN:
            out["window_type"] = WINDOW_TOKEN[p]
        elif re.fullmatch(r"T\d+", p):
            out["threshold"] = int(p[1:])
        elif re.fullmatch(r"W\d+", p):
            out["window_size"] = int(p[1:])
        elif re.fullmatch(r"D\d+", p):
            out["wait_duration"] = int(p[1:])
    return out


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

# Which (service, breaker) pairs actually determine "recovered" for a given
# (topology, fault_type) -- must match window_type_recovery_leak.py's own
# BREAKER_WATCH exactly, or this script's numbers cannot be cross-checked
# against it (the entire point of running both). Confirmed by reading that
# script's BREAKER_WATCH directly (analysis/window_type_recovery_leak.py:82-84)
# rather than re-guessing it -- extend only when that dict does.
BREAKER_WATCH = {
    ("LINEAR", "LATENCY"): ("order", ["inventoryServiceCB", "sharedDbCB"]),
}


def _walk_breaker(events: list[tuple[float, str]]) -> dict:
    """One breaker's chronologically-sorted (timestamp, transition-name) events ->
    first entry into OPEN, first post-open HALF_OPEN, last HALF_OPEN->CLOSED, and
    whether the breaker's own last recorded transition was a close.

    Mirrors window_type_recovery_leak.py::_walk_breaker exactly (same field
    semantics) -- deliberately, not independently reinvented, since agreement
    with that script on the observed (non-censored) rows is the cross-check this
    whole file exists to satisfy.
    """
    t_open = t_half_open_first = t_closed_last = None
    bounces = 0
    last_name = None
    for ts, name in events:
        if name in ("CLOSED_TO_OPEN", "HALF_OPEN_TO_OPEN"):
            if t_open is None:
                t_open = ts
            if name == "HALF_OPEN_TO_OPEN":
                bounces += 1
        elif name == HALF_OPEN_ENTRY and t_half_open_first is None:
            t_half_open_first = ts
        elif name == HALF_OPEN_SUCCESS:
            t_closed_last = ts
        last_name = name
    return {
        "t_open": t_open,
        "t_half_open_first": t_half_open_first,
        "t_closed_last": t_closed_last,
        "bounces": bounces,
        "recovered": t_open is not None and last_name == HALF_OPEN_SUCCESS,
    }


def _recovery_deadline(rec: dict, wait_duration: float | None) -> float | None:
    """The true right-censoring bound for this run's recovery observation: the
    wall-clock instant BreakerObserver._poll_for_recovery stops polling.

    experiments/breaker_observer.py::_poll_for_recovery sets
    `recovery_deadline = time.time() + wait_duration + 10` at the moment it is
    called, and runner.py calls observe_recovery() immediately after setting
    fault_cleared_at (experiments/runner.py:1370-1387, no intervening work) --
    so fault_cleared_at is that call's wall-clock instant to within
    measurement noise. This is NOT "the last transition timestamp recorded for
    this breaker": a breaker that logs only its OPEN_TO_HALF_OPEN entry and then
    emits no further event before the poll loop exits was still being watched
    for the rest of the deadline, it just didn't transition again in that time --
    treating "last logged event" as the censoring bound understates the true
    at-risk time and can collapse it to ~0.

    Sanity-checked directly against the real sidecar before relying on this:
    for all 26 runs that DID close, `fault_cleared_at + wait_duration + 10`
    exceeds the actual close time in every case (0 violations) -- confirming
    this bound is not just plausible but consistent with every observed
    recovery in the dataset.
    """
    fc = parse_timestamp(_get(rec, ("fault_cleared_at",)))
    if fc is None or wait_duration is None:
        return None
    return fc + float(wait_duration) + 10.0


def extract_observations(records: list[dict], breaker_filter: str | None = None) -> list[dict]:
    """One observation per RUN (matching window_type_recovery_leak.py's grain: one
    precise_half_open_to_closed value per master_dataset row, not per breaker).

    duration = t(all watched breakers recovered) - t(EARLIEST first HALF_OPEN entry
    across those breakers) -- i.e. the full span from the first probe attempt to
    final recovery, INCLUDING any failed-probe bounces in between. An earlier
    version of this function measured only the last (successful) HALF_OPEN entry,
    discarding the bounces as "not the recovery leg" -- that is a different
    quantity than window_type_recovery_leak.py measures (which explicitly takes
    t_half_open_first, not t_half_open_last, exactly because the bouncing IS part
    of what a leak on this leg would look like) and produced numbers roughly an
    order of magnitude smaller than that script's, not a mere rounding gap.

    A run only counts as recovered if EVERY breaker that opened also closed
    (BREAKER_WATCH's "all_recovered" semantics) -- one breaker still open means
    the run has not recovered, full stop, matching precise_row_for exactly.

    If not all opened breakers closed, the observation is RIGHT-CENSORED at
    _recovery_deadline(rec, wait_duration) -- the actual wall-clock bound the
    harness polled to, not "whatever this breaker's own last logged event was."

    Records with mode != "full" are dropped: only full-sweep rows populate
    data/master_dataset.csv's "current" population, and an experiment_id's
    W/D tokens are not reliably parseable as window_size/wait_duration outside
    that mode (e.g. occupancy mode's "-M5-L10" suffix rides on the same W/D
    token shape and would otherwise silently land in the wrong bucket).
    """
    obs = []
    for rec in records:
        if _get(rec, ("mode",)) != "full":
            continue
        exp_id = _get(rec, RUN_ID_KEYS)
        meta = parse_experiment_id(exp_id)
        replicate = _get(rec, REPLICATE_KEYS)
        machine = _get(rec, MACHINE_KEYS, "")

        watch = BREAKER_WATCH.get((meta["topology"], meta["fault_type"]))
        if watch is None:
            continue
        watch_service, watch_breakers = watch

        transitions = _get(rec, TRANSITIONS_KEYS, [])
        if isinstance(transitions, dict):
            transitions = [transitions]

        # D23/D24: gateway-service's own breakers sit outside BREAKER_WATCH's scope (the
        # loop below filters them out via svc != watch_service) but a real gateway trip
        # directly confounds order's own HALF_OPEN duration -- order waits on gateway to
        # let traffic through, which reads as a long "recovery" that has nothing to do
        # with order's own HALF_OPEN semantics. Computed from the same already-fetched
        # transitions list, independent of by_breaker/opened/BREAKER_WATCH -- purely
        # additive, does not change any existing field.
        gateway_tripped = any(
            isinstance(t, dict)
            and _get(t, SERVICE_KEYS, "") == "gateway"
            and str(_get(t, NAME_KEYS, "")).upper() == "CLOSED_TO_OPEN"
            for t in transitions
        )

        by_breaker: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for t in transitions:
            if not isinstance(t, dict):
                continue
            name = _get(t, NAME_KEYS)
            ts = parse_timestamp(_get(t, TIME_KEYS))
            if name is None or ts is None:
                continue
            svc = _get(t, SERVICE_KEYS, "")
            cb = _get(t, BREAKER_KEYS, "")
            if svc != watch_service or cb not in watch_breakers:
                continue
            if breaker_filter and breaker_filter not in cb:
                continue
            by_breaker[cb].append((ts, str(name).upper()))

        walked = {cb: _walk_breaker(sorted(evs)) for cb, evs in by_breaker.items()}
        opened = {cb: w for cb, w in walked.items() if w["t_open"] is not None}
        if not opened:
            continue  # nothing in BREAKER_WATCH opened this run -- not this leg's concern

        half_opens = [w["t_half_open_first"] for w in opened.values() if w["t_half_open_first"]]
        if not half_opens:
            continue
        t0 = min(half_opens)

        all_recovered = all(w["recovered"] for w in opened.values())
        closed_times = [w["t_closed_last"] for w in opened.values() if w["t_closed_last"]]

        if all_recovered and closed_times:
            duration, observed = max(closed_times) - t0, True
            ceiling = half_open_probe_deadline_s(meta["wait_duration"])
            if duration > ceiling:
                # Physically impossible: exceeds the harness's own hard ceiling for a
                # recovered (non-censored) run. Every instance found so far traces to a
                # real-world host wall-clock stall (e.g. a laptop's lid closing mid-poll)
                # rather than a harness bug -- confirmed via half_open_probe_timed_out=False
                # on the matching master_dataset row (the sleep hits the poll loop, not the
                # deadline check itself). Flagged and excluded, not silently dropped, matching
                # this repo's mark/archive-don't-delete philosophy elsewhere (D21).
                print(f"WARN: {exp_id} replicate {replicate}: duration_s={duration:.1f} "
                      f"exceeds half_open_probe_deadline_s({meta['wait_duration']})={ceiling:.1f} "
                      "-- excluded as an implausible (host-sleep-artifact) duration",
                      file=sys.stderr)
                continue
        else:
            deadline = _recovery_deadline(rec, meta["wait_duration"])
            if deadline is None:
                continue  # can't bound the censoring time -- exclude rather than guess
            duration, observed = deadline - t0, False

        if duration < 0:
            continue

        obs.append({
            "experiment_id": exp_id,
            "replicate": replicate,
            "machine_id": machine,
            "breaker": f"{watch_service}:{'+'.join(sorted(opened))}",
            "duration_s": float(duration),
            "observed": observed,
            "gateway_tripped": gateway_tripped,
            # Count of watched breakers (BREAKER_WATCH) that entered HALF_OPEN at least
            # once -- bounded by len(BREAKER_WATCH) (1 or 2 here), NOT a bounce count:
            # t_half_open_first is captured once per breaker in _walk_breaker, so a
            # breaker that bounces HALF_OPEN->OPEN->HALF_OPEN several times before
            # closing still contributes exactly 1 here. Use n_failed_probes for bounces.
            "n_half_open_entries": len(half_opens),
            "n_failed_probes": sum(w["bounces"] for w in opened.values()),
            **meta,
        })
    return obs


# --------------------------------------------------------------------------
# Kaplan-Meier
# --------------------------------------------------------------------------

def kaplan_meier(durations: np.ndarray, observed: np.ndarray) -> dict:
    """KM survival curve with Greenwood standard errors.

    Survival here is "still not recovered". S(t) falling to 0.5 gives the median
    recovery time. A curve that never reaches 0.5 -- which is exactly what a
    heavily censored arm produces -- yields a lower bound, not a NaN.
    """
    order = np.argsort(durations)
    d, e = np.asarray(durations)[order], np.asarray(observed)[order].astype(bool)
    n = len(d)

    times, surv, at_risk_out, events_out = [], [], [], []
    s, var_sum, at_risk = 1.0, 0.0, n
    variances = []

    i = 0
    while i < n:
        t = d[i]
        tied = (d == t)
        n_events = int(np.sum(tied & e))
        n_at_risk = at_risk
        if n_events > 0 and n_at_risk > 0:
            s *= (1.0 - n_events / n_at_risk)
            denom = n_at_risk * (n_at_risk - n_events)
            if denom > 0:
                var_sum += n_events / denom
            times.append(float(t))
            surv.append(float(s))
            at_risk_out.append(int(n_at_risk))
            events_out.append(n_events)
            variances.append(float(s * s * var_sum))
        at_risk -= int(np.sum(tied))
        i += int(np.sum(tied))

    # Median: first time S(t) <= 0.5.
    median, median_is_bound = None, False
    for t, sv in zip(times, surv):
        if sv <= 0.5:
            median = t
            break
    if median is None:
        median = float(np.max(d)) if n else None
        median_is_bound = True

    # Greenwood CI on S(t), log-log transformed so bounds stay in [0, 1].
    ci = []
    for t, sv, v in zip(times, surv, variances):
        if sv in (0.0, 1.0) or v <= 0:
            ci.append((float(sv), float(sv)))
            continue
        se_loglog = math.sqrt(v) / (sv * abs(math.log(sv)))
        lo = sv ** math.exp(1.96 * se_loglog)
        hi = sv ** math.exp(-1.96 * se_loglog)
        ci.append((float(min(lo, hi)), float(max(lo, hi))))

    return {
        "n": int(n),
        "n_events": int(np.sum(e)),
        "n_censored": int(n - np.sum(e)),
        "fully_censored": bool(np.sum(e) == 0),
        "median_s": median,
        "median_is_lower_bound": median_is_bound,
        "times": times,
        "survival": surv,
        "survival_ci": ci,
        "at_risk": at_risk_out,
        "events": events_out,
        "max_observed_s": float(np.max(d)) if n else None,
    }


def logrank(d1, e1, d2, e2) -> dict:
    """Two-sample log-rank test. Valid with censoring in either arm, including
    an arm with zero events -- which is the COUNT D_w=30 case."""
    d1, e1 = np.asarray(d1, float), np.asarray(e1, bool)
    d2, e2 = np.asarray(d2, float), np.asarray(e2, bool)
    all_t = np.unique(np.concatenate([d1[e1], d2[e2]]))
    if len(all_t) == 0:
        return {"statistic": None, "p_value": None,
                "note": "no events in either arm; test undefined"}

    O1 = E1 = V = 0.0
    for t in all_t:
        n1, n2 = np.sum(d1 >= t), np.sum(d2 >= t)
        n = n1 + n2
        o1, o2 = np.sum((d1 == t) & e1), np.sum((d2 == t) & e2)
        o = o1 + o2
        if n <= 1 or o == 0:
            continue
        O1 += o1
        E1 += o * n1 / n
        V += (o * (n1 / n) * (1 - n1 / n) * (n - o)) / (n - 1)
    if V <= 0:
        return {"statistic": None, "p_value": None, "note": "zero variance"}

    chi2 = (O1 - E1) ** 2 / V
    try:
        from scipy.stats import chi2 as chi2_dist
        p = float(chi2_dist.sf(chi2, 1))
    except ImportError:
        p = None
    return {"statistic": float(chi2), "p_value": p, "df": 1,
            "observed_group1": float(O1), "expected_group1": float(E1)}


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def analyse(obs: list[dict]) -> dict:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for o in obs:
        if o["wait_duration"] is None or o["window_type"] is None:
            continue
        buckets[(o["wait_duration"], o["window_type"])].append(o)

    per_bucket, comparisons = {}, []
    for (dw, wt), rows in sorted(buckets.items()):
        km = kaplan_meier(np.array([r["duration_s"] for r in rows]),
                          np.array([r["observed"] for r in rows]))
        per_bucket[f"D{dw}_{wt}"] = {"wait_duration": dw, "window_type": wt, **km}

    for dw in sorted({k[0] for k in buckets}):
        c = buckets.get((dw, "COUNT_BASED"), [])
        t = buckets.get((dw, "TIME_BASED"), [])
        if not c or not t:
            comparisons.append({
                "wait_duration": dw,
                "verdict": "ONE_ARM_EMPTY",
                "n_count": len(c), "n_time": len(t),
            })
            continue

        km_c = kaplan_meier(np.array([r["duration_s"] for r in c]),
                            np.array([r["observed"] for r in c]))
        km_t = kaplan_meier(np.array([r["duration_s"] for r in t]),
                            np.array([r["observed"] for r in t]))
        lr = logrank([r["duration_s"] for r in c], [r["observed"] for r in c],
                     [r["duration_s"] for r in t], [r["observed"] for r in t])

        # Ratio direction, stated honestly when either median is a bound.
        ratio = None
        ratio_note = ""
        if km_c["median_s"] and km_t["median_s"]:
            ratio = km_t["median_s"] / km_c["median_s"]
            if km_c["median_is_lower_bound"] and not km_t["median_is_lower_bound"]:
                ratio_note = ("COUNT median is a lower bound (never reached 50% recovery); "
                              "the true TIME/COUNT ratio is SMALLER than reported, "
                              "possibly below 1")
            elif km_t["median_is_lower_bound"] and not km_c["median_is_lower_bound"]:
                ratio_note = ("TIME median is a lower bound; the true ratio is LARGER "
                              "than reported")
            elif km_c["median_is_lower_bound"] and km_t["median_is_lower_bound"]:
                ratio_note = "both medians are lower bounds; ratio is not interpretable"

        comparisons.append({
            "wait_duration": dw,
            "count": {k: km_c[k] for k in
                      ("n", "n_events", "n_censored", "fully_censored",
                       "median_s", "median_is_lower_bound")},
            "time": {k: km_t[k] for k in
                     ("n", "n_events", "n_censored", "fully_censored",
                      "median_s", "median_is_lower_bound")},
            "median_ratio_time_over_count": ratio,
            "ratio_caveat": ratio_note,
            "logrank": lr,
        })

    # Verdict. Deliberately conservative: a fully-censored arm anywhere keeps the
    # INCOMPLETE label, matching PR #55's regression test, but KM still yields a
    # signed direction and a p-value, which the median-ratio table could not.
    usable = [c for c in comparisons if c.get("logrank", {}).get("p_value") is not None]
    any_fully_censored = any(
        c.get("count", {}).get("fully_censored") or c.get("time", {}).get("fully_censored")
        for c in comparisons if "count" in c
    )
    directions = [c["median_ratio_time_over_count"] for c in comparisons
                  if c.get("median_ratio_time_over_count")]
    consistent = bool(directions) and (all(r > 1 for r in directions) or all(r < 1 for r in directions))
    significant = [c for c in usable if c["logrank"]["p_value"] < 0.05]

    if not usable:
        verdict = "UNTESTABLE_NO_EVENTS"
    elif consistent and len(significant) == len(usable) and not any_fully_censored:
        verdict = "LEAK_CONFIRMED_ON_HALF_OPEN_LEG"
    elif consistent and significant:
        verdict = "LEAK_SUPPORTED_WITH_CENSORED_BUCKET"
    elif consistent:
        verdict = "LEAK_SUGGESTIVE_NOT_SIGNIFICANT"
    else:
        verdict = "NO_CONSISTENT_LEAK"

    return {
        "metric": "precise_half_open_to_closed",
        "estimator": "Kaplan-Meier, Greenwood log-log CI, log-rank two-sample test",
        "n_observations": len(obs),
        "verdict": verdict,
        "direction_consistent": consistent,
        "any_fully_censored_bucket": any_fully_censored,
        "per_bucket": per_bucket,
        "comparisons": comparisons,
    }


def render(result: dict) -> str:
    L = []
    L.append("D13 -- HALF_OPEN -> CLOSED recovery, Kaplan-Meier")
    L.append("=" * 72)
    L.append(f"observations: {result['n_observations']}   verdict: {result['verdict']}")
    L.append("")
    L.append(f"{'D_w':>5} {'arm':<12} {'n':>3} {'events':>7} {'cens':>5} {'median':>12}")
    L.append("-" * 72)
    for c in result["comparisons"]:
        dw = c["wait_duration"]
        if "count" not in c:
            L.append(f"{dw:>5} {'(one arm empty)':<12}")
            continue
        for arm, key in (("COUNT", "count"), ("TIME", "time")):
            k = c[key]
            med = "n/a" if k["median_s"] is None else (
                f">={k['median_s']:.2f}s" if k["median_is_lower_bound"] else f"{k['median_s']:.2f}s")
            L.append(f"{dw:>5} {arm:<12} {k['n']:>3} {k['n_events']:>7} {k['n_censored']:>5} {med:>12}")
        lr = c.get("logrank", {})
        p = lr.get("p_value")
        bits = []
        if c.get("median_ratio_time_over_count"):
            bits.append(f"TIME/COUNT median ratio {c['median_ratio_time_over_count']:.2f}x")
        if p is not None:
            bits.append(f"log-rank p={p:.4f}")
        if bits:
            L.append(f"{'':>5} -> " + "; ".join(bits))
        if c.get("ratio_caveat"):
            L.append(f"{'':>5}    CAVEAT: {c['ratio_caveat']}")
        L.append("")
    if result["any_fully_censored_bucket"]:
        L.append("NOTE: at least one arm never recovered within the observation window.")
        L.append("Its median is reported as a lower bound. KM still uses those rows;")
        L.append("they are not dropped, and the log-rank test remains valid.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Self-test -- mirrors PR #55's self_test_censoring contract: a fully-censored
# bucket must never vanish and must never be folded into a clean verdict.
# --------------------------------------------------------------------------

def self_test() -> bool:
    ok = True

    def mk(exp_id, rep, t0, wait_duration, closed_after=None):
        """closed_after=None means the run never closes within the observation
        window -- no HALF_OPEN_TO_OPEN filler event is appended either, matching
        the real shape found in data/cb_transitions.jsonl (a censored run can
        simply stop logging after its OPEN_TO_HALF_OPEN entry; nothing requires
        a further transition to exist). fault_cleared_at is set so that
        _recovery_deadline reproduces the same ~10s post-half-open budget
        observed in the real sidecar (fault_cleared_at + wait_duration + 10,
        with fault_cleared_at ~= t0 - wait_duration -- the wall-clock instant
        the breaker opened, since Resilience4j's OPEN->HALF_OPEN transition
        fires wait_duration after that)."""
        tr = [{"state_transition": "CLOSED_TO_OPEN", "creation_time": t0 - wait_duration,
               "service": "order", "circuit_breaker_name": "inventoryServiceCB"},
              {"state_transition": "OPEN_TO_HALF_OPEN", "creation_time": t0,
               "service": "order", "circuit_breaker_name": "inventoryServiceCB"}]
        if closed_after is not None:
            tr.append({"state_transition": "HALF_OPEN_TO_CLOSED",
                       "creation_time": t0 + closed_after,
                       "service": "order", "circuit_breaker_name": "inventoryServiceCB"})
        return {"experiment_id": exp_id, "replicate": rep, "mode": "full",
                "fault_cleared_at": t0 - wait_duration, "transitions": tr}

    recs = []
    for r in range(6):
        recs.append(mk("LIN-LAT-CNT-T50-W5-D5", r, 1000.0, 5, closed_after=2.0 + 0.1 * r))
        recs.append(mk("LIN-LAT-TIM-T50-W5-D5", r, 1000.0, 5, closed_after=19.0 + 0.1 * r))
        recs.append(mk("LIN-LAT-CNT-T50-W5-D30", r, 1000.0, 30, closed_after=None))
        recs.append(mk("LIN-LAT-TIM-T50-W5-D30", r, 1000.0, 30, closed_after=8.0 + 0.1 * r))

    obs = extract_observations(recs)
    # 24 records in, 24 observations out -- a censored run (no HALF_OPEN_TO_CLOSED)
    # still produces an observation via _recovery_deadline, it is never dropped.
    if len(obs) != 24:
        print(f"FAIL: expected 24 observations, got {len(obs)}"); ok = False

    res = analyse(obs)

    d30 = next(c for c in res["comparisons"] if c["wait_duration"] == 30)
    if not d30["count"]["fully_censored"]:
        print("FAIL: D_w=30 COUNT arm should be fully censored"); ok = False
    if d30["count"]["n"] != 6:
        print("FAIL: fully-censored bucket lost its rows"); ok = False
    if not d30["count"]["median_is_lower_bound"]:
        print("FAIL: censored median must be flagged as a lower bound"); ok = False
    if res["verdict"] == "LEAK_CONFIRMED_ON_HALF_OPEN_LEG":
        print("FAIL: fully-censored bucket must not yield a clean CONFIRMED verdict"); ok = False

    d5 = next(c for c in res["comparisons"] if c["wait_duration"] == 5)
    if d5["logrank"]["p_value"] is not None and d5["logrank"]["p_value"] > 0.05:
        print("FAIL: D_w=5 separation should be significant"); ok = False

    if parse_experiment_id("LIN-LAT-CNT-T50-W5-D30")["wait_duration"] != 30:
        print("FAIL: experiment_id parse"); ok = False
    if parse_timestamp("2026-09-14T11:02:31.417538+05:30[Asia/Kolkata]") is None:
        print("FAIL: ZonedDateTime parse"); ok = False

    # Implausible-duration exclusion (host-sleep artifact, e.g. a laptop lid closing
    # mid-poll): a "recovered" run whose duration exceeds half_open_probe_deadline_s
    # for its own wait_duration is physically impossible and must be excluded, not
    # silently averaged in. half_open_probe_deadline_s(5) = 3*5+60 = 75.
    impossible = mk("LIN-LAT-TIM-T50-W5-D5", 99, 1000.0, 5, closed_after=700.0)
    plausible = mk("LIN-LAT-TIM-T50-W5-D5", 98, 1000.0, 5, closed_after=19.3)
    obs_ceiling = extract_observations([impossible, plausible])
    if len(obs_ceiling) != 1 or obs_ceiling[0]["replicate"] != 98:
        print(f"FAIL: implausible-duration exclusion -- expected 1 observation (replicate "
              f"98 only), got {len(obs_ceiling)}: {[o['replicate'] for o in obs_ceiling]}")
        ok = False

    # D23/D24: gateway_tripped is computed independently of BREAKER_WATCH/by_breaker --
    # a record with a gateway CLOSED_TO_OPEN must flag True even though order's own
    # breaker (below) recovers cleanly; a record with no gateway transitions at all
    # must flag False.
    with_gateway_trip = mk("LIN-LAT-CNT-T50-W20-D30", 50, 1000.0, 30, closed_after=2.0)
    with_gateway_trip["transitions"].append({
        "state_transition": "CLOSED_TO_OPEN", "creation_time": 1005.0,
        "service": "gateway", "circuit_breaker_name": "orderServiceCB",
    })
    without_gateway_trip = mk("LIN-LAT-CNT-T50-W20-D30", 51, 1000.0, 30, closed_after=2.0)
    obs_gw = extract_observations([with_gateway_trip, without_gateway_trip])
    flags = {o["replicate"]: o["gateway_tripped"] for o in obs_gw}
    if flags != {50: True, 51: False}:
        print(f"FAIL: gateway_tripped -- expected {{50: True, 51: False}}, got {flags}")
        ok = False

    print("self-test PASSED" if ok else "self-test FAILED")
    if ok:
        print()
        print(render(res))
    return ok


def render_gateway_stratified(obs: list[dict]) -> str:
    """D23/D24: gateway-service's own breaker trips under COUNT_BASED at wait_duration>=15
    (a YAML gap in gateway's supposedly-never-opens config, unrelated to D13/D21's HALF_OPEN
    mechanism), and this confounds the pooled COUNT_BASED arm -- some of what reads as "COUNT
    recovering slowly" is actually order's breaker waiting on gateway to let traffic through,
    nothing to do with order's own HALF_OPEN semantics. Two things reported here, reusing
    analyse()/kaplan_meier() unchanged rather than modifying their (hardcoded 2-arm) bucketing:

    1. analyse() on the CLEANED set (COUNT-not-tripped + all TIME, since TIME never trips
       gateway) -- the real KM/log-rank/verdict table with the confound removed, directly
       comparable in shape to the pooled table already reported above.
    2. The gateway-tripped COUNT subset's own descriptive KM per wait_duration (no TIME
       counterpart to log-rank against, so median/n only, not a verdict).
    """
    L = []
    cleaned = [o for o in obs if o["window_type"] == "TIME_BASED" or not o["gateway_tripped"]]
    n_dropped = len(obs) - len(cleaned)
    L.append(f"gateway_tripped: dropping {n_dropped} gateway-confounded COUNT_BASED "
              f"observation(s) of {sum(1 for o in obs if o['window_type']=='COUNT_BASED')} "
              "total COUNT_BASED")
    L.append("")
    L.append(render(analyse(cleaned)))

    L.append("")
    L.append("gateway-tripped COUNT_BASED subset (descriptive only -- no TIME counterpart "
              "to test against):")
    by_dw: dict[float, list[dict]] = defaultdict(list)
    for o in obs:
        if o["window_type"] == "COUNT_BASED" and o["gateway_tripped"]:
            by_dw[o["wait_duration"]].append(o)
    for dw in sorted(by_dw):
        group = by_dw[dw]
        km = kaplan_meier(
            np.array([o["duration_s"] for o in group]),
            np.array([o["observed"] for o in group]),
        )
        bound = " (lower bound)" if km["median_is_lower_bound"] else ""
        L.append(f"  D_w={dw}: n={km['n']}  median={km['median_s']:.3f}s{bound}")
    for dw in (5, 15, 30):
        if dw not in by_dw:
            L.append(f"  D_w={dw}: n=0 (no gateway-tripped observations at this D_w)")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="data/cb_transitions.jsonl")
    ap.add_argument("--out", default="analysis/out/half_open_survival.json")
    ap.add_argument("--breaker", default=None,
                    help="substring filter, e.g. 'inventoryServiceCB'")
    ap.add_argument("--stratify-gateway", action="store_true",
                     help="D23/D24: also report the KM table with gateway-confounded "
                          "COUNT_BASED observations stratified out, alongside the pooled "
                          "table above (not a replacement for it).")
    ap.add_argument("--since", default=None,
                    help="YYYY-MM-DD -- keep only records whose fault_injected_at falls on or "
                         "after this date. cb_transitions.jsonl is a running, never-purged log "
                         "(D21: 'never delete, mark/archive instead'), so a harness fix landing "
                         "mid-history means the default (no filter) pools pre- and post-fix "
                         "records together in one verdict. Use this to isolate one side of a "
                         "before/after comparison -- e.g. the D21 poll-until-transition "
                         "verification read the post-2026-09-16 slice on its own before it was "
                         "trusted, rather than pooling it with the still-censored pre-fix rows.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return 0 if self_test() else 1

    path = Path(args.jsonl)
    if not path.exists():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        print("Note: cb_transitions.jsonl is gitignored -- it must be committed "
              "with `git add -f` or it is not in the checkout.", file=sys.stderr)
        return 1

    records = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"WARN: line {i} is not valid JSON ({exc}); skipped", file=sys.stderr)
    print(f"loaded {len(records)} records from {path}")

    if args.since:
        before = len(records)
        records = [r for r in records if r.get("fault_injected_at", "") >= args.since]
        print(f"--since {args.since}: kept {len(records)} of {before} records")

    obs = extract_observations(records, breaker_filter=args.breaker)
    if not obs:
        print("ERROR: zero observations extracted.", file=sys.stderr)
        print("Most likely the record shape differs from every alias this script "
              "knows. Keys seen on the first record:", file=sys.stderr)
        if records:
            print("  " + ", ".join(sorted(records[0].keys())), file=sys.stderr)
        return 1
    print(f"extracted {len(obs)} half-open observations "
          f"({sum(1 for o in obs if not o['observed'])} censored)")

    result = analyse(obs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print()
    print(render(result))
    print(f"\nwrote {out}")

    if args.stratify_gateway:
        print()
        print("=" * 72)
        print(render_gateway_stratified(obs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
