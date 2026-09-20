# Decision Log

Decisions that determine the shape of the paper, with the numbers that produced them. Entries
are append-only. **A decision recorded here is not reopened** — re-litigating scope mid-sprint is
the failure mode that costs the week, and it is the one risk the plan rates as certain.

Format: what was decided, the numbers, what was rejected, and what would have to be true to
revisit it.

---

## D-001 · $\tau_{\text{leg}}$ is reported as a curve, not chosen as a value

**Date:** Day 1 (Mon 10 Aug 2026) · **Decided by:** Soham · **Status:** final

**Decision.** The paper reports $B_{\text{real}}$ as a function of $\tau_{\text{leg}}$ over
$[0.05, 0.95]$ (Figure 7). No single threshold is adopted as *the* containment metric.

**Numbers** (`analysis/out/tau_sweep.json`, 80 runs / 26 configs):

- Only one service ever fires across all 320 leg observations: order-service, max rate
  **0.4867**.
- The shipped $\tau = 0.50$ sits above the entire support, so `real_blast_radius` is
  identically 0.0 in all 80 rows — constant by construction.
- The metric has resolution only on $\tau \in [0.25, 0.45]$: saturated at 0.25 below it,
  identically zero above it.
- **10 of 10 live threshold pairs rank the 26 configurations differently**, minimum Kendall's
  $\tau_b = 0.238$. Comparisons against $\tau = 0.50$ are undefined — it ranks everything at
  zero.

**Rejected:** re-pinning $\tau$ to a value inside the informative band. It would work, and it
would be a researcher degree of freedom exercised after seeing the data. The curve is both more
honest and more useful.

**Consequence:** H4 is supported on Day 1 with zero new experiments, against a plan that
scheduled it for Day 5 and expected it to be degenerate on LINEAR.

**Revisit if:** the FAN_OUT sweep produces legs on more than one service, which changes the
support and may move the informative band.

**Update (2026-09-06):** the FAN_OUT sweep has run (354 rows, merged into `data/master_dataset.csv`
via PR #37) and `analysis/tau_sweep.py` was re-run against the full 704-row file. The revisit
condition fired: **inventory-service now fires too**, not just order-service (2056 leg
observations, up from 320; max nonzero rate still 0.5). The τ=0.50 dead-zone finding is
unchanged and now far better-powered — `real_blast_radius` is still identically 0 for every τ
≥ 0.50 across all 704 rows. H4's rank-disagreement claim technically still holds (36/36 pairs
below τ_Kendall=1.0) but the magnitude changed a lot and should be reported accurately, not as
"stronger": **minimum pairwise Kendall's τ is now 0.891** (was 0.238 on the 80-row archive) —
rankings across different τ choices now agree much *more*, not less. One important caveat,
detailed in D15's update below: inventory-service's new nonzero readings are 100% concentrated
in `fault_type=CRASH` rows, always exactly 0.5000 with zero variance — this is the D17
leg-blending bug appearing on a second service via the shared `sharedDbCB` dependency, not
genuine multi-service cascading. Re-derive this table again once D17's fix lands and CRASH is
re-collected; the qualitative dead-zone/H4 findings are expected to survive, but exact numbers
will shift.

**Update (2026-09-18, the LATENCY-only re-derivation — not the revisit condition above, which
still needs FANOUT CRASH).** `analysis/tau_sweep.py`'s own output (`analysis/out/tau_sweep.json`
and `tau_sweep.csv`) was still the 2026-09-06, pre-CRASH-strip, 704-row file — stale since the
same day it was written, never re-run since. Re-run against `"current"` as it exists today
(360 rows, 100% `fault_type=LATENCY`, 198 LINEAR / 162 FANOUT — the 2026-09-06 strip's 324 plus
the D13 top-up's 36, 2026-09-15):

- **Only order-service ever fires** (`services_that_ever_fire: ["order-service"]`) — back to
  Day 1's single-leg regime, not the two-leg regime the 2026-09-06 update above described.
  Expected, not a regression: inventory-service's nonzero readings were 100% CRASH rows (the
  D17-leg-blending artifact this same update flagged), and CRASH rows are entirely absent from
  `current` right now (stripped 2026-09-06, LINEAR re-collection sits unmerged in PR #47,
  FANOUT re-collection never happened).
- **108 configs, 360 runs.** 153 of 153 non-degenerate threshold pairs still rank differently
  (H4's core claim unchanged in direction). **Minimum pairwise Kendall's τ is now 0.0189** —
  down from 0.891 on the 704-row CRASH+LATENCY file, and below even the original 80-row
  archive's 0.238. **Report this as what it is: the LATENCY-only, single-leg floor, not a
  contradiction of the 0.891 figure** — that number needed CRASH's second leg to exist at all,
  and this dataset doesn't have one right now. The three figures (0.238 → 0.891 → 0.0189) are
  three different datasets answering the same question, not a trend.
- The τ=0.50 dead-zone finding is unchanged in kind: `informative_tau_range` is now
  `[0.05, 0.9]` (max observed leg rate 0.9044, up from 0.5 — this session's LINEAR/FANOUT LATENCY
  sweep reaches higher failure rates than the archives this entry originally cited).

**Still blocked, not answered here:** the *combined* CRASH+LATENCY re-derivation this entry's
2026-09-06 update asked for needs FANOUT CRASH collected and merged — untouched by this update.
`STATUS.md`'s embargo on quoting a combined-dataset number stands.

---

## D-002 · Contaminated rows are marked, never dropped

**Date:** Day 1 · **Decided by:** Soham · **Status:** final

**Decision.** `excluded_reason` is added to the dataset schema (column 20). Rows failing an
audit signature are marked with a machine-readable code and retained. `analysis/quarantine.py`
is the only writer; `runner.py` always writes it empty.

**Numbers** (`analysis/out/quarantine.json`): 1 of 80 current rows, 2 of 162 v2 rows, 0 of 92 v3
rows. Codes: `STATE_LEAK_EARLY_OPEN`, `STATE_LEAK_BLAST`, `RECOVERY_TIMEOUT_HANG`.

**Rejected:** deleting the rows. A silently dropped row is indistinguishable from one never
collected, and the difference is exactly what a reviewer cloning the artifact will check.

**Also rejected:** quarantining v3 row-by-row on its 95.7% impossible-blast rate. That is one
subject reading degraded in every run — a dead *column*, not 88 bad rows. Marking the column and
keeping 92 usable $t_{\text{open}}$ values is the correct trade.

---

## D-003 · The matched-horizon comparison is tested on a diagonal band, and the paper says so

**Date:** Day 2 (Tue 11 Aug 2026) · **Decided by:** Soham · **Status:** final

**Decision.** The matched-horizon arm derives the partner window in **both** directions —
$T = W/\lambda$ and $W = \lambda T$ — and infeasible cells are emitted with `feasible = 0` and a
stated reason rather than dropped.

**Numbers** (`data/canary_matrix.csv`): matching in the plan's single direction
($T = W/\lambda$) yields **3 usable configurations out of 12**. $T$ falls below Resilience4j's
one-second resolution for every $\lambda > 5$ with $W \in \{5, 10, 20\}$. Adding the reverse
direction recovers 12 usable configurations spanning $H = 5$ to $H = 800$, bounded above by the
1000-call `slidingWindowSize` ceiling ($\lambda = 320$, $T = 20$ would need $W = 6400$).

**Consequence:** H1 is testable on a diagonal band of the $(\lambda, H)$ plane, not on the full
plane. Section VII states this as a design limit rather than letting a reviewer find the gap.

---

## D-004 · Day-2 Gate — which paper gets written

**Date:** Day 2 (Tue 11 Aug 2026); closed out retroactively 2026-09-08 (Soham) once the
canary matrix run existed to read · **Decided by:** Soham + Jay, jointly · **Status:** final — **Paper B**

### Gate table

| Canary outcome | Paper | Days 3–7 pivot |
|---|---|---|
| Crossover $\lambda^*$ visible **and** variance gap significant at matched $H$ | **A — "The Window Is an Estimator."** H1/H2 core, H3/H5 supporting | Full sweep includes $\lambda$. Target ICPE / IEEE Access |
| Crossover visible, variance gap not significant | **A′** — H2 alone: static window configuration is correct at exactly one traffic level | Same sweep, narrower claim |
| No $\lambda$ effect at all | **B — construct validity.** H3 + H5 + H4 + metric evolution | Drop $\lambda$. Days 3–4 go to FAN_OUT + TREE breadth |

`analysis/canary_readout.py` prints the recommendation directly. Its three branches are verified
against synthetic data (`--self-test`); the gate logic is not decided by hand at 23:00.

**Provenance note on the read.** The canary matrix run (`data/canary_matrix_runs.csv`, codespace,
300/300, 0 aborted, PR pending on `data/canary-matrix-codespace-full`) never persisted an `arm`
column — it isn't in `runner.DATASET_HEADERS`. Read here by joining the run results back onto the
design file `data/canary_matrix.csv` on `(run_index, replicate)` — not `experiment_id`, which the
design file predates the `-M{n_min}` suffix on. That join is a read-time reconstruction for this
entry only; `arm` still isn't persisted by the harness itself, so any future read of this file
needs the same join. 60/120 designed `matched_horizon` rows came back feasible (0 nulls after the
join) — matches D3's stated split.

### Preconditions — checked before reading the gate

- [x] **$\lambda$ fidelity.** Recorded (`lambda_achieved`, `lambda_deviation_flag`) on all 300
      rows. 38 of 300 (12.7%) missed target by >15%, concentrated at $\lambda$=80/320 — see
      numbers below. Not a blocker (D3-documented already: this is the harness's real ceiling
      at high offered load), but H2/H1 are read off `lambda_achieved`, never `lambda_target`.
- [x] **Monotone trip rate.** Flat at 1.00 in every cell for both window types — never falls,
      so no harness-diagnosis flag raised. (Flat-at-ceiling is itself the H2 result, not a
      measurement fault — see below.)
- [x] **`precondition_ok`** true on all 300/300 rows.
- [ ] **Mode-mixing check.** Not reached — H1 never gets past the horizon-overlap check (see
      below), so there is no variance-gap claim to disambiguate as sampling vs. bimodal mixing.

### Filled in

```
Decision:              Paper B — construct validity (H3 + H5 + H4 + metric-evolution narrative)
H2 crossover:          TIME_BASED absent -- trip rate 1.00 [0.80, 1.00] at every
                       lambda in {5, 20, 80, 320}; no lambda low enough in this design
                       to see TIME_BASED fail to trip
                       COUNT_BASED absent -- same, trip rate 1.00 at every lambda (consistent
                       with H2 as stated, which predicts absence here)
H1 at matched H:       NOT TESTABLE. The matched_horizon design (data/canary_matrix.csv, as
                       collected) put COUNT_BASED horizons at {25,50,100,200,400,800} and
                       TIME_BASED at {5,10,20} -- disjoint, zero overlapping H with >=3
                       tripped runs on both sides at any of the 9 horizon values observed.
                       (The generator itself was already fixed for this on main --
                       commit 6b045b4, shared MATCHED_HORIZONS list -- but this run predates
                       a re-generation of data/canary_matrix.csv against the fixed code, so
                       the fix doesn't reach this dataset. Re-running the matched_horizon arm
                       against the regenerated design is what would make H1 testable, per D3.)
Mode-mixing verdict:   not reached (H1 untestable upstream of this check)
phi (false-trip rate): 0.000 [0.000, 0.031] over 120 null-fault runs
lambda fidelity:       38 of 300 runs off target (>15%); worst deviation 35.3%
                       (by lambda_target: 5 and 20 -- 0 off; 80 -- 23 off; 320 -- 15 off)
Signed:                Soham 2026-09-08
```

**Consequence.** Per the gate table, absent crossover closes out Paper A and A′ outright — H2
does not distinguish window types at any sampled $\lambda$, so there's no "estimator" claim to
build a paper around from this arm. **Paper B is confirmed**: H3 (recovery-side leak, D13),
H5 (FAN_OUT leg containment, D15), H4 ($\tau_{\text{leg}}$ curve, D-001), and the metric-evolution
narrative (D17 and its downstream corrections) are the load-bearing chapters, not H1/H2.

**Not reopened on Day 4.** The Day-4 gate decides whether the *data* supports the chosen paper.
It does not reconsider which paper.

**Revisit if:** the matched_horizon arm is re-run against the regenerated `data/canary_matrix.csv`
(post 6b045b4) and H1 becomes testable — a positive H1 result alone does not reopen this gate
(H2's absence already rules out Paper A/A′ on its own), but would add an H1 finding to Paper B's
scope rather than change which paper this is.

---

## D-005 · Run-order seed

**Date:** Day 2 · **Status:** final

`RUN_ORDER_SEED = 20260811`, persisted to every dataset row as `run_order_seed` with position as
`run_index`. Sequential execution of a long sweep on one host confounds treatment with thermal
and memory drift; the seeded shuffle is what lets anyone re-derive the exact order from the
artifact alone.

---

## D8 · Canonical 47-column schema freeze (restructure re-run)

**Date:** 27 Aug 2026 · **Decided by:** Soham · **Status:** final

**Decision.** One canonical 47-column superset schema replaces the four-file schema fork
(`linear_schema.csv`, `fanout_schema.csv`, `master_dataset_schema.csv`,
`occupancy_dataset.csv`). All re-run sweeps — LINEAR + FAN_OUT, LATENCY + CRASH, ρ-boundary
+ timing — append to a single `data/master_dataset.csv` keyed to this header. A mode that
doesn't measure a given column leaves it **blank**, never `0`, never dropped.

**Numbers:** `linear_schema.csv` and `fanout_schema.csv` were already byte-identical (38
cols). The union across all four existing schema files is exactly **47 columns** — verified
programmatically against the file headers, nothing dropped, nothing invented. 9 telemetry
columns folded in from `master`/`occupancy` that linear/fanout lacked: `error_rate`,
`precondition_fail_reason`, `readiness_wait_s`, `cb_state_pre`, `buffered_calls_pre`,
`warmup_requests`, `warmup_duration_s`, `run_order_seed`, `run_index`.
`minimum_number_of_calls` is promoted from implicit (parsed from the `-M{n}` segment of
`experiment_id`) to an **explicit column** — it is the direct input to ρ = λ·T/n_min.
`occupancy_ratio` and `inert` are promoted to first-class columns (were occupancy-file-only
before).

**Rejected:** keeping four separate per-regime files. The restructure discards all existing
data and starts a fresh sweep spanning every regime in one pass — maintaining four diverging
headers through that would reproduce the exact failure already hit once: `log_results`'
stale-header guard silently refusing every write when `occupancy_dataset.csv`'s 36-col
header was pointed at `master_dataset.csv`'s 34-col header (the lost-overnight-run
incident).

**Consequence:** `runner.DATASET_HEADERS` (Jay) must emit exactly these 47 columns, in this
order, before the first re-run sweep launches — the header guard blocks any append that
disagrees, which is what stops a mixed-regime pool. All pre-restructure archived files
(`master_dataset_v1_prefix.csv`, `_v2_latency_5svc.csv`, `_v3_gateway_not_rebuilt.csv`) stay
read-only under their old headers — not touched, not migrated.

**Revisit if:** a future mode needs a column outside this union (e.g. a new fault-magnitude
parameter for the crash-toxicity sweep). Per the dictionary's own rule, any such addition
needs its own decision-log entry in the same commit that adds the column.

---


## D13 · H3's recovery-side negative control is downgraded to untested, pending the
transition sidecar

**Date:** 2026-08-25 (ad hoc D12 investigation, outside the Day 1–5 cadence) · **Decided
by:** Jay · **Status:** re-opened 2026-08-27 — see Update below; real signal found, not yet
confirmed at adequate sample size

**Decision.** H3's §4 leak-audit clearance never actually tested `window_type` as a factor
on $t_{\text{rec}}$ — it tested for breaker state carrying over between replicates, a
different contamination mode. `analysis/window_type_recovery_leak.py` runs the direct test.
H3's negative control on $t_{\text{rec}}$ is downgraded from "cleared" to "untested against
this specific mechanism, pending a re-run that retains `data/cb_transitions.jsonl`."

**Numbers** (`analysis/out/window_type_recovery_leak.json`, 79 rows / current archive; same
shape on `v2_latency_5svc` and `v3_gateway_not_rebuilt`): TIME's median $t_{\text{rec}}$ is
2.06–3.68x COUNT's at every matched $D_w \in \{5,15,30\}$. Decomposed: TIME's $t_{\text{open}}$
anchor runs a flat ~3s later than COUNT's at every $D_w$ (non-buggy — TIME_BASED windows
accumulate over wall-clock seconds), but TIME's excess over $D_w$ **grows** (19.1s → 20.2s →
35.1s) while COUNT's stays flat (~1.5–1.7s) — not explainable by a constant anchor shift
alone. The precise HALF_OPEN→CLOSED metric that would isolate the leak from the anchor shift
could not be computed: `data/cb_transitions.jsonl` does not exist in any archive on disk.

