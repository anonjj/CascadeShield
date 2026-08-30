"""
analysis/window_type_recovery_leak.py  (D12 -- the user's own working label; NOT a
docs/paper/decision-log.md D-00X entry, and NOT the unrelated "Day N" sprint-day
shorthand used elsewhere in this repo, e.g. resumable_runner.py's "(D9)".)

Does window_type leak into circuit-breaker RECOVERY time, contaminating H3's intended
double dissociation (window_type -> detection speed only, wait_duration -> recovery
speed only, docs/paper/hypotheses.md S3)?

An Aug-15 note observed TIME recovering ~2x slower than COUNT at the same wait_duration.
Re-run here against data/master_dataset.csv during planning: the effect is real, large
(2.06x-3.68x across wait_duration=5/15/30), and reproduces across every archived dataset
-- not noise. But the metric available to test it with is too coarse to prove *where* the
effect lives, so this script runs two analyses:

  (a) COARSE -- the original diagnostic, column-corrected, on time_to_recover as
      currently collected. time_to_recover = t(declared recovered) - t(cb_open_at)
      (runner.py:1179-1227), where "recovered" is the harness's blast_radius proxy
      reading 0.0 across two consecutive 1s-apart polls. That proxy (BlastRadiusService,
      checking only for the literal "CIRCUIT_OPEN" health status) flips the INSTANT the
      breaker leaves OPEN for HALF_OPEN -- it cannot distinguish HALF_OPEN from CLOSED at
      all. So (a) measures "OPEN -> left-OPEN", not "OPEN -> CLOSED", and a window_type
      effect on WHEN cb_open_at lands (plausible and non-buggy: TIME_BASED windows
      accumulate over wall-clock seconds, so trip timing legitimately differs from
      COUNT_BASED under identical load) will show up in this ratio even with a perfectly
      clean recovery-side dissociation. Reported for continuity with the Aug-15 note, NOT
      treated as a verdict on the mechanism -- see the anchor/excess decomposition below.

  (b) PRECISE -- derives the true HALF_OPEN -> CLOSED duration from real Resilience4j
      STATE_TRANSITION events in data/cb_transitions.jsonl (runner.py's
      log_cb_transitions/collect_new_transitions, sourced from
      /actuator/circuitbreakerevents/{breaker}). This is the only metric that actually
      isolates the leg a real leak would appear on, separate from the OPEN->HALF_OPEN
      leg (pure wait_duration, reported as a sanity check -- should be window-type-
      agnostic). It requires the sidecar file to exist; as of this writing it does not
      (real-runs-only, gitignored, absent from this checkout). (b) therefore ships fully
      implemented and exercised only via --self-test against an in-memory fixture; run
      against real data it reports SKIPPED_NO_SIDECAR rather than fabricating a verdict.

The suspected mechanism as originally stated ("HALF_OPEN re-evaluation goes back through
the TIME_BASED window") is NOT architecturally plausible for Resilience4j 2.2.0 (the
version this repo pins): HALF_OPEN always uses its own fixed-size ring buffer sized
exactly permittedNumberOfCallsInHalfOpenState, independent of slidingWindowType. If (b)
ever finds a real HALF_OPEN->CLOSED effect, it is a different mechanism than the one
originally suspected.

Usage:   python analysis/window_type_recovery_leak.py [dataset]   (default "current")
         python analysis/window_type_recovery_leak.py --self-test (fixture only, no I/O)
Output:  analysis/out/window_type_recovery_leak[_<dataset>].json
         analysis/out/window_type_recovery_leak[_<dataset>]_paired.csv
"""

import json
import sys

import numpy as np
import pandas as pd

from common import DATA_DIR, OUT_DIR, bootstrap_ci_grouped, cliffs_delta, load, write_json

COL_WINDOW = "window_type"
COL_WAIT = "wait_duration"
COL_RECOVERY = "time_to_recover"      # was recovery_time in the original diagnostic
COL_OPEN = "time_to_open"             # needed for the anchor/excess decomposition

# lambda_target is NOT a persisted column in data/master_dataset.csv (confirmed) --
# build MATCH_KEYS from whatever actually exists and report what got dropped, rather
# than silently match on fewer keys and let a reader assume arrival rate was controlled.
MATCH_KEYS_WANTED = ["topology", "fault_type", "window_size", "threshold",
                      "wait_duration", "lambda_target"]

CB_TRANSITIONS_FILENAME = "cb_transitions.jsonl"

