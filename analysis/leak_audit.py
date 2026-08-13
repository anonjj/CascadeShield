"""Day 1 (Soham) -- breaker-state leak audit across every dataset this project has produced.

WHY THIS EXISTS
---------------
`runner.py` does not reset circuit breakers between replicates. A breaker left OPEN by the
previous run starts the next one already tripped, which fabricates two things at once:

  * an impossibly fast `time_to_open` (the breaker was open before the fault landed), and
  * a `blast_radius` above zero on subjects whose own leg recorded no failures at all.

The second row of `LIN-LAT-CNT-T30-W20-D5` in the current dataset is the canonical example:
t_open = 0.303 s against 6.256 / 6.377 for its identical siblings, and B = 0.75 with three
of four legs at exactly 0.0000. That row invented precisely the multi-service cascade this
project was built to look for, which is why it has to be found everywhere it occurs before
any result is built on top of it.

THE TWO SIGNATURES
------------------
S1  EARLY_OPEN        `time_to_open` far below its sibling replicates.

                      The sprint plan words this as "more than 3 SD below its siblings",
                      but that rule is unusable as written: with 3 replicates the sibling
                      SD is estimated from two points, so a cell whose siblings agree to
                      three decimals gives SD ~ 0.002 s and a row 0.05 s faster scores
                      z = -41. Run naively it flags 33 of the 80 current rows, nearly all
                      of them on sub-0.1 s gaps that are plainly timer noise.

                      So the scale is borrowed across cells instead of estimated within
                      one. Per-cell residuals (x - cell median) are pooled *within window
                      type* -- COUNT and TIME have order-of-magnitude different spread --
                      and their MAD gives a robust sigma that a minority of contaminated
                      points cannot inflate. A row must clear that z gate AND be at least
                      MIN_ABSOLUTE_GAP_S seconds early in absolute terms, which is what
                      keeps timer noise out.

                      The reference is the median of the *whole* cell, the row included --
                      deliberately not leave-one-out. At n = 3 the leave-one-out median of
                      two siblings is just their midpoint, so on a cell like
                      (9.73, 9.61, 15.90) each member of the majority pair gets measured
                      against ~12.75 and both are flagged, while the genuine odd row is
                      not. Including the row keeps the reference on an actual observation,
                      where a single contaminated point cannot move it.

                      Hits are tiered. SEVERE means the row opened in under half its
                      siblings' time -- the unmistakable "breaker was already open"
                      signature. MODERATE means a real but smaller displacement.

                      Hits are then screened for recurrence, because contamination and
                      mechanism look identical row by row and only differ in how they
                      repeat. A leaked breaker is sporadic: one row, one cell, an
                      arbitrary displacement. A mechanism reproduces the *same*
                      displacement in unrelated configurations. Hits whose residuals
                      agree to within RECURRENCE_TOLERANCE across at least
                      RECURRENCE_MIN_CONFIGS distinct experiment_ids are therefore
                      reclassified RECURRENT_MODE and dropped from the leak count.

                      That screen is not a formality here. TIME_BASED / W = 5 t_open in
                      the current dataset is cleanly bimodal -- nine rows near 3.5 s,
                      eleven near 6.3 s, and nothing whatsoever in between -- so the
                      naive rule bills five separate configurations as contaminated when
                      what it has actually found is a discretisation of the detection
                      latency itself. See analysis/out/leak_audit.json -> recurrent_modes,
                      and note the consequence for H1: if TIME_BASED t_open is
                      mode-switching rather than continuous, a COUNT-vs-TIME variance gap
                      may be a mixing proportion rather than a sampling property.

S2  IMPOSSIBLE_BLAST  more subjects reported OPEN than there are legs with any observed
                      failure. A breaker cannot sit OPEN across the fault window while its
                      own leg records zero failed-or-rejected calls -- unless it entered the
                      run already open.

S2 is only *exact* where blast_radius and the leg vector range over the same nodes. On
`v2_latency_5svc` they do not (legs include the gateway, blast subjects exclude it), so S2
is reported there as a heuristic and, if it fires on most of the file, is reclassified as a
CONSTANT_OFFSET artifact rather than a per-run leak -- a leak is sporadic by nature.

Usage:  python analysis/leak_audit.py
Output: analysis/out/leak_audit.json, analysis/out/leak_audit_rows.csv
"""

