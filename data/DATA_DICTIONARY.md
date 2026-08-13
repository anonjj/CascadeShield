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
| **Control DVs** *(mandatory)* | $\phi$ false-trip rate (derived from `fault_type = NONE` rows), missed-detection rate, `flap_count` *(pending, Jay)* | Without $\phi$ no configuration in this paper may be described as safe. |
| **Provenance** | `experiment_id`, `environment`, `mode`, `replicate`, `run_timestamp`, `permitted_calls_half_open`, `run_index`, `run_order_seed`, image digests *(pending, Jay)* | Never model features. |
| **Validity** | `excluded_reason`, `precondition_ok` *(pending, Jay)*, `warmup_requests` / `warmup_duration_s` *(pending, Jay)* | Rows are marked, never deleted. |

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
**Planning file:** `data/experiment_matrix.csv` (the 486 planned configurations).

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
| `fault_type` | categorical | `LATENCY`, `CRASH`, `THROTTLE` | — | one-hot |
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

> **20-column real file.** The live `master_dataset.csv` carries five columns beyond the
> original 15-column skeleton: `permitted_calls_half_open` and `mode` (operational),
> `real_blast_radius` and `leg_failure_rates` (the request-level containment metric and the
> raw vector behind it), and `excluded_reason` (quarantine). `preprocessing.py` recognises
> the operational ones as provenance and excludes them from features.
> `data/master_dataset_schema.csv` is the header-only skeleton and tracks
> `runner.DATASET_HEADERS` exactly — if they disagree, `log_results` refuses to append.
>
> Jay's Day-1/Day-2 columns land in this same list and need dictionary entries in the
> commits that add them: `precondition_ok`, `warmup_requests`, `warmup_duration_s`,
> `run_index`, `run_order_seed`, `lambda_target`, `lambda_achieved`, `lambda_cv`,
> `effective_horizon`, `flap_count`, and the pinned image digest set.

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
