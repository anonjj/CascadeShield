# R2 — equal-exposure recovery experiment: pre-registered analysis plan

**Status:** frozen on commit. Nothing below may change after any R2 run under it.
**Commissioned by:** D28 (f99598e, h3-evidence-audit)
**Result will be recorded as:** D29

## 1. Question

Phase 4B could not test H3's recovery-side negative control, because fault exposure
after OPEN was a function of window type and window size (D28). R2 holds exposure
equal by construction and asks whether any recovery difference between COUNT_BASED
and TIME_BASED survives.

## 2. Design

- Fault cleared at `OPEN + D_w + 5s`, by the identical rule in both arms.
- Continuous load at 10 req/s from t=0 until the breaker closes.
- The same 24 configurations as Phase 4B (docs/paper/phase4b_only_ids.txt),
  3 replicates = 72 runs.
- LINEAR + LATENCY, one machine, `machine_id=jay-mac`, seed 20260929.
- Outputs: `data/r2_equal_exposure.csv`, `data/r2_cb_transitions.jsonl`.
- Prometheus and Grafana are stopped for the duration of the sweep, matching
  Phase 4B's collection conditions. The canary was run with them live; this is one
  reason its absolute values are not treated as a baseline (§4).

## 3. Primary prediction (the test)

Under D28's model, window type does not reach recovery at all. Therefore:

- **P1 — bounce count.** Exactly 1 bounce per run, in both arms, at every D_w.
- **P2 — arm difference.** Median recovery in the two arms differs by less than 1s
  within every D_w stratum.

P2 is the confirmatory test. It is a difference between arms measured in the same
sweep on the same host, so it does not depend on host-specific constants.

**Falsification.** D28 is contradicted if bounce counts differ systematically by
window type, or if a recovery gap greater than 1s appears in the same direction in
all three strata.

## 4. Secondary prediction (descriptive, not the test)

Recovery ≈ 2·D_w + (E_FAIL + E_OK), i.e. one failed HALF_OPEN episode, one wait
duration, one successful episode.

The episode constants E_FAIL = 3.5s and E_OK = 3.0s were fitted on Phase 4B, which
ran on soham-local (x86). R2 runs on jay-mac (arm64). **These constants are
therefore not expected to transfer**, and the canary already indicates they do not:
at D_w=5 the model predicts 16.5s and the canary observed 13.89–13.98s, consistent
with a smaller E_FAIL on this host.

This prediction is recorded for completeness and is **not** a test of D28. A miss
here is a host-constant difference, not evidence about window type.

## 5. Statistical treatment

- Unit of analysis: configuration (mean of its replicates), not the row.
- `stratified_cluster_permutation_test`, strata D_w ∈ {5,15,30}, 4v4 per stratum.
- Exact p floor computed on cluster counts; reported alongside the p-value, always.
- Direction consistency across strata checked and reported **before** any pooled
  p-value is quoted.
- Note: P2 is an equivalence claim, not a difference claim. A non-significant
  permutation test does not establish equivalence. The primary evidence for P2 is
  the observed per-stratum median difference against the 1s threshold, with the
  permutation test reported as secondary.

## 6. Exclusion rules

Applied in this order, before any outcome column is read:
1. Aborted runs.
2. Any gateway CLOSED_TO_OPEN in the sidecar.
3. Runs not VERIFIED_CLEAN under the horizon rule (§7).
4. Implausible duration (host-sleep ceiling, as in Phase 4B).
5. `lambda_deviation_flag` set.

## 7. Verification horizon

`end = run_timestamp`, as adopted in DEVIATION 02, including its recorded caveat
that this is not strictly outcome-independent (r = 0.994 with recovery time) but
is stricter, not more lenient, for slow recoveries.
The gateway poller runs continuously alongside the sweep, as in Phase 4B.

## 8. Claim scope

LINEAR + LATENCY, one machine (jay-mac, arm64), threshold 50 at window sizes
5/10/20 plus one threshold-70 probe per stratum, database state not reset between
runs. `slidingWindowSize` is calls under COUNT_BASED and seconds under TIME_BASED;
arms are matched on threshold, D_w, topology, fault type, load, and post-OPEN fault
exposure.

**Host note.** Phase 4B ran on soham-local (x86); R2 runs on jay-mac (arm64,
fanless, Docker in a VM). R2 numbers are therefore not directly comparable in
absolute terms with Phase 4B's. Every R2 claim is a within-R2 comparison between
arms. Image digests and architecture for both hosts are recorded in the R2 manifest.
The gateway image used for R2 (sha256:c281f7db…, arm64) is a different build from the
one recorded for Phase 4B (sha256:ce110c0a…). Both postdate D25 by source inspection,
but the digests cannot establish that on their own. All 72 R2 runs use the single R2
image, so this does not affect any within-R2 comparison — it is a further reason no R2
value is compared in absolute terms against Phase 4B.
## 9. The canary rows

Four runs were collected on 2026-09-30 before this plan existed
(LIN-LAT-CNT-T50-W5-D5, LIN-LAT-CNT-T50-W20-D5, LIN-LAT-TIM-T50-W5-D5,
LIN-LAT-TIM-T50-W20-D5, replicate 1). They are **discarded and re-collected**, so
that all 72 R2 rows post-date this plan's commit.

Their outputs are quarantined to `data/audit/r2_canary_20260930/` rather than
deleted, following the precedent set for Phase 4B's aborted launch
(`data/audit/aborted_launch_20260921T061403Z/`), so the record of what was run
remains available. They are not part of the R2 analysis set under any rule.

The decision was taken on provenance alone — the rows predate the pre-registration
— and not on any outcome column. The canary's observed values are reported in §4
only as evidence that the fitted episode constants do not transfer across hosts,
which is why §4 is descriptive rather than a test.
## 10. Freeze This file is committed before the first R2 sweep run. Its commit SHA goes in the R2 launch manifest and must predate the first run timestamp.