import numpy as np
import pandas as pd

from common import DATASETS, load, write_json, OUT_DIR

Z_THRESHOLD = -3.0        # robust z against the pooled within-window-type scale
MEDIAN_RATIO = 0.5        # SEVERE tier: opened in under half the sibling median
MIN_ABSOLUTE_GAP_S = 1.0  # necessary condition for any hit -- keeps timer noise out
MAD_TO_SIGMA = 1.4826     # MAD -> sd for a normal reference distribution
RECURRENCE_TOLERANCE = 0.15   # residuals within +/-15% of each other count as "the same"
RECURRENCE_MIN_CONFIGS = 3    # ... across this many distinct configs -> mechanism, not leak

# Above this share of rows, S2 is not a leak -- it is a constant artifact of the metric.
CONSTANT_OFFSET_SHARE = 0.5


def _robust_scale(residuals):
    """MAD-based sigma over pooled per-cell residuals. Falls back to the plain SD when the
    MAD is degenerate (every residual identical), and to None when neither is usable."""
    r = np.asarray([x for x in residuals if not pd.isna(x)], dtype=float)
    if len(r) < 3:
        return None
    mad = np.median(np.abs(r - np.median(r)))
    if mad > 0:
        return float(MAD_TO_SIGMA * mad)
    sd = float(np.std(r, ddof=1))
    return sd if sd > 0 else None


def early_open_flags(df):
    """S1. Returns (flags Series, diagnostic frame, scale dict used per window type)."""
    flags = pd.Series(False, index=df.index)
    diag = pd.DataFrame(index=df.index,
                        columns=["cell_median", "residual_s", "robust_z", "n_in_cell"],
                        dtype=float)
    diag["severity"] = None
    if "time_to_open" not in df.columns:
        return flags, diag, {}

    t = pd.to_numeric(df["time_to_open"], errors="coerce")
    strat = df["window_type"] if "window_type" in df.columns else pd.Series("ALL", index=df.index)

    # Pass 1 -- per-cell residuals, and the robust scale of each window type's residuals.
    for _, group in df.groupby(["experiment_id", "environment"], dropna=False):
        observed = t.loc[group.index].dropna()
        if len(observed) < 3:
            continue  # cannot judge a row against replicates that are not there
        med = observed.median()
        for idx in observed.index:
            diag.loc[idx, ["cell_median", "residual_s", "n_in_cell"]] = [
                med, observed.loc[idx] - med, len(observed)]

    scales = {}
    for wtype, sub in diag.groupby(strat):
        scales[str(wtype)] = _robust_scale(sub["residual_s"])

    # Pass 2 -- score each row against its window type's scale and tier the hits.
    for idx in diag.index:
        resid = diag.loc[idx, "residual_s"]
        med = diag.loc[idx, "cell_median"]
        if pd.isna(resid) or pd.isna(med):
            continue
        sigma = scales.get(str(strat.loc[idx]))
        z = resid / sigma if sigma else np.nan
        diag.loc[idx, "robust_z"] = z
        if -resid < MIN_ABSOLUTE_GAP_S:   # not materially early -> not this signature
            continue
        if (med + resid) < MEDIAN_RATIO * med:
            flags.loc[idx] = True
            diag.loc[idx, "severity"] = "SEVERE"
        elif not pd.isna(z) and z <= Z_THRESHOLD:
            flags.loc[idx] = True
            diag.loc[idx, "severity"] = "MODERATE"
    return flags, diag, scales


