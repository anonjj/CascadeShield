"""Gateway-contamination audit (Phase 2).

Builds a per-run gateway-trip sidecar view and classifies every dataset row against it.
READ-ONLY: never writes to any dataset, never adds a column to any CSV. Outputs land under
data/audit/ (gitignored).

Gateway status comes ONLY from the cb_transitions sidecar. `cb_state_pre` is a pre-load
snapshot and is NOT evidence about mid-run state. The D21 censoring columns
(half_open_probe_timed_out / half_open_probe_deadline_s) record half-open probe censoring
and are NOT evidence about gateway trips.

Two timeline boundaries gate what a sidecar record can prove:

  EVENTS_BUFFER_FIX  0494dd06 2026-08-27T17:16:00+05:30 -- CB_EVENT_BUFFER_SIZE 50 -> 5000
                     ("was silently dropping CLOSED_TO_OPEN"). A record collected before
                     this may have had a gateway CLOSED_TO_OPEN evicted from the 50-entry
                     ring before the harness polled it, so absence of a trip is NOT VERIFIED.
  D25_PIN            d1c6a481 2026-09-18T13:20:50+05:30 -- gateway measurement-plane pinned.

Categories (a row is assigned exactly one):
  VERIFIED_TRIPPED            sidecar record shows a gateway CLOSED_TO_OPEN
  VERIFIED_CLEAN              complete sidecar record, no gateway CLOSED_TO_OPEN, collected
                              after BOTH boundaries above
  NOT_VERIFIED_EVICTION       sidecar record, no gateway trip, but collected before the
                              events-buffer fix -- eviction possible
  NOT_VERIFIED_PRE_D25        sidecar record, no gateway trip, after the buffer fix but
                              before the D25 pin -- the gateway could still trip
  NOT_VERIFIED_INCOMPLETE     sidecar record present but missing fields needed to judge
  UNVERIFIED_POST_D25_NO_SIDECAR   no sidecar record, run dated after the D25 pin
  UNVERIFIED_PRE_D25_NO_SIDECAR    no sidecar record, run dated before the D25 pin
                                   (reported split by window_type: COUNT_BASED is the
                                   at-risk arm per D23; TIME_BASED had zero observed trips
                                   per D24 but remains unverified per row)

There is deliberately no "assumed clean" category.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from collections import defaultdict, Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVENTS_BUFFER_FIX = dt.datetime.fromisoformat("2026-08-27T17:16:00+05:30")
D25_PIN = dt.datetime.fromisoformat("2026-09-18T13:20:50+05:30")

# Max |run_timestamp - fault_injected_at| for a sidecar record to be evidence about a row.
# A run writes its CSV row and its sidecar record in the same pass, so the two stamps are
# minutes apart at most; this bounds an accidental cross-run match.
MATCH_TOLERANCE_S = 1800

GATEWAY_SERVICE = "gateway"
TRIP = "CLOSED_TO_OPEN"

DATASETS = [
    ("master_dataset.csv", "H3 recovery set / full sweep"),
    ("master_dataset_d21_recollect.csv", "D21 censoring re-collection"),
    ("master_dataset_crash_recollect_linear.csv", "CRASH re-collection"),
    ("master_dataset_calibration_codespace_linear_overlap.csv", "D6 calibration overlap"),
    ("master_dataset_calibration_soham_fanout_overlap.csv", "D6 calibration overlap"),
    ("occupancy_dataset.csv", "D7 occupancy / H2b"),
    ("master_dataset_v6_pre_d17_leg_blend_crash.csv", "archive, pre-D17"),
    ("master_dataset_v5_soham_linear_presweep.csv", "archive, pre-sweep"),
    ("master_dataset_v4_flat_concurrency.csv", "archive, flat concurrency"),
    ("master_dataset_v3_gateway_not_rebuilt.csv", "archive, stale gateway image"),
    ("master_dataset_v2_latency_5svc.csv", "archive"),
    ("master_dataset_v1_prefix.csv", "archive, null timing cols"),
    ("canary_matrix_runs.csv", "canary matrix executor"),
]

SIDECARS = [
    ("cb_transitions.jsonl", "main sidecar"),
    ("audit/canary_2026-09-20/COUNT_arm_transitions.jsonl", "Phase 1 canary COUNT arm"),
    ("audit/canary_2026-09-20/TIME_arm_transitions.jsonl", "Phase 1 canary TIME arm"),
]


def parse_ts(raw):
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r), (r.fieldnames or [])


def load_sidecars(paths):
    """Returns (strict, loose, records). Strict keys on
    (experiment_id, replicate, machine_id); loose on (experiment_id, replicate) for
    datasets or records lacking machine_id. The key actually used per dataset is
    reported, never silently widened without saying so."""
    records = []
    for rel, label in paths:
        p = os.path.join(REPO, "data", rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rec["_source"] = rel
                rec["_label"] = label
                records.append(rec)
    strict, loose = {}, defaultdict(list)
    for rec in records:
        eid = rec.get("experiment_id")
        rep = rec.get("replicate")
        mid = rec.get("machine_id")
        mode = rec.get("mode")
        try:
            rep = int(rep)
        except (TypeError, ValueError):
            pass
        # `mode` is part of the key, not decoration. A canary record and a full-sweep row
        # can share (experiment_id, replicate, machine_id) exactly -- the Phase 1 canary
        # reused LIN-LAT-CNT-T70-W20-D30 / LIN-LAT-TIM-T70-W20-D30 at replicates that also
        # exist in master_dataset.csv on the same machine. Without mode in the key those
        # post-D25 canary records false-match pre-D25 sweep rows and manufacture
        # VERIFIED_CLEAN rows that were never verified.
        if mid:
            strict[(eid, rep, mid, mode)] = rec
        loose[(eid, rep, mode)].append(rec)
    return strict, loose, records


def gateway_trips(rec):
    return [t for t in rec.get("transitions", [])
            if t.get("service") == GATEWAY_SERVICE and t.get("state_transition") == TRIP]


def sidecar_complete(rec):
    return bool(rec.get("fault_injected_at")) and "transitions" in rec


def classify(rec, run_ts):
    if rec is None:
        if run_ts is None:
            return "UNVERIFIED_NO_SIDECAR_UNDATED"
        return ("UNVERIFIED_POST_D25_NO_SIDECAR" if run_ts >= D25_PIN
                else "UNVERIFIED_PRE_D25_NO_SIDECAR")
    if gateway_trips(rec):
        return "VERIFIED_TRIPPED"
    if not sidecar_complete(rec):
        return "NOT_VERIFIED_INCOMPLETE"
    collected = parse_ts(rec.get("fault_injected_at")) or run_ts
    if collected is None:
        return "NOT_VERIFIED_INCOMPLETE"
    if collected < EVENTS_BUFFER_FIX:
        return "NOT_VERIFIED_EVICTION"
    if collected < D25_PIN:
        return "NOT_VERIFIED_PRE_D25"
    return "VERIFIED_CLEAN"


def audit_dataset(fname, note, strict, loose):
    path = os.path.join(REPO, "data", fname)
    if not os.path.exists(path):
        return None
    rows, header = read_csv(path)
    has_mid = "machine_id" in header
    key_used = (("experiment_id + replicate + machine_id + mode, disambiguated by "
                 "run_timestamp proximity (one-to-one)") if has_mid
                else ("experiment_id + replicate + mode, disambiguated by run_timestamp "
                      "proximity (machine_id absent from header)"))

    # ---- candidate generation -------------------------------------------------
    # (experiment_id, replicate, machine_id, mode) is NOT unique in every dataset:
    # master_dataset_d21_recollect.csv holds 45 rows over only 36 distinct such keys
    # (9 collisions), because `replicate` was reused across two collection passes on the
    # same day with genuinely different measurements. So the key alone cannot identify a
    # run. Candidates are therefore disambiguated by run_timestamp proximity to the
    # sidecar's fault_injected_at, and assigned one-to-one: a sidecar record is evidence
    # about exactly one run and must never be counted for two.
    cand_pairs = []
    row_meta = []
    for i, row in enumerate(rows):
        eid = row.get("experiment_id")
        try:
            rep = int(row.get("replicate", ""))
        except (TypeError, ValueError):
            rep = row.get("replicate")
        mid = row.get("machine_id") if has_mid else None
        mode = row.get("mode")
        run_ts = parse_ts(row.get("run_timestamp"))
        row_meta.append((eid, rep, mid, mode, run_ts))
        # Loose fallback is ONLY legitimate when one side genuinely lacks machine_id.
        # It must never join across machines: master_dataset.csv carries codespace /
        # soham-local / jay-mac / jay-overnight-rerun rows, while the in-repo sidecar is
        # 72/73 jay-mac. Attaching jay-mac gateway evidence to another machine's run
        # would manufacture verification that does not exist.
        cands = [c for c in loose.get((eid, rep, mode), [])
                 if not c.get("machine_id") or not mid or c.get("machine_id") == mid]
        for c in cands:
            ct = parse_ts(c.get("fault_injected_at"))
            if run_ts is None or ct is None:
                delta = None
            else:
                delta = abs((ct - run_ts).total_seconds())
                if delta > MATCH_TOLERANCE_S:
                    continue
            cand_pairs.append((delta if delta is not None else float("inf"), i, id(c), c))

    cand_pairs.sort(key=lambda t: t[0])
    assigned = {}
    used = set()
    for delta, i, cid, c in cand_pairs:
        if i in assigned or cid in used:
            continue
        assigned[i] = (c, delta)
        used.add(cid)

    per_row = []
    matched_strict = matched_loose = 0
    for i, row in enumerate(rows):
        eid, rep, mid, mode, run_ts = row_meta[i]
        rec, delta = assigned.get(i, (None, None))
        if rec is not None:
            if mid and rec.get("machine_id") == mid:
                matched_strict += 1
            else:
                matched_loose += 1
        cat = classify(rec, run_ts)
        per_row.append({
            "experiment_id": eid, "replicate": rep, "machine_id": mid or "",
            "window_type": row.get("window_type", ""),
            "wait_duration": row.get("wait_duration", ""),
            "run_timestamp": row.get("run_timestamp", ""),
            "category": cat,
        })
    return {
        "dataset": fname, "note": note, "n_rows": len(rows), "n_cols": len(header),
        "header": header, "key_used": key_used,
        "matched_strict": matched_strict, "matched_loose": matched_loose,
        "rows": per_row,
    }


def tabulate(result):
    """Row-level and distinct-configuration-level counts by window_type x wait_duration."""
    row_tab = defaultdict(Counter)
    cfg_map = defaultdict(lambda: defaultdict(set))
    for r in result["rows"]:
        cell = (r["window_type"] or "?", r["wait_duration"] or "?")
        row_tab[cell][r["category"]] += 1
        cfg_map[cell][r["category"]].add(r["experiment_id"])
    cfg_tab = {cell: Counter({k: len(v) for k, v in d.items()}) for cell, d in cfg_map.items()}
    return row_tab, cfg_tab


SHORT = {
    "VERIFIED_TRIPPED": "TRIPPED",
    "VERIFIED_CLEAN": "CLEAN",
    "NOT_VERIFIED_EVICTION": "NV:evict",
    "NOT_VERIFIED_PRE_D25": "NV:preD25",
    "NOT_VERIFIED_INCOMPLETE": "NV:incompl",
    "UNVERIFIED_POST_D25_NO_SIDECAR": "UNV:post,nosc",
    "UNVERIFIED_PRE_D25_NO_SIDECAR": "UNV:pre,nosc",
    "UNVERIFIED_NO_SIDECAR_UNDATED": "UNV:undated",
}


def render(result, out):
    row_tab, cfg_tab = tabulate(result)
    cats = sorted({c for t in row_tab.values() for c in t})
    p = out.append
    p("")
    p("=" * 110)
    p("%s   (%s)" % (result["dataset"], result["note"]))
    p("  rows=%d  header_cols=%d" % (result["n_rows"], result["n_cols"]))
    p("  join key: %s" % result["key_used"])
    unmatched = result["n_rows"] - result["matched_strict"] - result["matched_loose"]
    p("  sidecar matches: strict=%d  loose-fallback=%d  unmatched=%d"
      % (result["matched_strict"], result["matched_loose"], unmatched))
    p("=" * 110)
    for label, tab in (("ROW LEVEL", row_tab),
                       ("CONFIG LEVEL (distinct experiment_id)", cfg_tab)):
        p("")
        p("  -- %s --" % label)
        p("  %-13s%5s  " % ("window_type", "D_w") + "".join("%16s" % SHORT.get(c, c) for c in cats))
        for cell in sorted(tab):
            wt, dw = cell
            p("  %-13s%5s  " % (wt, dw) + "".join("%16d" % tab[cell].get(c, 0) for c in cats))
        tot = Counter()
        for cell in tab:
            tot.update(tab[cell])
        p("  %-13s%5s  " % ("TOTAL", "") + "".join("%16d" % tot.get(c, 0) for c in cats))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "data", "audit"))
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    strict, loose, records = load_sidecars(SIDECARS)
    out = []
    out.append("GATEWAY CONTAMINATION AUDIT")
    out.append("events-buffer fix boundary : %s  (0494dd06)" % EVENTS_BUFFER_FIX.isoformat())
    out.append("D25 gateway-pin boundary   : %s  (d1c6a481)" % D25_PIN.isoformat())
    out.append("sidecar records loaded     : %d" % len(records))
    trip_recs = [r for r in records if gateway_trips(r)]
    out.append("sidecar records w/ gateway CLOSED_TO_OPEN : %d" % len(trip_recs))

    results = []
    for fname, note in DATASETS:
        res = audit_dataset(fname, note, strict, loose)
        if res:
            results.append(res)
            render(res, out)

    text = "\n".join(out)
    print(text)
    with open(os.path.join(a.out_dir, "gateway_contamination.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(a.out_dir, "gateway_contamination.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k != "header"} for r in results], f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
