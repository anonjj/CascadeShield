#!/usr/bin/env python3
"""
H3 mechanism -- per-episode decomposition of HALF_OPEN recovery.

The question
------------
D22 established that bounce count (HALF_OPEN_TO_OPEN events) explains most of the
TIME-vs-COUNT recovery gap, and that TIME_BASED's bounce count rises with
slidingWindowSize while COUNT_BASED never bounces at all. D24 confirmed that
survives gateway-confound cleaning. What is still unidentified is WHY.

The live hypothesis (residual window contents): a TIME_BASED window retains
failure records for its full duration T. When the breaker re-evaluates after a
HALF_OPEN episode, the window still holds fault evidence from the last T seconds,
while a COUNT_BASED ring buffer has been overwritten by fresh successes. Larger T
means longer residual memory, so more attempts before one lands cleanly.

That hypothesis makes three separable predictions, and the second is the one that
can falsify it:

  P1  bounce_count scales with window_size for TIME_BASED, not for COUNT_BASED
      (already partly confirmed by D22 -- reproduced here as a control)

  P2  final_episode_duration -- the successful HALF_OPEN entry to
      HALF_OPEN_TO_CLOSED -- is roughly CONSTANT across window sizes.
      Residual-window-contents says the window governs HOW MANY attempts are
      needed, not how long the successful one takes. If the successful episode
      ALSO scales with window_size, the hypothesis is wrong and something inside
      the HALF_OPEN leg itself depends on T.

  P3  inter_attempt_interval -- HALF_OPEN_TO_OPEN to the next OPEN_TO_HALF_OPEN --
      tracks wait_duration and NOT window_size. This is a sanity check on the
      instrument: that gap is the breaker sitting in OPEN, which is definitionally
      wait_duration. If it doesn't hold, the extraction is wrong, not the theory.

Nothing in the codebase currently extracts per-episode timing -- n_failed_probes
is a count only. This script walks the raw transitions list to build it.

Usage
-----
    python3 analysis/recovery_decomposition.py --self-test
    python3 analysis/recovery_decomposition.py
    python3 analysis/recovery_decomposition.py --include-gateway-tripped

Writes analysis/out/recovery_decomposition.json and prints a readable report.
numpy only; no scipy needed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# half_open_probe_deadline_s is stdlib-only (breaker_observer.py's only imports are
# json/os/socket/sys/time/urllib.request) -- same import this script's sibling
# (half_open_survival.py) already uses to exclude the same class of artifact.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))
from breaker_observer import half_open_probe_deadline_s  # noqa: E402

# Gateway breakers live in the same transitions array but are the measurement
# plane, not experimental subjects (D23/D25). They are excluded from episode
# extraction and recorded as a per-run confound flag instead.
MEASUREMENT_PLANE_SERVICE = "gateway"

ENTRY = "OPEN_TO_HALF_OPEN"
FAIL = "HALF_OPEN_TO_OPEN"
CLOSE = "HALF_OPEN_TO_CLOSED"
TRIP = "CLOSED_TO_OPEN"

WINDOW_TOKEN = {"CNT": "COUNT_BASED", "TIM": "TIME_BASED"}


def parse_timestamp(raw):
    """creation_time is ISO-8601 with a bracketed zone suffix: ...Z[Etc/UTC].

    That suffix is not ISO and breaks datetime.fromisoformat and pd.Timestamp
    alike -- the same trap half_open_survival.parse_timestamp() already handles.
    Nanosecond precision is also present and must be clamped to microseconds.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
    s = re.sub(r"\[[^\]]+\]$", "", str(raw).strip())   # drop [Etc/UTC]
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)              # ns -> us
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def parse_experiment_id(exp_id):
    """window_type / threshold / window_size / wait_duration live in the id.

    Ids come in two lengths -- LIN-LAT-CNT-T50-W5-D30 and the occupancy form
    LIN-LAT-TIM-T50-W20-D15-M5-L10 -- so tokens are matched by shape, not position.
    M (min_calls) and L (lambda) are captured where present for completeness.
    """
    out = {"window_type": None, "threshold": None, "window_size": None,
           "wait_duration": None, "min_calls": None, "lambda_target": None,
           "topology": None, "fault_type": None}
    if not exp_id:
        return out
    for p in str(exp_id).split("-"):
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
        elif re.fullmatch(r"M\d+", p):
            out["min_calls"] = int(p[1:])
        elif re.fullmatch(r"L\d+", p):
            out["lambda_target"] = int(p[1:])
    return out