**Rejected:** treating the existing §4 leak-audit clearance as also covering a window_type
main-effect check on $t_{\text{rec}}$ — it doesn't; it never varied window_type as a factor.
**Also rejected:** reporting a leak/no-leak verdict from the coarse ratio alone — the anchor
shift is a real, legitimate, non-buggy confound that the coarse metric cannot separate from
a genuine recovery-side effect.

**Revisit if:** a future `experiments/runner.py` invocation retains `data/cb_transitions.jsonl`
for a sweep spanning both window types at matched $D_w$ — re-run
`analysis/window_type_recovery_leak.py` against it and read the `precise` block's verdict.

---

**Update (2026-08-27).** The revisit condition above is met. Along the way, two harness bugs
were found and fixed that had been silently preventing the precise metric from ever being
computed (see commits `0494dd0`, `cb7f9d7` on `worktree-session-handoff`):

1. `CB_EVENT_BUFFER_SIZE` was 50 — too small once traffic is deliberately sustained through
   the full `waitDurationInOpenState` (by design, so a HALF_OPEN probe fires): every rejected
   call during that period emits its own `NOT_PERMITTED` event into the *same* shared
   per-breaker ring buffer as `STATE_TRANSITION` events, and at $D_w \geq 15$ this reliably
   evicted the original `CLOSED_TO_OPEN` event before collection. Fixed: 50 → 5000.
2. The recovery-polling loop was breaking ~2s after the breaker left OPEN for HALF_OPEN
   (`blast_radius` flips to 0.0 the instant it leaves OPEN, not when it reaches CLOSED — a
   limitation the loop's own comment already documented), then collecting transitions
   immediately — never giving HALF_OPEN's probe calls a chance to resolve either way. Fixed:
   ~4s of additional real traffic + settle time after the loop exits, before collection.

With both fixed, `analysis/window_type_recovery_leak.py` returns
**`LEAK_CONFIRMED_ON_HALF_OPEN_LEG`**: TIME's median precise HALF_OPEN→CLOSED duration is
**8.9x–14.3x** COUNT's, monotonically increasing with $D_w$ (2.15s→19.03s at $D_w$=5;
2.16s→20.87s at $D_w$=15; 2.48s→35.35s at $D_w$=30) — the same shape as the coarse excess
decomposition, now on the metric that actually isolates the HALF_OPEN leg.

**Not yet promoting this to "final confirmed"**: every median above is **n=1 TIME_BASED row
per $D_w$ bucket** (`n_count` 1/3/3) — real, directionally consistent, mechanistically
unexplained (the originally-suspected mechanism is still architecturally ruled out for
Resilience4j 2.2.0, so *something else* is causing this), but too thin to close the question.
**Status stays "re-opened, preliminary" until a modest replicate top-up** (not a full re-sweep
— a handful more `TIME_BASED` runs at each $D_w$) raises `n_time` per bucket above 1.

---

**Update (2026-09-14, top-up + a new problem).** The replicate top-up ran: 36 runs on
`jay-mac` (commit `c59ef95`), `n=6` per $D_w$ bucket both window types — well above the "raise
`n_time` past 1" bar. But it surfaced that the *sample size* was never the real blocker: at
$D_w=30$, **COUNT closed 0 of 6** HALF_OPEN→CLOSED transitions within the observation
window — TIME closed 6/6 at every $D_w$. `analysis/window_type_recovery_leak.py`'s ratio
table computed a median over `.dropna()`ed values per arm, so a bucket with zero non-null
values had nothing to take a median of — the code `continue`d past it, and the $D_w=30$ row
silently disappeared from the table entirely rather than reporting "0/6 recovered." That is
exactly why commit `c59ef95`'s own message says D13 was not marked closed: the tool could not
honestly report what it had found.

**Update (2026-09-15, tool fixed — D19 censoring protocol applied).**
`analysis/window_type_recovery_leak.py` is migrated to D19's `compare_censored_groups` /
`censored_timing_summary` (`analysis/common.py`) — the same protocol `throughput_loss`'s
retirement (D20) and the statistical-treatment doc already mandate for any right-censored
timing DV. Every `wait_duration` level that collected rows on both arms now gets a row, even
when one arm has zero *observed* events; the row reports that arm's recovery **rate** (with a
cluster-bootstrap CI) separately from timing conditional on recovery, and is excluded from the
ratio/consistency verdict rather than forced into one. A regression test
(`self_test_censoring`, run via `--self-test`) reproduces this exact shape and asserts the
$D_w=30$ row survives.

**Corrected numbers**, re-run against the top-up data (`analysis/out/window_type_recovery_leak.json`):

| $D_w$ | COUNT recovered | TIME recovered | median COUNT | median TIME | ratio T/C |
|---|---|---|---|---|---|
| 5  | 6/6 (100%) | 6/6 (100%) | 1.907s | 19.748s | 10.35x |
| 15 | 2/6 (33%)  | 6/6 (100%) | 2.360s | 21.251s | 9.00x |
| 30 | **0/6 (0%)** | 6/6 (100%) | — (never recovered) | 35.576s | **undefined** |

**Verdict, corrected: `LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING`** — not
`LEAK_CONFIRMED_ON_HALF_OPEN_LEG`. This is a downgrade in *label*, not in the strength of the
evidence: COUNT failing to recover at all within the observation window at $D_w=30$ is, if
anything, a **more** extreme version of "TIME is not the slow one, COUNT is" than the finite
ratios at $D_w=5/15$ show — a censored observation means "took at least as long as the window,"
never "showed no effect." But a censored cell cannot be folded into a median-ratio comparison
honestly, which is the whole reason the label changes: the pattern is directionally consistent
everywhere it *can* be measured (10.35x, 9.00x, both well past the 1.15x bar) plus one cell
that couldn't be measured at all in the same direction the other two already point.

**H3's status stays "re-opened, preliminary."** The blocker is no longer sample size (n=6/bucket
is adequate) — it is the **estimator**: closing D13 for real needs a censoring-aware analysis
(Kaplan–Meier or a Cox model on `precise_half_open_to_closed`, right-censored at the
observation-window cap) rather than a median of the rows that happened to finish. That
estimation work is not done as part of this update — the tool now reports the true shape of
the data instead of an artifact of the reporting code masking it, which is the load-bearing
fix `c59ef95` was waiting on. `data/cb_transitions.jsonl` (37 records, force-tracked) is the
input a Kaplan–Meier pass would read.

**Revisit if:** a Kaplan–Meier/Cox estimator is added to `window_type_recovery_leak.py` (or a
new script) for `precise_half_open_to_closed`, or a further top-up extends the observation
window past $D_w=30$'s cap so COUNT's 0/6 stops being censored and starts being a real number.

---

**Update (2026-09-16, the Kaplan–Meier estimator this entry called for, run for real).**
`analysis/half_open_survival.py` (new) — the estimator this entry's own Revisit-if named.
Two extraction bugs were found and fixed before its numbers could be trusted (a legacy
occupancy-mode record polluting the $D_w=15$ bucket; the observation span and censoring
bound both needing to match `window_type_recovery_leak.py`'s own definitions exactly, not an
independently-reinvented one) — see that commit for the full account. $D_w$=5 (fully observed
on both arms) reproduces `window_type_recovery_leak.py`'s numbers almost exactly (10.38× here
vs 10.35× there), confirming the two scripts agree wherever there is nothing for an estimator
choice to disagree about.

**The corrected, full picture — neither of the two possible outcomes this entry anticipated:**

| $D_w$ | COUNT | TIME | ratio | log-rank |
|---|---|---|---|---|
| 5  | 6/6 recovered, median 1.90s | 6/6, median 19.73s | **10.38×** | **p = 0.0005** |
| 15 | 2/6 recovered, **≥12.86s** (true value unresolved) | 6/6, median 21.22s | 1.65× (lower bound) | p = 0.14 (not significant) |
| 30 | 0/6 recovered, **≥12.88s** (true value unresolved) | 6/6, median 35.53s | 2.76× (lower bound) | **undefined** — COUNT has zero events at all, so the test has no discriminating power here, not merely a null result |

**H3 does not close, and does not reverse.** $D_w$=5 — the only bucket with a fully-observed
COUNT arm — shows a real, large, statistically significant effect in the expected direction.
$D_w$=15 and $D_w$=30 are *directionally consistent* with that same pattern (COUNT's lower
bound is smaller than TIME's actual value at both, so a reversal is not supported either) but
are **not independently confirmable**: at $D_w$=15 the test is underpowered by censoring
(4 of 6 COUNT runs never recovered); at $D_w$=30 no valid significance test can even be
constructed, because COUNT recovered zero times across all six replicates.

**A genuine new finding, distinct from H3 itself: the harness's own recovery-observation
window doesn't scale with $D_w$.** `breaker_observer.py::_poll_for_recovery` bounds the
post-fault-clear observation at a flat `wait_duration + 10` seconds — and since
Resilience4j's `OPEN → HALF_OPEN` transition itself consumes almost exactly `wait_duration`
of that budget (it fires purely on elapsed time), only the fixed **~10-second remainder** is
ever available to observe the `HALF_OPEN → CLOSED` leg, *regardless of $D_w$*. Verified
directly against the sidecar: every one of the 26 real closures in the dataset lands inside
that ~10s budget, and the two fully/partially-censored buckets' lower bounds (12.86s, 12.88s)
sit right at its edge. This means COUNT's censoring rate rising with $D_w$ (0/6 → 4/6 → 6/6
recovered, reading $D_w$ 5→15→30) is at least partly an **instrument ceiling**, not
necessarily evidence that COUNT itself recovers more slowly at higher $D_w$ — the measurement
apparatus gives it proportionally less room to show a close as $D_w$ grows, independent of
window_type.

