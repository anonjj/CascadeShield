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

**Date:** Day 2 (Tue 11 Aug 2026) · **Decided by:** Soham + Jay, jointly · **Status:** ⏳ PENDING CANARY

> **This entry is not yet a decision.** It is filled in from
> `analysis/out/canary_readout.json` the evening the canary finishes, and closed before
> midnight on Day 2.

### Gate table

| Canary outcome | Paper | Days 3–7 pivot |
|---|---|---|
| Crossover $\lambda^*$ visible **and** variance gap significant at matched $H$ | **A — "The Window Is an Estimator."** H1/H2 core, H3/H5 supporting | Full sweep includes $\lambda$. Target ICPE / IEEE Access |
| Crossover visible, variance gap not significant | **A′** — H2 alone: static window configuration is correct at exactly one traffic level | Same sweep, narrower claim |
| No $\lambda$ effect at all | **B — construct validity.** H3 + H5 + H4 + metric evolution | Drop $\lambda$. Days 3–4 go to FAN_OUT + TREE breadth |

`analysis/canary_readout.py` prints the recommendation directly. Its three branches are verified
against synthetic data (`--self-test`); the gate logic is not decided by hand at 23:00.

### Preconditions — check these before reading the gate

- [ ] **$\lambda$ fidelity.** `lambda_achieved` recorded, and within 15% of target. If it was
      never recorded, **H1 and H2 cannot be claimed at all** — the independent variable is
      unmeasured. This is a hard blocker, not a caveat, and it is Jay's Day-2 instrumentation.
- [ ] **Monotone trip rate.** If trip rate *falls* as $\lambda$ rises for either window type,
      no mechanism explains that. Stop and diagnose the harness before reading anything else.
- [ ] **`precondition_ok`** true on every row (breakers asserted CLOSED before each run).
- [ ] **Mode-mixing check.** Per the leak audit, TIME_BASED $t_{\text{open}}$ is bimodal
      (−2.70 s displacement, 4 configs). Before claiming H1, establish whether any variance gap
      is a **sampling property** or a **mixing proportion between two discrete modes**. If it is
      mixing, H1 as stated is not supported and the finding is different — and more interesting.

### To be filled in

```
Decision:              Paper ___
H2 crossover:          TIME_BASED ___ (bracket: lambda in [___, ___] req/s)
                       COUNT_BASED ___ (must be absent for H2 as stated)
H1 at matched H:       Welch p = ___ (Holm ___), difference ___ s, 95% CI [___, ___]
                       Brown-Forsythe W = ___, p = ___ (Holm ___)
                       sd COUNT ___ vs TIME ___, Cliff's delta ___ (___)
Mode-mixing verdict:   ___
phi (false-trip rate): ___ [___, ___] over ___ null-fault runs
lambda fidelity:       ___ of ___ runs off target; worst deviation ___
Signed:                Soham ___  Jay ___
```

**Not reopened on Day 4.** The Day-4 gate decides whether the *data* supports the chosen paper.
It does not reconsider which paper.

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

## D14 · `machine_id` is added to the canonical schema, before `excluded_reason`

**Date:** 27 Aug 2026 · **Status:** final

**Decision.** `machine_id` is added to the canonical schema as a nullable string: a free-form
label for the machine or Codespace that produced the row (e.g. `codespace-abc123`). Blank —
never `0`, never a sentinel — when the harness did not record one, per D8's blank rule. It is
provenance, never a feature: `preprocessing.py`'s `FEATURE_COLUMNS` is an explicit allow-list,
so an unlisted column cannot reach a model. Note it is **not yet** added to that module's
`PROVENANCE_COLUMNS` either — today it simply rides along unreferenced, which is safe but
means `machine_id` is not currently loaded for the D6 grouping that motivates it.

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