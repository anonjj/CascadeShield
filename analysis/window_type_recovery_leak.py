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
import math
import sys

import numpy as np
import pandas as pd

from common import DATA_DIR, OUT_DIR, compare_censored_groups, load, write_json, _config_value_lists
from exact_tests import stratified_cluster_permutation_rank_test

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

def _censored_ratio_table(df, value_col):
    """Per-wait_duration TIME vs COUNT comparison for `value_col`, via D19's
    compare_censored_groups (analysis/common.py) -- the rate at which the event was
    observed at all is reported separately from the timing conditional on it having
    happened, exactly as the metrics contract requires for time_to_open/time_to_recover
    and their derived precise_* equivalents (DATA_DICTIONARY.md: "nulls ... are outcomes,
    not missing data").

    This replaced a version that called .dropna() on `value_col` per arm before taking a
    median, then skipped (`continue`d past) any wait_duration level where that left zero
    rows on either side. That silently dropped a bucket exactly when it was most
    informative: the D13 top-up (commit c59ef95) found TIME closing 6/6 at every
    wait_duration while COUNT closed 6/6 at D_w=5, 2/6 at D_w=15, and **0/6 at D_w=30**
    -- the D_w=30 row vanished from the table instead of reporting "0/6 recovered",
    which is precisely why that commit's own message says D13 was not marked closed.

    A wait_duration level with rows collected on both arms always gets a row now, even
    when one arm has zero *observed* events -- `fully_censored=True`, its rate is 0.0,
    and `ratio_time_over_count` is None (there is no finite time to ratio against; a
    censored event took at least as long as the observation window, quite possibly the
    single strongest data point in the arm's favor, not an absence of one). Such a row
    is excluded from `ratios`/the consistency verdict below rather than forcing a
    number out of it -- see the `fully_censored` flag on each row for which levels that
    affects. A level is skipped entirely only when one arm collected literally no rows.
    """
    rows = []
    ratios = []
    for wd, g in df.groupby(COL_WAIT):
        c = g[g[COL_WINDOW] == "COUNT"]
        t = g[g[COL_WINDOW] == "TIME"]
        if len(c) == 0 or len(t) == 0:
            continue
        cmp = compare_censored_groups(c, t, value_col, group_col="experiment_id")
        n_obs_c = cmp["a"]["n_observed"]
        n_obs_t = cmp["b"]["n_observed"]
        median_c = float(c[value_col].median()) if n_obs_c else None
        median_t = float(t[value_col].median()) if n_obs_t else None
        ratio = (median_t / median_c) if (median_c is not None and median_t is not None and median_c) else None
        fully_censored = (n_obs_c == 0 or n_obs_t == 0)
        if ratio is not None:
            ratios.append(ratio)
        rows.append({
            "wait_duration": float(wd),
            "n_count": int(len(c)),
            "n_time": int(len(t)),
            "n_observed_count": n_obs_c,
            "n_observed_time": n_obs_t,
            "rate_count": cmp["a"]["rate"],
            "rate_time": cmp["b"]["rate"],
            "median_count": median_c,
            "median_time": median_t,
            "ratio_time_over_count": ratio,
            "fully_censored": fully_censored,
            # (COUNT, TIME) order -- matches canary_readout.py and order_leg_containment.py's
            # convention for this same conceptual comparison; keep it consistent so `delta`'s
            # sign means the same thing across every script's JSON output. Computed only over
            # the observed (non-censored) rows on each side -- compare_groups degrades to
            # delta=None/"undefined" and p=None when one side has zero observed rows, rather
            # than raising.
            "cliffs_delta": cmp["conditional_timing_comparison"]["cliffs_delta"],
            "mann_whitney": cmp["conditional_timing_comparison"]["mann_whitney"],
            "ci_count": cmp["a"]["conditional_timing"],
            "ci_time": cmp["b"]["conditional_timing"],
        })
    return {
        "by_wait_duration": rows,
        "ratios": ratios,
        "median_ratio": float(np.median(ratios)) if ratios else None,
        "min_ratio": float(min(ratios)) if ratios else None,
        "max_ratio": float(max(ratios)) if ratios else None,
        # Require every collected level to have produced a ratio before calling the
        # pattern "consistent" -- a fully-censored level can't be folded into a median
        # comparison, and asserting consistency over the remaining levels while quietly
        # ignoring the one that couldn't produce a number is the exact overclaim this
        # migration exists to close off.
        "consistent_time_slower": bool(rows) and len(ratios) == len(rows) and all(r > RATIO_THRESHOLD for r in ratios),
        "consistent_count_slower": bool(rows) and len(ratios) == len(rows) and all(r < 1 / RATIO_THRESHOLD for r in ratios),
        # Same directional check as consistent_time_slower/consistent_count_slower, but
        # WITHOUT requiring len(ratios) == len(rows) -- i.e. "every level that COULD
        # produce a ratio agrees," evaluated separately from whether every level did
        # produce one. A fully-censored level correctly has no ratio and is silently
        # excluded here rather than voiding the direction check outright; this is what
        # _verdict's LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING branch must gate on --
        # partial coverage that still points one way is suggestive, partial coverage
        # that CONTRADICTS itself (one level says TIME is slower, another says COUNT
        # is) is not, and must not be reported as suggestive of anything.
        "partial_ratios_agree": bool(ratios) and (
            all(r > RATIO_THRESHOLD for r in ratios) or all(r < 1 / RATIO_THRESHOLD for r in ratios)
        ),
    }