def screen_recurrent_modes(df, flags, diag):
    """Separate mechanism from contamination by asking whether a hit repeats.

    Single-linkage clusters the flagged rows' residuals at RECURRENCE_TOLERANCE (relative).
    Any cluster spanning >= RECURRENCE_MIN_CONFIGS distinct experiment_ids is a reproducible
    displacement, not a leaked breaker: its rows are relabelled RECURRENT_MODE and cleared
    from `flags`. Returns (updated flags, list of cluster descriptions).
    """
    hits = sorted(flags.index[flags], key=lambda i: diag.loc[i, "residual_s"])
    clusters, modes = [], []
    for idx in hits:
        r = diag.loc[idx, "residual_s"]
        if clusters and abs(r - clusters[-1][-1][1]) <= RECURRENCE_TOLERANCE * abs(r):
            clusters[-1].append((idx, r))
        else:
            clusters.append([(idx, r)])

    for cluster in clusters:
        idxs = [i for i, _ in cluster]
        configs = sorted(set(df.loc[idxs, "experiment_id"]))
        if len(configs) < RECURRENCE_MIN_CONFIGS:
            continue
        residuals = [r for _, r in cluster]
        for i in idxs:
            flags.loc[i] = False
            diag.loc[i, "severity"] = "RECURRENT_MODE"
        modes.append({
            "n_rows": len(idxs),
            "n_configs": len(configs),
            "configs": configs,
            "residual_s_mean": float(np.mean(residuals)),
            "residual_s_min": float(np.min(residuals)),
            "residual_s_max": float(np.max(residuals)),
            "window_types": sorted(set(df.loc[idxs, "window_type"].astype(str)))
                            if "window_type" in df.columns else [],
        })
    return flags, modes


def late_open_outliers(diag, sigma_by_wtype, strat):
    """Rows whose t_open sits far ABOVE its cell median.

    Not a leak -- the leak makes breakers trip early, never late -- but the same scan sees
    them for free and they matter for the quarantine pass: a run whose breaker takes 32 s
    to open in a cell that otherwise opens in 9 s is the mild form of the same hang that
    produced the 7540.5 s time_to_recover row.
    """
    hits = []
    for idx in diag.index:
        resid, med = diag.loc[idx, "residual_s"], diag.loc[idx, "cell_median"]
        if pd.isna(resid) or pd.isna(med) or resid < MIN_ABSOLUTE_GAP_S:
            continue
        sigma = sigma_by_wtype.get(str(strat.loc[idx]))
        if sigma and resid / sigma >= -Z_THRESHOLD:
            hits.append(idx)
    return hits


def impossible_blast_flags(df, denominator):
    """S2. Returns (flags Series, per-row diagnostic frame)."""
    flags = pd.Series(False, index=df.index)
    diag = pd.DataFrame(index=df.index, columns=["n_open", "n_legs_firing", "n_legs_observed"], dtype=float)
    for idx, row in df.iterrows():
        legs = row["legs"]
        b = row["blast_frac"]
        if pd.isna(b) or not legs:
            continue
        n_open = int(round(b * denominator))
        n_firing = sum(1 for v in legs.values() if v > 0)
        diag.loc[idx] = [n_open, n_firing, len(legs)]
        flags.loc[idx] = n_open > n_firing
    return flags, diag


