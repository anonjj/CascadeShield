"""Phase 4B post-sweep integrity check. Run AFTER the 72-run sweep, BEFORE any analysis.

Every check below is a gate, not a diagnostic: if one fails, the dataset is not
cleared for the pre-registered H3 analysis (`docs/paper/h3-postd25-analysis-plan.md`).
Nothing here computes a statistic, and nothing here modifies a file.

Checks, in order:

  1  CSV has exactly N_EXPECTED_RUNS rows and every (experiment_id, replicate) is unique.
  2  Every experiment_id is in the manifest's --only-ids list, and each of the 24
     configs carries exactly the replicates 1..3. A run outside the list is a
     contaminant, not a bonus.
  3  Every sidecar record ADDED SINCE THE BASELINE is validated against
     experiment_id + replicate + machine_id + mode + the manifest's sweep window.
     Anything that fails -- an unexpected ID, the wrong machine, a record outside
     the sweep's time range, or the smoke run's own record -- is REPORTED AND
     EXCLUDED. It is never silently folded into the sweep's evidence. The baseline
     prefix is verified byte-identical first; if the sidecar was truncated or
     rewritten rather than appended to, the check stops there.
  4  Reconciliation: every CSV row matches exactly one in-scope sidecar record,
     one-to-one (analysis/phase4b_reconcile.py). Zero orphans either way.
  5  All rows have precondition_ok == True.
  6  No gateway CLOSED_TO_OPEN in any matched record.
  7  Poller coverage per run, via analysis/gateway_poll_verify.py's pre-registered
     horizon and verdict rule. Reports the per-run verdict table and the four
     failure modes separately.
  8  Gateway image IDs still equal the manifest's, and the running container is
     still on that image.

    python analysis/phase4b_postsweep_check.py --manifest data/audit/phase4b_manifest.json
    python analysis/phase4b_postsweep_check.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phase4b_reconcile import (AT_REATTEMPT_CAP, MATCHED, MAX_REATTEMPTS,  # noqa: E402
                               cell_of, count_prior_attempts, parse_ts,
                               reconcile, sha256_file)
import gateway_poll_verify as gpv  # noqa: E402

N_EXPECTED_CONFIGS = 24
N_EXPECTED_REPLICATES = 3
N_EXPECTED_RUNS = N_EXPECTED_CONFIGS * N_EXPECTED_REPLICATES


class Report:
    def __init__(self):
        self.rows = []

    def add(self, ok, name, detail=""):
        self.rows.append((bool(ok), name, detail))
        return ok

    def print(self):
        print()
        for ok, name, detail in self.rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
            for line in (detail.splitlines() if detail else []):
                print(f"           {line}")
        bad = [n for ok, n, _ in self.rows if not ok]
        print(f"\n{len(self.rows) - len(bad)}/{len(self.rows)} checks passed.")
        if bad:
            print("FAILED: " + "; ".join(bad))
        return not bad


# ------------------------------------------------------------------ the checks

def check_1_2_rows(rep, rows, only_ids):
    keys = [(r.get("experiment_id"), str(r.get("replicate"))) for r in rows]
    rep.add(len(rows) == N_EXPECTED_RUNS, f"1a. CSV has {N_EXPECTED_RUNS} rows",
            f"found {len(rows)}")
    dups = sorted({k for k in keys if keys.count(k) > 1})
    rep.add(not dups, "1b. (experiment_id, replicate) unique",
            "\n".join(f"duplicate: {k}" for k in dups))

    unexpected = sorted({e for e, _ in keys} - set(only_ids))
    rep.add(not unexpected, "2a. every experiment_id is in the manifest --only-ids list",
            "\n".join(f"NOT in list (excluded from analysis): {e}" for e in unexpected))
    per = {}
    for e, r in keys:
        per.setdefault(e, set()).add(r)
    want = {str(i) for i in range(1, N_EXPECTED_REPLICATES + 1)}
    wrong = sorted((e, sorted(per.get(e, set()))) for e in only_ids
                   if per.get(e, set()) != want)
    rep.add(not wrong, f"2b. all {len(only_ids)} configs carry replicates {sorted(want)}",
            "\n".join(f"{e}: {got}" for e, got in wrong))


def classify_records(records, baseline_n, only_ids, machine_id, mode,
                     sweep_start, sweep_end, smoke_id=None):
    """Split the post-baseline sidecar records into in-scope and excluded.

    Returns (in_scope, excluded) where excluded is a list of (record, reason).
    A record is excluded -- never counted -- for any of: unexpected experiment_id,
    the smoke run's ID, the wrong machine_id, the wrong mode, an out-of-range
    replicate, or a fault_injected_at outside the manifest's sweep window.
    """
    lo, hi = parse_ts(sweep_start), parse_ts(sweep_end)
    want_reps = {str(i) for i in range(1, N_EXPECTED_REPLICATES + 1)}
    in_scope, excluded = [], []
    for rec in records[baseline_n:]:
        eid = rec.get("experiment_id")
        t = parse_ts(rec.get("fault_injected_at"))
        if smoke_id is not None and eid == smoke_id:
            excluded.append((rec, "SMOKE_RUN"))
        elif eid not in set(only_ids):
            excluded.append((rec, "ID_NOT_IN_ONLY_IDS"))
        elif str(rec.get("machine_id") or "") != machine_id:
            excluded.append((rec, f"WRONG_MACHINE ({rec.get('machine_id')!r})"))
        elif str(rec.get("mode") or "") != mode:
            excluded.append((rec, f"WRONG_MODE ({rec.get('mode')!r})"))
        elif str(rec.get("replicate")) not in want_reps:
            excluded.append((rec, f"REPLICATE_OUT_OF_RANGE ({rec.get('replicate')!r})"))
        elif t is None or lo is None or hi is None or not (lo <= t <= hi):
            excluded.append((rec, f"OUTSIDE_SWEEP_WINDOW ({rec.get('fault_injected_at')!r})"))
        else:
            in_scope.append(rec)
    return in_scope, excluded


def check_3_sidecar(rep, records, manifest):
    base = manifest["sidecar_baseline"]
    n = int(base["lines"])
    rep.add(len(records) >= n, "3a. sidecar was appended to, not truncated",
            f"baseline {n} records, file now has {len(records)}")
    if len(records) < n:
        return [], []
    prefix = "".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n"
                     for r in records[:n])
    # The prefix is compared structurally (re-serialised, key-sorted) rather than
    # byte-for-byte, so a re-serialisation by any tool is not mistaken for tampering
    # while a changed, added or removed record still is.
    ok_prefix = manifest.get("sidecar_baseline_struct_sha256") in (None, _sha(prefix))
    rep.add(ok_prefix, "3b. the first N sidecar records are the recorded baseline",
            "" if ok_prefix else "baseline prefix changed -- STOP, the sidecar was rewritten")

    in_scope, excluded = classify_records(
        records, n, manifest["only_ids"], manifest["machine_id"], manifest["mode"],
        manifest["sweep_window"]["start"], manifest["sweep_window"]["end"],
        smoke_id=(manifest.get("smoke") or {}).get("experiment_id"))
    detail = [f"post-baseline records: {len(records) - n}",
              f"in scope: {len(in_scope)}   excluded: {len(excluded)}"]
    for rec, why in excluded:
        detail.append(f"EXCLUDED {why}: {rec.get('experiment_id')} "
                      f"rep={rec.get('replicate')} machine={rec.get('machine_id')} "
                      f"mode={rec.get('mode')} injected={rec.get('fault_injected_at')}")
    rep.add(len(in_scope) == N_EXPECTED_RUNS,
            f"3c. exactly {N_EXPECTED_RUNS} in-scope sidecar records", "\n".join(detail))
    return in_scope, excluded


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_4_reconcile(rep, rows, in_scope, machine_id, mode, prior_attempts=None):
    r = reconcile(rows, in_scope, machine_id=machine_id, mode=mode,
                  prior_attempts=prior_attempts)
    det = [f"matched={r['counts'].get(MATCHED, 0)}",
           f"orphan CSV rows={len(r['quarantine'])}",
           f"at re-attempt cap={len(r['capped'])}",
           f"orphan sidecar records={len(r['orphan_records'])}"]
    for i in r["quarantine"] + r["capped"]:
        det.append(f"unmatched row line {i + 2}: {rows[i].get('experiment_id')} "
                   f"rep={rows[i].get('replicate')} [{r['classes'][i]}]")
    for j in r["orphan_records"]:
        det.append(f"orphan record {j}: {in_scope[j].get('experiment_id')} "
                   f"rep={in_scope[j].get('replicate')}")
    rep.add(r["counts"].get(MATCHED, 0) == N_EXPECTED_RUNS
            and not r["quarantine"] and not r["capped"] and not r["orphan_records"],
            f"4. all {N_EXPECTED_RUNS} rows reconcile one-to-one with a record",
            "\n".join(det))
    return r


def check_4b_attempts(rep, rows, prior_attempts):
    """Pre-registration Section 10: every attempt is counted and reported, and no key
    exceeds MAX_REATTEMPTS. This gate reports the ledger even when it passes -- the
    re-collection count is required output, not just a tripwire."""
    per = {}
    for row in rows:
        c = cell_of(row)
        per[c] = prior_attempts.get(c, 0) + 1
    recollected = {c: n for c, n in per.items() if n > 1}
    over = {c: n for c, n in per.items() if n > MAX_REATTEMPTS + 1}
    det = [f"keys collected on the first attempt: {len(per) - len(recollected)}",
           f"keys re-collected at least once   : {len(recollected)}",
           f"cap: {MAX_REATTEMPTS} re-attempts ({MAX_REATTEMPTS + 1} attempts) per key"]
    for c, n in sorted(recollected.items()):
        det.append(f"  {c[0]} rep={c[1]}: attempt {n} of {MAX_REATTEMPTS + 1}"
                   + ("   <-- OVER CAP" if n > MAX_REATTEMPTS + 1 else ""))
    rep.add(not over, f"4b. no key exceeded {MAX_REATTEMPTS} re-attempts", "\n".join(det))


def check_5_precondition(rep, rows):
    bad = [(r.get("experiment_id"), r.get("replicate"), r.get("precondition_fail_reason"))
           for r in rows if str(r.get("precondition_ok")) != "True"]
    rep.add(not bad, f"5. all {N_EXPECTED_RUNS} rows have precondition_ok == True",
            "\n".join(f"{e} rep={p}: {why}" for e, p, why in bad))


def gateway_trips(rec):
    return [t for t in (rec.get("transitions") or [])
            if t.get("service") == "gateway" and t.get("state_transition") == "CLOSED_TO_OPEN"]


def check_6_gateway(rep, in_scope):
    bad = [(r.get("experiment_id"), r.get("replicate"), len(gateway_trips(r)))
           for r in in_scope if gateway_trips(r)]
    rep.add(not bad, "6. no gateway CLOSED_TO_OPEN in any in-scope record",
            "\n".join(f"{e} rep={p}: {n} trip(s)" for e, p, n in bad))


def check_7_poller(rep, rows, in_scope, poll_path):
    if not poll_path or not os.path.exists(poll_path):
        rep.add(False, "7. poller coverage per run",
                f"poll log not found: {poll_path!r} -- coverage is UNVERIFIED, which "
                "the plan treats as NOT_VERIFIED, not as clean")
        return {}
    ticks, pstart, pstop = gpv.load_poll(poll_path)
    # wait_duration rides along so a null time_to_recover falls back to the
    # pre-registered 3*wait+60 horizon rather than collapsing to +0s.
    ttr = {(r.get("experiment_id"), str(r.get("replicate"))):
           (r.get("time_to_recover", ""), r.get("wait_duration", ""))
           for r in rows}
    counts, lines = {}, [f"poll ticks={len(ticks)}"]
    n_fallback = 0
    for rec in in_scope:
        key = (rec.get("experiment_id"), str(rec.get("replicate")))
        r_ttr, r_wait = ttr.get(key, ("", ""))
        if r_ttr in (None, ""):
            n_fallback += 1
        lo, hi = gpv.horizon_for(rec.get("fault_injected_at"), rec.get("fault_cleared_at"),
                                 r_ttr, wait_duration=r_wait)
        if lo is None:
            counts["NOT_VERIFIED"] = counts.get("NOT_VERIFIED", 0) + 1
            lines.append(f"{key[0]} rep={key[1]}: NOT_VERIFIED (horizon undefined -- "
                         "unusable timestamps, or a null time_to_recover with no "
                         "wait_duration to fall back on)")
            continue
        res = gpv.check_run(ticks, pstart, pstop, lo, hi, gateway_trips(rec))
        counts[res["verdict"]] = counts.get(res["verdict"], 0) + 1
        lines.append(f"{key[0]:26s} rep={key[1]:>2s} {res['verdict']:<15} "
                     f"ticks={res['ticks']:>4d} uncovered={res['uncovered_s']:>3d} "
                     f"issues={','.join(res['issues']) or '-'}")
    if n_fallback:
        lines.append(f"!! {n_fallback} run(s) had a null time_to_recover; their horizon "
                     "used the pre-registered 3*wait+60 fallback")
    lines.append(f"totals: {counts}")
    rep.add(counts.get("VERIFIED_CLEAN", 0) == N_EXPECTED_RUNS,
            f"7. all {N_EXPECTED_RUNS} runs VERIFIED_CLEAN under the pre-registered "
            "horizon + coverage rule", "\n".join(lines))
    return counts


def _docker(args):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def check_8_image(rep, manifest, skip=False):
    if skip:
        rep.add(False, "8. gateway image unchanged vs manifest",
                "--skip-docker was passed: image provenance is UNVERIFIED")
        return
    img = _docker(["image", "inspect", manifest["gateway_image_repo"], "--format", "{{.Id}}"])
    cont = _docker(["inspect", manifest["gateway_container"], "--format", "{{.Image}}"])
    det = [f"manifest image     : {manifest['gateway_image_id']}",
           f"docker image now   : {img}",
           f"container .Image   : {cont}"]
    ok = (img is not None and cont is not None
          and img == manifest["gateway_image_id"] == cont)
    rep.add(ok, "8. gateway image ID unchanged, and the container is still on it",
            "\n".join(det))


# -------------------------------------------------------------------- self-test

def _mk_manifest(tmpd, baseline_n):
    return {
        "machine_id": "soham-local", "mode": "full", "seed": 20260920,
        "only_ids": [f"LIN-LAT-CNT-T50-W5-D{d}" for d in (5, 15, 30)],
        "sidecar_baseline": {"path": "x.jsonl", "lines": baseline_n},
        "sweep_window": {"start": "2026-09-21T00:00:00Z", "end": "2026-09-22T00:00:00Z"},
        "smoke": {"experiment_id": "LIN-LAT-CNT-T30-W5-D5"},
        "gateway_image_repo": "infra-gateway-service",
        "gateway_container": "gateway-service",
        "gateway_image_id": "sha256:deadbeef",
    }


def self_test():
    ok = True

    def expect(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))

    m = _mk_manifest(None, 2)
    base = [{"experiment_id": "OLD", "replicate": 1}, {"experiment_id": "OLD", "replicate": 2}]

    def rec(eid, r, machine="soham-local", mode="full", t="2026-09-21T10:00:00Z"):
        return {"experiment_id": eid, "replicate": r, "machine_id": machine,
                "mode": mode, "fault_injected_at": t, "fault_cleared_at": t,
                "transitions": []}

    good = rec("LIN-LAT-CNT-T50-W5-D5", 1)
    cases = [
        ("smoke record excluded", rec("LIN-LAT-CNT-T30-W5-D5", 1), "SMOKE_RUN"),
        ("unexpected id excluded", rec("LIN-LAT-TIM-T70-W20-D30", 1), "ID_NOT_IN_ONLY_IDS"),
        ("wrong machine excluded", rec("LIN-LAT-CNT-T50-W5-D5", 1, machine="jay-mac"),
         "WRONG_MACHINE ('jay-mac')"),
        ("wrong mode excluded", rec("LIN-LAT-CNT-T50-W5-D5", 1, mode="canary"),
         "WRONG_MODE ('canary')"),
        ("replicate out of range", rec("LIN-LAT-CNT-T50-W5-D5", 9),
         "REPLICATE_OUT_OF_RANGE (9)"),
        ("before sweep window", rec("LIN-LAT-CNT-T50-W5-D5", 1, t="2026-09-20T10:00:00Z"),
         "OUTSIDE_SWEEP_WINDOW ('2026-09-20T10:00:00Z')"),
        ("after sweep window", rec("LIN-LAT-CNT-T50-W5-D5", 1, t="2026-09-23T10:00:00Z"),
         "OUTSIDE_SWEEP_WINDOW ('2026-09-23T10:00:00Z')"),
    ]
    for label, bad, why in cases:
        ins, exc = classify_records(base + [good, bad], 2, m["only_ids"], m["machine_id"],
                                    m["mode"], m["sweep_window"]["start"],
                                    m["sweep_window"]["end"], m["smoke"]["experiment_id"])
        expect(label + " -> in scope", len(ins), 1)
        expect(label + " -> reason", [w for _, w in exc], [why])

    ins, exc = classify_records(base + [good], 2, m["only_ids"], m["machine_id"], m["mode"],
                                m["sweep_window"]["start"], m["sweep_window"]["end"],
                                m["smoke"]["experiment_id"])
    expect("clean record kept", (len(ins), len(exc)), (1, 0))

    r = Report()
    check_5_precondition(r, [{"experiment_id": "A", "replicate": 1,
                              "precondition_ok": "False",
                              "precondition_fail_reason": "READINESS_TIMEOUT"}])
    expect("precondition check fails on an aborted row", r.rows[0][0], False)

    r = Report()
    check_6_gateway(r, [{"experiment_id": "A", "replicate": 1, "transitions": [
        {"service": "gateway", "state_transition": "CLOSED_TO_OPEN"}]}])
    expect("gateway trip is caught", r.rows[0][0], False)
    r = Report()
    check_6_gateway(r, [{"experiment_id": "A", "replicate": 1, "transitions": [
        {"service": "order", "state_transition": "CLOSED_TO_OPEN"}]}])
    expect("a non-gateway trip is not a gateway trip", r.rows[0][0], True)

    r = Report()
    check_1_2_rows(r, [{"experiment_id": "LIN-LAT-CNT-T50-W5-D5", "replicate": "1"},
                       {"experiment_id": "LIN-LAT-CNT-T50-W5-D5", "replicate": "1"}],
                   m["only_ids"])
    expect("duplicate key caught", r.rows[1][0], False)
    expect("wrong row count caught", r.rows[0][0], False)

    # --- 2026-09-20 amendment: re-collection cap ledger (Section 10) ---------------
    cell = ("LIN-LAT-CNT-T50-W5-D5", "1")
    rows1 = [{"experiment_id": cell[0], "replicate": cell[1]}]
    r = Report(); check_4b_attempts(r, rows1, {})
    expect("first-attempt key passes the cap gate", r.rows[0][0], True)
    expect("first-attempt key is not listed as re-collected",
           "re-collected at least once   : 0" in r.rows[0][2], True)
    r = Report(); check_4b_attempts(r, rows1, {cell: 2})
    expect("attempt 3 (2 re-attempts) is at the cap, not over it", r.rows[0][0], True)
    expect("re-collection is reported even when it passes",
           "attempt 3 of 3" in r.rows[0][2], True)
    r = Report(); check_4b_attempts(r, rows1, {cell: 3})
    expect("attempt 4 exceeds the cap", r.rows[0][0], False)
    expect("over-cap key is named", "OVER CAP" in r.rows[0][2], True)

    # --- 2026-09-20 amendment: Section 5 horizon fallback -------------------------
    INJ2, CLR2 = "2026-09-21T10:00:00Z", "2026-09-21T10:00:09Z"
    a, b = gpv.horizon_for(INJ2, CLR2, "", wait_duration="30")
    expect("null time_to_recover -> 9 + (3*30+60) + 5", round(b - a, 1), 164.0)
    a, b = gpv.horizon_for(INJ2, CLR2, "2.5", wait_duration="30")
    expect("measured time_to_recover still wins", round(b - a, 1), 16.5)
    expect("null ttr and no wait_duration -> horizon undefined",
           gpv.horizon_for(INJ2, CLR2, "", wait_duration=""), (None, None))

    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest")
    ap.add_argument("--skip-docker", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return 0 if self_test() else 1
    if not a.manifest:
        ap.error("--manifest is required unless --self-test")

    with open(a.manifest, encoding="utf-8") as f:
        m = json.load(f)
    with open(m["dataset_path"], newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    with open(m["transitions_path"], encoding="utf-8") as f:
        records = [json.loads(l) for l in f if l.strip()]

    print(f"manifest     : {a.manifest}")
    print(f"git HEAD     : {m.get('git_head')}")
    print(f"dataset      : {m['dataset_path']} ({len(rows)} rows, "
          f"sha256 {sha256_file(m['dataset_path'])})")
    print(f"transitions  : {m['transitions_path']} ({len(records)} records, "
          f"sha256 {sha256_file(m['transitions_path'])})")
    print(f"poll log     : {m.get('poll_path')}")
    print(f"sweep window : {m['sweep_window']['start']} .. {m['sweep_window']['end']}")

    audit_dir = m.get("audit_dir", os.path.join("data", "audit"))
    prior = count_prior_attempts(audit_dir)

    rep = Report()
    check_1_2_rows(rep, rows, m["only_ids"])
    in_scope, _excluded = check_3_sidecar(rep, records, m)
    check_4_reconcile(rep, rows, in_scope, m["machine_id"], m["mode"], prior)
    check_4b_attempts(rep, rows, prior)
    check_5_precondition(rep, rows)
    check_6_gateway(rep, in_scope)
    check_7_poller(rep, rows, in_scope, m.get("poll_path"))
    check_8_image(rep, m, skip=a.skip_docker)
    return 0 if rep.print() else 1


if __name__ == "__main__":
    sys.exit(main())