def _stratified_leak_test(df, value_col, group_col="experiment_id"):
    """The single inferential claim for 'does window_type affect value_col,' holding
    wait_duration fixed as a blocking stratum -- closes D19's 2026-09-19 'Revisit if'
    (decision-log.md): window_type_recovery_leak.py previously tested each wait_duration
    bucket as its own independent contrast, the same per-D_w design H3's own D24 fix
    replaced. Every raw replicate row is preserved (stratified_cluster_permutation_rank_test,
    exact_tests.py), never collapsed to a per-configuration mean -- D19 section 5.2 ruled
    that out for this same underlying comparison (compare_censored_groups). The per-D_w
    rows in by_wait_duration (_censored_ratio_table) stay in the output as description;
    this is the inferential claim.

    A wait_duration bucket with zero configurations on either arm carries no label
    information and is excluded here, decided per-call (i.e. per DV and per slice, since
    censoring/config availability differ across them) -- reported in excluded_strata
    rather than silently dropped, mirroring D24's own exclusion of H3's D_w=30 (empty
    COUNT arm)."""
    strata = {}
    excluded = []
    for wd, g in df.groupby(COL_WAIT):
        c = g[g[COL_WINDOW] == "COUNT"]
        t = g[g[COL_WINDOW] == "TIME"]
        configs_c = _config_value_lists(c, value_col, group_col)
        configs_t = _config_value_lists(t, value_col, group_col)
        if not configs_c or not configs_t:
            excluded.append({"wait_duration": float(wd), "n1_clusters": len(configs_c),
                              "n2_clusters": len(configs_t), "reason": "empty arm"})
            continue
        strata[str(wd)] = (configs_c, configs_t)

    if not strata:
        return {"statistic": None, "p": None, "p_one_sided": None,
                "method": "undefined (no includable strata)", "total_assignments": None,
                "p_floor_one_sided": None, "p_floor_two_sided": None,
                "strata": [], "excluded_strata": excluded}

    res = stratified_cluster_permutation_rank_test(strata)
    return {
        "statistic": res.statistic, "p": res.p_value, "p_one_sided": res.p_value_one_sided,
        "method": res.method, "total_assignments": res.total_assignments, "note": res.note,
        "p_floor_one_sided": res.p_floor_one_sided, "p_floor_two_sided": res.p_floor_two_sided,
        "strata": [{"wait_duration": float(s.name), "n1_clusters": s.n1, "n2_clusters": s.n2,
                    "n_assignments": s.n_assignments} for s in res.strata],
        "excluded_strata": excluded,
    }