# fault_type/topology (uppercase, as persisted) -> (direct-caller service, breaker names
# on it whose OPEN state the coarse blast_radius/health-endpoint metric would have
# counted). BOTH breakers on that service are watched, not just the one on the fault's
# own path, because BlastRadiusService.hasOpenCircuitBreaker() flags a service degraded
# if ANY of its breakers reports CIRCUIT_OPEN -- to measure the same event the coarse
# metric measured. Extend only when a real dataset adds a combination not listed here;
# never silently default to "order" for one that isn't -- SKIPPED_UNMAPPED_TOPOLOGY_FAULT
# is the correct behavior for an unlisted combination.
BREAKER_WATCH = {
    ("LINEAR", "LATENCY"): ("order", ["inventoryServiceCB", "sharedDbCB"]),
}

RATIO_THRESHOLD = 1.15  # matches the original diagnostic's "consistent leak" bar


def norm(value):
    """COUNT_BASED -> COUNT, TIME_BASED -> TIME."""
    return str(value).upper().replace("_BASED", "").strip()


# --------------------------------------------------------------------- shared ratio math

def _ratio_table(df, value_col):
    """Median TIME/COUNT ratio of `value_col`, grouped by wait_duration.

    Returns per-wait-level rows (n, medians, ratio, Cliff's delta, cluster-bootstrap CI
    per arm) plus the plain ratio list and a two-sided consistency verdict -- "TIME
    slower at every level" and "COUNT slower at every level" are both reported, since a
    leak could in principle run either direction.
    """
    rows = []
    ratios = []
    for wd, g in df.groupby(COL_WAIT):
        c = g[g[COL_WINDOW] == "COUNT"][value_col].dropna()
        t = g[g[COL_WINDOW] == "TIME"][value_col].dropna()
        if len(c) == 0 or len(t) == 0:
            continue
        cm, tm = float(c.median()), float(t.median())
        ratio = (tm / cm) if cm else None
        if ratio is not None:
            ratios.append(ratio)
        rows.append({
            "wait_duration": float(wd),
            "n_count": int(len(c)),
            "n_time": int(len(t)),
            "median_count": cm,
            "median_time": tm,
            "ratio_time_over_count": ratio,
            # (COUNT, TIME) order -- matches canary_readout.py and order_leg_containment.py's
            # convention for this same conceptual comparison; keep it consistent so `delta`'s
            # sign means the same thing across every script's JSON output.
            "cliffs_delta": cliffs_delta(c.values, t.values),
            "ci_count": bootstrap_ci_grouped(g[g[COL_WINDOW] == "COUNT"], value_col),
            "ci_time": bootstrap_ci_grouped(g[g[COL_WINDOW] == "TIME"], value_col),
        })
    return {
        "by_wait_duration": rows,
        "ratios": ratios,
        "median_ratio": float(np.median(ratios)) if ratios else None,
        "min_ratio": float(min(ratios)) if ratios else None,
        "max_ratio": float(max(ratios)) if ratios else None,
        "consistent_time_slower": bool(ratios) and all(r > RATIO_THRESHOLD for r in ratios),
        "consistent_count_slower": bool(ratios) and all(r < 1 / RATIO_THRESHOLD for r in ratios),
    }


def _paired_view(df, value_col, match_keys):
    """Fully-matched paired view: same config on every listed key, only window_type
    differs. `match_keys` must already be filtered to columns that exist in `df`."""
    if not match_keys:
        return pd.DataFrame()
    piv = (df.groupby(match_keys + [COL_WINDOW])[value_col]
             .median().unstack(COL_WINDOW))
    if "COUNT" not in piv.columns or "TIME" not in piv.columns:
        return pd.DataFrame()
    piv = piv.dropna(subset=["COUNT", "TIME"]).copy()
    if len(piv):
        piv["ratio"] = piv["TIME"] / piv["COUNT"]
    return piv


# ------------------------------------------------------------------------- (a) coarse