def audit_one(name):
    spec = DATASETS[name]
    # Exclusions are deliberately NOT applied: the audit has to see every row, including
    # rows a previous pass already quarantined, or prevalence is understated.
    df = load(name, apply_exclusions=False)

    s1, s1_diag, s1_scales = early_open_flags(df)
    s1, recurrent_modes = screen_recurrent_modes(df, s1, s1_diag)
    s2, s2_diag = impossible_blast_flags(df, spec["blast_denominator"])

    n = len(df)
    s2_share = float(s2.mean()) if n else 0.0
    exact_node_sets = spec["leg_node_set"] == str(spec["blast_denominator"])
    # A per-run state leak is sporadic. If the cross-metric contradiction holds for most of
    # a file, the metric itself is offset -- that is a construct-validity finding, not a leak.
    if not spec["leg_node_set"]:
        s2_verdict = "NOT_APPLICABLE"      # no leg column in this archive
    elif s2_share >= CONSTANT_OFFSET_SHARE:
        s2_verdict = "CONSTANT_OFFSET"
    elif s2.any():
        s2_verdict = "STATE_LEAK"
    elif not exact_node_sets:
        # Zero hits prove nothing when the two metrics range over different nodes: the
        # gateway leg alone satisfies the inequality for every row. Do not read this as CLEAN.
        s2_verdict = "INDETERMINATE"
    else:
        s2_verdict = "CLEAN"

    # v1_prefix predates real_blast_radius / leg_failure_rates, so select intersectionally
    # rather than assuming the current schema across every archive.
    wanted = ["experiment_id", "replicate", "run_timestamp", "time_to_open",
              "time_to_recover", "blast_radius", "real_blast_radius", "leg_failure_rates"]
    rows = df.loc[s1 | s2, [c for c in wanted if c in df.columns]].copy()
    rows.insert(0, "dataset", name)
    hit1, hit2 = s1.loc[rows.index], s2.loc[rows.index]
    rows["signature"] = np.where(hit1 & hit2, "EARLY_OPEN+IMPOSSIBLE_BLAST",
                         np.where(hit1, "EARLY_OPEN", "IMPOSSIBLE_BLAST"))
    rows = (rows.join(s1_diag[["cell_median", "residual_s", "robust_z", "severity"]])
                .join(s2_diag[["n_open", "n_legs_firing"]]))
    strat = df["window_type"] if "window_type" in df.columns else pd.Series("ALL", index=df.index)
    late = late_open_outliers(s1_diag, s1_scales, strat)

    timing_present = "time_to_open" in df.columns and pd.to_numeric(
        df["time_to_open"], errors="coerce").notna().any()

    summary = {
        "dataset": name,
        "path": str(spec["path"].relative_to(spec["path"].parents[1])),
        "n_rows": n,
        "n_configs": int(df["experiment_id"].nunique()),
        "timing_columns_populated": bool(timing_present),
        "leg_column_present": bool(df["legs"].map(bool).any()),
        "blast_denominator": spec["blast_denominator"],
        "leg_node_set": spec["leg_node_set"],
        "cross_metric_check_is_exact": bool(exact_node_sets),
        "S1_early_open": {
            "n_flagged": int(s1.sum()),
            "n_severe": int((s1_diag["severity"] == "SEVERE").sum()),
            "n_moderate": int((s1_diag["severity"] == "MODERATE").sum()),
            "share": float(s1.mean()) if n else 0.0,
            "applicable": bool(timing_present),
            "n_rows_scoreable": int(s1_diag["residual_s"].notna().sum()),
            "n_reclassified_recurrent": int((s1_diag["severity"] == "RECURRENT_MODE").sum()),
            "robust_sigma_s_by_window_type": s1_scales,
        },
        # Reproducible displacements the leak rule caught and the recurrence screen cleared.
        # These are findings about the instrument, not contamination -- read them.
        "recurrent_modes": recurrent_modes,
        "S2_impossible_blast": {
            "n_flagged": int(s2.sum()),
            "share": s2_share,
            "verdict": s2_verdict,
            "applicable": bool(df["legs"].map(bool).any()),
        },
        "n_rows_flagged_by_either": int((s1 | s2).sum()),
        # Diagnostic only, NOT counted as a leak -- see late_open_outliers().
        "late_open_outliers": {
            "n": len(late),
            "rows": df.loc[late, ["experiment_id", "replicate", "time_to_open"]].to_dict("records"),
        },
        "note": spec["note"],
    }
    return summary, rows


def reconcile_across_datasets(rows):
    """The recurrence screen runs per file, so a mode that shows up twice in one archive and
    three more times in another survives as a "leak" in the first. Since every file came off
    the same instrument, re-run the clustering over the pooled hits and report which
    per-dataset MODERATE hits actually belong to a mode that is recurrent globally.
    """
    hits = rows[rows["severity"].isin(["SEVERE", "MODERATE", "RECURRENT_MODE"])].copy()
    hits = hits.dropna(subset=["residual_s"]).sort_values("residual_s")
    clusters, out = [], []
    for _, row in hits.iterrows():
        r = row["residual_s"]
        if clusters and abs(r - clusters[-1][-1]["residual_s"]) <= RECURRENCE_TOLERANCE * abs(r):
            clusters[-1].append(row)
        else:
            clusters.append([row])
    for cluster in clusters:
        configs = sorted({c["experiment_id"] for c in cluster})
        if len(configs) < RECURRENCE_MIN_CONFIGS:
            continue
        out.append({
            "residual_s_mean": float(np.mean([c["residual_s"] for c in cluster])),
            "n_rows": len(cluster),
            "n_configs": len(configs),
            "datasets": sorted({c["dataset"] for c in cluster}),
            "still_labelled_leak_per_file": [
                {"dataset": c["dataset"], "experiment_id": c["experiment_id"],
                 "replicate": int(c["replicate"]), "severity": c["severity"]}
                for c in cluster if c["severity"] in ("SEVERE", "MODERATE")],
        })
    return out