def decompose_run(rec, modes=("full",)):
    """One record -> per-breaker episode decomposition.

    For each subject breaker that entered HALF_OPEN, walk its transitions in order
    and split the recovery into:

        episodes            -- each OPEN_TO_HALF_OPEN to its terminal transition
        failed_episodes     -- those ending HALF_OPEN_TO_OPEN (a bounce)
        final_episode       -- the one ending HALF_OPEN_TO_CLOSED, if any
        inter_attempt gaps  -- HALF_OPEN_TO_OPEN to the NEXT OPEN_TO_HALF_OPEN,
                               i.e. time spent in OPEN between attempts

    total_s is the sum of all three, which must equal
    (last terminal - first entry) up to float error. That identity is checked in
    the self-test; a mismatch means an event was dropped or double-counted.
    """
    mode = rec.get("mode")
    if modes and mode not in modes:
        return []

    meta = parse_experiment_id(rec.get("experiment_id"))
    transitions = rec.get("transitions") or []

    gateway_tripped = any(
        t.get("service") == MEASUREMENT_PLANE_SERVICE and t.get("state_transition") == TRIP
        for t in transitions if isinstance(t, dict)
    )

    by_breaker = defaultdict(list)
    for t in transitions:
        if not isinstance(t, dict):
            continue
        svc = t.get("service", "")
        if svc == MEASUREMENT_PLANE_SERVICE:
            continue                                   # measurement plane, not a subject
        ts = parse_timestamp(t.get("creation_time"))
        name = t.get("state_transition")
        if ts is None or name is None:
            continue
        by_breaker[f"{svc}:{t.get('breaker','')}"].append((ts, str(name).upper()))

    rows = []
    for key, events in by_breaker.items():
        events.sort()
        episodes, gaps = [], []
        open_entry = None
        last_fail_ts = None

        for ts, name in events:
            if name == ENTRY:
                if last_fail_ts is not None:
                    gaps.append(ts - last_fail_ts)     # time spent in OPEN
                    last_fail_ts = None
                open_entry = ts
            elif name in (FAIL, CLOSE) and open_entry is not None:
                episodes.append({"start": open_entry, "end": ts,
                                 "duration_s": ts - open_entry,
                                 "closed": name == CLOSE})
                if name == FAIL:
                    last_fail_ts = ts
                open_entry = None

        if not episodes:
            continue

        failed = [e for e in episodes if not e["closed"]]
        closed = [e for e in episodes if e["closed"]]
        recovered = bool(closed)

        # An unterminated trailing ENTRY means the record ends mid-episode: the
        # run was censored. Not dropped -- flagged, per the project's convention.
        truncated = open_entry is not None

        final = closed[-1] if closed else None
        span = (episodes[-1]["end"] - episodes[0]["start"])

        # Same host-sleep-artifact check half_open_survival.py already applies to
        # this exact raw source (D13/D21): a recovered run's total span physically
        # cannot exceed the harness's own poll ceiling. Every instance found so far
        # traces to a real-world wall-clock stall (e.g. a laptop's lid closing
        # mid-poll), not a harness bug. Flagged and excluded, not silently dropped.
        if recovered and meta["wait_duration"] is not None:
            ceiling = half_open_probe_deadline_s(meta["wait_duration"])
            if span > ceiling:
                print(f"WARN: {rec.get('experiment_id')} replicate {rec.get('replicate')} "
                      f"({key}): total_s={span:.1f} exceeds "
                      f"half_open_probe_deadline_s({meta['wait_duration']})={ceiling:.1f} -- "
                      "excluded as an implausible (host-sleep-artifact) duration",
                      file=sys.stderr)
                continue

        rows.append({
            "experiment_id": rec.get("experiment_id"),
            "replicate": rec.get("replicate"),
            "machine_id": rec.get("machine_id", ""),
            "mode": mode,
            "breaker": key,
            "gateway_tripped": gateway_tripped,
            "recovered": recovered,
            "truncated": truncated,
            "n_episodes": len(episodes),
            "bounce_count": len(failed),
            "failed_episode_total_s": float(sum(e["duration_s"] for e in failed)),
            "failed_episode_mean_s": float(np.mean([e["duration_s"] for e in failed])) if failed else None,
            "final_episode_duration_s": float(final["duration_s"]) if final else None,
            "inter_attempt_total_s": float(sum(gaps)),
            "inter_attempt_mean_s": float(np.mean(gaps)) if gaps else None,
            "n_gaps": len(gaps),
            "total_s": float(span),
            **meta,
        })
    return rows