**Consequence for H3's status:** stays "re-opened, preliminary" — but the blocker has moved
again. It is no longer sample size (D13's own prior update already closed that gap, n=6),
and now it is no longer "no estimator" (this update supplies one). The blocker is the
**harness's fixed +10s recovery-observation budget**, which caps how much a censoring-aware
estimator can ever recover at high $D_w$ regardless of replicate count. Closing H3 for real
needs the observation budget itself widened (e.g. `wait_duration`-scaled, not a flat +10s)
and re-collected — not more analysis of the data already in hand.

**Rejected:** reporting this as "H3 confirmed" on the strength of the $D_w$=5 result alone, or
as "H3 refuted / an interaction" on the strength of the lower bounds not exceeding TIME's
values. Neither is what the data supports; both would be an overclaim in one direction or the
other, the exact failure mode this whole analysis chain (D19 → PR #55 → this update) exists to
close off.

**Revisit if:** `breaker_observer.py::_poll_for_recovery`'s deadline is changed to scale with
`wait_duration` (e.g. `2 * wait_duration` or similar) rather than a flat `+ 10`, and the
$D_w$=15/30 cells are re-collected under it — that would be the first design that gives COUNT
a fair chance to show its true recovery time at high $D_w$, censored or not.

---

**Update (2026-09-16, closed — D21's fix landed, re-collected, H3 confirmed).** The blocker
named above was not `_poll_for_recovery`'s deadline (that had 17–27s of slack even at
$D_w$=30, verified against real `fault_cleared_at` values — see D21). It was
`_drive_half_open_probes`: called unconditionally after `_poll_for_recovery` exits, running a
**fixed ~4.1 seconds** of driven traffic regardless of `wait_duration` or whether a real
transition had happened yet. Every one of the real censored COUNT records showed exactly 2
logged events (`CLOSED_TO_OPEN`, `OPEN_TO_HALF_OPEN`) and then silence — the shape of "this
window ended before anything else could happen," not "this genuinely never resolves."

Rewritten as poll-until-transition with a `3*wait_duration+60s` hard ceiling (D21, PR #57),
live-verified against the mesh before merging. Re-collected the same 18 LINEAR/LATENCY
configs × 2 replicates × 2 window types = 36 runs under the fixed harness
(`data/master_dataset_d21_recollect.csv`, registered as
`d21_poll_until_transition_verification` in `analysis/common.py` — standalone, not merged
into `current`; every `(experiment_id, replicate)` key here collides with rows already in
`current` from the main sweep, and the coarse `time_to_recover` metric was never actually
censored there in the first place, so there is nothing to fold in).

**Result: `half_open_probe_timed_out=False` on 36 of 36 runs.** Zero censoring anywhere, at
any $D_w$, on either arm. `data/cb_transitions.jsonl` is a running, never-purged log (D21's own
convention: mark/archive, never delete), so the pre-fix records from the original D13 top-up
still sit in it alongside these — `analysis/half_open_survival.py` gained a `--since` filter
for exactly this situation, and `--since 2026-09-16` (the committed
`analysis/out/half_open_survival_since_2026-09-16.json`) isolates just the post-fix slice:

| $D_w$ | COUNT | TIME | ratio | log-rank |
|---|---|---|---|---|
| 5  | 6/6, median 2.04s | 6/6, median 19.34s | **9.49×** | **p = 0.0005** |
| 15 | 6/6, median 9.83s | 6/6, median 21.27s | **2.16×** | **p = 0.0005** |
| 30 | 6/6, median 14.99s | 6/6, median 35.90s | **2.40×** | **p = 0.0005** |

**Verdict: `LEAK_CONFIRMED_ON_HALF_OPEN_LEG`.** H3 closes. TIME is slower than COUNT at every
$D_w$, significantly, with a complete (uncensored) sample on both arms.

**The corrected shape is genuinely new information, not a recovery of the original guess.**
The pre-fix censored data could only see $D_w$=5 cleanly; at $D_w$=15/30 it had no real COUNT
numbers to compare against at all. The true picture — now that COUNT's actual recovery times
are known instead of unresolved lower bounds — is that the ratio **shrinks** with $D_w$
(9.49× → 2.16× → 2.40×), not flat and not growing. COUNT's own recovery time scales with
$D_w$ almost exactly as expected (2.04/9.83/14.99s, tracking a modest constant above zero) —
what changes is that TIME's *relative* slowdown is largest at the shortest wait and shrinks
(then holds roughly steady) as $D_w$ grows. This is worth stating as the finding, not "TIME is
~9x slower" flatly, which the D_w=5-only view before this fix would have overclaimed as
constant across the range.

**One data-quality note, unrelated to the fix.** 2 of the 36 runs' *coarse* `time_to_recover`
(the wall-clock `_poll_for_recovery` duration, a separate metric from
`precise_half_open_to_closed` above) came back at 704.6s and 2657.1s — both `run_timestamp`s
hours apart from the rest of the sweep, consistent with a real-world system-suspend event
(the collecting laptop's lid closing) pausing the poll loop mid-wait; Python's wall clock
cannot distinguish "paused by the OS" from "actively elapsed." Caught automatically by
`analysis/quarantine.py`'s existing `RECOVERY_TIMEOUT_HANG` rule (`RECOVERY_CAP_S=120.0`,
already in the codebase, no new detection logic needed) once run against the new dataset.
Their `half_open_probe_timed_out` is still correctly `False` — the sleep hit
`_poll_for_recovery`'s loop specifically, not `_drive_half_open_probes`' separate, much
shorter poll-until-transition window that runs immediately after it. Neither row touches the
precise-metric result above, which is derived from real transition timestamps, not a live
poll duration, and is immune to this artifact by construction.

**Rejected:** merging the 36 new CSV rows into `current`. They use fresh replicates 1–2 for
experiment_ids that already carry replicates 1–5 in `current` (main sweep + the D13 top-up,
PR #54) — appending would create duplicate `(experiment_id, replicate)` keys. Not needed
regardless: `current`'s own coarse `time_to_recover` was independently confirmed to have
0/360 nulls (never actually censored, see this entry's earlier close-out of that separate
worry), so there is no number in `current` this re-collection would have corrected. The
sidecar (`data/cb_transitions.jsonl`) already carries everything the precise-metric verdict
above needed.

**Revisit if:** the mechanism behind TIME_BASED's HALF_OPEN leg being slower than
COUNT_BASED's — real, confirmed, but still unexplained — becomes tractable to investigate
directly (e.g. instrumenting the actual probe-call latencies during HALF_OPEN, not just the
transition timestamps either side of it).

**Update (2026-09-17, the revisit condition above is met — HALF_OPEN's gate is identified,
and it is not the mechanism that would have tied H3 to H2b).** Two things, done in order:

**Step 1 (free, no runs).** Regressed `precise_half_open_to_closed` on `window_size`, split by
`window_type`, using `analysis/half_open_survival.py`'s existing `extract_observations()`
against the post-D21-fix slice of `data/cb_transitions.jsonl` (`fault_injected_at >=
2026-09-16`; 36 observations, zero censoring). Found and excluded 2 further records
(`TIME-W20-D5-rep2`: 700.4s, `TIME-W20-D15-rep1`: 1703.4s) that exceed
`half_open_probe_deadline_s(wait_duration)` and are therefore physically impossible — the
same Mac-lid-sleep artifact this entry already documented for the *coarse* `time_to_recover`
column, but `half_open_survival.py` has no equivalent sanity ceiling on the *precise* metric
today (flagged as a real gap here; fixed the same day, see the correction appended below this
entry). With those
excluded (2 replicates per fully-crossed `(window_type, window_size, wait_duration)` cell —
descriptive, not a powered regression): **TIME_BASED's recovery duration increases with
`window_size`** at $D_w$=5 (19.3→19.3→28.7s) and $D_w$=15 (20.9→30.5→39.6s), flattening at
$D_w$=30. **COUNT_BASED shows no such relationship** at $D_w$=5/15 (flat), with an unexplained
increase at $D_w$=30 (10.0→15.1→25.3s, n=2, not over-interpreted). Suggestive of TIME_BASED's
recovery scaling with real wall-clock window-fill time; not mechanistic on its own.

**Step 2 (live discriminator, decisive).** Jay's proposal: if HALF_OPEN exit gates on
`minimumNumberOfCalls` (the javadoc's literal claim) rather than
`permittedNumberOfCallsInHalfOpenState` (this repo's §IV-A assumption), then a TIME_BASED
config with `permittedNumberOfCallsInHalfOpenState=3` fixed and `minimumNumberOfCalls` raised
from 3 (baseline) to 30 (discriminator) should recover ~10× slower — or, since HALF_OPEN only
*admits* `permittedNumberOfCallsInHalfOpenState` calls per episode (rest rejected, not
recorded), should never recover at all, running every replicate to PR #57's hard ceiling
(pre-registered as confirmation of n_min-governs, not a failed run, before executing).
6 replicates each, live mesh, `--mode full`/`topology=linear`/`fault=latency`, everything else
at canonical values (`failureRateThreshold=50, slidingWindowSize=10, waitDurationInOpenState=15,
targetRps=10`), same disposable `order-service` `CircuitBreaker`-event-trace diagnostic used to
settle D18 (worktree-only, never merged).

**Result: no difference.** Baseline (n_min=3): 6/6 recovered, `precise_half_open_to_closed`
19.75–20.20s (tight). Discriminator (n_min=30): 6/6 recovered, 19.65–20.13s — statistically
indistinguishable from baseline, not ~10× slower, not censored. The live `CircuitBreaker`
event trace settles *why*, unambiguously: every HALF_OPEN episode in both arms admits exactly
`permittedNumberOfCallsInHalfOpenState` (3) calls — every call beyond the 3rd is logged
`NOT_PERMITTED` immediately, including mid-episode before the 3rd completes — and evaluates
the instant all 3 finish (`bufferedCalls=3` at the transition event, both arms, both the
CLOSED→OPEN bounce and the eventual →CLOSED). `minimumNumberOfCalls` (3 vs 30) never appears
anywhere in this trace; the two arms' event logs are behaviorally identical apart from the
config value neither ever used.

**Conclusion: HALF_OPEN→CLOSED is governed by `permittedNumberOfCallsInHalfOpenState`, not
`minimumNumberOfCalls`.** The javadoc's literal claim ("HALF_OPEN persists until
`minimumNumberOfCalls` completes") does not match Resilience4j 2.2.0's observed runtime
behavior for this repo's breaker configuration — §IV-A's original assumption was correct, now
confirmed by direct per-call evidence rather than an unstated assumption. **This also means
H2b and H3 do *not* share a root cause** — D18's n_min-effective-clamping mechanism (confirmed
live, PR #59) governs the CLOSED-side evaluation gate; HALF_OPEN's exit gate is a completely
separate, already-correctly-assumed mechanism. The hoped-for unifying claim doesn't hold; what
does hold, now with call-level evidence instead of an inference, is more useful than the
un-investigated status quo. **TIME_BASED's HALF_OPEN leg being slower than COUNT_BASED's
remains a confirmed effect with an unidentified mechanism** — Step 1's window_size trend is
still the best lead, but window_size itself doesn't appear in `permittedNumberOfCallsInHalfOpenState`'s
admission logic either, so it isn't yet an explanation, only a correlate.

**Update (2026-09-17, correction — the "immune to this artifact by construction" claim above
was wrong, and the 36/36 table needs its p-values fixed).** This entry's earlier
data-quality-note paragraph claimed the precise-metric result was "immune to this artifact by
construction" because it's "derived from real transition timestamps, not a live poll
duration." That reasoning doesn't hold: 2 *precise*-metric records (`LIN-LAT-TIM-T50-W20-D5`
rep2, `LIN-LAT-TIM-T50-W20-D15` rep1) are themselves derived from real transition timestamps
that were wall-clock-corrupted by the same host-sleep event class — real transition
timestamps are not immune to a stalled wall clock, they just record whatever it reads. Both
records: `duration_s` of 700.4s/1703.4s, exceeding `half_open_probe_deadline_s(wait_duration)`
(75.0s/105.0s) — physically impossible for a genuinely-recovered run — while
`half_open_probe_timed_out=False` on both (clean completions per the harness's own
instrumentation; the corruption is purely a wall-clock artifact, not a harness failure).

Fixed 2026-09-17: `analysis/half_open_survival.py::extract_observations()` now excludes any
recovered duration exceeding `half_open_probe_deadline_s(wait_duration)`, flagged with a WARN
(not silent), and `analysis/out/half_open_survival_since_2026-09-16.json` was regenerated.
**Corrected table** (n=34, not 36 — 2 excluded):

| $D_w$ | COUNT | TIME | ratio | log-rank |
|---|---|---|---|---|
| 5  | 6/6, median 2.04s | 5/5, median 19.34s | **9.49×** | **p = 0.0014** |
| 15 | 6/6, median 9.83s | 5/5, median 21.27s | **2.16×** | **p = 0.0014** |
| 30 | 6/6, median 14.99s | 6/6, median 35.90s | **2.40×** | **p = 0.0005** |

**Medians and ratios are byte-identical to the original (uncorrected) table** — both excluded
values happened to be the maximum in their 6-record cell, and KM's median (the 3rd order
statistic of 6 fully-observed points) is unaffected by removing the 6th. Only the printed
p-values at $D_w$=5/15 were wrong (`0.0005` → `0.0014`, n drops 6→5 on the TIME arm at each);
$D_w$=30 is untouched (neither corrupted record has `wait_duration=30`). Still ≪0.05
everywhere — the verdict `LEAK_CONFIRMED_ON_HALF_OPEN_LEG` and every substantive claim in this
entry are unaffected. This is a printed-number correction, not a finding reversal.

**Methods note for §IV-E: a recurring host-sleep hazard, now 4 instances.** Two on the coarse
`time_to_recover` (704.6s, 2657.1s — caught by `quarantine.py`'s existing `RECOVERY_TIMEOUT_HANG`
rule, `RECOVERY_CAP_S=120.0`, no new logic needed). Two on the precise `precise_half_open_to_closed`
metric (700.4s, 1703.4s — the pair above, caught only after this fix). Same root cause each
time: a laptop-class collection host's wall clock stalls mid-poll (lid closing, OS suspend),
and Python's `time.time()` cannot distinguish "paused by the OS" from "actively elapsed." Worth
stating in the paper's methods section as a general hazard of laptop-class collection hosts,
caught in every instance by an automated ceiling/quarantine rule rather than by inspection —
the pattern that caught instances 1–2 is exactly the pattern that should have existed for
3–4 from the start, and now does.

---

## D14 · `machine_id` is added to the canonical schema, before `excluded_reason`

**Date:** 27 Aug 2026 · **Status:** final

**Decision.** `machine_id` is added to the canonical schema as a nullable string: a free-form
label for the machine or Codespace that produced the row (e.g. `codespace-abc123`). Blank —
never `0`, never a sentinel — when the harness did not record one, per D8's blank rule. It is
provenance, never a feature: `preprocessing.py`'s `FEATURE_COLUMNS` is an explicit allow-list,
so an unlisted column cannot reach a model. Note it is **not yet** added to that module's
`PROVENANCE_COLUMNS` either — today it simply rides along unreferenced, which is safe but
means `machine_id` is not currently loaded for the D6 grouping that motivates it.

**Update (2026-09-14).** The `PROVENANCE_COLUMNS` gap above is closed — commit `2b3095d`
("fix(ml): D14 -- add machine_id to PROVENANCE_COLUMNS") landed on `main`, so `machine_id`
is now loaded and available for the D6 grouping. The paragraph above is kept as written
because it records why the column was safe to add before that wiring existed.

**Why:** D6's cross-machine calibration compares runs collected on different hosts. Splitting a
sweep across machines confounds host with treatment, and nothing in the existing 47 columns
recovers which host wrote a given row after the fact — `environment` only distinguishes
`LOCAL` from `AWS`, not one Codespace from another. Without this column the calibration is
not computable from the artifact alone.

**Position:** immediately **before** `excluded_reason`, making it column 47 of 48. D8 keeps
`excluded_reason` last on purpose — it is assigned post-hoc by `analysis/quarantine.py`, so a
column appended after it would be shifted by a re-quarantine. Every header now ends with
`excluded_reason`: `runner.DATASET_HEADERS` and both derived headers splice their extra
columns in before it via `_with_extra_columns()`. That also corrects a pre-existing case of the
same fault — `injected_toxicity` (sweep mode) and `occupancy_ratio`/`inert` (occupancy mode)
were previously appended *after* `excluded_reason`.

**Rejected:** appending `machine_id` last, which is where it first landed — simpler, but it
breaks the D8 invariant this entry exists to protect. **Also rejected:** making it non-nullable
(rows already collected have no host to attribute, and back-filling a guess would be fabrication).

**Consequence:** the canonical schema goes 47 → 48 columns. No row-writing logic changed:
`log_results` builds a dict and writes through `resumable_runner.append_row`'s
`DictWriter(restval="", extrasaction="ignore")`, so a row that omits `machine_id` writes it
blank. The already-collected `data/master_dataset.csv` (20 columns on disk, 80 rows) will now
fail `load_completed()`'s header guard loudly, as designed — the next sweep starts a fresh file
rather than padding historical rows.

**Revisit if:** every run lands on one host again and the cross-machine comparison D6 needs is
retired — the column stays in the schema regardless (removing it would re-fork the header), but
it can stop being populated.

**Update (pre-sweep-ready reconciliation, 2026-08-27).** D16's instrumentation
(`MACHINE_ID = os.environ.get("MACHINE_ID", socket.gethostname())`, auto-captured -- no
flag to remember) now actually populates this column at the position this entry specifies,
closing the gap flagged above ("no row-writing logic changed... a row that omits machine_id
writes it blank"). Rows no longer omit it. `PROVENANCE_COLUMNS` still does not list it --
that gap stands as stated.

---

## D15 · $B$ (blast_radius, quartized) is retired; `order_leg` is the reported containment signal

> Renumbered from this branch's original D-007 during the pre-sweep-ready reconciliation
> (2026-08-27) — main had already independently renumbered the H3/D12 negative-control
> collision to D13 and reserved D14 for the machine_id schema addition, so this (and the
> cross-machine decision after it) continue that sequence rather than re-litigating it.

**Date:** 2026-08-26 (ad hoc D3 investigation, outside the Day 1–5 cadence) · **Decided
by:** Jay · **Status:** final

**Decision.** The quartized containment metric — legacy `blast_radius` (CB-state) and
`real_blast_radius` at any pinned $\tau_{\text{leg}}$ — is retired as a reported outcome. It
is not fixed (no threshold is re-pinned) and not replaced by a new binarized definition; it
is dropped to §7 threats-to-validity with an honest paragraph on why. `order_leg` — the raw,
continuous `leg_failure_rates["order-service"]` value, the one leg that ever fires on the
data collected so far — becomes the reported containment DV (hypotheses.md §5.4, §6). The
legacy CB-state `blast_radius` column itself needs no further code fix: it has been
structurally correct since the gateway-isolation change (§7); it stays in the schema for
reference but is cited nowhere as evidence.

**Numbers** (`analysis/out/order_leg_containment.json`, `current` archive, 79 rows): 32
distinct `order_leg` values (vs. 2 for the quartized metric on the same rows); COUNT_BASED
means monotonic in `window_size` (0.2798 / 0.3330 / 0.4160 at $W$ = 5/10/20, pooled 95% CI
[0.293, 0.355]); TIME_BASED tightly banded (0.4688 / 0.4665 / 0.4708, pooled 95% CI [0.461,
0.476]); clean separation with no overlap — COUNT_BASED max 0.4167 < TIME_BASED min 0.4500,
Cliff's $\delta = -1.0$ (large, $n_a$=41, $n_b$=38).

**Rejected:** re-pinning $\tau_{\text{leg}}$ inside D-001's informative band ($\tau \in
[0.25, 0.45]$). It would restore some resolution and rank configurations non-degenerately,
but keeps a researcher-chosen threshold that `order_leg` does not need at all — the
continuous value already separates window_type with zero overlap and moves monotonically
with a swept parameter.

**Consequence — the tension this decision surfaces.** Isolating the gateway (necessary to
kill the gateway-CB confound) also removed the only propagation path a chain topology can
expose: §5.3 shows exactly one leg (order-service) ever fires on LINEAR under LATENCY,
structurally, not by calibration accident. Cascade (more than one leg degraded at once) is
therefore unobservable on LINEAR-under-LATENCY by construction. **(2026-09-06: the "zero
FAN_OUT rows exist" claim that used to follow this sentence is now false — see Update below.
`--topology fanout` was implemented and has since been swept; the sweep's data just sat
unanalyzed for a few days.)**

**Revisit if:** a FAN_OUT sweep is run. Re-derive the same table — check whether a second
leg firing changes `order_leg`'s clean separation or monotonicity, and whether the
quartized metric becomes informative again now that more than two node-sets are reachable
(in which case this decision's "retire" call should be revisited, not assumed to still
hold).

**Update (2026-09-06) — the FAN_OUT sweep ran, H5 tested for real, and one more D17 connection
found.** 354 FAN_OUT rows merged into `data/master_dataset.csv` via PR #37 (2026-09-03);
`analysis/order_leg_containment.py` and a direct multi-leg check were re-run against the full
704-row file.

*The "retire" call itself stands — reaffirmed, not just assumed.* `order_leg` still has real
resolution (132 distinct values on 704 rows) that the quartized metric never had.

*But the "clean separation, no overlap, δ=-1.0" sub-claim does not survive on the combined
dataset* — and the reason is not FAN_OUT, it's `fault_type=CRASH`:

| fault_type | window_type | n | mean | min | max |
|---|---|---|---|---|---|
| CRASH | COUNT_BASED | 188 | 0.5000 | 0.5000 | 0.5000 |
| CRASH | TIME_BASED | 192 | 0.5000 | 0.5000 | 0.5000 |
| LATENCY | COUNT_BASED | 162 | 0.1201 | 0.0375 | 0.2250 |
| LATENCY | TIME_BASED | 162 | 0.3952 | 0.2686 | 0.4622 |

Every one of 380 CRASH rows reads `order_leg=0.5000` exactly, zero variance, both window
types — that is not real system behavior, it is **the same D17 leg-blending bug**
(`_get_cb_metric_count()` averaging two circuit breakers per service instead of taking the
max), this time via the `sharedDbCB` dependency order-service and inventory-service share:
CRASH fully fails whichever breaker it actually hits, the untouched sibling reads 0%, average
= exactly 50%. This is also why inventory-service now appears in `services_that_ever_fire`
(D-001's update above) — checked directly: inventory-service's 380 nonzero rows are the exact
380 CRASH rows, 1:1, independent of topology (188 LINEAR + 192 FANOUT). Not genuine
multi-service cascading; the same bug on a second service.

**LATENCY-only preserves the clean separation**: COUNT_BASED max 0.2250 < TIME_BASED min
0.2686, no overlap — the qualitative D15 claim holds. The exact magnitudes shifted a lot from
the original 79-row archive (COUNT mean was 0.28–0.42, now 0.1201) — plausibly from harness
fixes landed since (load-concurrency, precondition-reset), not a new bug, but re-quote from
current data, not the stale archive, going forward.

**H5, tested for real, is NOT supported** (this closes H5's "needs the FAN_OUT contrast" open
item from hypotheses.md, with a negative result): under LATENCY — the fault type not
contaminated by D17's bug — both LINEAR and FAN_OUT show `Var(B)=0`, exactly one leg
(order-service) firing in all 162+162 rows. FAN_OUT's parallel structure does not, as
currently injected, create observable multi-leg propagation. This isn't an artifact; it's a
real property of the current fault-injection design (LATENCY targets one edge regardless of
how many parallel downstream paths the topology offers).

**Action before re-quoting the combined-dataset table anywhere:** land D17's fix
(`fix/d17-leg-metric-blend`, already built, unmerged) and re-collect CRASH rows. Expect
order-service's and inventory-service's CRASH-row values to jump toward the true per-breaker
rate once the max-of-breakers fix is in, likely resolving (or reshaping, not necessarily
restoring) the separation on the combined dataset.

**Update (2026-09-18, LATENCY-only re-derivation — the "clean separation" sub-claim above no
longer holds, corrected here rather than left stale).** `analysis/order_leg_containment.json`
was still the 2026-09-06, pre-strip, 704-row output — stale the same day it was written. Re-run
against `"current"` as it exists today (360 rows, 100% LATENCY, 198 LINEAR / 162 FANOUT — the
strip's 324 plus the D13 top-up's 36 replicates, 2026-09-15):

| window_type | window_size | n | mean `order_leg` |
|---|---|---|---|
| COUNT_BASED | 5 | 60 | 0.1150 |
| COUNT_BASED | 10 | 60 | 0.0881 |
| COUNT_BASED | 20 | 60 | 0.1958 |
| TIME_BASED | 5 | 60 | 0.4668 |
| TIME_BASED | 10 | 60 | 0.4357 |
| TIME_BASED | 20 | 60 | 0.4005 |

**The "clean separation, no overlap" claim (COUNT max 0.2250 < TIME min 0.2686) does not
survive the D13 top-up.** COUNT_BASED's max on the current file is **0.3667** — some of the 36
new rows pushed a `window_size=20` cell higher than before — which now overlaps TIME_BASED's
min of 0.2686. This is not a reversal of D15's core claim: the pooled 95% CI on the mean is
[0.116, 0.150] for COUNT vs [0.409, 0.460] for TIME (no overlap at the distribution level), and
Cliff's $\delta$ = **-0.987** ("large", $n_a$=180, $n_b$=180) — barely moved from -1.0. **What
changes is the specific sentence that's safe to write**: "clean separation, zero overlap" is no
longer literally true and should not be quoted; "COUNT and TIME are non-overlapping at the CI
level with a large, near-maximal Cliff's δ" is the accurate replacement. `STATUS.md` updated to
match. The combined-dataset embargo two paragraphs up is untouched by this — still blocked on
FANOUT CRASH.

---

## D16 · Cross-machine confounding — calibrate before splitting the topology sweep across boxes

> Renumbered from this branch's original D-008 alongside D15 above. The `machine_id`
> instrumentation this decision calls for is now formalized in D14's exact schema position
> and `_with_extra_columns()` fix — this entry's calibration protocol and interim
> no-cross-topology-timing-claim rule stand independently of that schema detail.

**Date:** 2026-08-26 (ad hoc D6 investigation, outside the Day 1–5 cadence), calibration
run and read out 2026-09-02/03 · **Decided by:** Jay · **Status:** final —
**MACHINE_EFFECT_NEGLIGIBLE**, option (c) succeeded, cross-topology timing claims may proceed

**Decision.** The plan to run LINEAR on one machine and FAN_OUT on another reintroduces the
exact shared-VM timing confound already refused once for splitting a single sweep across
two boxes — except now machine is perfectly aligned with topology, so a LINEAR-vs-FAN_OUT
contrast on any timing DV cannot separate topology from machine. Confirmed by reading the
schema, not assumed: `environment` (`experiments/runner.py`) is already committed to the
LOCAL-vs-AWS divergence claim and both boxes here would read `LOCAL` — **there was no way to
tell which physical machine produced a row at all**, which is exactly what made this
confound easy to miss.

Two changes, both effective immediately:

1. **Instrumentation.** Every row is now stamped with `machine_id`
   (`socket.gethostname()`, auto-captured — no flag to remember, since forgetting one is
   how this stayed unnoticed). Distinct from `environment`; see `data/DATA_DICTIONARY.md`.
2. **Protocol, option (c) primary, (b) interim default.** Run an identical ~10-run LINEAR
   calibration block on both machines before or alongside the topology split — reuse
   `--mode canary --topology linear --limit 10` (canary already exists for exactly this;
   no new CLI mode needed) — then run `analysis/machine_calibration.py` against the two
   resulting CSVs. **Until that verdict exists, option (b) is the binding default:** no
   claim in this paper compares `time_to_open` or `time_to_recover` across topology. This
   protects the paper now, not only after the ~2–3h calibration is actually run.

**Numbers** (`analysis/out/machine_calibration.json`, real run: soham-local's full
LINEAR+LATENCY collection, n=159, 54 configs, vs. codespace's LINEAR overlap subset, n=18,
6 configs — the codespace-side data comes from the overlap arm run alongside the FAN_OUT
split, not a dedicated `--limit 10` canary block, but it's the same identical-LINEAR-on-both-
machines comparison the protocol calls for):

| DV | soham-local (95% CI) | codespace (95% CI) | Cliff's δ | magnitude |
|---|---|---|---|---|
| `time_to_open` | 5.55s [4.75, 6.43] | 5.12s [3.78, 6.68] | 0.021 | negligible |
| `time_to_recover` | 31.52s [26.47, 36.74] | 25.52s [19.34, 31.73] | 0.023 | negligible |

**VERDICT: `MACHINE_EFFECT_NEGLIGIBLE`** (worst magnitude across both DVs: negligible). The two
machines' confidence intervals overlap heavily on both DVs, and Cliff's delta sits an order of
magnitude below the "small" cutoff on both. Per this decision's own framework: **option (c)
succeeded — cross-topology `time_to_open`/`time_to_recover` claims may proceed without a
per-machine correction**, citing this JSON.

Previously (`--self-test`, synthetic fixtures only): 3/3 checks passed (negligible-offset pair
reads `MACHINE_EFFECT_NEGLIGIBLE`, ~3s-offset pair reads `MACHINE_EFFECT_DETECTED`,
single-machine input reads `SKIPPED_NO_CALIBRATION_DATA` rather than a fabricated verdict) —
that verified the script, not the system; the numbers above are the first real-mesh run.

**Rejected:** (a) same box, sequential — throws away the two machines' wall-clock
parallelism for no stated benefit once (c) costs ~2–3h and the analysis to read it already
exists and is self-tested.

**Scope boundary:** `order_leg` / blast-radius-style ratios (D15) are **not** gated by
this rule — treated as low machine-sensitivity per the original framing, only the timing
DVs are restricted.

**A different DV shows a real machine effect — not gated by this decision, but worth
knowing.** `lambda_achieved` (the offered arrival rate the harness's own load generator
actually delivers) is NOT one of `TIMING_DVS` and this script doesn't test it. A separate,
informal check across the same two machines' full primary+overlap LINEAR/FANOUT data
(n=180/side) found codespace delivering ~99.6% of target rate vs. soham-local's ~91.7% —
Welch's t ≈ 110–120, both directions, both topologies, consistent magnitude. This is a real,
large, reproducible instrument-level difference; it just doesn't propagate into
`time_to_open`/`time_to_recover` the way it might have. It matters directly for D7's
occupancy-ratio work (`ρ` is computed from `lambda_achieved`, not `lambda_target`) and for
`canary_matrix.py`'s `base` arm (H2's trip-rate-vs-λ curve) — both should be collected on one
machine where possible, or explicitly disclose which machine produced which λ cell if split.

**Consequence:** `machine_id`'s addition to `DATASET_HEADERS` header-mismatches the
existing 80-row `data/master_dataset.csv`. That file already needs a fresh restart once a
FAN_OUT/dual-machine sweep begins (LINEAR-only today, per D15's topology-count check) —
this is the same restart happening for one more reason, not new breakage.

**Revisit if:** a third machine joins data collection for LINEAR or FANOUT — this verdict
covers exactly the two machines calibrated above (soham-local, codespace) and does not
automatically extend to a new host without its own calibration block.

---

## D17 · `leg_failure_rates` blends two circuit breakers per service — `real_blast_radius` structurally cannot register a fully-failed single-edge fault

**Date:** 2026-09-04 (ad hoc investigation, surfaced while validating the canary-matrix
executor) · **Decided by:** Jay (finding confirmed); remediation signed off by Soham,
same as D-001's own $\tau_{\text{leg}}$ treatment · **Status:** final — fix merged to `main`
(PR #45, `0c64ca4`) 2026-09-06. CRASH re-collection (LINEAR, post-fix, 162/162 clean) has
started on `data/crash-recollect-linear` (`644c42c`); D-001/D15 stay flagged for
re-derivation until that re-collection is complete on both topologies.

**Decision.** `real_blast_radius` and `leg_failure_rates` for **order-service,
inventory-service, and payment-service**, in every row collected before this fix lands, must
be read as a *diluted* signal, not a literal per-edge severity — see Numbers.
`notification-service` (one breaker, not two) is unaffected. Fix: `compute_leg_failure_rates()`
now reports the **max** of a service's own breakers (option c) rather than an unweighted
average — see the code change on `experiments/runner.py` in this same PR.

**Mechanism.** `runner.py`'s `_get_cb_metric_count()` sums a Resilience4j actuator metric
"across a service's CB instances" (its own docstring) — the query filters only by outcome
kind (`tag=kind:{successful|failed|not_permitted}`), never by which circuit breaker. Every
subject except notification-service owns **two** breakers (a "next hop" plus `sharedDbCB`),
and each of those services' controllers call both downstream dependencies once per request,
unconditionally, regardless of whether the first call succeeded. Since any single injected
fault (this project has never injected more than one at a time) only ever degrades one of a
service's two downstream edges, `compute_leg_failure_rates()`'s per-service reading was an
**unweighted average of one broken breaker and one healthy breaker** — landing near half the
true fault severity by construction, not by measurement.

**Numbers** (`experiments/diagnose_leg_blend.py`, 5 replicates, TIME_BASED/T50/W20/D15/λ=20,
`inventory-service-proxy` latency fault — live mesh, codespace):

| Reading | mean | stdev |
|---|---|---|
| blended `order-service` leg (pre-fix metric) | 0.4010 | 0.0011 |
| `inventoryServiceCB` alone (the faulted edge) | 0.8020 | 0.0021 |
| `sharedDbCB` alone (untouched by this fault) | 0.0000 | 0.0000 |

$0.8020 / 2 = 0.4010$ to 4 decimal places — not "near half," exactly half, with stdev under
0.2% across every replicate. This is the arithmetic signature of the mechanism above, not
sampling noise.

**Independent confirming evidence, found 2026-09-06 (PR #44):** the same signature shows up
on `fault_type=CRASH` rows in `master_dataset.csv` — all 380 of them read `order_leg=0.5000`
exactly, zero variance, both window types, via the shared `sharedDbCB` dependency
order-service and inventory-service both own. CRASH fully fails whichever breaker it hits;
the untouched sibling reads 0%; blended average is exactly 50%. Full detail: D15's 2026-09-06
update below.

**This directly implicates D-001.** D-001's own numbers — "order-service, max rate 0.4867"
across 320 leg observations, cited as the reason $\tau_{\text{leg}}$ must be reported as a
curve rather than a fixed value — were computed through this same unfixed blending path.
D-001 is not being reopened by this entry (its curve-vs-value methodology stands regardless
of what caused the observed ceiling), but its **factual premise** — that order-service's true
leg severity tops out near 0.49 — may itself be an artifact of this bug rather than a
property of the system. A leg experiencing 100% true failure on its faulted edge is
mathematically incapable of reporting above 0.50 blended; D-001's entire informative band
$[0.25, 0.45]$ sits inside the range this bug can produce regardless of real severity.

**Rejected:** (a) report only the faulted edge's rate — needs infrastructure that doesn't
exist (no mapping anywhere from "which Toxiproxy proxy is faulted" to "which calling
service's breaker should reflect that," and the relationship is topology-dependent — under
FANOUT with the default fault target this could leave the leg unobservable entirely). (b)
report both breakers separately — breaks `analysis/common.py::parse_legs()`'s silent
last-wins behavior on duplicate keys, corrupting `tau_sweep.py` and, most directly,
`analysis/order_leg_containment.py` (backs the already-shipped D15). (c), chosen: report the
max — changes zero downstream schema, `parse_legs`/`tau_sweep`/`leak_audit` all keep working
fed a corrected number instead of a diluted one; `notification-service` is byte-identical
before/after, confirming it was never affected.

**Consequence — this is not retroactively recoverable.** Unlike $\tau_{\text{leg}}$ (D-001),
which is a post-hoc sensitivity sweep *because* `leg_failure_rates`' raw value was already
persisted and could be recomputed at any threshold from the existing CSV, this bug is upstream
of what gets persisted at all: `snapshot_cb_calls()` only ever captured the already-blended
per-service sum, never the raw per-breaker counts. **Every row collected before this fix
lands is permanently blended — there is no way to recover the true per-edge rate from
`master_dataset.csv`, any of its `v1`–`v5` archives, or `canary_matrix_runs.csv` after the
fact.** Data collected after this fix lands should get a version boundary (same `vN` archival
treatment `analysis/common.py`'s `DATASETS` registry already uses for `v1_prefix` through
`v5_soham_linear_presweep`) so old and new `leg_failure_rates` values are never silently
pooled as if they meant the same thing.

**Revisit if:** any consumer of `leg_failure_rates` needs to know *which* edge failed rather
than just the worst rate — option (c) loses that information by design. D-001 and D15 should
both be re-examined once real per-edge data exists post-fix; D15's 2026-09-06 update already
starts this for the `CRASH`-row artifact specifically.

---

## D18 · H2b (occupancy ratio) holds for TIME_BASED, is cleanly falsified for COUNT_BASED

**Date:** 2026-09-04/05 · **Decided by:** Jay (D7 live sweep, codespace) · **Status:** final

**Decision.** `experiments/runner.py --mode occupancy` ("D7", task.md) was run live for the
first time this session — 54 configs (36 TIME_BASED: 3$\lambda$×3$T$×4$n_{\min}$, 18
COUNT_BASED control: 2$\lambda$×3$W$×3$n_{\min}$) × 3 replicates, LINEAR topology, LATENCY
fault, on codespace. It tests H2b: whether the occupancy ratio $\rho = H/n_{\min}$ (effective
horizon over `minimumNumberOfCalls`) crossing 1 predicts breaker inertness, generalizing H2's
$\lambda$-only crossover claim to any window type.

**Numbers.** 162/162 runs completed (two sessions: an interrupted first attempt that stopped
cleanly after 16 rows when the codespace's SSH connection dropped — not a code bug, no
corrupted or partial rows — resumed and finished the remaining 146). 0 rows with
`precondition_ok=False`, 0 rows with `lambda_deviation_flag=True` — no exclusions needed
anywhere in the sweep, including at D7's higher $\lambda$ (up to 20 req/s, 2x the standard
sweep's default).

- **TIME_BASED (108 rows): H2b confirmed, clean crossover.** All 30 `inert=True` rows have
  $\rho \le 0.4996$; all 78 tripped rows have $\rho \ge 0.9967$. No overlap, across the full
  sampled range ($\rho$ from 0.1249 to 79.79).
- **COUNT_BASED (54 rows): H2b falsified, completely.** Every COUNT_BASED run tripped —
  `inert=True` appears zero times in this arm, across $\rho \in \{0.025, 0.05, 0.1, 0.2, 0.4,
  1.0, 2.0, 4.0\}$. Configs predicted strongly inert ($\rho = 0.025$, the window at 2.5% of
  its required occupancy) tripped exactly like configs at $\rho = 4.0$.

**Mechanism.** COUNT_BASED's sliding window is a fixed-capacity ring buffer of
`slidingWindowSize` calls. Once the buffer fills, Resilience4j evaluates the failure rate on
every subsequent call regardless of whether `minimumNumberOfCalls` was configured larger than
`slidingWindowSize` — window capacity is the real ceiling on "calls needed before evaluation,"
not `minimumNumberOfCalls` as an independent gate. TIME_BASED has no such fixed buffer (its
window accumulates over wall-clock time), so `minimumNumberOfCalls` genuinely gates evaluation
there, which is exactly why the ratio model works on that arm and not the other.

**Consequence for the paper.** H2b is reported as **window-type-scoped**, not universal: "the
occupancy ratio predicts inertness for TIME_BASED windows; COUNT_BASED windows evaluate as
soon as the window itself fills, independent of the configured minimum" — a stronger, more
precise claim than an unscoped "ratio predicts inertness" would have been, and one this sweep
is now the direct evidence for. Written into `hypotheses.md` §3 (table) and new §3.2.

**Rejected:** treating the COUNT_BASED null result as a design defect to fix and re-run.
There is nothing to fix — it is a true, reproducible property of `CountBasedSlidingWindow`
(zero inertness across an 8-point, 3-replicate-each ratio sweep is not sampling noise), and
it is a more useful result reported as the theory's scope boundary than it would be as a
discarded control arm.

**Revisit if:** a future run finds a COUNT_BASED config that *does* go inert — this would
falsify the "window capacity is the real ceiling" mechanism above and mean something else is
gating evaluation. Not expected: the 8-point ratio sweep already covers $n_{\min}$ both above
and below `slidingWindowSize` and found zero exceptions.

**Update (2026-09-17, mechanism live-verified, not just inferred).** Jay raised a sound
objection to the paragraph above: if `minimumNumberOfCalls=200` were genuinely enforced
against a 5-slot ring buffer, `bufferedCalls` could never reach 200 and the breaker should
never evaluate at all — yet every COUNT_BASED run tripped, down to $\rho=0.025$. Two things
were checked, live, before touching this entry:

1. **No config-level clamp exists.** `git grep` across every `.java`/`.py`/`.yml` file in this
   repo for `minimumNumberOfCalls`/`clamp` found nothing — the value passes from
   `runner.py`'s `write_env_file()` through `infra/.env` to `application.yml`'s
   `${CB_MINIMUM_CALLS:5}` binding unmodified. Confirmed further with a throwaway
   `@EventListener(ApplicationReadyEvent.class)` dump of the live `CircuitBreakerConfig` on
   `order-service` (never merged — added and removed in a disposable worktree): with
   `slidingWindowSize=5, minimumNumberOfCalls=200`, the config object itself reports
   `minimumNumberOfCalls=200`, unchanged. So the paragraph above is imprecise as literally
   written — nothing rewrites the *configured* value.
2. **The effective gate is still `min(minimumNumberOfCalls, slidingWindowSize)` — just applied
   at runtime, not in the config object.** A second throwaway diagnostic (same worktree
   pattern) subscribed to `cb.getEventPublisher()` and logged `bufferedCalls`/`failureRate`/
   `slowCallRate` on every recorded call, then replayed the exact D7 cell this entry's
   $\rho=0.025$ figure comes from (`LIN-LAT-CNT-T50-W5-D15-M200-L20`, COUNT_BASED, window=5,
   $n_{\min}$=200, $\lambda$=20) live against the real mesh via `runner.py --mode occupancy`.
   The call-by-call trace is unambiguous: `failureRate`/`slowCallRate` sit at `-1.0`
   (not-yet-evaluated) for calls 1–4, flip to a real value the instant `bufferedCalls` hits 5
   (the window's capacity — nowhere near 200), and `bufferedCalls` never exceeds 5 for the
   rest of the run. The CLOSED→OPEN transition fires shortly after
   (`slowCallRate=60.0 >= threshold 50.0`, at `bufferedCalls=5`). The replayed run reproduced
   `occupancy_ratio=0.0250, inert=False` — the exact cell this entry already reports.

**Conclusion: the mechanism paragraph above is correct in substance, now confirmed by direct
per-call runtime evidence instead of outcome data plus a plausible story.** The one precision
fix: the effective minimum-calls threshold Resilience4j actually evaluates against for a
`CountBasedSlidingWindow` is computed internally (consistent with `Math.min(configured
minimumNumberOfCalls, slidingWindowSize)`, observed, not read from Resilience4j's own source
in this pass) — it is invisible on the `CircuitBreakerConfig` object itself, which is why a
config dump alone (step 1) could not settle this, and a call-level event trace (step 2) was
needed. Nothing in this project's own source performs the capping; it is Resilience4j's
internal behavior for `COUNT_BASED` windows specifically, which is also why TIME_BASED (H2b's
other arm, no fixed-capacity buffer) is unaffected and continues to test
`minimumNumberOfCalls` as configured. §V-A's explanation and `hypotheses.md` §3.2 need no
correction; citing this update alongside them is sufficient. Both diagnostics were disposable
(added and removed in scratch worktrees; `infra/.env`, `order-service`'s image, and
`data/occupancy_dataset.csv`/`data/cb_transitions.jsonl` were all untouched by the replay,
which wrote to throwaway paths) — nothing here changes runnable code.

*(Separately noticed while wiring the replay, unrelated to H2b: `--only-ids` cannot currently
match any `occupancy`/`canary_matrix` config — the filter in `main()` calls
`make_experiment_id(args.topology, args.fault, c)` without `mode=args.mode`, so the `-M`/`-L`
suffix never gets appended to the computed ID and it can never equal a user-supplied full ID.
Not fixed here — logged so it doesn't need rediscovering.)*

---

## D19 · Statistical treatment defined: Mann-Whitney + Cliff's delta, bootstrap CIs, censoring as rate + conditional timing

**Date:** 2026-09-11 · **Decided by:** roadmap item B5 · **Status:** final (implementation);
one existing script not yet migrated, see below

**Decision.** The paper's default two-group significance test is the **Mann-Whitney U test**,
always reported with **Cliff's delta** as the effect size (`analysis/common.py::compare_groups`)
— not a t-test. Every right-censored timing DV (`time_to_open`, `time_to_recover`) is reported
as **two numbers, always together**: the rate at which the event was observed at all (trip
rate / recovery rate), and the timing distribution *conditional on it having happened* —
never a plain mean of the non-null rows, and never mean-imputed. Both halves are
cluster-bootstrapped by `experiment_id`, consistent with the existing configs-not-rows rule.
Full rationale and the four enforcing functions (`mann_whitney`, `compare_groups`,
`censored_timing_summary`, `compare_censored_groups`, all in `analysis/common.py`) are in
`docs/paper/statistical-treatment.md`.

**Why now.** `hypotheses.md` §6 already stated the principles (bootstrap CI, never
mean-impute) but not the mechanics, and `analysis/mde_power_check.py` had already gone ahead
using Cohen's *d* (a parametric effect size, fine as a design-time MDE heuristic, wrong as the
paper's reported statistic) with no written standard to check it against. Left undefined, two
people writing analysis scripts independently would not converge on the same test or the same
treatment of a censored cell.

**Validated against live data, not synthetic.** `censored_timing_summary` run against
`data/occupancy_dataset.csv`'s TIME_BASED arm (the D18 sweep) reproduces D18's own numbers
exactly: 108 rows, 30 censored, 78 observed, trip rate 0.722 [0.583, 0.861] over 36 configs,
conditional `time_to_open` 9.89s [8.16, 11.79] — see `statistical-treatment.md` §3.

**Rejected:** silently re-running `canary_readout.py::h1_matched_horizon` (currently
Welch's t + Cliff's delta + Brown-Forsythe) under the new standard as part of this decision.
Its numbers already back the closed D-004 Day-2 gate ("Paper B confirmed," 2026-09-08);
changing the significance test on an already-decided result is a reviewed step of its own, not
a side effect of defining the standard everything *else* should follow. Flagged in
`statistical-treatment.md` §5 as a known, deliberate deviation pending that follow-up.

**Revisit if:** the H1 migration above is done — re-run `h1_matched_horizon` under
`compare_censored_groups`/`mann_whitney`, confirm the conclusion is unchanged (or update D-004
if it isn't), and remove the §5.1 flag.

**Update (2026-09-14) — a second open item, found while merging this patch.**
`compare_censored_groups` computes its CIs with the cluster bootstrap (correct, per §2) but
runs its conditional-timing Mann-Whitney on raw rows, treating 3 replicates of one
`experiment_id` as 3 independent observations. The effect is one-directional — the reported
p-value is smaller than the design earns. No published number currently comes from this
function, so nothing in the paper is affected today, but the standard contradicts itself as
written. Recorded as `statistical-treatment.md` §5.2 rather than silently fixed: the fix
(aggregate to per-config means before testing) changes the unit of analysis and can flip a
contrast's significance, which is the same class of decision this entry's own **Rejected**
paragraph declines to make as a side effect. Pending review by this standard's author and
Soham.

**Update (2026-09-19) — §5.2 closed. The objection that blocked the 2026-09-14 fix doesn't
apply to the fix actually shipped.** The rejected fix was "aggregate each config to one
mean/median before testing" — that changes the unit of analysis (rows → configs) and can flip
a contrast, exactly as this entry's own §5.1 precedent says shouldn't happen as a side effect.
What actually closed this is a different design: `cluster_permutation_rank_test`
(`analysis/exact_tests.py`, new) permutes which whole *configurations* are labeled group 1 vs
group 2, but ranks every raw row under each relabeling — no configuration is ever collapsed to
a single value. This preserves within-configuration variance instead of averaging it away, so
the "changes the unit of analysis" objection doesn't apply: the unit being tested is still the
row, only the unit being *randomly assigned* is the configuration (which is what independence
actually requires). `compare_censored_groups` now builds `{config_id: [values]}` from the
`group_col` parameter it already carried but never used for significance, and calls this
instead of raw-row `compare_groups`. `cliffs_delta` is unchanged (row-level, as §5.1 already
established for the same reason — an effect size isn't the thing with the exchangeability
assumption).

**Verified by running both ways and diffing, not swapped in and trusted** — same standard this
entry sets for itself. `analysis/window_type_recovery_leak.py` (the only caller of
`compare_censored_groups` in the codebase) re-run before/after, all three COARSE sub-tables
(`time_to_recover`, `time_to_open_anchor`, `excess_over_wait_duration`) and both PRECISE
sub-tables (`half_open_to_closed`, `open_to_half_open` sanity check), `"current"` archive:

- **COARSE tables (18 vs 18 configs per $D_w$ bucket — the full threshold×window_size grid):**
  row-level p-values were absurd ($10^{-13}$ to $10^{-21}$) — Cliff's $\delta$ = -1.0 (complete
  separation) confirms the direction is real, but no permutation test on 18v18 independent
  units produces a $10^{-21}$ p. $\binom{36}{18} \approx 9 \times 10^9$ forced the new function's
  first-ever Monte Carlo fallback (not anticipated when it was scoped for H3's single-digit
  cluster counts — added here, same `+1`/`+1`-corrected convention as `exact_logrank_test`).
  Corrected p sits at the Monte Carlo floor, $\approx 5\times 10^{-5}$ (20,000 resamples) — an
  honest upper bound, not a precise estimate; the true exact floor at 18v18 complete separation
  is $\approx 1.1\times 10^{-10}$, just not resolvable by Monte Carlo at this resample count.
  **No verdict flag changed** (`consistent_time_slower`/`consistent_count_slower`/
  `partial_ratios_agree` identical before/after in all three tables) — direction and
  significance both survive, only the wildly overclaimed magnitude is corrected.
- **PRECISE `half_open_to_closed` — one real crossing, the kind this update promised to report
  rather than bury.** $D_w$=5: **p goes from 0.00216 (significant) to 0.1 (not significant)**
  once the true 3-vs-3 configuration count replaces the 6-vs-6 row count. $D_w$=15: p 0.0714 →
  0.5 — already non-significant before, more clearly so after, and the cluster counts now
  printed directly (1 COUNT config vs 3 TIME configs) are the same clustering shape H3's own
  stratified-permutation fix (this session, `decision-log.md` D24) found and corrected — this
  script tests each $D_w$ separately rather than stratified, which is a related but distinct
  open question from today's fix, not resolved here (see Revisit-if). $D_w$=30: unaffected,
  still fully censored on the COUNT arm both ways. **No verdict flag changed** here either —
  `window_type_recovery_leak.py`'s verdict logic reads ratio-consistency, not p-values, so a
  p-value crossing 0.05 doesn't itself flip `LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING` — but
  the crossing is real and is the actual finding this verification step exists to surface.
  **No published number is affected**: this table's p-values were never cited in
  `hypotheses.md` §4.1 or anywhere else (only its ratios were, confirmed by grep) — the
  "nothing published depends on it" statement two paragraphs up was true when written and
  stays true after this fix, it just stops being true by accident.
- **PRECISE `open_to_half_open` (negative control, should be window-type-agnostic):** all three
  $D_w$ stay solidly non-significant before and after (p 0.48→0.70, 0.39→0.50, 0.70→0.90) — the
  sanity check the script's own docstring wants continues to pass.

**Top-level verdict unchanged:** `LEAK_SUGGESTIVE_INCOMPLETE_DUE_TO_CENSORING`, before and
after.

**A methods point worth recording directly, since §IV-E will claim a centralized protocol
rather than one reimplemented per script.** `compare_groups`, `mann_whitney`, and
`compare_censored_groups` each have exactly **one caller** in this codebase (grepped
2026-09-18) — `compare_censored_groups`'s one caller is `window_type_recovery_leak.py`,
`compare_groups`'s one caller was `compare_censored_groups` itself (now replaced), and
`mann_whitney`'s one caller was `compare_groups`. A three-function standard with a single
consumer chain is *why* this defect was containable — one call site to audit and fix, not a
dozen. Recorded in `statistical-treatment.md` §5.2's own closing note, not just here.

**Revisit if:** `window_type_recovery_leak.py`'s per-$D_w$ testing (three separate contrasts,
one per wait_duration bucket) gets redesigned the way H3's own test was — stratified across
$D_w$ as blocking factor, one combined p-value for "does window_type affect this timing DV" —
rather than three independent ones. Not done as part of this update; flagged because the
$D_w$=15 cluster shape found here (1 vs 3 configs) is the identical shape that made H3's
per-$D_w$ testing invalid in the first place.

---

## D20 · Throughput (`throughput_loss`) is retired as a reported outcome, not repaired

**Date:** 2026-09-14 · **Decided by:** roadmap item B7 · **Status:** final (reporting);
one carried item in the ML layer, see below

**Decision.** No TPS-derived number appears in any table, figure, or claim in this paper.
`throughput_loss` is struck from the §6 secondary-DV list and moves to §7 as a stated threat.
The column stays in the 36-column schema and in every collected dataset — retired from
reporting, not deleted — exactly as `blast_radius` was under D15.

**The bug B7 names is already fixed, and is not the reason.** `508575f` (2026-06-18) replaced
the pacing-overhead subtraction with `execution_time = last_completion - t0`, stamping the true
last completion inside `send_request` under the existing lock. That is, precisely, the fix
README §4.7 still described as "queued for the Week 2 hardening pass." Every row of
`data/master_dataset.csv` was collected 2026-09-02, eleven weeks after that commit, so no live
row carries the fast-fail inflation. §4.7 was never reconciled against the fix; corrected in
this same commit.

**Why it is retired anyway: the measurement window is a function of the independent variable.**
`throughput_loss = max(0.0, 1 - throughput / baseline_throughput)` (`runner.py:1391`) divides
two `generate_load` calls that are not the same experiment:

- **baseline** (`runner.py:1245`) — fixed at `requests_count=20, concurrency=3` and the default
  50 ms pacing, roughly one second of load, identical in every run;
- **fault phase** (`runner.py:1312`) — `requests_count`, `concurrency` and `interval_s` all come
  from `compute_load_plan()`, which derives them from `slidingWindowType`, `slidingWindowSize`,
  `waitDurationInOpenState` and `fault_type`.

The denominator is constant; the numerator's measurement window is sized by the very factors
under comparison. The 324 live rows carry that fingerprint exactly:

| `window_type` | mean | by `window_size` 5 / 10 / 20 | by `wait_duration` 5 / 15 / 30 |
|---|---|---|---|
| COUNT_BASED | 0.728 | 0.734 / 0.723 / 0.726 | 0.728 / 0.727 / 0.728 |
| TIME_BASED | 0.894 | 0.925 / 0.896 / 0.863 | 0.854 / 0.900 / 0.929 |

COUNT_BASED plans are sized in calls, so the load duration barely moves and `throughput_loss`
is flat to within 0.011 across both IVs. TIME_BASED plans are sized in seconds, so the duration
tracks both IVs and `throughput_loss` slides monotonically with each. The between-window-type
gap (+0.166) is therefore not separable from the load plan that produced it — the number most
likely to be reported is the one most contaminated.

**It cannot be repaired post hoc.** Neither `throughput` nor `baseline_throughput` is in
`DATASET_HEADERS`; only the derived ratio is written. No corrected value can be recomputed from
any existing row. A fix means re-collection: the 324 rows above took **11 h 19 min** wall-clock
(`run_timestamp` 2026-09-02T12:01:36Z → 23:20:36Z), on top of the FANOUT CRASH re-collection
already queued as STATUS.md's remaining-work item 1.

**What retiring it costs: nothing that is claimed.** No hypothesis H1–H6 tests throughput, no
script under `analysis/` computes it, and it appears in the paper docs exactly once — the §6
secondary-DV list. B7's own reading is confirmed: it is not a headline DV. The headline figure
is detection latency vs. false-trip rate (§6).

**Rejected:** (a) *matching the load plans and re-collecting.* ~11 h of compute plus a schema
change to add the two raw TPS columns, spent on a secondary DV that supports no claim, while
the machines are needed for remaining-work items 1–3. (b) *reporting it with a caveat.* A
reviewer who asks how the two load phases were matched has no satisfactory answer, and carrying
one confounded number invites the same discount to be applied to the primary DVs.

**Carried, not closed — the ML layer.** `ml/preprocessing.py::IF_NUMERIC_FEATURES` fits the
Isolation Forest on `throughput_loss` alongside `blast_radius` and `error_rate`, so its anomaly
scores inherit the confound above. Not changed here: the ML layer is Soham's, sits outside
Paper B's hypothesis set (STATUS.md's remaining work names no ML task), and by its own README
still runs partly on synthetic data. **If any ML result enters the paper, `throughput_loss` must
be dropped from `IF_NUMERIC_FEATURES` and the model re-fit first.** Flagged rather than silently
changed, for the same reason D19 declined to re-run `h1_matched_horizon` as a side effect.

**Revisit if:** TPS becomes a claim this paper wants to make. Three things must land together —
baseline and fault phases measured at the same offered rate, concurrency and duration; raw
`throughput` and `baseline_throughput` added to the schema so the ratio is auditable; and the
`max(0.0, ...)` clamp at `runner.py:1391` reconsidered, since it floors throughput *gain* at
zero loss. The clamp never bites in the current all-LATENCY dataset (0 of 324 rows sit at
0.0000) but will under CRASH, where an open breaker's fast-fail can push TPS above baseline.

---

## D21 · `half_open_probe_timed_out` / `half_open_probe_deadline_s` — censoring becomes observable, not inferred; the coarse `time_to_recover` ceiling worry is closed

**Date:** 2026-09-16 · **Decided by:** Jay, from PR #56's Kaplan-Meier finding · **Status:** final (schema + harness fix); the targeted re-collection is a follow-up, not part of this entry

**Decision.** Two new schema columns, positioned immediately after `machine_id` (D14's
precedent — appended, never inserted, and always before `excluded_reason`, D8):

- `half_open_probe_timed_out` (nullable bool) — did `BreakerObserver._drive_half_open_probes`'
  poll-until-transition loop ever observe a real `HALF_OPEN_TO_CLOSED` for this run, or did it
  hit its own ceiling first? Blank — never a sentinel — when `cb_open_at` was `None` (nothing
  to probe), matching `lambda_deviation_flag`'s own established None-vs-False convention.
- `half_open_probe_deadline_s` (nullable float) — the ceiling that run's probe-driving loop was
  actually watching against (`3 * wait_duration + 60`, deterministic from `wait_duration` but
  recorded directly, matching `readiness_wait_s`'s own precedent for not making a reader
  recompute or assume a value later).

**Why.** PR #56's KM analysis found that every real censored COUNT record in the tracked
sidecar shows exactly 2 logged events (`CLOSED_TO_OPEN`, `OPEN_TO_HALF_OPEN`) and then
silence — and until now, "was this censored, or did it just never get logged for some other
reason" could only be answered by counting sidecar events after the fact and inferring intent.
That is the same shape of gap `machine_id` (D14) and `cb_state_pre` (D8) each closed for their
own kind of silent failure — this closes it for HALF_OPEN-probe censoring specifically.

**The harness fix that makes the new column meaningful, not just a name.** Tracing why those
records show exactly 2 events found the real constraint: `observe_recovery()` called
`_drive_half_open_probes()` **unconditionally** for a **fixed** `(permitted_calls_half_open + 2)
× 0.3s + 2s ≈ 4.1 seconds` of driven traffic, regardless of `wait_duration` and regardless of
whether a real transition had happened yet — not `_poll_for_recovery`'s much larger,
`wait_duration`-scaled deadline, which turned out to have 17–27 seconds of slack even at
$D_w$=30 (verified directly against 6 real `fault_cleared_at` values, 0 violations of the
bound in all 26 real closures on record).

`_drive_half_open_probes` is now **poll-until-transition**, mirroring `_poll_for_recovery`'s own
pattern: drive light traffic, check `collect(snapshot)` after each round, and stop the moment
any watched breaker's transitions include `HALF_OPEN_TO_CLOSED`. A bounce back to `OPEN` does
**not** stop the loop — that isn't a terminal outcome, and ending observation on a bounce would
just be the same under-observation bug with a different trigger. A hard ceiling
(`3 × wait_duration + 60s`, exposed as its own pure function `half_open_probe_deadline_s` for
testability) exists so a genuinely stuck breaker can't hang a run; hitting it is the real,
logged `half_open_probe_timed_out=True` outcome, not a silent exit.

`_poll_for_recovery`'s own deadline is separately widened from a flat `+10` to
`wait_duration + max(30, 2 * wait_duration)`, as originally proposed — kept even though the
evidence says it was never the binding constraint on COUNT's censoring, because it's harmless
(the loop exits early on success regardless) and removes one more place a fixed constant didn't
scale with the thing it was bounding.

**A separate worry, investigated and closed — no code change needed.** Does the same ceiling
that censors the *precise* `precise_half_open_to_closed` metric also censor the *coarse*
`time_to_recover` column already published as H3's headline figures? **No, provably:**
`_poll_for_recovery` has exactly two outcomes — a real number, or `None` on timeout — with no
path that returns a truncated value, and `runner.py` writes `None` as an explicit blank
(`""`), never a fabricated number. `df.time_to_recover.isna().sum() == 0` across all 360 rows
in the live dataset: every single run detected recovery before its own deadline. This
return-value logic was introduced once (`8106199`) and never changed since, so the argument
holds for the dataset's entire collection history, not just current code. Directly
cross-checked against real `fault_cleared_at` values for the tightest-margin cell
(TIME_BASED, $D_w$=30): margins of 17.7–27.1 seconds to spare, because that fault window's own
load generation runs 42–52 seconds *after* the breaker already trips (sized to fill a large
sliding window), pushing the deadline far later than a naive small-gap estimate would suggest.
H3's originally published coarse figures do not need re-reading on account of this ceiling.

**Rejected:** widening only `_poll_for_recovery`'s deadline and stopping there, as first
proposed. The evidence (every censored record's identical 2-event shape, and the
17–27s of unused slack on `_poll_for_recovery`'s own budget) points at
`_drive_half_open_probes`'s fixed window as the actual constraint; widening the wrong constant
would have consumed the ~1–2h re-collection window without resolving anything.

**Consequence.** `data/master_dataset.csv`'s existing 360 rows predate these two columns and
will read blank for both once the header is updated to include them (standard for every prior
schema addition — D14's `machine_id` did the same for the rows that predated it). Not done in
this commit — this entry is the harness fix and schema definition; merging the header update
and the targeted $D_w$∈{5,15,30} re-collection (control-inclusive, per the plan) into the live
file is a follow-up commit once that data exists.

**Revisit if:** the targeted re-collection lands and either (a) COUNT now recovers within the
widened, poll-until-transition window at $D_w$=15/30 — H3 gets closeable real numbers — or
(b) `half_open_probe_timed_out=True` persists even under the new harness — a genuine,
directly-provable finding (COUNT_BASED's HALF_OPEN probes structurally fail more often at
higher $D_w$) rather than an instrument-ceiling artifact.

**Update (2026-09-16) — outcome (a).** The 36-run targeted re-collection landed
(`d21_poll_until_transition_verification`, `analysis/common.py`) with
`half_open_probe_timed_out=False` on 36 of 36 runs — zero censoring at any $D_w$, on either
arm. H3 closes: `LEAK_CONFIRMED_ON_HALF_OPEN_LEG`, significant at every level (log-rank
p=0.0014 at $D_w$=5/15, p=0.0005 at $D_w$=30 — 2 of the 36 runs' precise-metric durations were
later found host-sleep-corrupted and excluded from the KM computation itself, n=34; see D13's
2026-09-17 correction for the full account), TIME slower throughout with the ratio shrinking
from 9.49× at $D_w$=5 to 2.16×/2.40× at $D_w$=15/30. Full numbers and the corrected-shape
discussion are in D13's own closing update, appended just above D14 — this entry's job was the
fix and the observability columns, D13's is the hypothesis outcome, and both are now closed.

---

## D22 · H3's HALF_OPEN slowdown is partly explained: bounce count, not a complete mechanism

**Date:** 2026-09-17 · **Decided by:** Jay, hypothesis + test design; verified against existing
data, no new runs · **Status:** partial — a real, dominant contributor identified; not a
complete mechanism

**Decision.** D13's 2026-09-17 update (HALF_OPEN→CLOSED governed by
`permittedNumberOfCallsInHalfOpenState`, not `minimumNumberOfCalls`) left an open question: 3
probes at Resilience4j's ~0.3s polling interval should resolve in about a second, yet TIME_BASED
recovery runs 19–40s. Jay's hypothesis: the time is mostly repeated
`HALF_OPEN → OPEN → wait_duration → HALF_OPEN` bounces before one episode finally closes, driven
by a TIME_BASED window still holding failure records from the last `window_size` seconds on
re-evaluation, while a COUNT_BASED ring buffer gets overwritten by fresh successes almost
immediately. Larger `window_size` → longer residual fault memory → more bounces, which would
also produce D13's observed `window_size` correlation.

**Testable from existing data, no new runs.** `analysis/half_open_survival.py::extract_observations()`
already computes `n_failed_probes` — the actual `HALF_OPEN_TO_OPEN` bounce count per run (its
sibling field `n_half_open_entries` is a documentation trap: bounded by `len(BREAKER_WATCH)`,
always `1` in this data, carries no bounce information — fixed with a clarifying comment
alongside this entry's other `half_open_survival.py` change). New script,
`analysis/bounce_count_analysis.py`, reuses `extract_observations()` directly rather than
re-deriving anything, against the same post-D21-fix, corruption-excluded slice (n=34,
`--since 2026-09-16`) this decision-log's corrected D13 table uses.

**Numbers.**

| window_type | window_size | n | mean bounces | raw |
|---|---|---|---|---|
| COUNT_BASED | 5, 10, 20 | 6 each | **0.000** | all zero, every cell |
| TIME_BASED | 5 | 6 | 1.333 | [1,2,1,1,1,2] |
| TIME_BASED | 10 | 6 | 1.500 | [1,2,2,1,1,2] |
| TIME_BASED | 20 | 4 | 1.750 | [3,1,2,1] |

**COUNT_BASED never bounces, in any of 18 observations.** **TIME_BASED's bounce count rises
with `window_size`**, directionally exactly as the hypothesis predicts (n too small — 2 reps/
cell, 4 for W20 after exclusions — for a powered trend test, stated as descriptive).

A naive two-term decomposition (`duration_s ≈ bounce_count × wait_duration + final_episode_s`)
was tried first and found to *over*-explain the TIME−COUNT gap at $D_w$=15/30 (109–148% of the
gap) — because COUNT_BASED's own zero-bounce "final episode" duration also scales with
`window_size`/`wait_duration` (2s → 10–17s) even though it never bounces, which a two-term
model can't represent. Replaced with a joint OLS regression instead
(`duration_s ~ 1 + bounce_count + wait_duration + window_type`, `n=34`, numpy `lstsq`, no
p-values reported — descriptive on this sample size, not an inferential claim):

```
intercept      = -3.069
bounce_count   =  6.446  (seconds per additional bounce)
wait_duration  =  0.746  (seconds per additional second of D_w)
is_time_based  =  9.767  (seconds, TIME vs COUNT at bounce=0, same D_w)
R^2            =  0.862
```

**Verdict: bounce count is the dominant, but not sole, driver.** It explains a large share of
variance (R²=0.862) and each bounce costs a real, substantial ~6.4s (matching `wait_duration`'s
own typical scale — consistent with a bounce being "wait out the OPEN state, try again"). But
`is_time_based`'s own coefficient (~9.8s) is not driven to zero — **a real residual gap between
TIME_BASED and COUNT_BASED remains even at bounce_count=0, same `wait_duration`** — meaning
bounces alone do not fully explain the slowdown; something about TIME_BASED's single-episode
HALF_OPEN evaluation is itself slower too, not identified here.

**Also unexplained, flagged not resolved:** two 0-bounce COUNT_BASED runs
(`LIN-LAT-CNT-T50-W20-D30`, both replicates, ~25.3s) took far longer than every other COUNT
cell (2–15s) despite bouncing zero times — the bounce model predicts these should be fast, and
they aren't. Not a fluke (both replicates agree); not explained by this entry.

**Rejected:** reporting this as "H3's mechanism, solved." The residual `is_time_based`
coefficient and the unexplained COUNT `W20/D30` outlier are real gaps this entry does not paper
over — the honest claim is "bounce count is a real, dominant, partial mechanism," not "the
mechanism."

**Consequence for the paper.** §V-D can now say TIME_BASED's HALF_OPEN slowdown is *primarily*
attributable to repeated bounces (residual window contents blocking a clean evaluation, exactly
as the residual-fault-memory hypothesis predicts), quantified at ~6.4s/bounce, with an
acknowledged ~9.8s residual and one unexplained outlier cell left open — a stronger, more
precise claim than "unidentified," short of a fully solved mechanism.

**Revisit if:** the ~9.8s residual or the COUNT `W20/D30` outlier becomes tractable to
investigate directly (e.g. instrumenting per-probe latency within a single HALF_OPEN episode,
not just bounce counts and total duration).

**Update (2026-09-18, the revisit condition is met — mechanism fully decomposed, residual-window-contents confirmed, not falsified).**
`analysis/recovery_decomposition.py` (new, `--self-test`) walks each run's raw
`transitions` list directly (not `n_failed_probes`, an independent extraction path from D22's
own) and splits total recovery into three additive, self-test-verified parts: failed episodes,
inter-attempt OPEN gaps, and the final successful episode. Three predictions, against
`data/cb_transitions.jsonl` (`--modes full`, gateway-tripped rows excluded — D23/D25 — plus the
same host-sleep-artifact ceiling check `half_open_survival.py` already applies to this exact
source, which independently caught and excluded the identical two records D13/D21 already
flagged: `TIME-W20-D5` at 700.4s, `TIME-W20-D15` at 1703.4s, both far past
`half_open_probe_deadline_s` — the same artifact, found again via an unrelated code path, not
re-discovered by copying the exclusion list):

- **P1 (control, reproduces D22): bounce count rises with `window_size` for TIME_BASED, flat
  at zero for COUNT_BASED.** TIME mean bounces 1.33 → 1.42 → 1.90 at W=5/10/20 (n=34,
  slope=+0.039/unit, t=+2.20, R²=0.131 — weaker R² than D22's original per-run number, expected
  at this more granular per-episode extraction, same direction). COUNT_BASED: 0/16 bounce, exactly
  matching D22.
- **P2 — the discriminator. Final-episode duration does NOT scale with `window_size`.** TIME
  mean final-episode 2.38s → 2.33s → 2.29s at W=5/10/20 (n=34, slope=-0.006s/unit, t=-0.72,
  R²=0.016; predicted change across the whole swept range is -0.08s, 4% of the 2.33s mean —
  not material). **The successful HALF_OPEN attempt itself costs the same ~2.3s regardless of
  window size.** This is the falsification test residual-window-contents had to pass, and it
  passes cleanly — not narrowly.
- **P3 (instrument sanity): the inter-attempt OPEN gap tracks `wait_duration`, not
  `window_size`, almost exactly.** Slope on `wait_duration` = +1.024 (≈1, as it must be — the
  gap *is* `wait_duration` by construction), t=+49.58, R²=0.987; slope on `window_size` = +0.060,
  R²=0.001 — no confound. Validates the extraction independent of the two hypotheses above.

**Mechanism, now fully chained, not just partly explained.** Larger `window_size` → more bounces
needed before one attempt lands clean (P1) → each bounce costs one full `wait_duration` sitting
in OPEN (P3, exact) → the attempt that finally succeeds takes the same ~2.3s no matter how large
the window was (P2). `total_s ≈ bounce_count × (wait_duration + ~2.3s) + ~2.3s` — this is no
longer "bounce count explains most of it, ~9.8s unexplained" (D22) or "~2.75s unexplained"
(D24's gateway-cleaned residual) — the residual **is** the failed-episode time, already fully
accounted for by the additive decomposition itself (episodes + gaps = total, verified by
`--self-test`'s own identity check). There is no more "residual" left to explain; there was
never a separate mechanism beyond bounce count and the constant per-attempt/per-gap costs
already on record.

**Consequence for the paper.** §V-D can now state the mechanism as closed, not partial: TIME_BASED's
extra HALF_OPEN recovery time relative to COUNT_BASED is entirely attributable to needing more
probe attempts at larger window sizes (residual window contents, D22's original hypothesis),
each attempt costing a fixed OPEN-state wait plus a fixed ~2.3s evaluation — nothing inside the
HALF_OPEN leg itself depends on `T` once bounce count is accounted for.

**Rejected:** treating this as new mechanism-discovery. It's a decomposition of numbers D22/D24
already reported, using a finer-grained but consistent extraction — the qualitative claim
(bounce count is the driver) is unchanged; what's new is that the previously-"unexplained"
residual no longer needs its own explanation.

---

## D23 · The gateway's "never-opens" measurement-plane isolation is incomplete — it does open, live-verified, under COUNT_BASED

**Date:** 2026-09-17 · **Decided by:** Jay, live-verified against the real mesh with the same
`CB_CONFIG_DUMP`/`CircuitBreaker`-event diagnostic used for D18 · **Status:** final — the
isolation claim in `hypotheses.md` §7 and its H6 row is corrected; H6's untestability verdict
needs re-deciding separately (not done in this entry)

**How this was found.** While investigating D22's unexplained 0-bounce COUNT_BASED
`W20/D30` outlier (~25.3s, vs 2–3s for other COUNT cells), the raw `cb_transitions.jsonl`
records for those runs showed a *second* breaker — `gateway:orderServiceCB`, outside
`BREAKER_WATCH`'s scope — independently cycling `CLOSED_TO_OPEN → OPEN_TO_HALF_OPEN →
HALF_OPEN_TO_CLOSED` on its own clock. Order's breaker closed **1.5–1.6s after gateway's own
`OPEN_TO_HALF_OPEN`**, not 1.5s after order's own HALF_OPEN began — order was waiting on
gateway to let traffic through, not slow to recover itself.

**Decision.** `services/gateway-service/src/main/resources/application.yml`'s
`measurement-plane` config (added `dcb9214`, 2026-07-30, specifically to keep gateway's three
outbound breakers from engaging and confounding the sweep) sets
`minimum-number-of-calls: 1000000`, `failure-rate-threshold: 100`,
`slow-call-rate-threshold: 100`, `slow-call-duration-threshold: 60s` — but never sets
`sliding-window-size` or `sliding-window-type`, and doesn't declare `base-config: default`.
Live-verified via a disposable `CB_CONFIG_DUMP` listener on `gateway-service` (same code as
D18's, worktree-only, never merged): the two unset fields silently track `default`'s swept
values anyway (`slidingWindowSize=20, slidingWindowType=COUNT_BASED` when `.env` was set to
those, `=10/COUNT_BASED` — the compose file's own inline fallback — when no `.env` was
present at all). This is Resilience4j Spring Boot's own `configs` fallback behavior, not
something this repo's code sets explicitly anywhere.

Combined with D18's already-published, live-confirmed mechanism (a `COUNT_BASED` window
evaluates once its ring buffer — sized by `slidingWindowSize`, not `minimumNumberOfCalls` —
fills, regardless of the configured minimum), this means gateway's real evaluation gate is
`min(1000000, slidingWindowSize)` = `slidingWindowSize` itself. `minimumNumberOfCalls`'s
"1,000,000, never reached" design **never applies to COUNT_BASED sweeps** — only
`failureRateThreshold=100`/`slowCallRateThreshold=100` stand between gateway and a trip, and
a window that fills entirely with real failures (every call gateway makes while order's own
breaker is OPEN and fast-failing) clears that bar easily.

**Live confirmation, call-by-call**, replaying `LIN-LAT-CNT-T50-W20-D30` (the exact config
behind the D22 outlier) against the real mesh: `orderServiceCB`'s `bufferedCalls` climbs
0→20 on ordinary pre-fault traffic; `failureRate` flips from `-1.0` (not-yet-evaluated) to
`0.0` the instant `bufferedCalls` hits 20 — evaluation gated by ring-buffer fill, exactly as
D18 found for the swept breakers, not by the configured 1,000,000 floor. During the fault
window, the same ring buffer refills with real failures and trips:
`CLOSED_TO_OPEN` at `bufferedCalls=20, failedCalls=20, failureRate=100.0`.

**This is not isolated to the two D22 outlier runs.** Across the full `data/cb_transitions.jsonl`
history (73 records, spanning both before and after D21's unrelated HALF_OPEN fix — this bug
predates and is independent of that one), **20 records show a real gateway
`CLOSED_TO_OPEN`**, spanning exactly 5 experiment_ids — `W5/D15`, `W5/D30`, `W10/D15`,
`W10/D30`, `W20/D30` — **all `COUNT_BASED`, all `wait_duration ∈ {15, 30}`, zero among
`TIME_BASED`** (0 of every `TIME_BASED` record in the sidecar). This matches D18's TIME_BASED
finding exactly: `minimumNumberOfCalls` genuinely gates evaluation for `TIME_BASED` windows
(no ring-buffer bypass), so the 1,000,000 floor *does* hold there — the isolation is real for
`TIME_BASED` sweeps and broken for `COUNT_BASED` ones.

**Scope: is this confined to the D13/D21 recovery-focused re-collection, or does it reach the
main dataset too?** `experiments/runner.py`'s `PARAM_VALUES` — the grid the *main* full sweep
draws from — covers the identical space (`slidingWindowSize ∈ {5,10,20}`,
`waitDurationInOpenState ∈ {5,15,30}`, both window types). The mechanism has no dependency on
which sweep invokes it; it is a property of `gateway-service`'s own YAML, present since
2026-07-30, unchanged since. **Directly confirmed only for the 73 sidecar-covered records**
(`data/cb_transitions.jsonl` does not reach back to the original historical full-sweep
collection) — stated honestly as structurally implicated by an unchanged, shared code path,
not row-by-row verified for the full historical dataset. This is the answer to "dataset-scoped
or never as complete as believed": **not dataset-scoped** — the same YAML, same bug, same
parameter grid underlies every `COUNT_BASED` sweep this repo has ever run at
`wait_duration ≥ 15`, `full` mode or otherwise.

**On `cb_state_pre` (D8) — precise about what it does and doesn't show.** `check_breaker_precondition()`
(`experiments/runner.py:802`) runs immediately after `update_containers()` force-recreates
every container and **before** any load or fault injection (`run_experiment_run`'s step 2b) —
a pre-load snapshot. It does cover gateway's three breakers (`SERVICE_BREAKERS` includes
`orderServiceCB`/`inventoryServiceCB`/`paymentServiceCB` under `gateway`), so "every breaker
including gateway's read CLOSED at load start, every replicate" is real and remains valid —
it is the correct, unaffected evidence that breaker state does not leak between replicates.
**It has never measured, and is not evidence for, breaker state *during* a run.** Any claim
built on `cb_state_pre` (or on it alone) that gateway "stays closed" or "never engages" for
the duration of a run is not supported by what this column actually checks — that broader
claim is what `hypotheses.md` §7 got wrong, corrected below.

**Corrected: `hypotheses.md`'s H6 §7 bullet** ("H6's condition was removed by the
`measurement-plane` isolation block... Every current row is `isolated`") — false as a
universal claim. Replaced with a statement scoped to what's actually true: the isolation
holds for `TIME_BASED` sweeps, and for `COUNT_BASED` sweeps below the `slidingWindowSize`/`wait_duration`
combination needed to fill gateway's leaked window, and does not hold above it.
**`STATUS.md`'s H6 row** ("Gateway CLOSED in all 704 rows") is corrected the same way — no
row-level source for that specific figure was found anywhere in this repo (not in
`hypotheses.md`, not elsewhere), and it is contradicted directly by the 20 sidecar records
above regardless of its original basis.

**Not decided here: what this means for H6 itself.** H6 ("a uniformly configured edge breaker
suppresses interior breaker engagement") was marked untestable *because* the isolation was
believed complete. It no longer is, for the `COUNT_BASED`/higher-`wait_duration` cells — which
means H6 may be directly testable from data already partially in hand (the 5 gateway-tripping
experiment_ids are natural instances of the H6 condition), not only via "deliberate
reconstruction of a removed confound" as `hypotheses.md` currently frames the only path to
testing it. Re-deciding H6's testability verdict is a separate, follow-up decision, not made
in this entry — this entry's scope is the isolation claim's correctness, not H6's disposition.

**Rejected:** fixing `measurement-plane`'s YAML (adding explicit `sliding-window-size`/
`sliding-window-type`, or `base-config: default` plus overrides) as part of this entry. That
would change what future sweeps measure — a decision for whoever re-derives D15/D-001 and
decides whether the historical (leaky) isolation or a genuinely-fixed one is what the paper's
existing 324–360 rows should be described as having used. Silently patching it here would
retroactively change the meaning of already-collected data without a decision record saying
so.

**Revisit if:** the YAML gets fixed (own decision-log entry, per this repo's schema/config-change
convention) — or if H6's testability verdict gets re-decided using the data this entry
surfaces.

---

## D24 · D13's KM table and D22's regression, stratified by `gateway_tripped` — the within-COUNT $D_w$ trend was the leak, not a COUNT_BASED property

**Date:** 2026-09-17 · **Decided by:** Jay, three follow-ups in order: audit `master_dataset.csv`
for gateway activity, re-run D13's KM table stratified by `gateway_tripped`, recompute D22's
residual against the cleaned baseline · **Status:** final for the numbers below; both scripts'
pooled output is kept alongside the cleaned output, not replaced by it

**1. `master_dataset.csv` (360 rows) audit — structurally inconclusive, not a negative result.**
`analysis/gateway_leg_audit.py` (new): gateway can never appear in `leg_failure_rates`,
`blast_radius`, or `real_blast_radius`, in any row — `CB_METRIC_TARGETS`
(`experiments/runner.py`) and `SERVICE_ACTUATOR_URLS` (`BlastRadiusService.java`) both
hard-code the 4 downstream services only, by design, gateway explicitly excluded in both. The
one indirect proxy — `error_rate` (client-observed, through gateway) vs `leg_failure_rates`'
order-service entry (order's own outbound health) — is confounded by an unrelated, previously
unnoticed artifact: their ratio is a near-constant `2.0000` across `FANOUT/codespace` (n=162),
`LINEAR/soham-local` (n=159), and `LINEAR/jay-overnight-rerun` (n=3), and exactly `1.0000` for
`LINEAR/jay-mac` (n=36) — splitting cleanly by **collection batch**, not by `window_size`/
`wait_duration`. D23's flagged parameter region (COUNT_BASED, `wait_duration∈{15,30}`,
`window_size∈{10,20}`, n=80) shows the identical mean ratio (1.9000) as the rest of
`COUNT_BASED` (n=100, also 1.9000) — no separation at all. **Verdict: inconclusive by
construction**, not "gateway was clean in the main dataset." Building a threshold on this
ratio now would misattribute an unrelated, unexplained batch confound to gateway — flagged as
a new, separate, unsolved observation (own future investigation if pursued), not resolved
here.

**2. D13's KM table, stratified by `gateway_tripped`.** `analysis/half_open_survival.py` gains
a `gateway_tripped` field on every observation (purely additive — computed from the same
`transitions` list already fetched for `BREAKER_WATCH`, independent of it, verified inert
against every existing field) and a `--stratify-gateway` report that reuses `analyse()`
unchanged on the cleaned set (`COUNT-not-tripped + all TIME`, since `TIME_BASED` never trips
gateway) plus a direct `kaplan_meier()` call for the gateway-tripped `COUNT_BASED` subset
(descriptive only — no `TIME` counterpart to log-rank against). On the same n=34 slice D13/D22
already used:

| $D_w$ | COUNT-not-tripped | COUNT-tripped | TIME (unsplit) |
|---|---|---|---|
| 5  | 2.038s (n=6) | *(empty, n=0)* | 19.343s (n=5) |
| 15 | 2.413s (n=2) | 10.164s (n=4) | 21.267s (n=5) |
| 30 | *(empty, n=0)* | 14.987s (n=6) | 35.896s (n=6) |

**The published "COUNT gets slower at higher $D_w$" shape (2.04→9.83→14.99s) was gateway
contamination, not a real `COUNT_BASED` recovery-time effect.** $D_w$=30's entire `COUNT_BASED`
sample (6/6) is gateway-tripped — there is zero clean `COUNT_BASED` data at $D_w$=30 at all;
$D_w$=15 is 4/6 gateway-tripped. **H3's core TIME>COUNT claim survives on clean data**: $D_w$=5
(ratio 9.49×, log-rank p=0.0014, unchanged — no gateway trips at $D_w$=5 at all) and $D_w$=15
(ratio **8.81×**, log-rank **p=0.0082**, on the 2 clean `COUNT_BASED` observations vs 5 `TIME`)
— still significant, same direction. **$D_w$=30 is now untestable** (`ONE_ARM_EMPTY` —
`analyse()`'s own existing verdict logic, no code change needed to produce this correctly) —
an honest gap, not a null result. This also directly retro-explains D22's previously-flagged
"unexplained" `W20/D30` outlier: it isn't 2 anomalous runs, both `duration_s≈25.3s` rows are
exactly the two largest values in the gateway-tripped $D_w$=30 group.

**3. D22's regression, recomputed on `gateway_tripped==False`.** `analysis/bounce_count_analysis.py`
gains `--exclude-gateway-tripped`, reusing the same `duration_s ~ 1 + bounce_count +
wait_duration + is_time_based` OLS on the cleaned rows (all `TIME_BASED` kept, 10 of 18
`COUNT_BASED` dropped, n=24):

| | original (n=34) | cleaned (n=24) |
|---|---|---|
| intercept | -3.069 | -5.275 |
| bounce_count | 6.446 | 9.726 |
| wait_duration | 0.746 | 0.992 |
| **is_time_based** | **9.767** | **2.748** |
| R² | 0.862 | 0.934 |

The ~9.8s "unexplained residual" D22 flagged **mostly dissolves** (→2.7s, ~3.5× smaller) once
gateway-confounded rows are removed — most of what looked like a genuine TIME-intrinsic
slowdown independent of bounces was gateway confound, not a real residual mechanism. Bounce
count's own per-bounce cost is if anything **understated** by the original pooled regression
(6.446 → 9.726 once cleaned). **Caveat, printed directly in the script's own output, not left
to prose:** cleaned `COUNT_BASED` rows only span $D_w \in \{5,15\}$ (n=6, n=2) — zero survive
at $D_w$=30 — so the cleaned `wait_duration` coefficient (0.992) is driven almost entirely by
`TIME_BASED`'s own $D_w$ effect for that region, not a genuine cross-arm slope. Report it, but
it is not equally well-supported as the original 0.746.

**Consequence for the paper.** §V-D can now say: H3's TIME>COUNT direction and significance
hold on clean data at $D_w$∈{5,15}; the *within-COUNT* $D_w$ trend previously reported
(2.04→9.83→14.99s) does not — it was gateway contamination, and $D_w$=30 is currently
untestable for `COUNT_BASED` with existing data. D22's bounce-count mechanism is stronger, not
weaker, once cleaned (R²=0.934, larger per-bounce cost) — the "not a complete mechanism"
framing softens to "bounces explain nearly all of it, with a small, now much less mysterious
residual likely explained by non-bounce per-episode probe-evaluation cost, not a TIME-intrinsic
mystery."

**Rejected:** deleting or overwriting the original pooled tables/coefficients in D13/D22 or in
`analysis/out/half_open_survival_since_2026-09-16.json`. Both scripts print the pooled and
cleaned versions side by side — the pooled numbers are what was actually published and cited
first, and the append-only convention applies to analysis output the same way it applies to
prose.

**Revisit if:** more `COUNT_BASED` replicates at $D_w$=30 get collected under conditions where
gateway's isolation is confirmed to hold (i.e., after the YAML gap D23 found is actually
fixed) — that would finally give H3 a testable $D_w$=30 `COUNT_BASED` arm. Also revisit if the
~2x/1x batch artifact found in step 1 gets investigated and turns out to be gateway-related
after all (it currently shows no relationship to D23's parameter region, but its actual cause
is still unknown).

**Update (2026-09-18, the chi-square p-values were asymptotic artifacts — corrected below; the
correction below was itself wrong and is retracted in the second update further down. Kept,
struck through in spirit rather than deleted, per this file's append-only convention — the
retraction explains exactly what was wrong and why, which a silent rewrite would lose.**
`half_open_survival.logrank()`'s p-values come from a chi-square approximation, valid only
asymptotically; it has no floor and can report values a permutation test could never produce at
small n. `analysis/exact_tests.py` (new, `--self-test`) implemented
`exact_p_floor`/`exact_logrank_test` and reported, at $D_w$=5 ($n_1$=6, $n_2$=5 rows): exact
p=0.004329 vs. floor 1/462; at $D_w$=15 ($n_1$=2, $n_2$=5 rows): exact p=0.047619, "== floor",
both read as "H3's direction and significance survive at both $D_w$."

**These row counts were never checked against the actual number of independent configurations
behind them, and they should have been.** See the next update.

**Update (2026-09-18, second pass — the row-level "exact" p-values above are RETRACTED
entirely, not merely re-weakened; replaced with a stratified cluster permutation test that is
the first correct significance test this repository has run on this comparison.** Prompted by a
direct question: is "$n_1$=6, $n_2$=5" at $D_w$=5 six independent configurations, or fewer
configurations with repeated replicates? Checked directly, `data/cb_transitions.jsonl`,
`--since 2026-09-16`, gateway-cleaned:

| $D_w$ | COUNT rows | COUNT **configs** | TIME rows | TIME **configs** |
|---|---|---|---|---|
| 5  | 6 | **3** (W5, W10, W20 × 2 replicates each) | 5 | **3** (W5×2, W10×2, W20×1) |
| 15 | 2 | **1** (W20 × 2 replicates — W5/W10 both entirely gateway-tripped) | 5 | **3** (W5×2, W10×2, W20×1) |
| 30 | 0 | 0 (all gateway-tripped) | 6 | 3 |

**No cell has rows == configs.** The row-level exact test above treated each *replicate* as an
independent unit for the permutation's exchangeability assumption, which is false — two
replicates of the same configuration are not exchangeable with a replicate of a different
configuration; they share everything except run-to-run noise. This is worse than a weaker
result at $D_w$=15: with only **1** independent COUNT configuration there, there is no
between-configuration variation on that side to test at all. A permutation test needs $\ge 2$
independent units per arm to say anything; the previous "exact p=0.047619" at $D_w$=15 was
computed on 2 units that were not independent, so it was never a valid test of anything, not
just an optimistic one. **$D_w$=15 alone is unsupportable — its own cluster floor,
$1/\binom{4}{1}=0.25$ one-sided, can never reach significance no matter what the data show,
because $\binom{4}{1}=4$ is the entire space of ways to relabel 1 COUNT config among 4 pooled
configs.**

**The fix: test what H3 actually claims, once, holding $D_w$ fixed as a blocking factor
instead of testing each $D_w$ separately.** H3 is "TIME_BASED recovers slower than
COUNT_BASED" — one claim, not "...at $D_w$=5" and "...at $D_w$=15" as two claims requiring two
significant p-values. `analysis/exact_tests.py` gains
`stratified_cluster_permutation_test`/`stratified_p_floor`: the unit is a configuration (mean
of its replicates), $D_w$ is a stratum, and the null is the exact product of each stratum's
own $\binom{n_1+n_2}{n_1}$ config relabelings ($D_w$=30 excluded — COUNT arm empty, contributes
no label information). $D_w$=5: $\binom{6}{3}=20$ ways to relabel. $D_w$=15: $\binom{4}{1}=4$
ways. Total joint assignments: $20 \times 4 = 80$. Floor: $1/80=0.0125$ one-sided,
$2/80=0.025$ two-sided.

Config-level means (COUNT / TIME, seconds):

| $D_w$ | COUNT configs | TIME configs |
|---|---|---|
| 5  | W5=2.071, W10=2.041, W20=2.066 | W5=19.259, W10=19.327, W20=28.739 |
| 15 | W20=2.471 | W5=20.852, W10=30.527, W20=39.608 |

**Every COUNT config beats every TIME config in both strata (complete separation).** Run
through `stratified_cluster_permutation_test` (unweighted stratified rank-sum, exact
enumeration of all 80 joint relabelings — not Monte Carlo, not asymptotic): the observed
labeling is the single most extreme of all 80, so **the exact p equals the floor exactly:
two-sided p = 0.025, one-sided p = 0.0125.** This is the correct, honest, first-ever valid
significance test of H3's actual claim on this data — no inflated n, no per-$D_w$ multiple
testing, no row-replicate exchangeability violation.

**Consequence for the paper.** State H3's significance as **one number**: stratified cluster
permutation, $p=0.025$ (two-sided), $n=6$ configurations total (3+3 at $D_w$=5, 1+3 at
$D_w$=15, $D_w$=30 excluded for an empty COUNT arm). Retire every per-$D_w$ p-value this
comparison has ever reported (the chi-square ones from D13/D21, and both row-level and
config-blind framings above) — they were each testing a narrower, unintended claim, at an
inflated or otherwise invalid n. The *direction* (TIME slower than COUNT) is unchanged and was
never in question; what changes is that there is now exactly one correct p-value for it,
instead of three incorrect ones.

**Rejected:** matched-pairs by window_size at $D_w$=5 (3 configs per arm happen to share the
same swept window_size values). Tempting, but it halves the permutation space for no
statistical gain here — a sign-based paired test on 3 pairs has only $2^3=8$ assignments
(floor 1/8), strictly worse than the unpaired $\binom{6}{3}=20$ the data actually supports.
Pairing is the right move only when it removes a real nuisance source of variance the unpaired
test can't otherwise control for; window_size is already the stratifying axis's covariate here,
not a nuisance to be differenced away.

**Same root cause as this session's other small-n traps (D18, D23, the resilience4j javadoc
entry under D13, and this same entry's own first-pass row-level "fix" above):** the unit of
independence was never checked before being fed to a formula that assumes it. A floor check
without a cluster check catches an asymptotic-approximation bug but walks straight into the
next one.

---

## D25 · `measurement-plane`'s inheritance gap is fixed — every field pinned explicitly, live-verified against a real fault, zero gateway transitions

**Date:** 2026-09-18 · **Decided by:** Jay, closing the "own decision-log entry" D23 deferred ·
**Status:** final — the fix is live in `services/gateway-service/src/main/resources/application.yml`
and verified against the running mesh, not just reasoned about

**The diagnostic D23 asked for, run.** Rebuilt `gateway-service` with a disposable
`CB_CONFIG_DUMP` `CommandLineRunner` (same convention as D18/D23's, worktree-only, deleted
before this commit) and set `infra/.env` to a real W5 sweep (`CB_SLIDING_WINDOW_SIZE=5`,
`COUNT_BASED`) — the specific case D23's own dump hadn't isolated (D23 tested at W20/W10).
Result, pre-fix, all three gateway breakers identical:

```
slidingWindowType=COUNT_BASED slidingWindowSize=5 minimumNumberOfCalls=1000000
failureRateThreshold=100.0 slowCallRateThreshold=100.0 slowCallDurationThreshold=PT1M
waitDurationInOpenStateMs=5000 permittedCallsInHalfOpen=5 autoTransitionEnabled=true
rejected(4xx)Recorded=false rejected(4xx)Ignored=true unavailable(5xx)Recorded=true
```

**D23 is right as written, at W5 too** — `slidingWindowSize` tracks the swept value (5), not
the library default (100). The hardcoded `minimum-number-of-calls: 1000000` gate is silently
capped by `min(1000000, slidingWindowSize)` = `slidingWindowSize` exactly as D23's bytecode
analysis predicted.

**The three other gaps flagged alongside the diagnostic turned out not to be gaps.**
`record-exceptions`/`ignore-exceptions`, `wait-duration-in-open-state`,
`permitted-number-of-calls-in-half-open-state`, and
`automatic-transition-from-open-to-half-open-enabled` were all unset on `measurement-plane`
too — and the live dump shows every one of them **also** silently inherited from
`configs.default`'s real values (the 4xx firewall is present: `DownstreamRejectedException`
tested `Ignored=true`/`Recorded=false`, `DownstreamUnavailableException` tested
`Recorded=true`; `waitDurationInOpenStateMs=5000` and `permittedCallsInHalfOpen=5` both match
`default`'s then-current swept/env values, not the library defaults of 60000ms/10;
`autoTransitionEnabled=true` matches `default`'s hardcoded value). D23's 2.2.0
implicit-fallback mechanism isn't scoped to the two window fields it was originally verified
against — it's whole-config: **any field `measurement-plane` doesn't set, it gets from
`configs.default`, not from Resilience4j's library defaults.** This resolves the "23.7s
OPEN→HALF_OPEN matches neither 60s nor 30s cleanly" puzzle without further mystery: gateway's
wait-duration-in-open-state was never a fixed 60s to begin with, it was whatever `default`'s
swept value was at the time of that trace — the 23.7s figure is a gap between two different
breakers' transition timestamps (order's OPEN to gateway's own later HALF_OPEN), not a
single breaker's wait-duration measured from its own OPEN.

**The fix — pin everything explicitly, in both directions, switch to `TIME_BASED`.**
`measurement-plane` now sets `sliding-window-type: TIME_BASED`, `sliding-window-size: 600`,
`minimum-number-of-calls: 1000000` (now genuinely unreachable — `TIME_BASED` has no
ring-buffer-fill bypass, D18), plus explicit `wait-duration-in-open-state: 60s`,
`permitted-number-of-calls-in-half-open-state: 10`,
`automatic-transition-from-open-to-half-open-enabled: false`, `event-consumer-buffer-size`,
and the same `record-exceptions`/`ignore-exceptions` pair `default` uses. No field is left to
inherit from anywhere, in either direction — the ambiguity that caused this is removed, not
just patched around for the current parameter grid.

**Live-verified, not just rebuilt.** Post-fix dump, all three gateway breakers:

```
slidingWindowType=TIME_BASED slidingWindowSize=600 minimumNumberOfCalls=1000000
failureRateThreshold=100.0 slowCallRateThreshold=100.0 slowCallDurationThreshold=PT1M
waitDurationInOpenStateMs=60000 permittedCallsInHalfOpen=10 autoTransitionEnabled=false
rejected(4xx)Recorded=false rejected(4xx)Ignored=true unavailable(5xx)Recorded=true
```

Then a real fault run through the actual harness (`experiments/runner.py --mode canary
--only-ids LIN-LAT-CNT-T70-W20-D30 --replicates 1` — canary's own "Extreme Conservative"
config, `COUNT_BASED`, `wait_duration=30`, `window_size=20`, writing to the disposable
`data/canary_runs.csv`/`canary_cb_transitions.jsonl`, not the real dataset): 60 requests
against a 3000ms latency fault, 17/60 failed (28.3% error rate) — order's own breaker engaged
normally. `gateway-service`'s `/actuator/circuitbreakerevents`: `orderServiceCB` recorded 310
real `SUCCESS`/`ERROR` call events (`bufferedCalls=310, failedCalls=42` by run's end,
`failureRate` still `-1.0%` — never evaluated, exactly as intended) and **zero**
`CLOSED_TO_OPEN` events; `inventoryServiceCB`/`paymentServiceCB` (not on the fault path) show
zero events at all. `failureRateThreshold` reads back `100.0%` live, not the swept run's `70%`
— confirms `measurement-plane` is no longer touched by the sweep's env vars in any field.

**Scope check — is `measurement-plane` the only place this shape exists?** `grep -rn
"base-config" services/`: every instance in `order-service`, `inventory-service`,
`payment-service`, and `notification-service` declares `base-config: default` explicitly.
`measurement-plane` was the only *named, non-`default`* config profile with no `base-config`
of its own anywhere in the codebase — the one shape that exercises 2.2.0's implicit-fallback
branch at all. **Not a repo-wide pattern, confined to the one block now fixed.**

**Consequence for the paper.** D23's finding (gateway silently tripped under `COUNT_BASED`,
`wait_duration∈{15,30}`, 20/73 sidecar records) describes the *pre-2026-09-18* mesh state and
is unaffected by this fix — historical data keeps its D23/D24 correction. Any run collected
**after** this commit has a gateway that structurally cannot trip (`TIME_BASED`, `minimumNumberOfCalls`
genuinely unreachable) — if D15/D-001 gets re-derived post-FANOUT-CRASH on freshly collected
data, that re-collection inherits the fix and the D23 gateway-contamination caveat no longer
applies to it. Worth a one-line note wherever the re-derivation happens, not a rewrite of D23/D24.

**Rejected:** touching `hypotheses.md`'s H6 disposition here. D23 already corrected the
isolation claim's text; whether H6 becomes newly untestable (isolation now genuinely holds,
same as it does for `TIME_BASED` sweeps already) or stays as D23 left it is a separate
decision, not made in this entry.

**Revisit if:** a future config change reintroduces a named, non-`default` profile without an
explicit `base-config` — `grep -rn "base-config" services/` is now the fast way to check for
that shape before it becomes a silent leak again.

---

## D27 · Novelty claim checked against the literature — reframed as systematic characterization, not first observation

**Date:** 2026-09-20 · **Decided by:** Jay, closing task T1 ("Verify the novelty claim") ·
**Status:** final — search evidence is [`docs/paper/related-work.md`](related-work.md)

**The claim had never been checked.** T1's brief paraphrase — "no prior work treats the
count/time window distinction at the application library layer" — doesn't appear verbatim
anywhere in the repo. The actual, live claim is `README.md:13`'s already-hedged "a dimension
largely absent from existing Resilience4j empirical literature." No `docs/paper/related-work.md`,
bibliography, or decision-log entry existed before this one; the claim was written from project
notes and never checked against a source outside the repo.

**Search run.** The five query terms from the task (`"sliding window" + circuit breaker`,
`failure-rate estimation + microservice resilience`, `Resilience4j empirical`, `circuit breaker
misconfiguration`, `"minimumNumberOfCalls"`) across Consensus, Firecrawl's arXiv-affiliated
paper search, and targeted web search against the named venues (ICPE, ICSA, ISSRE, Middleware,
SoCC, ASE, ICSE SEIP, IEEE Access, SPE, EMSE, arXiv), plus the Resilience4j GitHub issue/discussion
tracker. Full near-miss table with URLs and differentiation notes: `related-work.md`.

**Finding.** No prior work isolates `COUNT_BASED` vs `TIME_BASED` sliding-window type as the
studied independent variable in a live-instrumented, controlled empirical study of an
application-layer resilience library. The nearest work (Aderaldo et al.'s ResilienceBench
family, *SPE* 2024/2025) is methodologically closest — controlled, live, real Resilience4j/Polly
— but sweeps retry/workload parameters, never window type. Model-based work (Mendonça et al.,
ICSA 2020) covers CB parameter tuning but isn't live-instrumented. One study at the adjacent
infrastructure layer (Bansal et al. 2025, Envoy service mesh) does controlled live fault
evidence for circuit thresholds — one layer down from where CascadeShield sits. The Resilience4j
maintainer tracker (issues #1731, #1349, discussion #1815) shows the count/time distinction's
behavioral quirks are known operationally to practitioners, but not characterized as a research
question with controlled, replicated evidence.

**Decision — the novelty sentence.** Reframe as **first systematic empirical characterization
of the count/time window distinction, with live instrumented evidence** — not "first
observation" (practitioners have observed pieces of this on the issue tracker) and not an
unqualified "no prior work exists" claim (adjacent empirical and model-based work exists; none
of it is this specific comparison at this layer with this rigor). `README.md:13` updated to
this framing in the same commit as this entry.

**Rejected:** leaving the claim as an unverified assertion until manuscript writing starts.
T1 was rated blocking specifically because a wrong novelty claim is worse than a delayed one —
closing it now, before H3/H4/H5 prose is drafted, means the paper's contribution paragraph can
be written directly from `related-work.md` instead of from memory.

**Revisit if:** the manuscript's actual Related Work section, once drafted, needs citations
beyond this near-miss table (e.g., a reviewer names a specific paper this search missed) — add
it to `related-work.md` as a new row, don't reopen this entry.
