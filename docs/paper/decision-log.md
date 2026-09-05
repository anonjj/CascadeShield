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

---

## D16 · Cross-machine confounding — calibrate before splitting the topology sweep across boxes

> Renumbered from this branch's original D-008 alongside D15 above. The `machine_id`
> instrumentation this decision calls for is now formalized in D14's exact schema position
> and `_with_extra_columns()` fix — this entry's calibration protocol and interim
> no-cross-topology-timing-claim rule stand independently of that schema detail.

**Date:** 2026-08-26 (ad hoc D6 investigation, outside the Day 1–5 cadence) · **Decided
by:** Jay · **Status:** final (protocol + interim rule), pending the calibration run itself

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

**Numbers:** none yet — `analysis/machine_calibration.py --self-test` passes (3/3 fixture
checks: negligible-offset pair reads `MACHINE_EFFECT_NEGLIGIBLE`, ~3s-offset pair reads
`MACHINE_EFFECT_DETECTED`, single-machine input reads `SKIPPED_NO_CALIBRATION_DATA` rather
than a fabricated verdict). No real calibration data exists in this environment — neither
machine is available here.

**Rejected:** (a) same box, sequential — throws away the two machines' wall-clock
parallelism for no stated benefit once (c) costs ~2–3h and the analysis to read it already
exists and is self-tested.

**Scope boundary:** `order_leg` / blast-radius-style ratios (D15) are **not** gated by
this rule — treated as low machine-sensitivity per the original framing, only the timing
DVs are restricted.

**Consequence:** `machine_id`'s addition to `DATASET_HEADERS` header-mismatches the
existing 80-row `data/master_dataset.csv`. That file already needs a fresh restart once a
FAN_OUT/dual-machine sweep begins (LINEAR-only today, per D15's topology-count check) —
this is the same restart happening for one more reason, not new breakage.

**Revisit if:** the calibration block is run and `analysis/machine_calibration.py` returns
`MACHINE_EFFECT_NEGLIGIBLE` — cross-topology timing claims may then proceed, citing the
JSON. If it returns `MACHINE_EFFECT_DETECTED`, the paper either applies the measured
per-machine offset as a stated correction or keeps option (b) permanently for that DV pair.

---

## D18 · H2b (occupancy ratio) holds for TIME_BASED, is cleanly falsified for COUNT_BASED

> Numbered D18 to avoid colliding with D17 (leg-metric-blending finding, PR #39), which is
> still open/unmerged at the time this was written. Renumber if the two land in a different
> order.

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