def _paired_view(df, value_col, match_keys):
    """Fully-matched paired view: same config on every listed key, only window_type
    differs. `match_keys` must already be filtered to columns that exist in `df`.

    Secondary cross-check only -- median()/unstack() here silently drops a (config,
    window_type) cell that is fully censored (median of an all-null group is NaN, and
    the subsequent dropna(subset=["COUNT","TIME"]) removes the row). That is a real
    loss of information for the same reason _censored_ratio_table's docstring
    describes; the by_wait_duration table above is the one that is safe to read a
    verdict off of. This view exists for the paired-CSV export and is not otherwise
    load-bearing.
    """
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

def coarse_ratio_check(df, gw_lookup=None):
    d = df.copy()
    d[COL_WINDOW] = d[COL_WINDOW].map(norm)
    d = d[d[COL_WINDOW].isin(["COUNT", "TIME"])].copy()
    d["excess"] = d[COL_RECOVERY] - d[COL_WAIT]

    used_keys = [k for k in MATCH_KEYS_WANTED if k in d.columns]
    missing_keys = [k for k in MATCH_KEYS_WANTED if k not in d.columns]
    piv = _paired_view(d, COL_RECOVERY, used_keys)

    # gw_lookup is None when data/cb_transitions.jsonl is absent (real-runs-only,
    # gitignored) -- the gateway-cleaned slice of the stratified test is then simply
    # not reported, same "can't compute it, say so" posture the PRECISE path already
    # takes for the whole sidecar-dependent metric.
    d_cleaned = gateway_cleaned_slice(d, gw_lookup) if gw_lookup is not None else None

    def dv_table(value_col):
        table = _censored_ratio_table(d, value_col)
        table["stratified_test"] = {"pooled": _stratified_leak_test(d, value_col)}
        if d_cleaned is not None:
            table["stratified_test"]["gateway_cleaned"] = _stratified_leak_test(d_cleaned, value_col)
        return table

    return {
        "n_rows": int(len(d)),
        "n_count": int((d[COL_WINDOW] == "COUNT").sum()),
        "n_time": int((d[COL_WINDOW] == "TIME").sum()),
        "match_keys": {"requested": MATCH_KEYS_WANTED, "used": used_keys, "missing": missing_keys},
        "time_to_recover": dv_table(COL_RECOVERY),
        # Separates "TIME opens later" (a flat anchor shift, not a recovery-side leak)
        # from "TIME's post-open excess grows with wait_duration" (not explainable by a
        # constant shift -- the pattern actually found against the real archive).
        "time_to_open_anchor": dv_table(COL_OPEN),
        "excess_over_wait_duration": dv_table("excess"),
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
            # machine_id via .get: records written before breaker_observer started
            # stamping it (pre-D14) have no such key at all, and D14's own rule is that
            # machine_id goes BLANK -- never a sentinel -- when the harness did not
            # record one. A bare rec["machine_id"] turns one legacy line into a KeyError
            # that takes down the whole analysis.
            key = (rec["experiment_id"], str(rec["replicate"]), rec["mode"], rec["environment"],
                   rec.get("machine_id", ""))
            index[key] = rec
    return index


def gateway_tripped_lookup(cb_transitions_path):
    """{(experiment_id, replicate, mode, environment, machine_id): bool} -- did gateway's
    own circuit breaker trip (CLOSED_TO_OPEN) anywhere in this run's transitions, independent
    of BREAKER_WATCH scoping (order's own breakers only). D23/D24 (decision-log.md): a real
    gateway trip confounds order's own COUNT_BASED recovery reading -- order waits on gateway
    to let traffic back through, which reads as a long "recovery" that has nothing to do with
    order's own breaker semantics. Reuses load_transition_index's join key so a caller can zip
    this lookup against the same key it already builds for the PRECISE path. A key absent here
    (no matching sidecar record) is the caller's problem, not this function's -- callers must
    default a missing key to False (absence of transition evidence isn't evidence of a trip),
    same permissive default D24 used."""
    index = load_transition_index(cb_transitions_path)
    return {
        key: any(t.get("service") == "gateway" and t.get("state_transition") == "CLOSED_TO_OPEN"
                 for t in rec.get("transitions", []))
        for key, rec in index.items()
    }


def gateway_cleaned_slice(df, gw_lookup):
    """D24's gateway-cleaning rule (decision-log.md), applied here to a COARSE-table
    dataframe rather than half_open_survival.py's own KM observations: TIME_BASED rows are
    kept regardless (the confound is COUNT-specific); COUNT_BASED rows are kept only if the
    gateway did not trip during that row's run. Missing lookup keys default to
    gateway_tripped=False, matching gateway_tripped_lookup's own contract."""
    window = df[COL_WINDOW].map(norm)
    machine = df["machine_id"] if "machine_id" in df.columns else pd.Series([""] * len(df), index=df.index)
    keys = list(zip(df["experiment_id"], df["replicate"].astype(str), df["mode"], df["environment"],
                     machine.fillna("")))
    tripped = pd.Series([gw_lookup.get(k, False) for k in keys], index=df.index)
    keep = (window == "TIME") | (~tripped)
    return df[keep].copy()


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

    # .get(): rows from an archive that predates D14's machine_id column (e.g. the
    # v2/v3 legacy datasets) have no such key at all. Mirrors load_transition_index's
    # own handling just above -- a bare row["machine_id"] turns one legacy row into a
    # KeyError that takes down the whole analysis, which only stayed latent this long
    # because no checkout had a real data/cb_transitions.jsonl to exercise this path
    # against an archived (non-"current") dataset until now.
    key = (row["experiment_id"], str(row["replicate"]), row["mode"], row["environment"],
           row.get("machine_id", ""))
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


def precise_recovery_from_transitions(cb_transitions_path, master_df, gw_lookup=None):
    index = load_transition_index(cb_transitions_path)
    records = []
    for _, row in master_df.iterrows():
        r = precise_row_for(row, index)
        r["experiment_id"] = row["experiment_id"]
        r["replicate"] = row["replicate"]
        r[COL_WINDOW] = norm(row[COL_WINDOW])
        r[COL_WAIT] = row[COL_WAIT]
        # Carried straight from master_df so gateway_cleaned_slice can join this
        # table the same 5-key way load_transition_index/precise_row_for already do --
        # not otherwise used by anything below.
        r["mode"] = row["mode"]
        r["environment"] = row["environment"]
        r["machine_id"] = row.get("machine_id", "")
        records.append(r)
    pdf = pd.DataFrame(records)

    ok = pdf[pdf["status"] == "OK"]
    status_counts = {k: int(v) for k, v in pdf["status"].value_counts().items()}
    ok_cleaned = gateway_cleaned_slice(ok, gw_lookup) if gw_lookup is not None else None

    def precise_dv_table(value_col):
        if value_col not in ok.columns:
            return None
        table = _censored_ratio_table(ok, value_col)
        table["stratified_test"] = {"pooled": _stratified_leak_test(ok, value_col)}
        if ok_cleaned is not None:
            table["stratified_test"]["gateway_cleaned"] = _stratified_leak_test(ok_cleaned, value_col)
        return table

    return {
        "status_counts": status_counts,
        "n_ok": int(len(ok)),
        "half_open_to_closed": precise_dv_table("precise_half_open_to_closed"),
        "open_to_half_open_sanity_check": precise_dv_table("precise_open_to_half_open"),
        "rows": pdf.to_dict("records"),
    }


# ---------------------------------------------------------------------------- verdict

def _verdict(coarse, precise, precise_status):
    if precise_status != "COMPUTED":
        return "MECHANISM_UNTESTED_NO_SIDECAR"
    hoc = precise.get("half_open_to_closed")
    if not hoc or not hoc["by_wait_duration"]:
        return "AMBIGUOUS"
    if hoc["consistent_time_slower"] or hoc["consistent_count_slower"]:
        return "LEAK_CONFIRMED_ON_HALF_OPEN_LEG"
    if hoc["partial_ratios_agree"] and any(r["fully_censored"] for r in hoc["by_wait_duration"]):
        # partial_ratios_agree already confirms every level that COULD produce a ratio
        # points the same direction (see _censored_ratio_table) -- checked explicitly,
        # not inferred from `ratios` being non-empty, which says nothing about whether
        # those ratios agree with each other. (An earlier version of this check used
        # `hoc["ratios"]` here and asserted in a comment that non-empty implied
        # agreement; it didn't -- two ratios pointing opposite directions are both
        # non-null and both land in `ratios`, and that version would call a flatly
        # self-contradictory pair of measured levels "suggestive of a leak.") At least
        # one level here also had zero observed events on one arm -- that arm didn't
        # fail to show an effect there, it hit the ceiling of the observation window,
        # which _censored_ratio_table deliberately refuses to fold into a median.
        # Report the pattern as suggestive rather than confirmed until it is re-derived
        # with a censoring-aware estimator (e.g. Kaplan-Meier / a Cox model), not a
        # median-of-observed-rows comparison, per D19.
        return "LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING"
    coarse_rec = coarse["time_to_recover"]
    coarse_consistent = coarse_rec["consistent_time_slower"] or coarse_rec["consistent_count_slower"]
    if coarse_consistent:
        return "CONFIRMED_ANCHOR_SHIFT_ONLY_DISSOCIATION_HOLDS"
    return "AMBIGUOUS"


# ------------------------------------------------------------------------------- main

def main(dataset="current"):
    df = load(dataset)
    sidecar_path = DATA_DIR / CB_TRANSITIONS_FILENAME
    # gateway_tripped_lookup only needs the sidecar file itself, independent of whether
    # PRECISE's per-row join succeeds below -- computed once, reused by both COARSE's and
    # PRECISE's gateway-cleaned stratified test.
    gw_lookup = gateway_tripped_lookup(sidecar_path) if sidecar_path.exists() else None
    coarse = coarse_ratio_check(df, gw_lookup)

    if sidecar_path.exists():
        precise = precise_recovery_from_transitions(sidecar_path, df, gw_lookup)
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

    _print_summary(dataset, coarse, precise, precise_status, verdict)
    return payload


def _fmt(v, spec="{:.3f}"):
    return spec.format(v) if v is not None else "   n/a"


def _print_censored_table(label, table):
    print("\n[{}] rate (D19: event observed at all) + timing conditional on it".format(label))
    print("wait_duration | COUNT obs/n (rate) | TIME obs/n (rate) | median C | median T | ratio T/C")
    print("-" * 92)
    for r in table["by_wait_duration"]:
        rc = r["rate_count"]["point"]
        rt = r["rate_time"]["point"]
        rc_s = "{:.0%}".format(rc) if rc is not None else " n/a"
        rt_s = "{:.0%}".format(rt) if rt is not None else " n/a"
        flag = "  <-- FULLY CENSORED ONE ARM" if r["fully_censored"] else ""
        print("{:>13.0f} | {:>3}/{:<3} ({:>4}) | {:>3}/{:<3} ({:>4}) | {:>8} | {:>8} | {:>7}{}".format(
            r["wait_duration"], r["n_observed_count"], r["n_count"], rc_s,
            r["n_observed_time"], r["n_time"], rt_s,
            _fmt(r["median_count"]), _fmt(r["median_time"]),
            "{:.2f}x".format(r["ratio_time_over_count"]) if r["ratio_time_over_count"] is not None else "  --  ",
            flag))
    if table["ratios"]:
        print("-" * 92)
        print("ratio, fully-observed levels only: median {:.2f}x (range {:.2f}-{:.2f})  |  "
              "consistent_time_slower={}  consistent_count_slower={}".format(
                  table["median_ratio"], table["min_ratio"], table["max_ratio"],
                  table["consistent_time_slower"], table["consistent_count_slower"]))
    censored_levels = [r["wait_duration"] for r in table["by_wait_duration"] if r["fully_censored"]]
    if censored_levels:
        print("fully-censored levels (excluded from the ratio/consistency verdict above): {}".format(
            censored_levels))


def _print_summary(dataset, coarse, precise, precise_status, verdict):
    print("dataset: {}  |  rows: {}  |  COUNT={}  TIME={}".format(
        dataset, coarse["n_rows"], coarse["n_count"], coarse["n_time"]))
    print("match_keys used: {}  (dropped, not in dataset: {})".format(
        coarse["match_keys"]["used"], coarse["match_keys"]["missing"]))

    _print_censored_table("COARSE time_to_recover (OPEN -> left-OPEN, see docstring)",
                           coarse["time_to_recover"])

    anchor = coarse["time_to_open_anchor"]
    excess = coarse["excess_over_wait_duration"]
    print("\n[COARSE] anchor/excess decomposition")
    print("wait_duration | median t_open C | T    | median excess C | T")
    print("-" * 62)
    a_by_wd = {r["wait_duration"]: r for r in anchor["by_wait_duration"]}
    e_by_wd = {r["wait_duration"]: r for r in excess["by_wait_duration"]}
    for wd in sorted(a_by_wd):
        a, e = a_by_wd[wd], e_by_wd.get(wd)
        print("{:>13.0f} | {:>15} | {:>4} | {:>16} | {:>5}".format(
            wd, _fmt(a["median_count"]), _fmt(a["median_time"]),
            _fmt(e["median_count"]) if e else "n/a", _fmt(e["median_time"]) if e else "n/a"))

    print("\n[PRECISE] status: {}".format(precise_status))
    if precise_status == "COMPUTED" and precise:
        print("status_counts: {}".format(precise["status_counts"]))
        if precise.get("half_open_to_closed"):
            _print_censored_table("PRECISE half_open_to_closed", precise["half_open_to_closed"])
        if precise.get("open_to_half_open_sanity_check"):
            _print_censored_table("PRECISE open_to_half_open (sanity check, should be window-type-agnostic)",
                                   precise["open_to_half_open_sanity_check"])

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


def self_test_censoring():
    """Regression test for the exact bug that kept D13 open: a wait_duration level
    where one arm has rows but zero *observed* events must still appear in
    by_wait_duration (not silently dropped), must be flagged fully_censored, and must
    not by itself support a blanket 'consistent' directional claim -- reproducing the
    D13 top-up's own shape (commit c59ef95): TIME recovers every time; COUNT recovers
    at D_w=5 and D_w=15 but 0/3 at D_w=30.
    """
    def rows(wd, window_type, prefix, values):
        return [{"experiment_id": "{}-{}".format(prefix, i), COL_WAIT: wd,
                  COL_WINDOW: window_type, "precise_half_open_to_closed": v}
                for i, v in enumerate(values)]

    data = (rows(5, "COUNT", "cnt5", [2.0, 2.1, 1.9])
            + rows(5, "TIME", "tim5", [15.0, 14.0, 16.0])
            + rows(15, "COUNT", "cnt15", [2.5, 2.6, 2.4])
            + rows(15, "TIME", "tim15", [22.0, 21.0, 23.0])
            + rows(30, "COUNT", "cnt30", [np.nan, np.nan, np.nan])   # 0/3 recovered
            + rows(30, "TIME", "tim30", [30.0, 31.0, 29.0]))
    df = pd.DataFrame(data)

    table = _censored_ratio_table(df, "precise_half_open_to_closed")
    by_wd = {r["wait_duration"]: r for r in table["by_wait_duration"]}

    assert set(by_wd) == {5.0, 15.0, 30.0}, "D_w=30 must not vanish from by_wait_duration"
    assert by_wd[30.0]["fully_censored"] is True
    assert by_wd[30.0]["n_observed_count"] == 0
    assert by_wd[30.0]["rate_count"]["point"] == 0.0
    assert by_wd[30.0]["ratio_time_over_count"] is None
    assert by_wd[5.0]["fully_censored"] is False and by_wd[15.0]["fully_censored"] is False

    # D_w=5 and D_w=15 alone would both clear RATIO_THRESHOLD (~7x, ~8.7x) -- confirm
    # the fully-censored D_w=30 level blocks the blanket "consistent" claim rather than
    # being quietly excluded from it.
    assert len(table["ratios"]) == 2
    assert table["consistent_time_slower"] is False

    verdict = _verdict(
        {"time_to_recover": {"consistent_time_slower": False, "consistent_count_slower": False}},
        {"half_open_to_closed": table}, "COMPUTED")
    assert verdict == "LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING", verdict

    # Sanity: with no censoring at all, three clean levels DO earn "consistent".
    clean = pd.DataFrame(
        rows(5, "COUNT", "c5", [2.0, 2.1, 1.9]) + rows(5, "TIME", "t5", [15.0, 14.0, 16.0])
        + rows(15, "COUNT", "c15", [2.5, 2.6, 2.4]) + rows(15, "TIME", "t15", [22.0, 21.0, 23.0])
        + rows(30, "COUNT", "c30", [2.8, 2.9, 2.7]) + rows(30, "TIME", "t30", [30.0, 31.0, 29.0]))
    clean_table = _censored_ratio_table(clean, "precise_half_open_to_closed")
    assert clean_table["consistent_time_slower"] is True
    clean_verdict = _verdict(
        {"time_to_recover": {"consistent_time_slower": False, "consistent_count_slower": False}},
        {"half_open_to_closed": clean_table}, "COMPUTED")
    assert clean_verdict == "LEAK_CONFIRMED_ON_HALF_OPEN_LEG", clean_verdict

    print("self-test: censoring regression (D13's D_w=30 shape) OK")


def self_test_contradictory_ratios():
    """Regression test for a bug found in code review of the censoring migration itself:
    _verdict's LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING branch checked only that
    hoc["ratios"] was non-empty, not that those ratios agreed in direction. Two levels
    that flatly contradict each other -- one showing TIME far slower, the other showing
    COUNT far slower -- both produce non-null, non-empty ratios; a third, fully-censored
    level was then enough to make the old code report "suggestive of a leak" over data
    that doesn't even agree with itself. partial_ratios_agree (_censored_ratio_table)
    exists specifically to gate this, and this test locks in that AMBIGUOUS is the
    correct verdict here, not LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING.
    """
    def rows(wd, window_type, prefix, values):
        return [{"experiment_id": "{}-{}".format(prefix, i), COL_WAIT: wd,
                  COL_WINDOW: window_type, "precise_half_open_to_closed": v}
                for i, v in enumerate(values)]

    # D_w=5: TIME far slower than COUNT. D_w=15: the OPPOSITE -- COUNT far slower than
    # TIME. D_w=30: COUNT fully censored. The two measurable levels contradict each
    # other outright; censoring at D_w=30 must not launder that into "suggestive."
    data = (rows(5, "COUNT", "cnt5", [2.0, 2.0, 2.0]) + rows(5, "TIME", "tim5", [20.0, 20.0, 20.0])
            + rows(15, "COUNT", "cnt15", [20.0, 20.0, 20.0]) + rows(15, "TIME", "tim15", [2.0, 2.0, 2.0])
            + rows(30, "COUNT", "cnt30", [np.nan, np.nan, np.nan])
            + rows(30, "TIME", "tim30", [30.0, 30.0, 30.0]))
    df = pd.DataFrame(data)

    table = _censored_ratio_table(df, "precise_half_open_to_closed")
    assert table["ratios"] == [10.0, 0.1], table["ratios"]
    assert table["partial_ratios_agree"] is False, "contradictory ratios must not agree"

    verdict = _verdict(
        {"time_to_recover": {"consistent_time_slower": False, "consistent_count_slower": False}},
        {"half_open_to_closed": table}, "COMPUTED")
    assert verdict == "AMBIGUOUS", verdict

    print("self-test: contradictory-ratios-plus-censoring regression OK")


def self_test_stratified():
    """Regression test for _stratified_leak_test and gateway_cleaned_slice -- the wiring
    that closes D19's 2026-09-19 'Revisit if' (decision-log.md). Reproduces the exact
    cluster shape found against real data: D_w=5 has 3 configs/arm, D_w=15 has 1 COUNT
    config vs 3 TIME configs (H3's own D24 floor=0.25 shape), D_w=30's COUNT arm is
    empty and must be excluded rather than silently zeroed."""
    def rows(wd, window_type, configs):
        out = []
        for cfg, values in configs.items():
            for i, v in enumerate(values):
                out.append({"experiment_id": cfg, "replicate": i + 1, COL_WAIT: wd,
                             COL_WINDOW: window_type, "value": v})
        return out

    data = (
        rows(5, "COUNT", {"c1": [2.0, 2.1], "c2": [2.2], "c3": [1.9]})
        + rows(5, "TIME", {"t1": [19.0], "t2": [19.3], "t3": [28.7]})
        + rows(15, "COUNT", {"c4": [2.5, 2.4]})
        + rows(15, "TIME", {"t4": [20.9], "t5": [30.5], "t6": [39.6]})
        + rows(30, "TIME", {"t7": [25.0], "t8": [26.0], "t9": [24.0]})
        # D_w=30 has NO COUNT rows at all -- empty arm, must be excluded not zeroed.
    )
    df = pd.DataFrame(data)

    result = _stratified_leak_test(df, "value")
    assert result["method"] == "exact-enumeration", result["method"]
    assert result["total_assignments"] == 20 * 4, result["total_assignments"]
    strata_wds = {s["wait_duration"] for s in result["strata"]}
    assert strata_wds == {5.0, 15.0}, strata_wds
    excluded_wds = {e["wait_duration"] for e in result["excluded_strata"]}
    assert excluded_wds == {30.0}, excluded_wds
    assert result["excluded_strata"][0]["reason"] == "empty arm"
    # Complete separation (every COUNT value < every TIME value in both strata) -> the
    # observed assignment is the single most extreme of all 80. Unlike the mean-collapsed
    # stratified test, this row-preserving statistic has no guaranteed symmetric null
    # (block sizes vary, so there's no guaranteed "mirror" combo with negated statistic --
    # see exact_tests.py's cluster_permutation_rank_test self-test, which already shows
    # two-sided p == one-sided p == 1/3 for its own complete-separation case, same
    # property, not new here). p lands at the ONE-sided floor, not the two-sided one.
    assert math.isclose(result["p"], result["p_floor_one_sided"]), \
        (result["p"], result["p_floor_one_sided"])
    assert math.isclose(result["p"], result["p_one_sided"]), (result["p"], result["p_one_sided"])

    # gateway_cleaned_slice: TIME rows kept regardless; COUNT rows kept only if not
    # gateway_tripped. c1 is tripped -> both its replicate rows dropped; c2/c3/c4 untouched.
    gw_lookup = {
        ("c1", "1", "full", "LOCAL", ""): True,
        ("c1", "2", "full", "LOCAL", ""): True,
    }
    df2 = df.assign(mode="full", environment="LOCAL", machine_id="")
    cleaned = gateway_cleaned_slice(df2, gw_lookup)
    assert set(cleaned[cleaned[COL_WINDOW] == "COUNT"]["experiment_id"]) == {"c2", "c3", "c4"}, \
        "gateway-tripped COUNT config c1 must be dropped, others kept"
    assert (set(cleaned[cleaned[COL_WINDOW] == "TIME"]["experiment_id"])
            == set(df2[df2[COL_WINDOW] == "TIME"]["experiment_id"])), \
        "TIME rows must be kept regardless of gateway_tripped"
    assert "c4" in set(cleaned["experiment_id"]), "missing lookup key must default to not-tripped"

    print("self-test: stratified leak test + gateway-cleaned slice OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        self_test_censoring()
        self_test_contradictory_ratios()
        self_test_stratified()
    else:
        arg = sys.argv[1] if len(sys.argv) > 1 else "current"
        main(arg)