# ---------------------------------------------------------------------------
# Regression -- ordinary least squares via numpy, no scipy dependency
# ---------------------------------------------------------------------------

def ols(y, X, names):
    """Least squares with R^2, adjusted R^2, and per-coefficient t statistics.

    Adjusted R^2 is reported alongside raw R^2 deliberately: these samples are
    small, and R^2 rising while n falls is expected rather than informative.
    """
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    if n <= k:
        return {"n": int(n), "error": "not enough observations for this many terms"}

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())

    # Degenerate cases, reported rather than emitted as nan or a 1e16 t statistic.
    # A constant response has no variance to explain, so R^2 is undefined -- not
    # zero, not one. And a residual sum of squares at float noise level makes the
    # standard error meaningless, which is how an absurd t value gets printed and
    # then believed. Both are flagged here instead.
    scale = max(abs(float(y.mean())), 1.0)
    response_constant = ss_tot <= (1e-12 * scale * scale * n)
    fit_degenerate = ss_res <= (1e-12 * scale * scale * n)

    if response_constant:
        return {"n": int(n), "degenerate": "response is constant -- no variance "
                "to explain; slope and R^2 are undefined",
                "response_mean": float(y.mean()),
                "coefficients": {names[i]: {"estimate": float(beta[i]),
                                            "std_error": None, "t": None}
                                 for i in range(k)}}

    r2 = 1.0 - ss_res / ss_tot
    adj = 1.0 - (1 - r2) * (n - 1) / (n - k) if n > k else float("nan")

    dof = n - k
    se = [None] * k
    if dof > 0 and ss_res > 0 and not fit_degenerate:
        try:
            cov = (ss_res / dof) * np.linalg.pinv(X.T @ X)
            se = [float(math.sqrt(max(cov[i, i], 0.0))) for i in range(k)]
        except np.linalg.LinAlgError:
            pass

    return {
        "n": int(n), "r2": float(r2), "adj_r2": float(adj), "dof": int(dof),
        "exact_fit": bool(fit_degenerate),
        "coefficients": {
            names[i]: {
                "estimate": float(beta[i]),
                "std_error": se[i],
                "t": (float(beta[i] / se[i]) if se[i] else None),
            } for i in range(k)
        },
    }


