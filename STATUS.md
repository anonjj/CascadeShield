# CascadeShield — Project Status

**Last updated:** 2026-09-18 · **Update this file whenever a PR lands or a sweep finishes.**

> This is the single source of truth for *where the project is*. It is meant to be read first,
> from any tool — Claude Code, Claude in the browser, Cowork, or a human. The reasoning behind
> any line here lives in `docs/paper/decision-log.md`; this file says **what is true now**.

---

## The one thing to know

**The paper is decided: Paper B — construct validity.** Decision D-004 (the "Day-2 Gate"),
taken jointly by Soham and Jay, closed out 2026-09-08 by Soham once the canary-matrix run
existed to read against. Explicitly *not* reopenable by later data.

| | |
|---|---|
| **Load-bearing chapters** | H3 (recovery-side leak), H4 (τ_leg curve), H5 (leg containment), and the metric-evolution narrative (D-001 → D15 → D17) |
| **Retired** | H1 and H2. No λ effect was found at all — trip rate sat flat at 1.00 for both window types at every sampled λ — which ruled out Paper A and A′ outright |

Everything below is ordered by whether it blocks Paper B.

---

## Status at a glance

| Workstream | State | Blocks writing? |
|---|---|---|
| Paper direction (D-004) | ✅ **Done** — Paper B, 2026-09-08 | — |
| Harness + mesh (6 services, Toxiproxy, D17 fix) | ✅ **Done** — D17 fix merged (PR #45) | — |
| LATENCY data, LINEAR + FANOUT | ✅ **Done** — 324 rows live | — |
| Occupancy / H2b sweep (D7, D18) | ✅ **Done** — 162/162 runs, hypothesis closed | — |
| Canary matrix (D-004 gate) | ✅ **Done** — 300/300 runs; data in PR #43, unmerged | — |
| CRASH re-collection, **LINEAR** | ✅ **Done** — 162/162; PR #47, unmerged | — |
| CRASH re-collection, **FANOUT** | 🔴 **Not collected** — needs a free machine, ~6h | **Yes** |
| D15 / D-001 re-derivation after CRASH | 🔴 **Blocked** on the line above | **Yes** |
| D13 / H3 (recovery leak) | ✅ **Confirmed** — `LEAK_CONFIRMED_ON_HALF_OPEN_LEG`, 36/36 recovered on both arms at all three D_w after the poll-until-transition fix (D21); KM computed on 34/36 (2 host-sleep-corrupted durations excluded), significant everywhere (p=0.0014 at D_w=5/15, p=0.0005 at D_w=30) | — |
| Statistical treatment (D19) | ✅ **Defined** — Mann-Whitney + Cliff's δ, bootstrap CIs, censoring as rate + conditional timing. Two known deviations flagged, neither blocking | — |
| Throughput / TPS reporting (D20) | ✅ **Retired** — `throughput_loss`'s measurement window is sized by the swept window params, so it is confounded with the IV and not repairable post hoc. No TPS number appears in the paper | — |
| Manuscript | 🔴 **Not started** — no draft exists anywhere in the repo | — |

**One thing blocks writing:** the FANOUT CRASH re-collection (and the re-analysis it unblocks).
D13/H3 closed 2026-09-16 — see below. Nothing else.

---

## Hypothesis scoreboard

| ID | Claim | Verdict | Where |
|---|---|---|---|
| **H1** | At matched horizon H, COUNT vs TIME differ in variance, not mean, of `time_to_open` | ⚪ **Not testable** on collected data — COUNT horizons {25…800} and TIME {5,10,20} are disjoint, zero overlap. Generator fixed (`6b045b4`) but the data predates it | D-004, D-003 |
| **H2** | A crossover λ\* exists below which TIME_BASED cannot trip | ❌ **No effect found.** Trip rate 1.00 at every λ ∈ {5,20,80,320}, both window types. This is what selected Paper B | D-004 |
| **H2b** | Occupancy ratio ρ = effective_horizon / n_min crossing 1 predicts inertness | ✅ **Confirmed for TIME_BASED** (clean crossover, no overlap) · ❌ **cleanly falsified for COUNT_BASED** (0/54 rows ever inert). Mechanism: COUNT's ring buffer caps `minimumNumberOfCalls` — **live-verified 2026-09-17**, not just inferred: a per-call `CircuitBreaker` event trace on a real replay of the ρ=0.025 cell shows evaluation starting at `bufferedCalls=5` (window capacity), never at 200; the cap is applied internally by Resilience4j at runtime, invisible on the static `CircuitBreakerConfig` object (checked and ruled out separately) | D18 |
| **H3** | Double dissociation: window params → detection, wait_duration → recovery | ✅ **Confirmed 2026-09-16.** `LEAK_CONFIRMED_ON_HALF_OPEN_LEG` — after D21's poll-until-transition fix, **36/36 recovered on both arms at all three $D_w$** (was 2/6, 0/6 for COUNT under the old fixed-~4.1s probe window — a pure instrument artifact, not a property of COUNT_BASED). TIME slower at every level, significant throughout (log-rank p=0.0014 at $D_w$=5/15, p=0.0005 at $D_w$=30 — the precise-metric KM is computed on 34/36 runs, 2 excluded as host-sleep-corrupted durations, unchanged medians/ratios): **9.49× at $D_w$=5, 2.16× at $D_w$=15, 2.40× at $D_w$=30** (medians COUNT 2.04/9.83/14.99s vs TIME 19.34/21.27/35.90s). The ratio *shrinking* with $D_w$ — not flat, not growing — is a genuinely new shape versus the pre-fix censored read, which could only see the two extremes and had no real COUNT numbers at $D_w$≥15 to compare against. Verification data kept standalone (`d21_poll_until_transition_verification`, not merged into `current` — see `analysis/common.py`), since the coarse `time_to_recover` metric was never actually censored (confirmed independently, 0/360 nulls) and needed no fix. **Live-verified 2026-09-17:** HALF_OPEN→CLOSED is governed by `permittedNumberOfCallsInHalfOpenState` (3), not `minimumNumberOfCalls` — confirmed via a live discriminator (n_min=3 vs n_min=30, everything else identical) that recovered in statistically indistinguishable time (~20s both arms) plus a per-call event trace showing exactly 3 calls admitted per HALF_OPEN episode regardless of n_min. This rules out the hoped-for shared-root-cause tie to H2b (D18) — HALF_OPEN's gate and H2b's CLOSED-side n_min-clamping gate are separate mechanisms. **Partially explained 2026-09-17 (D22):** HALF_OPEN→OPEN bounce count is a real, dominant driver — COUNT_BASED never bounces (0/18 observations); TIME_BASED bounces 1.33/1.5/1.75× on average as `window_size` grows (5/10/20), matching the residual-window-contents hypothesis. Joint regression (`duration_s ~ bounce_count + wait_duration + window_type`, n=34): R²=0.862, ~6.4s per bounce. **Not a complete mechanism** — a genuine ~9.8s TIME-vs-COUNT residual remains even at bounce_count=0, and two 0-bounce COUNT `W20/D30` runs (~25.3s) are unexplained by this model. See `analysis/bounce_count_analysis.py`. **Corrected 2026-09-17 (D24):** the two flagged items above were gateway contamination (D23), not COUNT_BASED properties. Stratified by `gateway_tripped` (`--stratify-gateway`): the within-COUNT $D_w$ trend (2.04→9.83→14.99s) dissolves — $D_w$=30 has **zero** clean COUNT_BASED data (6/6 gateway-tripped), $D_w$=15 is 4/6 tripped. **TIME>COUNT still holds on clean data** at $D_w$=5 (9.49×) and $D_w$=15 (8.81×); $D_w$=30 is untestable (COUNT arm entirely gateway-tripped). **Significance, corrected 2026-09-18, twice.** First pass (`analysis/exact_tests.py`) replaced the chi-square p-values with row-level exact permutation p's (D5: p=0.0043, D15: p=0.0476) — that pass is itself **retracted**: it never checked whether those rows were independent configurations. They weren't — $D_w$=5 is 3 configs/arm with 2 replicates each, $D_w$=15 is **1 COUNT config** (2 replicates of the same `W20-D15`) vs 3 TIME configs. A permutation test needs ≥2 independent units per arm; $D_w$=15 alone cannot support one (its own cluster floor is 1/4=0.25, unreachable at α=0.05 regardless of the data). **Corrected test:** `stratified_cluster_permutation_test` — configuration is the unit (mean of its replicates), $D_w$ is a blocking stratum, H3's claim is tested **once**, not per-$D_w$. $D_w$=5 (3v3 configs, C(6,3)=20 relabelings) × $D_w$=15 (1v3 configs, C(4,1)=4 relabelings) = 80 joint assignments; every COUNT config beats every TIME config in both strata (complete separation), so **p = 0.025 (two-sided), exactly the floor — the correct, honest, first-valid significance test of this comparison.** $D_w$=30 excluded from the test (empty COUNT arm, no label information). See `analysis/exact_tests.py` and decision-log.md's two 2026-09-18 updates to D24 (the first retracted by the second). D22's residual **shrinks to 2.75s** (from 9.77s) and R² rises to 0.934 once cleaned (`--exclude-gateway-tripped`) — bounces explain nearly all of it. A `master_dataset.csv` audit for gateway activity (`analysis/gateway_leg_audit.py`) came back structurally inconclusive — gateway is excluded from every per-leg column by design — and surfaced an unrelated, unsolved ~2×/1× error_rate ratio artifact that splits by collection batch, flagged not solved | D13, D18, D21, D22, D23, D24 |
| **H4** | Competing containment definitions rank configs differently (Kendall τ < 1) | ✅ **Supported.** 36/36 pairs below τ=1.0. Magnitude moved a lot after FAN_OUT data: min pairwise τ is now **0.891**, was 0.238 — rankings agree *more* than first measured, but never perfectly | D-001 |
| **H5** | Blast-radius resolution is topology-dependent: Var(B)=0 on a chain, >0 with parallel subjects | ❌ **Tested and NOT supported.** FANOUT+LATENCY gives Var(B)=0 too, identical to LINEAR — 162/162 rows each side, exactly one leg firing | D15 |
| **H6** | A uniform edge breaker suppresses interior breaker engagement (gateway shadowing) | 🟡 **"Untestable" verdict corrected 2026-09-17 (D23), not yet re-decided.** The `measurement-plane` isolation was believed complete (`cb_state_pre` "CLOSED at load start" was the evidence — a pre-load snapshot, never evidence for mid-run state). Live-verified it's incomplete: gateway's breaker never sets `sliding-window-size`/`sliding-window-type`, which silently track the swept `default` values, so — combined with D18's confirmed mechanism — gateway's breaker **does** trip under COUNT_BASED at `wait_duration ∈ {15,30}` (20 real trips across 5 experiment_ids in `data/cb_transitions.jsonl`; 0 under TIME_BASED, where the isolation genuinely holds). H6 may be directly testable now, not just via deliberate reconstruction — testability verdict needs re-deciding, not done yet | D23, hypotheses.md §7 |

---

## Open loops that block writing

### 1. CRASH re-collection → D15 and D-001 re-derivation

D17 found that `leg_failure_rates` averaged two circuit breakers per service, halving true
severity. The fix (max-of-breakers) merged 2026-09-06 as PR #45 / `0c64ca4`. **Every CRASH row
collected before that is diluted** — all 380 read exactly `0.5000`, zero variance.

| Step | State |
|---|---|
| Archive pre-fix data as `v6`, strip CRASH from live file | ✅ Done (PR #46). Live file is now **324 rows, LATENCY-only** |
| Re-collect **LINEAR** CRASH | ✅ Done — 162/162, `order_leg` now uniformly `1.0000` |
| Re-collect **FANOUT** CRASH | 🔴 **Not done.** Two attempts died (codespace VM restart; then billing lockout). No data survived |
| Merge both into `master_dataset.csv`, bump `n_expected` 324 → ~648 | 🔴 Blocked |
| Re-run `analysis/tau_sweep.py` + `analysis/order_leg_containment.py` | 🔴 Blocked |
| Update D15, D-001, hypotheses.md §5.4 with real numbers | 🔴 Blocked |

**D15 carries an explicit embargo:** *"Action before re-quoting the combined-dataset table
anywhere: land D17's fix and re-collect CRASH rows."* Until that is done, **do not quote D15's
combined-dataset separation numbers.** The LATENCY-only separation still holds and is safe to
cite (COUNT max 0.2250 < TIME min 0.2686).

**Honest caveat already known:** post-fix CRASH saturates at exactly `1.0000` regardless of
window type, so it still won't discriminate COUNT vs TIME — it is now *correctly* saturated
instead of incorrectly diluted. LATENCY remains the only fault type with resolution for that
comparison.

### 2. D13 / H3 — replicate top-up is done; the estimator is now the blocker

The precise HALF_OPEN→CLOSED metric works (two harness bugs fixed: event buffer 50→5000, plus
settle time after the recovery loop), and the replicate top-up ran (36 runs on `jay-mac`,
commit `c59ef95`, `n=6`/bucket — `data/cb_transitions.jsonl` committed with `-f` this time, 37
records). That surfaced a real problem in the *analysis* code, not the data: at D_w=30, COUNT
recovered 0/6 times within the observation window, and
`analysis/window_type_recovery_leak.py`'s old `.dropna()`-then-median table silently dropped
that row rather than reporting "0/6" — which is why `c59ef95`'s own message declined to call
D13 closed.

**Fixed 2026-09-15**: the script now goes through D19's `compare_censored_groups` protocol
(`analysis/common.py`), the same one `throughput_loss`'s retirement (D20) already established
for right-censored DVs. Every D_w level with rows on both arms is reported, censored or not; a
regression test (`self_test_censoring`) locks in that a fully-censored bucket can't vanish or
be silently folded into a "consistent" verdict again. Re-run against the top-up data, the
script reports `LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING` (D_w=5 10.35x, D_w=15 9.00x,
D_w=30 COUNT never recovers) — see decision-log.md's D13 entry for the full numbers and why
that label is a change in what's provable, not a weakening of the finding.

**Update (2026-09-16) — the estimator is done, and it moves the blocker again.**
`analysis/half_open_survival.py` (new) implements Kaplan-Meier + log-rank, dependency-light
(numpy only). Two extraction bugs found and fixed first (a legacy occupancy-mode record
polluting the D_w=15 bucket; the observation span and censoring bound both needed to match
`window_type_recovery_leak.py`'s own definitions exactly). $D_w$=5 agrees with that script
almost exactly (10.38× vs 10.35×) — confirms the two scripts agree wherever there's nothing
for an estimator choice to disagree about.

**Result: neither closes nor reverses.** $D_w$=5 is real and significant (p=0.0005, TIME
10.4× slower). $D_w$=15 is directionally consistent but not significant (p=0.14, COUNT only
2/6 recovered). $D_w$=30 has **no valid significance test at all** — COUNT recovered 0/6
times, so the log-rank test has zero variance to work with, not merely a null result.

**New finding: the harness's recovery-observation window is a flat +10s, not scaled to D_w.**
`breaker_observer.py::_poll_for_recovery`'s deadline is `wait_duration + 10` from when the
fault clears — and since the OPEN→HALF_OPEN transition itself consumes ~wait_duration of that
budget (Resilience4j auto-transitions purely on elapsed time), only ~10s ever remains to
observe the HALF_OPEN→CLOSED leg, *regardless of D_w*. Verified against every one of the 26
real closures in the dataset: 0 violations of this bound. This means COUNT's rising censoring
rate at higher D_w (0/6 → 4/6 → 6/6 uncensored, reading D_w 5→15→30) is at least partly an
**instrument ceiling**, not necessarily COUNT itself recovering more slowly.

**Update (2026-09-16) — fixed the real constant, re-collected, H3 closes.** Tracing WHY
every censored COUNT record showed exactly 2 events (`CLOSED_TO_OPEN`, `OPEN_TO_HALF_OPEN`)
then silence found the actual cause: not `_poll_for_recovery`'s deadline (which had 17-27s of
slack even at $D_w$=30, verified against real `fault_cleared_at` values), but
`_drive_half_open_probes` — called unconditionally for a **fixed ~4.1 seconds** regardless of
`wait_duration` or whether a transition had happened yet. Rewritten as poll-until-transition
(D21, PR #57): drive traffic, stop the moment `HALF_OPEN_TO_CLOSED` lands, hard ceiling
`3*wait_duration+60s`. Two new columns (`half_open_probe_timed_out`,
`half_open_probe_deadline_s`) make censoring observable going forward instead of inferred.

Re-collected 18 configs × 2 replicates × 2 window types = 36 runs under the fixed harness
(`d21_poll_until_transition_verification`, standalone — not merged into `current`, see
`analysis/common.py`). **Result: `half_open_probe_timed_out=False` on all 36/36 runs.** Zero
censoring anywhere, at any $D_w$, on either arm. `analysis/half_open_survival.py` against just
this post-fix data (**34 of 36** — 2 excluded as implausible durations, see below): verdict
`LEAK_CONFIRMED_ON_HALF_OPEN_LEG`, log-rank p=0.0014 at $D_w$=5/15, p=0.0005 at $D_w$=30, TIME
slower throughout — **9.49× at $D_w$=5, 2.16× at $D_w$=15, 2.40× at $D_w$=30** (medians COUNT
2.04/9.83/14.99s, TIME 19.34/21.27/35.90s — medians and ratios are unchanged by the 2
exclusions; only the exact p-values at $D_w$=5/15 moved, still ≪0.05). The censoring was purely
the fixed harness window — not a property of COUNT_BASED's HALF_OPEN behavior — and the
corrected shape (ratio shrinking with $D_w$, not flat) is new information the censored data
literally could not have shown, since it never had real COUNT numbers at $D_w$≥15 to compare
against.

**Data-quality notes, not related to the fix — a recurring host-sleep artifact, now 4
instances.** 2 of the 36 runs' *coarse* `time_to_recover` (a wall-clock poll duration, separate
from the precise sidecar-timestamp metric above) came back at 704.6s and 2657.1s — a real-world
system-sleep event mid-poll on the collecting machine, not a code defect. Caught automatically
by `quarantine.py`'s existing `RECOVERY_TIMEOUT_HANG` rule (`RECOVERY_CAP_S=120.0`), no new
detection logic needed. Their `half_open_probe_timed_out` is still correctly `False` — the
sleep hit `_poll_for_recovery`'s loop, not the separate, much shorter window
`_drive_half_open_probes` runs afterward. **Two more turned up on the *precise* metric itself**
(`LIN-LAT-TIM-T50-W20-D5` rep2: 700.4s, `LIN-LAT-TIM-T50-W20-D15` rep1: 1703.4s — the 2
exclusions above), never previously filtered since `half_open_survival.py` had no equivalent
ceiling check on this metric. Fixed 2026-09-17: `extract_observations()` now excludes any
recovered duration exceeding `half_open_probe_deadline_s(wait_duration)`, flagged with a WARN,
not silently. Four host-sleep artifacts total now, every one caught by an automated ceiling
rule rather than by inspection — a recurring wall-clock hazard on laptop-class collection
hosts, worth a line in the paper's methods section.

**D13/H3 is closed.** Full numbers and reasoning in `docs/paper/decision-log.md`'s D13 and
D21 entries.

---

## Open PRs — what to do with each

| PR | Branch | State | Recommendation |
|---|---|---|---|
| **#43** | `data/canary-matrix-codespace-full` | MERGEABLE | **Merge.** 300/300 canary-matrix rows, 0 aborted. Already read out for D-004. Note it lacks an `arm` column — joins to `data/canary_matrix.csv` on `(run_index, replicate)` |
| **#47** | `data/crash-recollect-linear` | MERGEABLE | **Hold**, then merge together with the FANOUT half so the dataset moves in one step |
| **#49** | `docs/b8-readme-regen` | MERGEABLE | **Merge.** README §1 + Appendix A regenerated; all claims verified against main |
| **#48** | `experiment/occupancy-ratio` | ⚠️ **CONFLICTING** | **Close it — do not merge.** See below |

**Why #48 must not be merged.** Its content already reached main by another route (PRs #36/#42).
Main's `runner.py` is strictly *ahead* of that branch: main has `socket`, `BreakerObserver`,
`resumable_runner`, `constants`, and `DATASET_PATH_OVERRIDE`, none of which exist on #48, and
main's `compute_occupancy_ratio(effective_horizon, min_calls)` is a refactor of #48's older
four-argument version. Meanwhile #48's branch carries `data/master_dataset.csv` at **0 lines**
against main's 325. **Merging it would revert the harness and destroy the dataset.**

This is also the branch the local checkout sits on, which is a large part of why local state
looks confusing. After closing #48, `git checkout main && git reset --hard origin/main`.

---

## Data inventory

**Live:** `data/master_dataset.csv` — **324 rows, LATENCY-only** (matches
`analysis/common.py`'s `DATASETS["current"]["n_expected"]`). CRASH rows are absent by design,
pending re-collection.

| Archive | Rows | Why it exists |
|---|---|---|
| `v1_prefix` | 486 | Pre-timing-collector; both timing DVs 100% null |
| `v2_latency_5svc` | 162 | First sweep with timing; blast_radius and leg vector span disjoint node sets |
| `v3_gateway_not_rebuilt` | 92 | Gateway container not rebuilt — transitional, not a result set |
| `v4_flat_concurrency` | 798 | Pre-LOAD_CONCURRENCY-fix; 242 rows flagged `lambda_deviation_flag` |
| `v5_soham_linear_presweep` | 324 | Soham's independent LINEAR sweep; superseded, audit only |
| `v6_pre_d17_leg_blend_crash` | 704 | Pre-D17-fix snapshot; every CRASH row saturated at 0.5000 |

**Five traps, all real:**

1. **7 of 8 analysis outputs are stale.** Only `analysis/out/canary_readout.json` postdates the
   2026-09-06 CRASH-strip. `order_leg_containment.json` and `tau_sweep.json` were written ~75
   minutes *before* it; `leak_audit.json` dates to 2026-08-13. **Any number read out of
   `analysis/out/` today describes the pre-strip dataset.** Re-run before quoting.
2. **`data/occupancy_dataset.csv` (162 rows) is not registered in `DATASETS`** — H2b/D18's whole
   evidence base cannot be loaded via `analysis/common.py::load()` like everything else.
3. ~~**`scipy` is an undeclared dependency.**~~ **Fixed — PR #52.** It had been satisfied only
   transitively via `scikit-learn`, so a bare `pandas`+`numpy` install would `ImportError`
   across all 8 scripts under `analysis/`. Now pinned in `ml/requirements.txt`.
4. ~~**The roadmap board that drives "B" items lives outside the repo.**~~ **Closed
   2026-09-14 — the board is gone and is not being reconstructed.** Searched exhaustively:
   both GitHub Projects exist but hold **0 items**, the repo has no linked project and no
   milestones, the `.docx` planning files contain no B-numbers, no published artifact matches,
   and no branch in history mentions any B-number except B5 and B8. The originating browser
   session no longer has it either.

   **This is a small loss, deliberately accepted.** Both known items shipped — **B5 → PR #51**,
   **B8 → PR #49** — so the board indexed work, and the work survived. This file's *Remaining
   work* table was derived from the decision log, hypotheses, the `DATASETS` registry and a
   repo-wide sweep for open-work markers — never from the board — so nothing here depends on
   it. The residual risk is unknowable but bounded: an item that lived only in that chat and
   was written down nowhere else.

   **Consequence: B-numbers are a dead reference.** Do not chase them. `docs/paper/statistical-
   treatment.md` and D19 cite "B5 (roadmap board)" and PR #49 cites B8 — those citations stay
   as historical record, but they point at nothing retrievable. **The backlog is the *Remaining
   work* table in this file.** Add to it here; do not start a second list somewhere a session
   can't read.

   **Amendment, same day.** A **B7** card ("Drop TPS from reported results," P1) surfaced hours
   after this was written — pasted in from a screenshot the owner still had, not from a
   recovered board. So the board is unreachable, not provably gone, and more cards may yet
   arrive the same way. Treat any that do as input to the *Remaining work* table, not as a
   revival of B-numbering. B7 itself is decided and closed: **D20**, throughput retired from
   reporting.
5. **A stray `master_dataset.csv` sits at the repo root** (798 rows, matching the v4 archive),
   untracked and in no git history. **It is not the live file.** Delete it.

---

## Remaining work, in order

| # | Task | Effort | Needs |
|---|---|---|---|
| 1 | FANOUT CRASH re-collection | ~6 h | A free machine (see below) |
| 2 | Merge #47 + FANOUT, bump `n_expected` to ~648, re-run `tau_sweep.py` + `order_leg_containment.py`, update D15 / D-001 / hypotheses §5.4 | ~1 h | #1 |
| 3 | ~~D13/H3~~ ✅ **closed 2026-09-16** — poll-until-transition fix (D21, PR #57), re-collected 36/36 clean, `LEAK_CONFIRMED_ON_HALF_OPEN_LEG` | — | — |
| 4 | Merge #43 and #47 (#47 waits for FANOUT) | minutes | #1 for #47 |
| 5 | Conditional — **only if an ML result enters the paper**: drop `throughput_loss` from `ml/preprocessing.py::IF_NUMERIC_FEATURES` and re-fit, per D20's carried item. The Isolation Forest currently inherits the confound | ~min | — |
| 6 | **Start writing Paper B** | — | #1 |

**Optional, no longer required:** re-running the `matched_horizon` arm against the regenerated
design to make H1 testable (~1.5 h). Paper B doesn't need H1; per D-004 a positive result would
only *add* a finding, never change the paper.

**Machines.** Jay's codespace is billing-locked (free-tier compute exhausted; quota resets at
the next cycle). Free options: Jay's Mac (16 GB / 8 CPU, Colima installed but not running,
~17 GB disk free — tight for the 6 service images) or Soham's laptop (already proven on this
harness as `soham-local`). D16 cleared cross-machine splitting for these DVs, so either is
methodologically fine. [GitHub Student Pack](https://education.github.com/pack) would raise the
codespace quota to 180 core-hours for free, but takes days to verify.

---

## Operational footguns

Learned the hard way, repeatedly. These are in `CLAUDE.md` too so sessions load them
automatically.

1. **`export DATASET_PATH_OVERRIDE=...` before *every* run**, and check it after launch.
   `get_dataset_path()` has no case for several modes and silently falls through to
   `master_dataset.csv`. This has misfiled data **twice** (PR #37; the canary-matrix smoke test).
2. **Long sweeps: `nohup … & disown`.** An SSH drop does not kill the job — but a codespace **VM
   restart kills both the job and Docker**. After any restart: `docker compose up -d --build`,
   then confirm `curl http://localhost:8474/proxies` returns JSON before relaunching.
3. **Verify the output file exists ~2 min after launching**, not 6 hours later.
4. **`cb_transitions.jsonl` is gitignored.** Anything needing it must commit it with `git add -f`
   or the run is wasted (this is exactly why D13 needed a second top-up before landing at n=6).
5. **Never push or merge directly to `main`.** Branch per unit of work, PR via `gh pr create`.
6. **Use a `git worktree`** when the local checkout has unrelated uncommitted work.
7. **On a laptop, `caffeinate -dims` does not survive a closed lid.** Clamshell sleep suspends
   the whole process tree regardless of caffeinate flags; a poll loop mid-sleep just sees a huge
   wall-clock jump on wake, not a crash — silently inflating any wall-clock-duration measurement
   (2 of 36 rows in the D21 re-collection hit 704s/2657s this way). Keep the lid open (or add
   `-s` and stay on AC power, which still won't survive an actual lid close) for any long
   detached run; `quarantine.py`'s `RECOVERY_TIMEOUT_HANG` rule catches the symptom after the
   fact, but doesn't stop it happening.

---

## Keeping this file honest

Update it in the same PR as the work it describes — that is the only thing that stops it rotting
the way `SESSION_HANDOFF.md` did (it sat three weeks describing a finished task as "in
progress"). If you find a line here that is wrong, fix it rather than working around it.

**Reasoning lives elsewhere, on purpose:** `docs/paper/decision-log.md` (why each decision went
the way it did), `docs/paper/hypotheses.md` (full hypothesis text and evidence),
`docs/paper/statistical-treatment.md` (D19 — which test, which CI, how censored columns are
reported; `analysis/common.py::compare_groups` / `compare_censored_groups` are the only
sanctioned entry points),
`data/DATA_DICTIONARY.md` (schema — note its column list has drifted; `DATASET_HEADERS` in
`experiments/runner.py` is authoritative at **36 columns**).
