"""Reconcile the Phase 4B dataset CSV against the cb_transitions sidecar.

WHY THIS EXISTS
---------------
A Phase 4B run is only usable if its CSV row and its sidecar record are the *same*
run. The Phase 2 audit found two ways that join silently manufactured evidence:
a mode collision (canary IDs colliding with sweep IDs) and a cross-machine
fallback (jay-mac gateway evidence attached to other machines' rows). So the join
key here is the full one -- experiment_id + replicate + machine_id + mode -- plus a
derived time window, and it is assigned ONE-TO-ONE: a sidecar record is never
counted as evidence about two runs.

The inverse failure is an *orphaned CSV row*: a row exists with no record behind
it. `resumable_runner.load_completed()` keys resumption on (experiment_id,
replicate) and treats any row with precondition_ok=="True" as done, so an orphaned
row permanently blocks its own cell from being re-run. Moving the row out of the
CSV is what makes the runner reschedule that key.

WHAT IT TOUCHES
---------------
The CSV only. The sidecar (`data/cb_transitions.jsonl`) is append-only evidence and
is NEVER read-modify-written by this script -- it is opened read-only. Nothing here
hand-edits a dataset: rows are moved wholesale, never rewritten.

THE TIME WINDOW, AND WHY IT IS THE SHAPE IT IS
----------------------------------------------
The sidecar record carries `fault_injected_at` and `fault_cleared_at`; the CSV row
carries `run_timestamp`. They are different instants in the same run, in a fixed
order set by runner.py:

    runner.py:1265  fault_injected_at = _now_iso()      <-- before the load
    runner.py:1384  fault_cleared_at  = _now_iso()      <-- fault removed
    runner.py:1402  observer.observe_recovery(...)      <-- the only open-ended phase
    runner.py:1442  log_results(...)  -> run_timestamp  <-- CSV row stamped here
    runner.py:1451  observer.log(...)                   <-- sidecar record appended

So for a genuine (row, record) pair:

    fault_injected_at  <=  run_timestamp  <=  fault_cleared_at
                                              + half_open_probe_deadline_s(wait)
                                              + POST_RECOVERY_MARGIN_S

The upper bound is not a guess. `half_open_probe_deadline_s(wait) = 3*wait + 60`
(`experiments/breaker_observer.py:30`) is the harness's OWN hard ceiling on
`_drive_half_open_probes`, i.e. on the only phase between `fault_cleared_at` and
`log_results` whose duration is data-dependent. Everything after that ceiling is
arithmetic plus a metrics scrape, which `POST_RECOVERY_MARGIN_S` (60s) covers with
an order of magnitude to spare. Concretely the window is 135s wide at D_w=5, 165s
at D_w=15, 210s at D_w=30 -- tight enough that two runs of the same cell minutes
apart cannot both match, wide enough that no real pair is ever rejected.

`LOW_SLACK_S` (2s) exists only because both timestamps come from
`time.strftime(...%S...)`, which TRUNCATES rather than rounds, so `run_timestamp`
can legitimately print up to a second before the instant it was taken.

This replaces the Phase 2 audit's flat 1800s proximity tolerance, which was chosen
to disambiguate two historical collection passes rather than derived from the
harness.

USAGE
-----
    python analysis/phase4b_reconcile.py --dataset data/phase4b_postd25.csv \
        --transitions data/cb_transitions.jsonl --machine-id soham-local
    python analysis/phase4b_reconcile.py ... --apply
    python analysis/phase4b_reconcile.py --self-test

--apply refuses to run while a runner process is alive.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# --- window constants (see module docstring for the derivation) ---------------
POST_RECOVERY_MARGIN_S = 60.0
LOW_SLACK_S = 2.0
# Fallback when a row carries no usable wait_duration: the largest wait in
# runner.PARAM_VALUES, i.e. the widest window the grid can produce. Erring wide
# here risks a false match; it is used only for rows the CSV has already damaged,
# and every row it is used for is reported.
FALLBACK_WAIT_S = 30.0
# run_status.json is considered evidence of a live runner only if it was touched
# within this many seconds -- a runner killed mid-sweep leaves phase=="running"
# forever, and that must not permanently block reconciliation.
STATUS_FRESH_S = 900.0

MATCHED = "MATCHED"
ORPHAN_ROW = "ORPHAN_ROW"
ORPHAN_ROW_ABORTED = "ORPHAN_ROW_ABORTED"
DUPLICATE_KEY = "DUPLICATE_KEY"
ORPHAN_RECORD = "ORPHAN_RECORD"


# ----------------------------------------------------------------- primitives

def parse_ts(raw):
    """ISO-8601 -> epoch seconds, or None. Naive stamps are treated as UTC, which
    is what runner.py writes (time.gmtime + a literal 'Z')."""
    if raw in (None, ""):
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def half_open_probe_deadline_s(wait_duration):
    """Mirror of experiments/breaker_observer.py:half_open_probe_deadline_s.
    Duplicated rather than imported so this analysis script never drags in
    runner.py's module-scope Toxiproxy client (the same reason constants.py
    exists)."""
    return 3.0 * float(wait_duration) + 60.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def row_wait_duration(row):
    """(wait_duration_seconds, used_fallback)."""
    raw = (row.get("wait_duration") or "").strip()
    try:
        return float(raw), False
    except (TypeError, ValueError):
        return FALLBACK_WAIT_S, True


def match_window(row, rec):
    """(lo, hi) epoch bounds that run_timestamp must fall in for `rec` to be this
    row's record, or (None, None) when the record has no usable timestamps."""
    lo = parse_ts(rec.get("fault_injected_at"))
    cleared = parse_ts(rec.get("fault_cleared_at"))
    if lo is None:
        return None, None
    if cleared is None:
        cleared = lo
    wait, _ = row_wait_duration(row)
    return lo - LOW_SLACK_S, cleared + half_open_probe_deadline_s(wait) + POST_RECOVERY_MARGIN_S