def _fit(rows, response, predictor):
    """Single-predictor fit of `response` on `predictor`, with intercept."""
    usable = [r for r in rows
              if r.get(response) is not None and r.get(predictor) is not None]
    if len(usable) < 3:
        return {"n": len(usable), "error": "too few observations"}
    y = [r[response] for r in usable]
    xs = [float(r[predictor]) for r in usable]
    X = [[1.0, x] for x in xs]
    fit = ols(y, X, ["intercept", predictor])

    # Effect size, not just significance. The project's own metrics contract says
    # a bare p-value is a rejection reason; the same applies to a bare t. What
    # matters for P2 is how much the response actually moves across the range of
    # window sizes we swept -- a slope can be significant and trivial, or
    # non-significant and large at n=12.
    slope = fit.get("coefficients", {}).get(predictor, {}).get("estimate")
    if slope is not None and xs:
        span = max(xs) - min(xs)
        mean_y = float(np.mean(y))
        fit["predictor_range"] = [min(xs), max(xs)]
        fit["response_mean"] = fit.get("response_mean", mean_y)
        fit["predicted_change_over_range"] = float(slope) * span
        fit["relative_change"] = (abs(float(slope) * span) / abs(mean_y)
                                  if abs(mean_y) > 1e-9 else None)
    return fit


def analyse(rows):
    """P1-P3, per arm."""
    out = {"n_rows": len(rows), "predictions": {}}

    for arm in ("COUNT_BASED", "TIME_BASED"):
        a = [r for r in rows if r["window_type"] == arm]
        recovered = [r for r in a if r["recovered"]]

        out["predictions"][arm] = {
            "n": len(a),
            "n_recovered": len(recovered),
            "n_bouncing": sum(1 for r in a if r["bounce_count"] > 0),
            "total_bounces": sum(r["bounce_count"] for r in a),

            # P1 -- control. Does bounce count scale with window size?
            "P1_bounce_count_vs_window_size": _fit(a, "bounce_count", "window_size"),

            # P2 -- THE DISCRIMINATOR. Does the SUCCESSFUL episode scale with
            # window size? Residual-window-contents says no.
            "P2_final_episode_vs_window_size":
                _fit(recovered, "final_episode_duration_s", "window_size"),
            "P2_control_final_episode_vs_wait_duration":
                _fit(recovered, "final_episode_duration_s", "wait_duration"),

            # P3 -- instrument sanity. The OPEN gap should be wait_duration.
            "P3_inter_attempt_vs_wait_duration":
                _fit([r for r in a if r["inter_attempt_mean_s"] is not None],
                     "inter_attempt_mean_s", "wait_duration"),
            "P3_control_inter_attempt_vs_window_size":
                _fit([r for r in a if r["inter_attempt_mean_s"] is not None],
                     "inter_attempt_mean_s", "window_size"),
        }

        by_w = defaultdict(list)
        for r in recovered:
            if r["window_size"] is not None:
                by_w[r["window_size"]].append(r)
        out["predictions"][arm]["by_window_size"] = {
            str(w): {
                "n": len(rs),
                "mean_bounce_count": float(np.mean([x["bounce_count"] for x in rs])),
                "mean_final_episode_s": float(np.mean(
                    [x["final_episode_duration_s"] for x in rs
                     if x["final_episode_duration_s"] is not None])) if rs else None,
                "mean_inter_attempt_s": float(np.mean(
                    [x["inter_attempt_mean_s"] for x in rs
                     if x["inter_attempt_mean_s"] is not None]))
                    if any(x["inter_attempt_mean_s"] is not None for x in rs) else None,
                "mean_total_s": float(np.mean([x["total_s"] for x in rs])),
            } for w, rs in sorted(by_w.items())
        }

    out["verdict"] = _verdict(out["predictions"])
    return out