def coarse_ratio_check(df):
    d = df.copy()
    d[COL_WINDOW] = d[COL_WINDOW].map(norm)
    d = d[d[COL_WINDOW].isin(["COUNT", "TIME"])].copy()
    d["excess"] = d[COL_RECOVERY] - d[COL_WAIT]

    used_keys = [k for k in MATCH_KEYS_WANTED if k in d.columns]
    missing_keys = [k for k in MATCH_KEYS_WANTED if k not in d.columns]
    piv = _paired_view(d, COL_RECOVERY, used_keys)

    return {
        "n_rows": int(len(d)),
        "n_count": int((d[COL_WINDOW] == "COUNT").sum()),
        "n_time": int((d[COL_WINDOW] == "TIME").sum()),
        "match_keys": {"requested": MATCH_KEYS_WANTED, "used": used_keys, "missing": missing_keys},
        "time_to_recover": _ratio_table(d, COL_RECOVERY),
        # Separates "TIME opens later" (a flat anchor shift, not a recovery-side leak)
        # from "TIME's post-open excess grows with wait_duration" (not explainable by a
        # constant shift -- the pattern actually found against the real archive).
        "time_to_open_anchor": _ratio_table(d, COL_OPEN),
        "excess_over_wait_duration": _ratio_table(d, "excess"),
        "paired": {
            "n_pairs": int(len(piv)),
            "median_paired_ratio": float(piv["ratio"].median()) if len(piv) else None,
            "share_time_slower": float((piv["ratio"] > 1).mean()) if len(piv) else None,
            "rows": piv.reset_index().to_dict("records") if len(piv) else [],
        },
    }


# ------------------------------------------------------------------------ (b) precise

def load_transition_index(path):
    """{(experiment_id, replicate, mode, environment, machine_id): record}. Joins on all
    five keys (the docstring in runner.py recommends the first three; environment and
    machine_id are added here to rule out cross-environment/cross-machine collisions --
    D16's calibration protocol runs the identical experiment_id/replicate/mode/
    environment on two different machines by design, so machine_id is load-bearing, not
    defensive). If a key repeats, the last line in the file wins -- an append-only log's
    most recent write is the authoritative one."""
    index = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec["experiment_id"], str(rec["replicate"]), rec["mode"], rec["environment"],
                   rec["machine_id"])
            index[key] = rec
    return index


def _parse_java_ts(s):
    """Resilience4j's actuator API serializes creationTime via Java's
    ZonedDateTime.toString(), which appends a bracketed zone id (e.g.
    "2026-08-27T09:31:15.986004462Z[Etc/UTC]") that ISO-8601 doesn't have and
    pandas.Timestamp rejects outright. The leading offset/Z already fully
    determines the instant -- every service runs the same JVM timezone
    (see collect_new_transitions's ordering comment) -- so the bracket is
    redundant; strip it rather than teach pandas a Java-specific format."""
    return pd.Timestamp(s.split("[")[0])


def _walk_breaker(events):
    """One breaker's chronologically-sorted STATE_TRANSITION events -> the timestamps
    of its first OPEN, its first post-open HALF_OPEN, its last HALF_OPEN->CLOSED, a
    HALF_OPEN->OPEN bounce count, and whether it ended the record CLOSED."""
    events = sorted(events, key=lambda e: e["creation_time"])
    t_open = None
    t_half_open_first = None
    t_closed_last = None
    bounces = 0
    last_state = None
    for e in events:
        st = e.get("state_transition")
        ts = e.get("creation_time")
        if st in ("CLOSED_TO_OPEN", "HALF_OPEN_TO_OPEN"):
            if t_open is None:
                t_open = ts
            if st == "HALF_OPEN_TO_OPEN":
                bounces += 1
        elif st == "OPEN_TO_HALF_OPEN" and t_half_open_first is None:
            t_half_open_first = ts
        elif st == "HALF_OPEN_TO_CLOSED":
            t_closed_last = ts
        last_state = st
    return {
        "t_open": t_open,
        "t_half_open_first": t_half_open_first,
        "t_closed_last": t_closed_last,
        "bounces": bounces,
        "recovered": t_open is not None and last_state == "HALF_OPEN_TO_CLOSED",
    }


