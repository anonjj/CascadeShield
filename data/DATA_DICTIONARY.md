# CascadeShield — Master Dataset Schema (Data Dictionary)

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
> schema-identical to the real grid. **`data/master_dataset.csv` is currently
> synthetic placeholder data** — real measured data replaces it once a live sweep runs.

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

> **17-column real file.** The live `master_dataset.csv` carries two operational columns
> — `permitted_calls_half_open` and `mode` — beyond the original 15-column skeleton.
> `preprocessing.py` recognises them as provenance (excluded from features) so the file
> validates cleanly against the schema contract. Additional columns have since been
> appended for `real_blast_radius` / `leg_failure_rates` and the precondition gate below
> — `preprocessing.py`'s `load_dataset()` only checks that required columns are *present*,
> so extras always ride along without breaking the contract.

### Dependent variables — measured outcomes → **targets / Isolation Forest inputs**

| Column | Type | Range | Unit | Null when… |
|--------|------|-------|------|------------|
| `blast_radius` | float | `0.0–1.0` | fraction | never null. **Primary outcome.** Fraction of the **four CB-bearing downstream subject services** (order, inventory, payment, notification) with an open circuit breaker during the fault window → values in `{0, 0.25, 0.5, 0.75, 1.0}`. **Denominator = 4** (changed from 5): `shared-db-service` is dropped (leaf, no outbound calls / no `@CircuitBreaker`, can never trip, only dilutes), and `gateway-service` is excluded as the *measurement plane*, not a subject — an edge breaker sees the summed chain latency and would always trip first (the "gateway CB confound"). Emitted as a 0.0–1.0 fraction: `BlastRadiusService` returns 0–100 and `runner.py`'s `get_blast_radius()` normalises before writing — `preprocessing.py` does not rescale again (`BLAST_RADIUS_SCALE = 1.0`). **Not comparable** to the archived `master_dataset_v2_latency_5svc.csv` (5-service denominator). |
| `time_to_open` | float | `≥ 0` | seconds | CB never opened (threshold not reached / fault too mild) → **null is meaningful, not missing** |
| `time_to_recover` | float | `≥ 0` | seconds | system did not return to baseline within the observation window → null is meaningful |
| `error_rate` | float | `0.0–1.0` | fraction | never null. Peak error rate across the mesh during the fault. |
| `throughput_loss` | float | `0.0–1.0` | fraction | never null. Fractional drop in successful TPS vs the pre-fault baseline. |

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

**Current state:** `data/master_dataset.csv` is synthetic (`ml/generate_synthetic_data.py`), not
measured — see the `*** THIS DATA IS SIMULATED ***` notice in that script. It exists so the ML
pipeline can be developed and demonstrated before the real sweep lands; swap it for real
`runner.py` output (`python ml/train_all.py --no-generate`) once that sweep runs.

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