def _verdict(preds):
    """Read P2 for the TIME_BASED arm. That is the falsification test.

    Judged on effect size AND significance, not significance alone. Two traps this
    avoids, both of which bit the first version of this script:

      - A PERFECT fit yields a zero residual, hence no standard error and no t
        statistic. Reading "no t" as "not significant" would report the strongest
        possible dependence as evidence of independence -- precisely backwards.
      - At n around 12, a slope can be large and practically decisive while
        falling short of |t| > 2.

    So the criterion is: does the response move materially across the swept range
    of window sizes? RELATIVE_CHANGE_THRESHOLD is the fraction of the mean
    response that counts as material -- 25% here, which is far above measurement
    noise on a multi-second quantity and far below the ~10x effects this study
    reports elsewhere.
    """
    RELATIVE_CHANGE_THRESHOLD = 0.25

    t = preds.get("TIME_BASED", {})
    p2 = t.get("P2_final_episode_vs_window_size", {})
    if "error" in p2:
        return {"verdict": "INCONCLUSIVE", "reason": p2["error"]}

    if "degenerate" in p2:
        return {"verdict": "CONSISTENT_WITH_RESIDUAL_WINDOW_CONTENTS",
                "reason": (f"final-episode duration is constant across window sizes "
                           f"(mean {p2.get('response_mean', float('nan')):.2f}s) -- the "
                           f"strongest form of what the hypothesis predicts.")}

    coef = p2.get("coefficients", {}).get('window_size', {})
    est, tstat = coef.get("estimate"), coef.get("t")
    if est is None:
        return {"verdict": "INCONCLUSIVE", "reason": "no slope estimate"}

    change = p2.get("predicted_change_over_range")
    rel = p2.get("relative_change")
    exact = p2.get("exact_fit", False)
    r2 = p2.get("r2")

    material = rel is not None and rel >= RELATIVE_CHANGE_THRESHOLD
    significant = tstat is not None and abs(tstat) > 2.0
    # An exact fit has no t but is maximal evidence of dependence, so it counts
    # as significant when the movement is also material.
    decisive = material and (significant or exact)

    detail = (f"slope {est:+.3f}s per unit; predicted change "
              f"{change:+.2f}s across W in {p2.get('predictor_range')} "
              f"({rel:.0%} of the {p2.get('response_mean', float('nan')):.2f}s mean); "
              f"t={'exact fit, undefined' if exact else tstat}; R2={r2:.3f}")

    if decisive:
        return {"verdict": "RESIDUAL_WINDOW_CONTENTS_NOT_SUFFICIENT",
                "reason": (f"final-episode duration DOES scale with window_size. "
                           f"{detail}. Something inside the HALF_OPEN leg itself "
                           f"depends on T, so bounce count alone does not carry "
                           f"the mechanism.")}
    if material and not significant:
        return {"verdict": "INCONCLUSIVE",
                "reason": (f"final-episode duration moves materially with window_size "
                           f"but not reliably at this n. {detail}. More replicates "
                           f"would separate these; do not read as support either way.")}
    return {"verdict": "CONSISTENT_WITH_RESIDUAL_WINDOW_CONTENTS",
            "reason": (f"final-episode duration shows no material dependence on "
                       f"window_size. {detail}. The window governs how many attempts "
                       f"are needed, not how long the successful one takes -- which "
                       f"is what the hypothesis predicts.")}