def precise_row_for(row, index):
    """One master_dataset row -> its precise HALF_OPEN->CLOSED reading, or a SKIPPED_*
    status explaining why it couldn't be computed. Never guesses a breaker for a
    (topology, fault_type) combination not in BREAKER_WATCH."""
    watch = BREAKER_WATCH.get((row["topology"], row["fault_type"]))
    if watch is None:
        return {"status": "SKIPPED_UNMAPPED_TOPOLOGY_FAULT"}
    service, breakers = watch

    key = (row["experiment_id"], str(row["replicate"]), row["mode"], row["environment"],
           row["machine_id"])
    rec = index.get(key)
    if rec is None:
        return {"status": "SKIPPED_NO_MATCHING_RECORD"}

    per_breaker = {}
    for breaker in breakers:
        events = [t for t in rec.get("transitions", [])
                  if t.get("service") == service and t.get("breaker") == breaker]
        if events:
            per_breaker[breaker] = _walk_breaker(events)

    opened = {b: w for b, w in per_breaker.items() if w["t_open"] is not None}
    if not opened:
        return {"status": "NEVER_OPENED"}

    t_open = min(_parse_java_ts(w["t_open"]) for w in opened.values())
    half_opens = [_parse_java_ts(w["t_half_open_first"]) for w in opened.values()
                  if w["t_half_open_first"]]
    t_half_open = min(half_opens) if half_opens else None
    n_bounces = sum(w["bounces"] for w in opened.values())

    # "Recovered" mirrors BlastRadiusService's "any OPEN -> degraded" semantics: not
    # clean until every breaker that opened is back to CLOSED.
    all_recovered = all(w["recovered"] for w in opened.values())
    closed_times = [_parse_java_ts(w["t_closed_last"]) for w in opened.values() if w["t_closed_last"]]
    recovered_at = max(closed_times) if (all_recovered and closed_times) else None

    result = {
        "status": "OK",
        "n_half_open_bounces": int(n_bounces),
        "precise_recovered": recovered_at is not None,
    }
    if t_half_open is not None:
        result["precise_open_to_half_open"] = (t_half_open - t_open).total_seconds()
    if recovered_at is not None:
        result["precise_time_to_recover"] = (recovered_at - t_open).total_seconds()
        if t_half_open is not None:
            result["precise_half_open_to_closed"] = (recovered_at - t_half_open).total_seconds()
    return result


def precise_recovery_from_transitions(cb_transitions_path, master_df):
    index = load_transition_index(cb_transitions_path)
    records = []
    for _, row in master_df.iterrows():
        r = precise_row_for(row, index)
        r["experiment_id"] = row["experiment_id"]
        r["replicate"] = row["replicate"]
        r[COL_WINDOW] = norm(row[COL_WINDOW])
        r[COL_WAIT] = row[COL_WAIT]
        records.append(r)
    pdf = pd.DataFrame(records)

    ok = pdf[pdf["status"] == "OK"]
    status_counts = {k: int(v) for k, v in pdf["status"].value_counts().items()}

    return {
        "status_counts": status_counts,
        "n_ok": int(len(ok)),
        "half_open_to_closed": (_ratio_table(ok, "precise_half_open_to_closed")
                                 if "precise_half_open_to_closed" in ok.columns else None),
        "open_to_half_open_sanity_check": (_ratio_table(ok, "precise_open_to_half_open")
                                            if "precise_open_to_half_open" in ok.columns else None),
        "rows": pdf.to_dict("records"),
    }


# ---------------------------------------------------------------------------- verdict

def _verdict(coarse, precise, precise_status):
    if precise_status != "COMPUTED":
        return "MECHANISM_UNTESTED_NO_SIDECAR"
    hoc = precise.get("half_open_to_closed")
    if not hoc or not hoc["ratios"]:
        return "AMBIGUOUS"
    if hoc["consistent_time_slower"] or hoc["consistent_count_slower"]:
        return "LEAK_CONFIRMED_ON_HALF_OPEN_LEG"
    coarse_rec = coarse["time_to_recover"]
    coarse_consistent = coarse_rec["consistent_time_slower"] or coarse_rec["consistent_count_slower"]
    if coarse_consistent:
        return "CONFIRMED_ANCHOR_SHIFT_ONLY_DISSOCIATION_HOLDS"
    return "AMBIGUOUS"


# ------------------------------------------------------------------------------- main

def main(dataset="current"):
    df = load(dataset)
    coarse = coarse_ratio_check(df)

    sidecar_path = DATA_DIR / CB_TRANSITIONS_FILENAME
    if sidecar_path.exists():
        precise = precise_recovery_from_transitions(sidecar_path, df)
        precise_status = "COMPUTED"
        precise_note = None
    else:
        precise = None
        precise_status = "SKIPPED_NO_SIDECAR"
        precise_note = (
            "data/cb_transitions.jsonl is real-runs-only and gitignored; it does not "
            "exist in this checkout. The precise HALF_OPEN->CLOSED metric cannot be "
            "computed until a run of experiments/runner.py retains it. This script's "
            "join logic is exercised by --self-test against a synthetic fixture only."
        )

    verdict = _verdict(coarse, precise, precise_status)
    payload = {
        "dataset": dataset,
        "coarse": coarse,
        "precise": {"status": precise_status, "note": precise_note, "result": precise},
        "verdict": verdict,
    }

    suffix = "" if dataset == "current" else "_{}".format(dataset)
    write_json("window_type_recovery_leak{}.json".format(suffix), payload)
    if coarse["paired"]["rows"]:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(coarse["paired"]["rows"]).to_csv(
            OUT_DIR / "window_type_recovery_leak{}_paired.csv".format(suffix), index=False)

    _print_summary(dataset, coarse, precise_status, verdict)
    return payload


