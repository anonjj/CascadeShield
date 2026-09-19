"""Independent gateway-trip poller and per-run coverage checker (Phase 4B).

READ-ONLY. Makes its own HTTP GETs against the gateway's existing actuator endpoints.
It does not import or call any runner/breaker_observer helper, so it is an independent
witness rather than a second view of the same instrumentation: if the runner's sidecar
path fails, this does not fail with it.

Two subcommands:

  poll    one continuous session for the whole sweep, ~1s cadence, appending JSONL:
          timestamp, per-breaker state, per-breaker bufferedCalls. Records its own
          start and stop markers so a killed poller is distinguishable from a quiet one.

  check   slices the poll log per run using the run's recorded timestamps and the
          pre-registered observation horizon, and classifies each run.

Verdict rule (pre-registered, see docs/paper/h3-postd25-analysis-plan.md):

  A run is VERIFIED_CLEAN only if ALL of:
    * its sidecar record shows no gateway CLOSED_TO_OPEN, AND
    * every polled gateway state inside the horizon is CLOSED, AND
    * the poller has COMPLETE coverage of that horizon.

  Incomplete coverage means NOT_VERIFIED even when the sidecar is clean -- absence of
  evidence from a poller that was not looking is not evidence of absence.

Four distinct failure modes are reported separately, because they need different
responses:
    POLL_ERROR        a tick exists but its HTTP GET failed -> instrument problem
    MISSING_TICK      no tick covers some second of the horizon -> coverage gap
    GATEWAY_NOT_CLOSED a tick observed a non-CLOSED gateway state -> contamination
    POLLER_STOPPED    the horizon extends beyond the poller's last tick / stop marker
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request

BREAKERS = ("orderServiceCB", "inventoryServiceCB", "paymentServiceCB")
STATE_RE = re.compile(r'resilience4j_circuitbreaker_state\{(.*?)\}\s+([0-9.eE+-]+)')
BUF_RE = re.compile(r'resilience4j_circuitbreaker_buffered_calls\{(.*?)\}\s+([0-9.eE+-]+)')

# Pre-registered horizon margin, seconds. See the analysis plan: the horizon runs from
# fault_injected_at to fault_cleared_at + time_to_recover + HORIZON_MARGIN_S.
HORIZON_MARGIN_S = 5.0
# A second of the horizon counts as covered if some tick lies within this of it.
COVERAGE_TOLERANCE_S = 1.6


# --------------------------------------------------------------------------- poll

def _get(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _tags(blob):
    return dict(re.findall(r'(\w+)="([^"]*)"', blob))


def scrape(base):
    rec = {"states": {}, "buffered": {}, "errors": []}
    try:
        cb = json.loads(_get(base + "/actuator/circuitbreakers"))
        details = cb.get("circuitBreakers", cb)
        for name in BREAKERS:
            d = details.get(name)
            if isinstance(d, dict):
                rec["states"][name] = d.get("state")
            elif isinstance(d, str):
                rec["states"][name] = d
    except Exception as e:
        rec["errors"].append(f"circuitbreakers: {e!r}")
    try:
        prom = _get(base + "/actuator/prometheus")
        for blob, val in STATE_RE.findall(prom):
            t = _tags(blob)
            if t.get("name") in BREAKERS and float(val) == 1.0:
                rec["states"].setdefault(t["name"], (t.get("state") or "").upper())
        agg = {}
        for blob, val in BUF_RE.findall(prom):
            t = _tags(blob)
            if t.get("name") in BREAKERS:
                agg[t["name"]] = agg.get(t["name"], 0.0) + float(val)
        rec["buffered"] = agg
    except Exception as e:
        rec["errors"].append(f"prometheus: {e!r}")
    return rec


def cmd_poll(a):
    prev = None
    n = 0
    with open(a.out, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": "poller_start", "t": time.time(),
                            "label": a.label, "interval": a.interval}) + "\n")
        f.flush()
        try:
            while True:
                t0 = time.time()
                rec = scrape(a.base)
                rec["t"] = t0
                rec["iso"] = dt.datetime.utcfromtimestamp(t0).strftime("%Y-%m-%dT%H:%M:%SZ")
                rec["ok"] = not rec["errors"] and bool(rec["states"])
                if prev is not None:
                    rec["gap_s"] = round(t0 - prev, 3)
                prev = t0
                n += 1
                f.write(json.dumps(rec) + "\n")
                f.flush()
                time.sleep(max(0.0, a.interval - (time.time() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            f.write(json.dumps({"_meta": "poller_stop", "t": time.time(), "ticks": n}) + "\n")
    return 0


# -------------------------------------------------------------------------- check

def parse_ts(raw):
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def load_poll(path):
    ticks, start, stop = [], None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("_meta") == "poller_start":
                start = r["t"]
            elif r.get("_meta") == "poller_stop":
                stop = r["t"]
            elif "_meta" not in r:
                ticks.append(r)
    ticks.sort(key=lambda x: x["t"])
    return ticks, start, stop


def horizon_for(fault_injected_at, fault_cleared_at, time_to_recover):
    """Pre-registered observation horizon.

    start = fault_injected_at                       (sidecar record)
    end   = fault_cleared_at                        (sidecar record)
          + time_to_recover                         (CSV column)
          + HORIZON_MARGIN_S

    time_to_recover is measured from cb_open_at, not from fault_cleared_at, so adding it
    to fault_cleared_at over-covers rather than under-covers. That is deliberate: this
    horizon gates a coverage REQUIREMENT, and erring long makes the requirement stricter.
    """
    lo = parse_ts(fault_injected_at)
    hi_base = parse_ts(fault_cleared_at) or lo
    if lo is None or hi_base is None:
        return None, None
    ttr = float(time_to_recover) if time_to_recover not in (None, "") else 0.0
    return lo, hi_base + ttr + HORIZON_MARGIN_S


def check_run(ticks, poll_start, poll_stop, lo, hi, sidecar_trips,
              tolerance=COVERAGE_TOLERANCE_S):
    """Classify one run. Returns a dict with the verdict and every distinct issue."""
    issues = []
    win = [t for t in ticks if lo <= t["t"] <= hi]

    # POLLER_STOPPED: the horizon reaches beyond where the poller was alive.
    last_alive = poll_stop if poll_stop is not None else (ticks[-1]["t"] if ticks else None)
    if poll_start is None or last_alive is None:
        issues.append("POLLER_STOPPED")
    else:
        if lo < poll_start - tolerance or hi > last_alive + tolerance:
            issues.append("POLLER_STOPPED")

    # POLL_ERROR: a tick exists but its fetch failed.
    if any(t.get("errors") or not t.get("ok", False) for t in win):
        issues.append("POLL_ERROR")

    # MISSING_TICK: some second of the horizon has no tick within tolerance.
    stamps = [t["t"] for t in win]
    uncovered = 0
    s = lo
    while s <= hi:
        if not any(abs(x - s) <= tolerance for x in stamps):
            uncovered += 1
        s += 1.0
    if uncovered:
        issues.append("MISSING_TICK")

    # GATEWAY_NOT_CLOSED: any observed non-CLOSED gateway state.
    bad = [(t.get("iso"), b, st) for t in win
           for b, st in (t.get("states") or {}).items() if st and st != "CLOSED"]
    if bad:
        issues.append("GATEWAY_NOT_CLOSED")

    peak = {}
    for t in win:
        for b, v in (t.get("buffered") or {}).items():
            peak[b] = max(peak.get(b, 0.0), v)

    if sidecar_trips or bad:
        verdict = "FAILED"
    elif issues:
        verdict = "NOT_VERIFIED"
    else:
        verdict = "VERIFIED_CLEAN"

    return {"verdict": verdict, "issues": sorted(set(issues)), "ticks": len(win),
            "uncovered_s": uncovered, "non_closed": bad[:5], "peak_buffered": peak,
            "sidecar_trips": sidecar_trips}


# ----------------------------------------------------------------------- selftest

def _tick(t, state="CLOSED", ok=True, err=False):
    return {"t": t, "iso": dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ok": ok, "errors": (["boom"] if err else []),
            "states": {b: state for b in BREAKERS},
            "buffered": {b: 10.0 for b in BREAKERS}}


def self_test():
    ok = True

    def expect(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))

    lo, hi = 1000.0, 1030.0
    full = [_tick(1000.0 + i) for i in range(31)]

    # 1. clean, complete coverage
    r = check_run(full, 999.0, 1031.0, lo, hi, [])
    expect("clean+complete -> VERIFIED_CLEAN", r["verdict"], "VERIFIED_CLEAN")
    expect("clean+complete -> no issues", r["issues"], [])

    # 2. injected GAP in the middle (drop 10 consecutive ticks)
    gapped = [t for t in full if not (1010.0 <= t["t"] <= 1019.0)]
    r = check_run(gapped, 999.0, 1031.0, lo, hi, [])
    expect("injected gap -> NOT_VERIFIED", r["verdict"], "NOT_VERIFIED")
    expect("injected gap -> MISSING_TICK", "MISSING_TICK" in r["issues"], True)
    expect("injected gap -> uncovered seconds", r["uncovered_s"] > 0, True)

    # 3. injected NON-CLOSED state
    dirty = [_tick(1000.0 + i, state=("OPEN" if i == 12 else "CLOSED")) for i in range(31)]
    r = check_run(dirty, 999.0, 1031.0, lo, hi, [])
    expect("injected OPEN -> FAILED", r["verdict"], "FAILED")
    expect("injected OPEN -> GATEWAY_NOT_CLOSED", "GATEWAY_NOT_CLOSED" in r["issues"], True)

    # 4. injected poll ERROR tick
    errd = [_tick(1000.0 + i, ok=(i != 7), err=(i == 7)) for i in range(31)]
    r = check_run(errd, 999.0, 1031.0, lo, hi, [])
    expect("injected poll error -> NOT_VERIFIED", r["verdict"], "NOT_VERIFIED")
    expect("injected poll error -> POLL_ERROR", "POLL_ERROR" in r["issues"], True)

    # 5. poller stopped before the horizon ends
    short = [t for t in full if t["t"] <= 1020.0]
    r = check_run(short, 999.0, 1020.0, lo, hi, [])
    expect("poller stopped early -> NOT_VERIFIED", r["verdict"], "NOT_VERIFIED")
    expect("poller stopped early -> POLLER_STOPPED", "POLLER_STOPPED" in r["issues"], True)

    # 6. sidecar trip dominates even with perfect polling
    r = check_run(full, 999.0, 1031.0, lo, hi, [{"state_transition": "CLOSED_TO_OPEN"}])
    expect("sidecar trip -> FAILED", r["verdict"], "FAILED")

    # 7. clean sidecar + incomplete coverage must NOT be VERIFIED_CLEAN
    r = check_run(gapped, 999.0, 1031.0, lo, hi, [])
    expect("clean sidecar + gap -> not clean", r["verdict"] != "VERIFIED_CLEAN", True)

    # 8. horizon arithmetic
    a, b = horizon_for("2026-09-20T10:00:00Z", "2026-09-20T10:00:09Z", "31.1")
    expect("horizon length = 9 + 31.1 + 5", round(b - a, 1), 45.1)

    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("poll", help="run the continuous read-only poller")
    p.add_argument("--base", default="http://localhost:8080")
    p.add_argument("--out", required=True)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--label", default="")

    c = sub.add_parser("check", help="classify runs against a poll log")
    c.add_argument("--polls", required=True)
    c.add_argument("--transitions", required=True)
    c.add_argument("--dataset", required=True)

    sub.add_parser("self-test", help="run the built-in self-test")

    a = ap.parse_args()
    if a.cmd == "poll":
        return cmd_poll(a)
    if a.cmd == "self-test":
        return 0 if self_test() else 1

    import csv
    ticks, pstart, pstop = load_poll(a.polls)
    recs = [json.loads(l) for l in open(a.transitions, encoding="utf-8") if l.strip()]
    rows = list(csv.DictReader(open(a.dataset, newline="", encoding="utf-8-sig")))
    ttr = {(r["experiment_id"], str(r["replicate"])): r.get("time_to_recover", "")
           for r in rows}
    print(f"poll ticks={len(ticks)}  sidecar records={len(recs)}  dataset rows={len(rows)}")
    counts = {}
    for rec in recs:
        key = (rec.get("experiment_id"), str(rec.get("replicate")))
        lo, hi = horizon_for(rec.get("fault_injected_at"), rec.get("fault_cleared_at"),
                             ttr.get(key, ""))
        if lo is None:
            print(f"  {key}: NOT_VERIFIED (no usable timestamps)")
            counts["NOT_VERIFIED"] = counts.get("NOT_VERIFIED", 0) + 1
            continue
        trips = [t for t in rec.get("transitions", [])
                 if t.get("service") == "gateway" and t.get("state_transition") == "CLOSED_TO_OPEN"]
        r = check_run(ticks, pstart, pstop, lo, hi, trips)
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print(f"  {key[0]:26s} rep={key[1]:>2s} {r['verdict']:<15} "
              f"ticks={r['ticks']:>4d} uncovered={r['uncovered_s']:>3d} "
              f"issues={','.join(r['issues']) or '-'}")
    print("\ntotals:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