def render(res):
    L = ["H3 mechanism -- per-episode recovery decomposition", "=" * 74,
         f"rows: {res['n_rows']}", ""]
    for arm, d in res["predictions"].items():
        L.append(f"--- {arm} (n={d['n']}, recovered={d['n_recovered']}, "
                 f"bouncing={d['n_bouncing']}, total bounces={d['total_bounces']})")
        if d["by_window_size"]:
            L.append(f"  {'W':>4} {'n':>3} {'bounces':>8} {'final_ep':>10} "
                     f"{'inter_att':>10} {'total':>8}")
            for w, s in d["by_window_size"].items():
                fe = "n/a" if s["mean_final_episode_s"] is None else f"{s['mean_final_episode_s']:.2f}s"
                ia = "n/a" if s["mean_inter_attempt_s"] is None else f"{s['mean_inter_attempt_s']:.2f}s"
                L.append(f"  {w:>4} {s['n']:>3} {s['mean_bounce_count']:>8.2f} "
                         f"{fe:>10} {ia:>10} {s['mean_total_s']:>7.2f}s")
        for label, key in (("P1 bounce ~ window_size", "P1_bounce_count_vs_window_size"),
                           ("P2 final_ep ~ window_size  <-- DISCRIMINATOR",
                            "P2_final_episode_vs_window_size"),
                           ("P2 final_ep ~ wait_duration", "P2_control_final_episode_vs_wait_duration"),
                           ("P3 inter_att ~ wait_duration", "P3_inter_attempt_vs_wait_duration"),
                           ("P3 inter_att ~ window_size", "P3_control_inter_attempt_vs_window_size")):
            f = d.get(key, {})
            if "error" in f:
                L.append(f"    {label:<42} n={f.get('n',0)} -- {f['error']}")
                continue
            if "degenerate" in f:
                L.append(f"    {label:<42} n={f.get('n',0)} -- {f['degenerate']} "
                         f"(mean {f.get('response_mean', float('nan')):.2f})")
                continue
            pred = [k for k in f["coefficients"] if k != "intercept"][0]
            c = f["coefficients"][pred]
            t = "n/a" if c["t"] is None else f"{c['t']:+.2f}"
            flag = "  [EXACT FIT -- t unreliable]" if f.get("exact_fit") else ""
            L.append(f"    {label:<42} slope={c['estimate']:+8.3f}  t={t:>7}  "
                     f"R2={f['r2']:.3f} adj={f['adj_r2']:.3f} n={f['n']}{flag}")
        L.append("")
    v = res["verdict"]
    L += [f"VERDICT: {v['verdict']}", f"  {v['reason']}"]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test():
    ok = True

    def mk(exp_id, rep, bounces, gap, ep, final, mode="full", gateway=False):
        t0, tr = 1000.0, []
        def iso(x):
            return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f000Z[Etc/UTC]")
        def ev(svc, brk, name, ts):
            return {"service": svc, "breaker": brk, "state_transition": name,
                    "creation_time": iso(ts)}
        tr.append(ev("order", "inventoryServiceCB", TRIP, t0 - 5))
        if gateway:
            tr.append(ev("gateway", "orderServiceCB", TRIP, t0 - 3))
        cur = t0
        for _ in range(bounces):
            tr.append(ev("order", "inventoryServiceCB", ENTRY, cur))
            tr.append(ev("order", "inventoryServiceCB", FAIL, cur + ep))
            cur += ep + gap
        tr.append(ev("order", "inventoryServiceCB", ENTRY, cur))
        tr.append(ev("order", "inventoryServiceCB", CLOSE, cur + final))
        return {"experiment_id": exp_id, "replicate": rep, "mode": mode,
                "machine_id": "test", "transitions": tr}

    # TIME: bounces rise with W; final episode CONSTANT at 2s -> hypothesis holds.
    recs = []
    for w, b in ((5, 1), (10, 2), (20, 3)):
        for r in range(4):
            recs.append(mk(f"LIN-LAT-TIM-T50-W{w}-D15", r, b, 15.0, 3.0, 2.0))
    for w in (5, 10, 20):
        for r in range(4):
            recs.append(mk(f"LIN-LAT-CNT-T50-W{w}-D15", r, 0, 15.0, 3.0, 2.0))

    rows = [x for rec in recs for x in decompose_run(rec)]
    if len(rows) != 24:
        print(f"FAIL: expected 24 rows, got {len(rows)}"); ok = False

    # Decomposition identity: the parts must sum to the whole.
    for r in rows:
        parts = (r["failed_episode_total_s"] + r["inter_attempt_total_s"]
                 + (r["final_episode_duration_s"] or 0.0))
        if abs(parts - r["total_s"]) > 1e-6:
            print(f"FAIL: decomposition does not sum: {parts} vs {r['total_s']}")
            ok = False
            break

    t = [r for r in rows if r["window_type"] == "TIME_BASED"]
    if sorted({r["bounce_count"] for r in t}) != [1, 2, 3]:
        print("FAIL: TIME bounce counts not extracted per window size"); ok = False
    c = [r for r in rows if r["window_type"] == "COUNT_BASED"]
    if any(r["bounce_count"] for r in c):
        print("FAIL: COUNT arm should have zero bounces"); ok = False

    res = analyse(rows)
    if res["verdict"]["verdict"] != "CONSISTENT_WITH_RESIDUAL_WINDOW_CONTENTS":
        print(f"FAIL: constant final episode should be consistent, got "
              f"{res['verdict']['verdict']}"); ok = False

    # Negative control: make the final episode scale with W -> must falsify.
    recs2 = []
    for w, b, f in ((5, 1, 2.0), (10, 2, 8.0), (20, 3, 20.0)):
        for r in range(4):
            recs2.append(mk(f"LIN-LAT-TIM-T50-W{w}-D15", r, b, 15.0, 3.0, f))
    rows2 = [x for rec in recs2 for x in decompose_run(rec)]
    if analyse(rows2)["verdict"]["verdict"] != "RESIDUAL_WINDOW_CONTENTS_NOT_SUFFICIENT":
        print("FAIL: scaling final episode should falsify the hypothesis"); ok = False

    # mode filter and gateway flag
    if decompose_run(mk("LIN-LAT-TIM-T50-W20-D15-M5-L10", 2, 2, 15., 3., 2.,
                        mode="occupancy")):
        print("FAIL: occupancy-mode record should be skipped"); ok = False
    g = decompose_run(mk("LIN-LAT-CNT-T50-W5-D30", 1, 0, 15., 3., 2., gateway=True))
    if not g or not g[0]["gateway_tripped"]:
        print("FAIL: gateway trip not flagged"); ok = False
    if g and g[0]["n_episodes"] != 1:
        print("FAIL: gateway events must not become subject episodes"); ok = False

    if parse_timestamp("2026-08-23T13:38:59.121482962Z[Etc/UTC]") is None:
        print("FAIL: bracketed-zone timestamp parse"); ok = False

    print("self-test PASSED" if ok else "self-test FAILED")
    if ok:
        print(); print(render(res))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="data/cb_transitions.jsonl")
    ap.add_argument("--out", default="analysis/out/recovery_decomposition.json")
    ap.add_argument("--include-gateway-tripped", action="store_true",
                    help="keep rows where a gateway breaker tripped (D23 confound)")
    ap.add_argument("--modes", default="full",
                    help="comma-separated record modes to keep")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return 0 if self_test() else 1

    path = Path(args.jsonl)
    if not path.exists():
        print(f"ERROR: {path} not found. Note cb_transitions.jsonl is gitignored "
              f"and must be committed with `git add -f`.", file=sys.stderr)
        return 1

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    records, rows = [], []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"WARN: line {i} invalid JSON ({e}); skipped", file=sys.stderr)
    for rec in records:
        rows.extend(decompose_run(rec, modes=modes))

    n_all = len(rows)
    n_gw = sum(1 for r in rows if r["gateway_tripped"])
    if not args.include_gateway_tripped:
        rows = [r for r in rows if not r["gateway_tripped"]]

    print(f"loaded {len(records)} records; {n_all} decomposed rows "
          f"(modes={modes}); {n_gw} gateway-tripped, "
          f"{'kept' if args.include_gateway_tripped else 'excluded'}")
    if not rows:
        print("ERROR: no rows left to analyse.", file=sys.stderr)
        return 1

    res = analyse(rows)
    res["gateway_tripped_excluded"] = (not args.include_gateway_tripped)
    res["n_gateway_tripped"] = n_gw
    res["rows"] = rows

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str))
    print(); print(render(res)); print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
