# CascadeShield — Master Dataset Schema (Data Dictionary)

> 🔒 **FROZEN Day 1 (Mon 10 Aug 2026) against the §1.4 metrics contract in
> `docs/paper/hypotheses.md`.** This file is the contract, not a description of it. Every
> column added from here on requires an entry **in the same commit** that adds the column.
> No column changes without a `docs/paper/decision-log.md` entry.

## The metrics contract (frozen)

| Class | Columns | Rule |
|---|---|---|
| **Primary DVs** | `time_to_open`, `time_to_recover` | Every reported mean carries a bootstrap CI. |
| **Secondary DVs** | `leg_failure_rates` (continuous severity), `blast_radius` / `real_blast_radius` (quartized), `throughput_loss`, p95/p99 client latency *(pending)* | $B_{\text{real}}$ is reported **as a function of $\tau_{\text{leg}}$**, never at one pinned threshold — see `analysis/tau_sweep.py` and decision D-001. |
| **Control DVs** *(mandatory)* | $\phi$ false-trip rate (from `fault_type = NONE` rows ✅), missed-detection rate, `flap_count` *(pending, Jay)* | Without $\phi$ no configuration in this paper may be described as safe. |
| **Provenance** | `experiment_id`, `environment`, `mode`, `replicate`, `run_timestamp`, `permitted_calls_half_open`, `run_index` ✅, `run_order_seed` ✅, image digests *(pending, Jay)* | Never model features. |
| **Validity** | `excluded_reason` ✅, `precondition_ok` / `precondition_fail_reason` / `readiness_wait_s` / `cb_state_pre` / `buffered_calls_pre` ✅, `warmup_requests` / `warmup_duration_s` ✅ | Rows are marked, never deleted. `precondition_ok = False` means the run never happened; `excluded_reason` means it happened but is untrustworthy. Analyses drop both. |
| **λ factor** | `lambda_target`, `lambda_achieved`, `lambda_cv`, `lambda_deviation_flag`, `effective_horizon` ✅ (PRs #16–#18) | H1 and H2 are claims *about* $\lambda$, so results are reported against `lambda_achieved` and never `lambda_target`. `analysis/canary_readout.py` refuses to report H1/H2 at all if `lambda_achieved` is absent, and takes its off-target verdict from `lambda_deviation_flag` rather than recomputing it — the harness sees per-request dispatch timestamps this layer cannot. |

> **`effective_horizon` is continuous — do not group on it directly.** It is derived from
> `lambda_achieved`, so no two runs share a value and any group-by puts each run in a bucket
> of one. H1 contrasts are grouped on the horizon each run was *designed* at
> (`effective_horizon_nominal`, from `data/canary_matrix.csv`), with the achieved mean
> reported alongside — a cell designed at H = 100 that delivered 60 is a finding, not a
> rounding detail. See `h1_matched_horizon()` in `analysis/canary_readout.py`.

Standing rules:

1. Nulls in `time_to_open` / `time_to_recover` are **outcomes**, not missing data — never
   mean-imputed. Under H2 the null *is* the measurement.
2. Effective sample size is the number of **configurations**, not rows. Pooled CIs use the
   cluster bootstrap in `analysis/common.py`.
3. Every $p$-value is reported with an effect size. No bare $p$-values.
4. The four dataset files below are **never pooled**. Their metric regimes differ; the column
   names do not, so `runner.log_results`' header guard will not catch a mixed append.

## Dataset files and what each is good for

| File | Rows | Timing | `blast_radius` | Usable for |
|---|---:|---|---|---|
| `master_dataset.csv` | 80 | ✅ | 4-subject denominator | Everything. 79 rows analysable after quarantine. |
| `master_dataset_v2_latency_5svc.csv` | 162 | ✅ | 5-subject, **disjoint from leg node set** | H3 timing (160 rows after quarantine). Not containment. |
| `master_dataset_v3_gateway_not_rebuilt.csv` | 92 | ✅ | ❌ **constant offset, 95.7% of rows** | Timing only. `blast_radius` / `real_blast_radius` must not be used as outcomes. |
| `master_dataset_v1_prefix.csv` | 486 | ❌ **100% null** | raw 0–100 percent, 5-subject | **Nothing.** No timing was ever collected. Provenance only — never source a claim to it. |

See `docs/paper/leak-audit.md` for how each verdict was reached.

---

> ⚠️ **ARCHIVED DATASET — NOT COMPARABLE ACROSS THE METRIC CHANGE.**
> `data/master_dataset_v2_latency_5svc.csv` holds the **162 LATENCY runs** from the first
> LINEAR sweep under the fixed harness. Their `blast_radius` and `real_blast_radius` were
> computed against a **5-service denominator** (the five downstream services, and — for
> `real_blast_radius` — a leg set that also included the gateway). After the blast-radius
> metric change (gateway removed from the sweep as the measurement plane; denominator
> redefined to the **4 CB-bearing downstream services**: order, inventory, payment,
> notification), those values are on a different scale and are **NOT comparable** to any run
> produced afterward. The two must never be pooled into one file: the CSV column names are
> unchanged, so `runner.log_results`' stale-header guard will NOT catch a mixed append. The
> next sweep must start a **fresh** `data/master_dataset.csv`; this archive is read-only.

**Status:** Defined (Week 1). **Lock target:** end of Week 2 — no column changes after that.
**Primary file:** `data/master_dataset_schema.csv` (header-only skeleton; experiments append rows).
**Planning file:** `data/experiment_matrix.csv` (486 fault-bearing configurations —
`LATENCY`/`CRASH`/`THROTTLE` — plus 162 `NONE` no-fault control configurations, 648 total).

> 🔄 **SWEEP IN PROGRESS — current `master_dataset.csv` is a partial rebuild.**
> After the blast-radius metric change the dataset was reseeded from empty, and collection is
> still underway: **80 rows, `LINEAR` / `LATENCY` only** — one cell of the planned 486-config
> matrix. Because that cell has not yet produced a run with zero tripped subjects, every row
> currently labels `unsafe` and the classifier target is **single-class, so the Decision Tree
> classifier is not trainable yet**. This is sweep incompleteness, not a threshold problem —
> τ is set from the measurement scale (see *How the two models use these columns*) and does
> not need adjusting. The regressor and Isolation Forest paths are unaffected. Expect two
> classes once the sweep reaches configs that contain the fault.

## Row identity

A single row = **one execution** of one configuration in one environment.

The unique key is the triple **(`experiment_id`, `environment`, `replicate`)**, *not* `experiment_id`
alone. There are **486 unique configurations**; with environments and replicates the table grows
past 486 (e.g. 486 configs × 2 environments × 3 replicates = 2,916 rows).

`486 = 3 (topology) × 3 (fault_type) × 2 (window_type) × 3 (threshold) × 3 (window_size) × 3 (wait_duration)`

---

## Columns

### Key

| Column | Type | Example | Notes |
|--------|------|---------|-------|
| `experiment_id` | string | `LIN-LAT-CNT-T50-W50-D10` | Deterministic from the 6 config fields. Identifies the configuration, not the row. |

### Independent variables — swept config → **Decision Tree input features**

| Column | Type | Valid values | Unit | ML encoding |
|--------|------|--------------|------|-------------|
| `topology` | categorical | `LINEAR` (planned: `FAN_OUT`, `SHARED_DEP_MESH`) | — | one-hot |
| `fault_type` | categorical | `LATENCY`, `CRASH`, `THROTTLE`, `NONE` | — | one-hot (`NONE` excluded — see note below) |
| `window_type` | categorical (binary) | `COUNT_BASED`, `TIME_BASED` | — | binary (0/1) — **the primary novelty variable** |
| `threshold` | int | `{30, 50, 70}` (range 1–100) | percent | numeric |
| `window_size` | int | `{5, 10, 20}` (range 1–1000) | **calls if COUNT_BASED, seconds if TIME_BASED** | numeric (see note) |
| `wait_duration` | int | `{5, 15, 30}` (range 1–600) | seconds in OPEN state | numeric |

> **Sweep vs. plan.** The values above reflect the **real sweep grid** (what `runner.py`
> actually sweeps), not `experiment_matrix.csv`, which still lists the originally *planned*
> grid (`LINEAR_CHAIN`/`FAN_OUT`/`SHARED_DEP_MESH`, `window_size {10,50,100}`,
> `wait_duration {5,10,30}`) and is kept only as historical documentation.
> `ml/generate_synthetic_data.py` builds its config grid directly from
> `ml/preprocessing.py`'s constants (not from `experiment_matrix.csv`) so it stays
> schema-identical to the real grid. **`data/master_dataset.csv` holds real measured
> runs** — 80 rows over 26 LINEAR/LATENCY configurations, collected 1 Aug 2026. The earlier
> synthetic placeholder is gone; do not reintroduce `generate_synthetic_data.py` output into
> this file.

> **`fault_type=NONE` — the no-fault control condition.** Without it, a config reading
> `blast_radius=0` under a real fault is not distinguishable from a config that would read 0
> regardless of whether anything actually happened — "safe" is only a meaningful claim
> relative to a baseline false-trip rate (**phi**), which requires actually running the mesh
> with no fault injected. `runner.py --fault none` runs this control condition (`inject_fault`
> is a deliberate no-op; Toxiproxy stays clean for the whole window) and **enforces
> `--replicates >= 10`** for every config when selected (`MIN_NONE_FAULT_REPLICATES` in
> `runner.py`) — under-sampling the control defeats the reason to collect it. `NONE` is
> deliberately **not** in `ml/preprocessing.py`'s `FAULT_TYPES`: it isn't a fault the
> recommender should learn to react to, and one-hot-encoding it would silently produce an
> all-zero row indistinguishable from an unrecognised category. `load_dataset()` drops
> `fault_type=NONE` rows before returning (same pattern as the `precondition_ok=False`
> filter above) — compute phi directly from the raw CSV instead of through that function.
> `experiments/compute_phi.py [path/to/dataset.csv]` does exactly that: it reads the raw
> CSV directly (stdlib only, same convention as `validate_gate.py`), keeps only valid
> `fault_type=NONE` rows (`precondition_ok=True` — an aborted run measured nothing and
> would silently deflate phi if counted as "no trip"), and reports phi overall, per
> topology, and per swept config (flagging any config with `blast_radius > 0` — a
> confirmed false trip under no fault at all — and any config sampled below
> `MIN_NONE_FAULT_REPLICATES`). Unlike `validate_gate.py`, this is a report, not a
> pass/fail gate: there is no established "acceptable" phi threshold yet, so it always
> exits 0 on a successful read (2 if the dataset file is missing, 1 if it has no usable
> `fault_type=NONE` rows).

> **`window_size` unit warning.** Its meaning *changes with `window_type`*: a value of `50` means
> "50 calls" under COUNT_BASED but "50 seconds" under TIME_BASED. The raw number is therefore not
> directly comparable across window types. Handle this in feature engineering (see
> `ml/feature_engineering.md`) — do not feed the raw column to the model as if it were one scale.

### Operational / provenance — not features, but required for analysis

| Column | Type | Valid values | Notes |
|--------|------|--------------|-------|
| `permitted_calls_half_open` | int | `{5}` in this sweep (range ≥ 1) | Half-open probe budget — a **fixed** CB knob, not swept. Carried for provenance; **excluded from features**. |
| `environment` | categorical | `LOCAL`, `AWS` | **Required for the ±15% divergence claim** — that metric is a per-config LOCAL-vs-AWS comparison. |
| `mode` | categorical | `full` (this sweep); e.g. `canary` | Run mode/batch label. Carried for provenance; **excluded from features**. |
| `replicate` | int | `1..R` (R ≥ 3 recommended) | Repeat index. Enables mean ± variance per config instead of a single noisy run. |
| `run_timestamp` | string (ISO 8601) | `2026-06-21T14:32:05Z` | Provenance. Never used as a model feature. |

> **29-column schema.** Beyond the original 15-column skeleton the schema now carries:
> `permitted_calls_half_open` and `mode` (operational); `real_blast_radius` and
> `leg_failure_rates` (the request-level containment metric and the raw vector behind it);
> the precondition-gate and warmup block (`precondition_ok`, `precondition_fail_reason`,
> `readiness_wait_s`, `cb_state_pre`, `buffered_calls_pre`, `warmup_requests`,
> `warmup_duration_s`); run-order randomization (`run_order_seed`, `run_index`); and
> `excluded_reason` (quarantine, always last).
> `preprocessing.py` recognises the operational ones as provenance and excludes them from
> features, and its `load_dataset()` only checks that required columns are *present*, so
> extras ride along without breaking the contract.
>
> `data/master_dataset_schema.csv` is the header-only skeleton and tracks
> `runner.DATASET_HEADERS` exactly — if they disagree, `log_results` refuses to append.
> **The live `master_dataset.csv` (80 rows) predates the precondition and run-order columns
> and therefore no longer matches**; that is intended, since the next sweep starts a fresh
> file. Do not "fix" it by padding columns onto historical rows.
>
> Still outstanding for the Day-2 canary: `lambda_target`, `lambda_achieved`, `lambda_cv`,
> `effective_horizon`, plus `flap_count` and the pinned image digest set. Each needs a
> dictionary entry in the commit that adds it.

### Dependent variables — measured outcomes → **targets / Isolation Forest inputs**

| Column | Type | Range | Unit | Null when… |
|--------|------|-------|------|------------|
| `blast_radius` | float | `0.0–1.0` | fraction | never null. **Primary outcome.** Fraction of the **four CB-bearing downstream subject services** (order, inventory, payment, notification) with an open circuit breaker during the fault window → values in `{0, 0.25, 0.5, 0.75, 1.0}`. **Denominator = 4** (changed from 5): `shared-db-service` is dropped (leaf, no outbound calls / no `@CircuitBreaker`, can never trip, only dilutes), and `gateway-service` is excluded as the *measurement plane*, not a subject — an edge breaker sees the summed chain latency and would always trip first (the "gateway CB confound"). Emitted as a 0.0–1.0 fraction: `BlastRadiusService` returns 0–100 and `runner.py`'s `get_blast_radius()` normalises before writing — `preprocessing.py` does not rescale again (`BLAST_RADIUS_SCALE = 1.0`). **Not comparable** to the archived `master_dataset_v2_latency_5svc.csv` (5-service denominator). |
| `time_to_open` | float | `≥ 0` | seconds | CB never opened (threshold not reached / fault too mild) → **null is meaningful, not missing** |
| `time_to_recover` | float | `≥ 0` | seconds | system did not return to baseline within the observation window → null is meaningful |
| `error_rate` | float | `0.0–1.0` | fraction | never null. Peak error rate across the mesh during the fault. |
| `throughput_loss` | float | `0.0–1.0` | fraction | never null. Fractional drop in successful TPS vs the pre-fault baseline. |

### Validity / quarantine

| Column | Type | Valid values | Notes |
|--------|------|--------------|-------|
| `excluded_reason` | string | `""` (analysable) or a `+`-joined list of the codes below | **Written only by `analysis/quarantine.py`, never by a run** — `runner.py` always emits it empty. Rows are marked rather than deleted so a reviewer can see exactly what was excluded and why; a silently dropped row is indistinguishable from one never collected. Every analysis in `analysis/` drops these rows by default (`common.load(..., apply_exclusions=True)`); pass `apply_exclusions=False` to count them. |

Exclusion codes:

| Code | Meaning | Detected by |
|---|---|---|
| `STATE_LEAK_EARLY_OPEN` | Breaker entered the run already OPEN. `time_to_open` under half its cell median and ≥ 1 s early, against a MAD-based scale pooled within window type. | `analysis/leak_audit.py` S1, SEVERE tier |
| `STATE_LEAK_BLAST` | More subjects reported OPEN than there are legs with any observed failure — a breaker cannot sit OPEN while its own leg records zero failed-or-rejected calls. | `analysis/leak_audit.py` S2 |
| `RECOVERY_TIMEOUT_HANG` | `time_to_recover` above the 120 s protocol cap. The archive's worst case is 7540.5 s (2.1 h) where every other row tops out at 65.7 s. | `analysis/quarantine.py` |

Deliberately **not** excluded, and why:

- **`RECURRENT_MODE` hits.** A displacement that reproduces across ≥ 3 configurations is a
  property of the instrument, not contamination. TIME_BASED `time_to_open` is bimodal (−2.70 s,
  four configurations); excluding those rows would delete a finding that bears on H1.
- **Whole datasets whose S2 rate exceeds 50%.** That is a constant offset in the metric, not
  per-run contamination. The *column* is marked unusable and the rows are kept — see the file
  table at the top.

> **Meaningful nulls.** `time_to_open` / `time_to_recover` are null *because of a real outcome*
> (the breaker never tripped, or the system never recovered), not random missingness. Do **not**
> mean-impute them. Either carry a companion boolean (`cb_opened`, `recovered`) or use an explicit
> sentinel — decide this in feature engineering before model training, not after.

### Breaker-state-reset precondition columns

The highest-priority harness bug found so far: circuit breaker state was observed carrying
over between replicates of an **identical** config — one `LIN-LAT-CNT-T30-W20-D5` replicate
tripped in 0.303s with three legs at exactly `0.0000` failure rate, against 6.256s/6.138s for
its identical siblings, consistent with a breaker that started the run already
OPEN/near-tripped rather than one that tripped fresh off real failures inside the run's own
window. `update_containers()` already force-recreates every container before every run, which
*should* reset Resilience4j's in-memory registry — these columns make that reset explicit
(`POST /actuator/circuitbreakers/{name}` → `transitionToClosedState()`) and record the
verification against ground truth (`GET /actuator/circuitbreakers`) instead of trusting the
recreate blindly.

| Column | Type | Range | Notes |
|--------|------|-------|-------|
| `precondition_ok` | bool | `True`/`False` | never null. `False` means the run was aborted **before fault injection** — every outcome column above (`blast_radius`, `error_rate`, ...) is blank on that row, not `0.0`. Exclude these rows from training/analysis; they measure nothing. |
| `precondition_fail_reason` | string | e.g. `READINESS_TIMEOUT`, `order:inventoryServiceCB=state:OPEN`, `order:inventoryServiceCB=buffered:10` | `""` when `precondition_ok=True`. `state:X` = breaker didn't reset to CLOSED; `buffered:N` = breaker read CLOSED but still carried buffered calls from the prior run's window (the direct signal that force-recreate did not actually reset that service's JVM); `UNREACHABLE` = actuator endpoint didn't respond; `READINESS_TIMEOUT` = one or more of the six services never reported `/actuator/health` UP. |
| `readiness_wait_s` | float | `≥ 0` | never null. Wall-clock seconds spent polling all six services (including `shared-db-service`, which has no breaker of its own but sits in every call chain) before proceeding or hitting the readiness deadline. |
| `cb_state_pre` | string | `"service:breaker=STATE;..."` | Per-breaker state from `GET /actuator/circuitbreakers`, read immediately after the reset attempt, for all five CB-bearing services. Ground truth, not an inference from health or from the recreate having merely been attempted. |
| `buffered_calls_pre` | string | `"service:breaker=N;..."` | Per-breaker `bufferedCalls` from the same read. `0` on a genuinely fresh container; non-zero is the direct test of whether `update_containers()`'s force-recreate is doing what its docstring assumes. |

> **`precondition_ok=False` rows are filtered before training, not just documented.**
> `ml/preprocessing.py`'s `load_dataset()` drops them automatically (with a logged warning
> naming the file and count) whenever the `precondition_ok` column is present, so a blank
> `blast_radius` never silently reaches the encoders as a fabricated value. Datasets from
> before this fix (no `precondition_ok` column at all — synthetic data, archived pre-fix
> sweeps) are untouched by this filter; there is nothing in them to drop.

### JIT warmup columns

A cold Spring Boot JVM (interpreted bytecode, C1/C2 JIT not yet compiled the hot path) can
add 100ms+ latency to individual requests — noise on the same order as, or larger than,
some of what's measured here, and real contamination of a DV (`time_to_open`,
`time_to_recover`) whose true effects are single-digit seconds. `runner.py` now runs a
discard-phase warmup against the run's endpoint immediately after the breaker-reset
precondition passes and *before* the baseline throughput measurement — so that measurement
isn't itself contaminated — until **both** 200 requests have completed **and** 10 seconds
have elapsed (`WARMUP_MIN_REQUESTS` / `WARMUP_MIN_DURATION_S` in `runner.py`; "whichever is
longer" means neither floor may be skipped). Responses are read and discarded; nothing from
this phase feeds `blast_radius`/`error_rate`/etc.

| Column | Type | Range | Notes |
|--------|------|-------|-------|
| `warmup_requests` | int | `≥ 200` | never null on a `precondition_ok=True` row; blank on a `precondition_ok=False` row (aborted before warmup ran). Proves the warmup dose actually ran rather than merely asserting it. |
| `warmup_duration_s` | float | `≥ 10.0` | never null on a `precondition_ok=True` row; blank on a `precondition_ok=False` row. Wall-clock seconds the discard phase actually took (may exceed 10s if the request pacing made the 200-request floor the binding constraint). |

### Run-order randomization columns

Sequential execution of a long sweep on one host confounds treatment (config) with
thermal/memory drift over the sweep's wall-clock duration — later configs would
systematically run on a warmer/more-fragmented host, biasing exactly the comparison the
sweep exists to make. `runner.py`'s `main()` builds the full `(config, replicate)` run list
up front and shuffles it with `build_shuffled_run_list()` before executing anything, using a
dedicated `random.Random(seed)` instance (never the global `random` module, so nothing else
in the process can perturb the sequence). The seed defaults to a fresh value drawn from OS
entropy each invocation (`--seed` overrides it, e.g. to reproduce a specific order for
debugging) and is printed to stdout as well as persisted here.

| Column | Type | Range | Notes |
|--------|------|-------|-------|
| `run_order_seed` | int | — | never null. Same value on every row from one sweep invocation. Feed to `--seed` to reproduce the exact execution order. |
| `run_index` | int | `1..total_runs` | never null. The run's position in the **shuffled execution order**, not its position in the config/replicate grid — do not assume `run_index` correlates with `threshold`/`window_size`/etc.; that's the point. |

Unlike `warmup_requests`/`precondition_ok`/etc., these two are **never blank** — a run's
position in the sequence is known the moment it starts, independent of whether it goes on to
pass its precondition check, warm up, or measure anything.

### Achieved arrival-rate columns

`compute_load_plan()` sizes an offered rate (`target_rps`, i.e. λ) for the fault window, and
`generate_load()` paces its dispatch loop to hit it — but pacing is a request, not a
guarantee. Under a saturated thread pool (or a backend gone slow/hanging under the injected
fault itself), each `send_request` call queues behind the previous one, so the rate that
actually reaches the gateway can drift from what was requested. A config that "looks safe"
only because its offered load silently fell short of the nominal rate would be a false
negative that a nominal-rate-only comparison across configs could never catch — this is
measured, not assumed, precisely to close that gap.

`lambda_achieved` and `lambda_cv` are computed in `generate_load()` from each dispatched
request's actual send timestamp (post-queueing), not from the requested `interval_s`
schedule: `lambda_achieved = (n-1) / span` over the sorted dispatch timestamps, and
`lambda_cv` is the coefficient of variation (`stdev / mean`) across the inter-dispatch
intervals between them — a high CV flags a bursty/uneven offered rate even when its mean
happens to land on target.

| Column | Type | Range | Notes |
|--------|------|-------|-------|
| `lambda_target` | float | `> 0` | the requested rate for this run's fault-window load (`plan["target_rps"]`, defaults to `LOAD_RATE_RPS`). Blank on a `precondition_ok=False` row. |
| `lambda_achieved` | float | `≥ 0` | the measured rate, from real dispatch timestamps over the fault-window `generate_load()` call. Blank when fewer than `LAMBDA_MIN_REQUESTS_FOR_RATE` (3) requests were dispatched, or on a `precondition_ok=False` row. |
| `lambda_cv` | float | `≥ 0` | coefficient of variation across inter-dispatch intervals in that same window. `0` = perfectly even pacing; larger values mean burstier/uneven dispatch. Blank under the same conditions as `lambda_achieved`. |
| `lambda_deviation_flag` | bool | `True`/`False` | `True` when `abs(lambda_achieved - lambda_target) / lambda_target > LAMBDA_DEVIATION_THRESHOLD` (0.15, i.e. 15%). Blank (not `False`) when `lambda_achieved` couldn't be measured — absence of a measurement is not evidence of no deviation. **Rows with this flag `True` should be treated with the same suspicion as `precondition_ok=False` rows when comparing configs at their nominal rate** — the load that config actually received didn't match what the sweep asked for. |

### Effective horizon column

`window_size` means different things depending on `window_type`: for `COUNT_BASED` it's a
call count (the ring buffer is `window_size` calls deep), but for `TIME_BASED` it's a
duration in seconds — the window is whatever calls landed in the trailing `window_size`
seconds. `CB_MINIMUM_CALLS` (the harness's pinned `minimumNumberOfCalls`, see the CB config
columns above) is evaluated in the **call-count** unit either way, so a `TIME_BASED` window's
actual call count depends on the *achieved* arrival rate during the run, not the requested
one — the same rate `lambda_achieved` measures.

`effective_horizon` (H) makes that call count explicit rather than leaving it implicit and
config-dependent: `H = window_size` for `COUNT_BASED` (already denominated in calls); `H =
lambda_achieved × window_size` for `TIME_BASED` (rate × duration = calls actually observed).
A `TIME_BASED` run with `H < CB_MINIMUM_CALLS` never had enough calls in its trailing window
to evaluate the breaker at all during the fault window — a harness/load artifact that is
otherwise indistinguishable from a genuine "safe" (never tripped) outcome in `blast_radius`.

| Column | Type | Range | Notes |
|--------|------|-------|-------|
| `effective_horizon` | float | `≥ 0` | calls available to the sliding window during the fault window (see formula above). Blank on a `precondition_ok=False` row. For `TIME_BASED`, also blank whenever `lambda_achieved` is blank (can't derive an achieved-rate-based horizon without a measured rate). **Compare against `CB_MINIMUM_CALLS` (5) before trusting a `TIME_BASED` "safe" reading** — `H < CB_MINIMUM_CALLS` means the breaker's evaluation window never actually filled. |

---

## How the two models use these columns

- **Decision Tree recommender** — features = the 6 independent variables; target = a label derived
  from `blast_radius` (`safe` if `blast_radius ≤ τ`, else `unsafe`). Given a desired fault/topology, it
  recommends a CB config. Interpretability is the reason it was chosen over deep learning.
  - **τ = 0.1** (`DEFAULT_TAU` in `preprocessing.py`). The value follows from the
    **measurement scale**, not from any particular sweep's class balance. With a denominator
    of 4 CB-bearing subjects, `blast_radius` is quantised to quarters — `{0, 0.25, 0.5, 0.75,
    1.0}` — so its smallest non-zero value is `0.25`. Any τ in `(0, 0.25)` therefore draws the
    identical boundary, and `τ = 0.1` states the intended contract: **zero blast = safe, any
    subject tripped = unsafe**. `τ = 0.5` would *not* be a rescaling of that rule but a
    materially weaker one — "up to half the mesh may trip and still count as safe". If the
    subject denominator changes, re-check that τ still sits below one quantisation step.
    Tunable; see `ml/preprocessing.py`.
- **Isolation Forest anomaly detector** — fit on the outcome columns to flag config/outcome
  combinations that behave unexpectedly (e.g. a "safe-looking" config that produced a large
  blast radius). Feature set (see `ml/preprocessing.py → build_outcome_frame`):
  - Numeric (StandardScaler-normalised): `blast_radius`, `error_rate`, `throughput_loss`
  - Boolean flags for meaningful nulls: `cb_opened` (1 if `time_to_open` is non-null),
    `recovered` (1 if `time_to_recover` is non-null)
  - **`open_breaker_rate` is NOT an Isolation Forest feature** — it is not in the dataset
    schema and is not computed anywhere in the pipeline.

## Source of truth for outcome values

Each measured column maps 1:1 to a Prometheus metric scraped during the run (Jay's stack). The
`blast_radius` metric in particular **must** fire and be scrapable before any full sweep — confirm
this in the Week 2 metrics-exposure check.

**Current state:** `data/master_dataset.csv` is **real measured `runner.py` output** — 80 rows,
26 LINEAR/LATENCY configurations, collected 1 Aug 2026, one row quarantined. Train against it
with `python ml/train_all.py --no-generate`; `ml/generate_synthetic_data.py` is now only for
pipeline smoke tests and its output must never be written to this file.

**Regenerating every number in the paper.** No figure or statistic is produced by hand:

| Script | Produces |
|---|---|
| `analysis/leak_audit.py` | `out/leak_audit.json`, `out/leak_audit_rows.csv` — contamination prevalence per dataset |
| `analysis/quarantine.py --apply` | populates `excluded_reason`; `out/quarantine.json` |
| `analysis/tau_sweep.py` | `out/tau_sweep.json`, `out/tau_sweep.csv`, `figures/fig7_tau_sweep.{png,pdf}` — H4 |
| `analysis/canary_readout.py` | `out/canary_readout.json`, `figures/fig4*.{png,pdf}` — H1, H2, $\phi$, and the Day-2 gate |
| `experiments/canary_matrix.py` | `data/canary_matrix.csv` — the Day-2 run list with seeded order |

`analysis/common.py` holds the shared loaders and the bootstrap / effect-size helpers. It is the
only place that knows each archive's metric regime, which is what stops two files with identical
column names being pooled by accident.

## Sidecar: `data/cb_transitions.jsonl` (real runs only — not part of the ML schema)

`error_rate` / `blast_radius` cannot tell you whether an *interior* breaker (order,
inventory, payment, notification's own CBs on their downstream calls) actually opened —
Resilience4j trips on the slow-call-rate path independently of the failure-rate path, and
a call that takes longer than `slow-call-duration-threshold` (2s) but still returns 200
scores 0% failure rate while counting fully toward slow-call rate. Only the real
Resilience4j `STATE_TRANSITION` events settle that.

`runner.py` snapshots each breaker's `/actuator/circuitbreakerevents/{name}` ring buffer
before the fault and diffs it after the run, writing one JSON line per run to
`data/cb_transitions.jsonl` (`data/canary_cb_transitions.jsonl` in canary mode):

```json
{"experiment_id": "...", "topology": "LINEAR", "fault_type": "THROTTLE",
 "window_type": "COUNT_BASED", "environment": "LOCAL", "mode": "full", "replicate": 1,
 "fault_injected_at": "...", "fault_cleared_at": "...",
 "transitions": [
   {"service": "order", "breaker": "sharedDbCB", "state_transition": "CLOSED_TO_OPEN", "creation_time": "..."},
   ...
 ]}
```

Join to `master_dataset.csv` via (`experiment_id`, `replicate`, `mode`). `transitions` is
`[]` when no interior breaker opened during the run — that's a real, informative result,
not a missing record. Kept as a separate sidecar rather than new CSV columns because the
transition list is variable-length and ordered; not part of `preprocessing.py`'s schema
contract or fed to either model.