def _print_summary(dataset, coarse, precise_status, verdict):
    rec = coarse["time_to_recover"]
    print("dataset: {}  |  rows: {}  |  COUNT={}  TIME={}".format(
        dataset, coarse["n_rows"], coarse["n_count"], coarse["n_time"]))
    print("match_keys used: {}  (dropped, not in dataset: {})".format(
        coarse["match_keys"]["used"], coarse["match_keys"]["missing"]))

    print("\n[COARSE] time_to_recover (OPEN -> left-OPEN, see docstring)")
    print("wait_duration |  n(C/T) | median C | median T | ratio T/C")
    print("-" * 62)
    for r in rec["by_wait_duration"]:
        print("{:>13.0f} | {:>2}/{:<3} | {:>8.3f} | {:>8.3f} | {:>6.2f}x".format(
            r["wait_duration"], r["n_count"], r["n_time"],
            r["median_count"], r["median_time"], r["ratio_time_over_count"]))
    if rec["ratios"]:
        print("-" * 62)
        print("median ratio: {:.2f}x (range {:.2f}-{:.2f})".format(
            rec["median_ratio"], rec["min_ratio"], rec["max_ratio"]))

    anchor = coarse["time_to_open_anchor"]
    excess = coarse["excess_over_wait_duration"]
    print("\n[COARSE] anchor/excess decomposition")
    print("wait_duration | median t_open C | T    | median excess C | T")
    print("-" * 62)
    a_by_wd = {r["wait_duration"]: r for r in anchor["by_wait_duration"]}
    e_by_wd = {r["wait_duration"]: r for r in excess["by_wait_duration"]}
    for wd in sorted(a_by_wd):
        a, e = a_by_wd[wd], e_by_wd.get(wd)
        print("{:>13.0f} | {:>15.3f} | {:>4.3f} | {:>16.3f} | {:>5.3f}".format(
            wd, a["median_count"], a["median_time"],
            e["median_count"] if e else float("nan"), e["median_time"] if e else float("nan")))

    print("\n[PRECISE] status: {}".format(precise_status))
    print("\nVERDICT: {}".format(verdict))


# --------------------------------------------------------------------------- self-test