def main():
    summaries, all_rows = [], []
    for name in DATASETS:
        s, r = audit_one(name)
        summaries.append(s)
        all_rows.append(r)
        print("\n=== {} ({} rows) ===".format(name, s["n_rows"]))
        print("  S1 early-open      : {:>3} flagged ({} severe / {} moderate) of {} scoreable{}".format(
            s["S1_early_open"]["n_flagged"], s["S1_early_open"]["n_severe"],
            s["S1_early_open"]["n_moderate"], s["S1_early_open"]["n_rows_scoreable"],
            "" if s["S1_early_open"]["applicable"] else "  [N/A -- timing columns are null]"))
        for m in s["recurrent_modes"]:
            print("     ! recurrent mode, NOT a leak: {} rows across {} configs at "
                  "{:+.2f}s ({})".format(m["n_rows"], m["n_configs"], m["residual_s_mean"],
                                         "/".join(m["window_types"])))
        print("  S2 impossible-blast: {:>3} flagged ({:.1%})  verdict={}{}".format(
            s["S2_impossible_blast"]["n_flagged"], s["S2_impossible_blast"]["share"],
            s["S2_impossible_blast"]["verdict"],
            "" if s["cross_metric_check_is_exact"] else "  [heuristic -- disjoint node sets]"))

    rows = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.to_csv(OUT_DIR / "leak_audit_rows.csv", index=False)
    print("\nwrote analysis/out/leak_audit_rows.csv ({} rows)".format(len(rows)))

    # The consequence that actually matters for the sprint: can H3's detection-latency
    # numbers still be computed on data that is both timed and uncontaminated?
    h3_capable = [s for s in summaries if s["timing_columns_populated"]]
    global_modes = reconcile_across_datasets(rows) if len(rows) else []
    for m in global_modes:
        if m["still_labelled_leak_per_file"]:
            print("\nglobal recurrence: mode at {:+.2f}s spans {} configs across {} -- "
                  "{} row(s) still labelled a leak in their own file belong to it".format(
                      m["residual_s_mean"], m["n_configs"], "/".join(m["datasets"]),
                      len(m["still_labelled_leak_per_file"])))

    # Per-file counts still include hits the cross-file screen later attributed to a mode, so
    # subtract them here -- otherwise the headline prevalence overstates contamination by
    # counting the same reproducible artifact once per archive it appears in.
    globally_explained = sum(len(m["still_labelled_leak_per_file"]) for m in global_modes)
    flagged = sum(s["S1_early_open"]["n_flagged"] for s in h3_capable)
    severe = sum(s["S1_early_open"]["n_severe"] for s in h3_capable)
    timed_rows = sum(s["n_rows"] for s in h3_capable)

    verdict = {
        "datasets_with_timing": [s["dataset"] for s in h3_capable],
        "n_timed_rows": timed_rows,
        "flagged_per_file": flagged,
        "explained_by_global_recurrence": globally_explained,
        "leak_rows_after_global_screen": flagged - globally_explained,
        "severe_rows_in_timed_data": severe,
        "prevalence_after_global_screen": ((flagged - globally_explained) / timed_rows
                                           if timed_rows else 0.0),
        "h3_recompute_required": bool(flagged - globally_explained > 0),
        "h3_numbers_move": bool((flagged - globally_explained) / timed_rows > 0.05
                                if timed_rows else False),
    }

    write_json("leak_audit.json", {
        "signatures": {
            "S1_early_open": {
                "rule": ("gap >= {}s AND (t_open < {}x sibling median [SEVERE] "
                         "OR robust z <= {} [MODERATE])").format(
                    MIN_ABSOLUTE_GAP_S, MEDIAN_RATIO, Z_THRESHOLD),
                "scale": "MAD-based sigma over per-cell residuals, pooled within window_type",
                "requires": ">= 3 non-null time_to_open per (experiment_id, environment)",
            },
            "S2_impossible_blast": {
                "rule": "round(blast_frac * denominator) > count(leg failure rate > 0)",
                "exact_only_when": "leg node set == blast subject set",
                "reclassified_as_constant_offset_above_share": CONSTANT_OFFSET_SHARE,
            },
        },
        "per_dataset": summaries,
        "global_recurrent_modes": global_modes,
        "verdict": verdict,
    })
    return summaries


if __name__ == "__main__":
    main()