def key_of(obj):
    return (str(obj.get("experiment_id") or ""), str(obj.get("replicate") or ""),
            str(obj.get("machine_id") or ""), str(obj.get("mode") or ""))


# -------------------------------------------------------------------- matching

def reconcile(rows, records, machine_id=None, mode="full"):
    """Pure function: no I/O. Returns a report dict.

    rows    -- list of CSV row dicts (order preserved; index is identity)
    records -- list of sidecar record dicts (index is identity)
    """
    # 1. Duplicate (experiment_id, replicate) keys in the CSV. A cell with two
    #    measurements cannot be reconciled -- we cannot know which is the real
    #    one -- so EVERY row of a duplicated key is quarantined and the cell is
    #    recollected. Detected before matching so a duplicate can never be
    #    "resolved" by whichever row happens to win the greedy assignment.
    seen = {}
    for i, r in enumerate(rows):
        seen.setdefault((str(r.get("experiment_id") or ""), str(r.get("replicate") or "")),
                        []).append(i)
    dup_idx = {i for idxs in seen.values() if len(idxs) > 1 for i in idxs}

    # 2. Candidate pairs: full key equality, correct mode, correct machine, and
    #    run_timestamp inside the derived window.
    cands = []
    fallback_rows = set()
    for i, row in enumerate(rows):
        if i in dup_idx:
            continue
        if str(row.get("mode") or "") != mode:
            continue
        if machine_id is not None and str(row.get("machine_id") or "") != machine_id:
            continue
        rts = parse_ts(row.get("run_timestamp"))
        if rts is None:
            continue
        _, used_fb = row_wait_duration(row)
        if used_fb:
            fallback_rows.add(i)
        for j, rec in enumerate(records):
            if str(rec.get("mode") or "") != mode:
                continue
            if key_of(row) != key_of(rec):
                continue
            lo, hi = match_window(row, rec)
            if lo is None or not (lo <= rts <= hi):
                continue
            cleared = parse_ts(rec.get("fault_cleared_at")) or lo
            cands.append((abs(rts - cleared), i, j))

    # 3. One-to-one assignment, closest pair first.
    cands.sort()
    row_to_rec, rec_to_row = {}, {}
    for _, i, j in cands:
        if i in row_to_rec or j in rec_to_row:
            continue
        row_to_rec[i] = j
        rec_to_row[j] = i

    classes = {}
    for i, row in enumerate(rows):
        if i in dup_idx:
            classes[i] = DUPLICATE_KEY
        elif i in row_to_rec:
            classes[i] = MATCHED
        elif str(row.get("precondition_ok") or "") != "True":
            classes[i] = ORPHAN_ROW_ABORTED
        else:
            classes[i] = ORPHAN_ROW

    orphan_records = [j for j in range(len(records)) if j not in rec_to_row]
    keep = [i for i in range(len(rows)) if classes[i] == MATCHED]
    quarantine = [i for i in range(len(rows)) if classes[i] != MATCHED]

    counts = {}
    for c in classes.values():
        counts[c] = counts.get(c, 0) + 1
    counts[ORPHAN_RECORD] = len(orphan_records)

    return {"classes": classes, "row_to_rec": row_to_rec, "rec_to_row": rec_to_row,
            "orphan_records": orphan_records, "keep": keep, "quarantine": quarantine,
            "counts": counts, "fallback_wait_rows": sorted(fallback_rows),
            "n_rows": len(rows), "n_records": len(records)}