def self_test():
    """In-memory fixture exercising every status branch of precise_row_for(), with no
    file I/O and no dependence on data/cb_transitions.jsonl existing."""
    base = pd.Timestamp("2026-08-01T00:00:00Z")

    def ts(seconds):
        return (base + pd.Timedelta(seconds=seconds)).isoformat()

    def transition(service, breaker, state, seconds):
        return {"service": service, "breaker": breaker, "state_transition": state,
                "creation_time": ts(seconds)}

    def row(experiment_id, replicate, window_type, wait_duration,
            topology="LINEAR", fault_type="LATENCY", mode="full", environment="LOCAL",
            machine_id="host-a"):
        return pd.Series({
            "experiment_id": experiment_id, "replicate": replicate, "mode": mode,
            "environment": environment, "machine_id": machine_id, "topology": topology,
            "fault_type": fault_type, "window_type": window_type,
            "wait_duration": wait_duration,
        })

    index = {}

    # 1. Clean COUNT run: opens at t=0, half-open at t=5 (wait_duration), closed at t=7.
    r1 = row("LIN-LAT-CNT-A", 1, "COUNT_BASED", 5)
    index[("LIN-LAT-CNT-A", "1", "full", "LOCAL", "host-a")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_CLOSED", 7),
        ]
    }

    # 2. Clean TIME run: same wait_duration, but HALF_OPEN->CLOSED takes far longer
    #    (15s instead of 2s) -- this is the shape a real leak would produce.
    r2 = row("LIN-LAT-TIM-A", 1, "TIME_BASED", 5)
    index[("LIN-LAT-TIM-A", "1", "full", "LOCAL", "host-a")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_CLOSED", 20),
        ]
    }

    # 3. HALF_OPEN bounce: probe fails once, re-opens, then eventually closes.
    r3 = row("LIN-LAT-CNT-B", 1, "COUNT_BASED", 5)
    index[("LIN-LAT-CNT-B", "1", "full", "LOCAL", "host-a")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_OPEN", 6),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 11),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_CLOSED", 13),
        ]
    }

    # 4. Never recovered: opens, goes half-open, bounces back open, record ends there.
    r4 = row("LIN-LAT-CNT-C", 1, "COUNT_BASED", 5)
    index[("LIN-LAT-CNT-C", "1", "full", "LOCAL", "host-a")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_OPEN", 6),
        ]
    }

    # 5. Unmapped topology/fault combination -- not in BREAKER_WATCH.
    r5 = row("FAN-CRS-CNT-A", 1, "COUNT_BASED", 5, topology="FANOUT", fault_type="CRASH")

    # 6. No matching sidecar record for this row at all.
    r6 = row("LIN-LAT-CNT-D", 1, "COUNT_BASED", 5)

    # 7. Breaker never opened (empty transitions list for the watched breakers).
    r7 = row("LIN-LAT-CNT-E", 1, "COUNT_BASED", 5)
    index[("LIN-LAT-CNT-E", "1", "full", "LOCAL", "host-a")] = {"transitions": []}

    # 8. Two machines colliding on every OTHER key (D16's calibration protocol runs
    #    identical experiment_id/replicate/mode/environment on both boxes by design) --
    #    machine_id must keep them distinct in the index, not last-write-wins overwrite.
    r8a = row("LIN-LAT-CNT-F", 1, "COUNT_BASED", 5, machine_id="host-a")
    r8b = row("LIN-LAT-CNT-F", 1, "COUNT_BASED", 5, machine_id="host-b")
    index[("LIN-LAT-CNT-F", "1", "full", "LOCAL", "host-a")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_CLOSED", 7),
        ]
    }
    index[("LIN-LAT-CNT-F", "1", "full", "LOCAL", "host-b")] = {
        "transitions": [
            transition("order", "inventoryServiceCB", "CLOSED_TO_OPEN", 0),
            transition("order", "inventoryServiceCB", "OPEN_TO_HALF_OPEN", 5),
            transition("order", "inventoryServiceCB", "HALF_OPEN_TO_CLOSED", 25),
        ]
    }

    res1 = precise_row_for(r1, index)
    assert res1["status"] == "OK" and res1["precise_recovered"] is True
    assert res1["precise_open_to_half_open"] == 5.0
    assert res1["precise_half_open_to_closed"] == 2.0
    assert res1["n_half_open_bounces"] == 0

    res2 = precise_row_for(r2, index)
    assert res2["status"] == "OK" and res2["precise_recovered"] is True
    assert res2["precise_open_to_half_open"] == 5.0
    assert res2["precise_half_open_to_closed"] == 15.0

    res3 = precise_row_for(r3, index)
    assert res3["status"] == "OK" and res3["precise_recovered"] is True
    assert res3["n_half_open_bounces"] == 1
    assert res3["precise_open_to_half_open"] == 5.0          # FIRST half-open, pre-bounce
    assert res3["precise_half_open_to_closed"] == 8.0         # 13 - 5

    res4 = precise_row_for(r4, index)
    assert res4["status"] == "OK" and res4["precise_recovered"] is False
    assert "precise_time_to_recover" not in res4
    assert "precise_half_open_to_closed" not in res4

    res5 = precise_row_for(r5, index)
    assert res5["status"] == "SKIPPED_UNMAPPED_TOPOLOGY_FAULT"

    res6 = precise_row_for(r6, index)
    assert res6["status"] == "SKIPPED_NO_MATCHING_RECORD"

    res7 = precise_row_for(r7, index)
    assert res7["status"] == "NEVER_OPENED"

    res8a = precise_row_for(r8a, index)
    res8b = precise_row_for(r8b, index)
    assert res8a["status"] == "OK" and res8b["status"] == "OK"
    assert res8a["precise_half_open_to_closed"] == 2.0, "host-a's own record, not host-b's"
    assert res8b["precise_half_open_to_closed"] == 20.0, "host-b's own record, not host-a's"

    print("self-test: 8/8 fixtures OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        arg = sys.argv[1] if len(sys.argv) > 1 else "current"
        main(arg)