# ------------------------------------------------------------ runner liveness

def _process_cmdlines():
    """Best-effort list of running process command lines. Returns None when no
    method worked -- which is NOT the same as 'no runner running', and is treated
    as a refusal below."""
    try:
        import psutil  # optional
        out = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            if p.info["pid"] == os.getpid():
                continue
            out.append(" ".join(p.info["cmdline"] or []))
        return out
    except Exception:
        pass
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "Select-Object -ExpandProperty CommandLine"],
                capture_output=True, text=True, timeout=60)
        else:
            r = subprocess.run(["ps", "-eo", "args="],
                               capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        return r.stdout.splitlines()
    except Exception:
        return None


RUNNER_RE = re.compile(r"runner\.py", re.I)


def runner_active(status_path, ignore_stale_status=False):
    """(is_active, [reasons]). Two independent signals; either one blocks --apply."""
    reasons = []
    cmds = _process_cmdlines()
    if cmds is None:
        reasons.append("could not enumerate processes -- cannot prove no runner is "
                       "alive, refusing (this is the safe direction)")
    else:
        hits = [c for c in cmds if RUNNER_RE.search(c or "")
                and "phase4b_reconcile" not in (c or "")]
        if hits:
            reasons.append(f"runner process alive: {hits[0][:160]}")
    try:
        with open(status_path, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("phase") == "running":
            age = time.time() - (parse_ts(st.get("updated_at")) or 0.0)
            if age <= STATUS_FRESH_S:
                reasons.append(f"{status_path}: phase=running, updated {age:.0f}s ago")
            elif not ignore_stale_status:
                reasons.append(
                    f"{status_path}: phase=running but stale ({age:.0f}s). If the "
                    "runner really is dead, re-run with --ignore-stale-status")
    except FileNotFoundError:
        pass
    except Exception as e:
        reasons.append(f"{status_path}: unreadable ({e!r}) -- refusing")
    return bool(reasons), reasons


# ----------------------------------------------------------------------- apply

def apply_changes(dataset, header, rows, rep, audit_dir, stamp):
    """Back up, write the orphans file, then atomically rewrite the CSV with only
    the matched rows. Returns a dict of paths and hashes."""
    os.makedirs(audit_dir, exist_ok=True)
    before_sha = sha256_file(dataset)
    backup = os.path.join(audit_dir, f"phase4b_csv_backup_{stamp}.csv")
    shutil.copy2(dataset, backup)
    backup_sha = sha256_file(backup)
    if backup_sha != before_sha:
        raise SystemExit(f"backup hash mismatch: {backup_sha} != {before_sha}")

    orphans = os.path.join(audit_dir, f"phase4b_orphans_{stamp}.csv")
    with open(orphans, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(header) + ["reconcile_class"],
                           restval="", extrasaction="ignore")
        w.writeheader()
        for i in rep["quarantine"]:
            r = dict(rows[i])
            r["reconcile_class"] = rep["classes"][i]
            w.writerow(r)
        f.flush()
        os.fsync(f.fileno())

    # Atomic rewrite: same directory (so os.replace stays on one filesystem), the
    # runner's exact header (so load_completed's header guard still passes).
    d = os.path.dirname(os.path.abspath(dataset)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".phase4b_reconcile_", suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(header), restval="",
                               extrasaction="ignore")
            w.writeheader()
            for i in rep["keep"]:
                w.writerow(rows[i])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dataset)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return {"backup": backup, "backup_sha256": backup_sha, "before_sha256": before_sha,
            "orphans": orphans, "orphans_sha256": sha256_file(orphans),
            "after_sha256": sha256_file(dataset)}


# -------------------------------------------------------------------- self-test

def _row(eid, rep_, ts, machine="soham-local", mode="full", wait=5, ok="True"):
    return {"experiment_id": eid, "replicate": str(rep_), "machine_id": machine,
            "mode": mode, "wait_duration": str(wait), "run_timestamp": ts,
            "precondition_ok": ok, "time_to_recover": "3.0"}


def _rec(eid, rep_, inj, cleared, machine="soham-local", mode="full"):
    return {"experiment_id": eid, "replicate": rep_, "machine_id": machine,
            "mode": mode, "fault_injected_at": inj, "fault_cleared_at": cleared,
            "transitions": []}


def self_test():
    ok = True

    def expect(label, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))

    A, B = "LIN-LAT-CNT-T50-W5-D5", "LIN-LAT-TIM-T50-W5-D5"
    INJ, CLR, RTS = "2026-09-21T10:00:00Z", "2026-09-21T10:00:40Z", "2026-09-21T10:01:10Z"

    print("1. clean: every row matches exactly one record")
    r = reconcile([_row(A, 1, RTS), _row(B, 1, RTS)],
                  [_rec(A, 1, INJ, CLR), _rec(B, 1, INJ, CLR)])
    expect("counts", r["counts"], {MATCHED: 2, ORPHAN_RECORD: 0})
    expect("keep", r["keep"], [0, 1])
    expect("quarantine", r["quarantine"], [])

    print("2. orphan CSV row (completed row, no record)")
    r = reconcile([_row(A, 1, RTS), _row(B, 1, RTS)], [_rec(A, 1, INJ, CLR)])
    expect("class of row 1", r["classes"][1], ORPHAN_ROW)
    expect("quarantine", r["quarantine"], [1])
    expect("keep", r["keep"], [0])

    print("2b. aborted CSV row (precondition_ok != True, no record -- expected)")
    r = reconcile([_row(A, 1, RTS), _row(B, 1, RTS, ok="False")], [_rec(A, 1, INJ, CLR)])
    expect("class of row 1", r["classes"][1], ORPHAN_ROW_ABORTED)
    expect("still quarantined", r["quarantine"], [1])

    print("3. orphan sidecar record (record with no row)")
    r = reconcile([_row(A, 1, RTS)], [_rec(A, 1, INJ, CLR), _rec(B, 2, INJ, CLR)])
    expect("orphan_records", r["orphan_records"], [1])
    expect("count", r["counts"][ORPHAN_RECORD], 1)
    expect("row still matched", r["classes"][0], MATCHED)

    print("4. duplicate (experiment_id, replicate) -- both rows quarantined")
    r = reconcile([_row(A, 1, RTS), _row(A, 1, "2026-09-21T11:01:10Z")],
                  [_rec(A, 1, INJ, CLR)])
    expect("row 0", r["classes"][0], DUPLICATE_KEY)
    expect("row 1", r["classes"][1], DUPLICATE_KEY)
    expect("keep nothing", r["keep"], [])
    expect("record left orphaned", r["orphan_records"], [0])

    print("5. wrong machine_id -- must NOT match (Phase 2 cross-machine fallback)")
    r = reconcile([_row(A, 1, RTS, machine="jay-mac")], [_rec(A, 1, INJ, CLR)],
                  machine_id="soham-local")
    expect("row unmatched", r["classes"][0], ORPHAN_ROW)
    expect("record unmatched", r["orphan_records"], [0])
    r = reconcile([_row(A, 1, RTS)], [_rec(A, 1, INJ, CLR, machine="jay-mac")],
                  machine_id="soham-local")
    expect("record machine differs -> no match", r["classes"][0], ORPHAN_ROW)

    print("6. wrong mode -- must NOT match (Phase 2 canary/sweep mode collision)")
    r = reconcile([_row(A, 1, RTS)], [_rec(A, 1, INJ, CLR, mode="canary")])
    expect("canary record does not match a full row", r["classes"][0], ORPHAN_ROW)
    r = reconcile([_row(A, 1, RTS, mode="canary")], [_rec(A, 1, INJ, CLR)])
    expect("canary row is not considered at all", r["classes"][0], ORPHAN_ROW)

    print("7. run_timestamp outside the window")
    # D_w=5 -> hi = cleared + (3*5+60) + 60 = cleared + 135s = 10:02:55.
    r = reconcile([_row(A, 1, "2026-09-21T10:02:50Z")], [_rec(A, 1, INJ, CLR)])
    expect("just inside upper bound", r["classes"][0], MATCHED)
    r = reconcile([_row(A, 1, "2026-09-21T10:03:00Z")], [_rec(A, 1, INJ, CLR)])
    expect("just outside upper bound", r["classes"][0], ORPHAN_ROW)
    r = reconcile([_row(A, 1, "2026-09-21T09:59:57Z")], [_rec(A, 1, INJ, CLR)])
    expect("before fault injection", r["classes"][0], ORPHAN_ROW)
    r = reconcile([_row(A, 1, "2026-09-21T09:59:59Z")], [_rec(A, 1, INJ, CLR)])
    expect("1s early is inside LOW_SLACK_S", r["classes"][0], MATCHED)

    print("7b. window widens with wait_duration, as 3*wait+60 requires")
    # D_w=30 -> hi = cleared + (3*30+60) + 60 = cleared + 210s = 10:04:10.
    r = reconcile([_row(A, 1, "2026-09-21T10:04:00Z", wait=30)], [_rec(A, 1, INJ, CLR)])
    expect("D_w=30 row that D_w=5 would reject", r["classes"][0], MATCHED)

    print("8. one-to-one: two records in window for one row -> exactly one is used")
    r = reconcile([_row(A, 1, RTS)],
                  [_rec(A, 1, INJ, CLR), _rec(A, 1, "2026-09-21T10:00:05Z",
                                              "2026-09-21T10:00:45Z")])
    expect("row matched once", r["classes"][0], MATCHED)
    expect("exactly one record left over", len(r["orphan_records"]), 1)

    print("9. --apply rewrites the CSV so the runner reschedules the quarantined key")
    tmpd = tempfile.mkdtemp(prefix="phase4b_reconcile_selftest_")
    try:
        header = ["experiment_id", "replicate", "machine_id", "mode", "wait_duration",
                  "run_timestamp", "precondition_ok", "time_to_recover"]
        ds = os.path.join(tmpd, "ds.csv")
        rows = [_row(A, 1, RTS), _row(B, 1, RTS)]
        with open(ds, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for x in rows:
                w.writerow(x)
        rep = reconcile(rows, [_rec(A, 1, INJ, CLR)])
        res = apply_changes(ds, header, rows, rep, os.path.join(tmpd, "audit"),
                            "20260921T000000Z")
        with open(ds, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            after = list(rd)
            after_header = list(rd.fieldnames)
        expect("csv keeps only the matched row", [r["experiment_id"] for r in after], [A])
        expect("header preserved", after_header, header)
        with open(res["orphans"], newline="", encoding="utf-8") as f:
            orph = list(csv.DictReader(f))
        expect("orphans file holds the quarantined row",
               [(r["experiment_id"], r["reconcile_class"]) for r in orph],
               [(B, ORPHAN_ROW)])
        expect("backup hash == pre-apply hash", res["backup_sha256"], res["before_sha256"])
        expect("backup differs from rewritten csv",
               res["after_sha256"] != res["before_sha256"], True)
        # The point of the rewrite: load_completed must no longer see B's key.
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "experiments"))
        try:
            from resumable_runner import load_completed
            done = load_completed(ds, header)
            expect("load_completed no longer holds the quarantined key",
                   (B, "1") in done, False)
            expect("load_completed still holds the matched key", (A, "1") in done, True)
        except ImportError:
            print("  [skip] resumable_runner not importable")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset")
    ap.add_argument("--transitions")
    ap.add_argument("--machine-id", default=None,
                    help="require this machine_id on BOTH sides (recommended: soham-local)")
    ap.add_argument("--mode", default="full")
    ap.add_argument("--status-path", default=os.path.join("data", "run_status.json"))
    ap.add_argument("--audit-dir", default=os.path.join("data", "audit"))
    ap.add_argument("--apply", action="store_true",
                    help="quarantine unmatched rows and rewrite the CSV atomically")
    ap.add_argument("--ignore-stale-status", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        return 0 if self_test() else 1
    if not a.dataset or not a.transitions:
        ap.error("--dataset and --transitions are required unless --self-test")

    with open(a.dataset, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        header = list(rd.fieldnames or [])
        rows = list(rd)
    with open(a.transitions, encoding="utf-8") as f:
        records = [json.loads(l) for l in f if l.strip()]

    rep = reconcile(rows, records, machine_id=a.machine_id, mode=a.mode)

    print(f"dataset      : {a.dataset}  ({rep['n_rows']} rows, sha256 {sha256_file(a.dataset)})")
    print(f"transitions  : {a.transitions}  ({rep['n_records']} records, "
          f"sha256 {sha256_file(a.transitions)})")
    print(f"filter       : mode={a.mode!r}  machine_id={a.machine_id!r}")
    print(f"window       : [inj-{LOW_SLACK_S:g}s, cleared+3*wait+60+{POST_RECOVERY_MARGIN_S:g}s]")
    print()
    for k in (MATCHED, ORPHAN_ROW, ORPHAN_ROW_ABORTED, DUPLICATE_KEY, ORPHAN_RECORD):
        print(f"  {k:<20} {rep['counts'].get(k, 0)}")
    if rep["fallback_wait_rows"]:
        print(f"\n  !! {len(rep['fallback_wait_rows'])} row(s) had no usable wait_duration; "
              f"the widest window ({FALLBACK_WAIT_S:g}s) was used for them")

    print("\nCSV rows without a sidecar record:")
    any_row = False
    for i in rep["quarantine"]:
        any_row = True
        r = rows[i]
        print(f"  line {i + 2:>4}  {rep['classes'][i]:<20} {r.get('experiment_id')} "
              f"rep={r.get('replicate')} machine={r.get('machine_id')} "
              f"mode={r.get('mode')} ts={r.get('run_timestamp')} "
              f"precondition_ok={r.get('precondition_ok')}")
    if not any_row:
        print("  (none)")

    print("\nSidecar records without a CSV row:")
    if not rep["orphan_records"]:
        print("  (none)")
    for j in rep["orphan_records"]:
        rec = records[j]
        print(f"  line {j + 1:>4}  {rec.get('experiment_id')} rep={rec.get('replicate')} "
              f"machine={rec.get('machine_id')} mode={rec.get('mode')} "
              f"injected={rec.get('fault_injected_at')}")

    if not a.apply:
        print("\nDRY RUN -- nothing was written. Re-run with --apply to quarantine.")
        return 0

    active, reasons = runner_active(a.status_path, a.ignore_stale_status)
    if active:
        print("\nREFUSING --apply: a runner may be active.", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        print("  Stop the runner, then re-run.", file=sys.stderr)
        return 2
    if not rep["quarantine"]:
        print("\nNothing to quarantine; CSV left untouched.")
        return 0

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    res = apply_changes(a.dataset, header, rows, rep, a.audit_dir, stamp)
    print(f"\nbackup   : {res['backup']}\n           sha256 {res['backup_sha256']}")
    print(f"orphans  : {res['orphans']}\n           sha256 {res['orphans_sha256']} "
          f"({len(rep['quarantine'])} row(s))")
    print(f"dataset  : {a.dataset}\n           sha256 {res['before_sha256']} -> "
          f"{res['after_sha256']}  ({len(rep['keep'])} row(s) kept)")
    print("\nThe sidecar was NOT modified. Resume with the same --seed and --only-ids.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
