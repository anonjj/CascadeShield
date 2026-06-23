# CascadeShield — Master Dataset Schema (Data Dictionary)

**Status:** Defined (Week 1). **Lock target:** end of Week 2 — no column changes after that.
**Primary file:** `data/master_dataset_schema.csv` (header-only skeleton; experiments append rows).
**Planning file:** `data/experiment_matrix.csv` (the 486 planned configurations).

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
| `topology` | categorical | `LINEAR_CHAIN`, `FAN_OUT`, `SHARED_DEP_MESH` | — | one-hot |
| `fault_type` | categorical | `LATENCY`, `CRASH`, `THROTTLE` | — | one-hot |
| `window_type` | categorical (binary) | `COUNT_BASED`, `TIME_BASED` | — | binary (0/1) — **the primary novelty variable** |
| `threshold` | int | `{30, 50, 70}` (range 1–100) | percent | numeric |
| `window_size` | int | `{10, 50, 100}` (range 1–1000) | **calls if COUNT_BASED, seconds if TIME_BASED** | numeric (see note) |
| `wait_duration` | int | `{5, 10, 30}` (range 1–600) | seconds in OPEN state | numeric |

> **`window_size` unit warning.** Its meaning *changes with `window_type`*: a value of `50` means
> "50 calls" under COUNT_BASED but "50 seconds" under TIME_BASED. The raw number is therefore not
> directly comparable across window types. Handle this in feature engineering (see
> `ml/feature_engineering.md`) — do not feed the raw column to the model as if it were one scale.

### Operational / provenance — not features, but required for analysis

| Column | Type | Valid values | Notes |
|--------|------|--------------|-------|
| `environment` | categorical | `LOCAL`, `AWS` | **Required for the ±15% divergence claim** — that metric is a per-config LOCAL-vs-AWS comparison. |
| `replicate` | int | `1..R` (R ≥ 3 recommended) | Repeat index. Enables mean ± variance per config instead of a single noisy run. |
| `run_timestamp` | string (ISO 8601) | `2026-06-21T14:32:05Z` | Provenance. Never used as a model feature. |

### Dependent variables — measured outcomes → **targets / Isolation Forest inputs**

| Column | Type | Range | Unit | Null when… |
|--------|------|-------|------|------------|
| `blast_radius` | float | `0.0–1.0` | fraction | never null. **Primary outcome.** Share of the topology's services that breached their error-rate SLO during the fault window. |
| `time_to_open` | float | `≥ 0` | seconds | CB never opened (threshold not reached / fault too mild) → **null is meaningful, not missing** |
| `time_to_recover` | float | `≥ 0` | seconds | system did not return to baseline within the observation window → null is meaningful |
| `error_rate` | float | `0.0–1.0` | fraction | never null. Peak error rate across the mesh during the fault. |
| `throughput_loss` | float | `0.0–1.0` | fraction | never null. Fractional drop in successful TPS vs the pre-fault baseline. |

> **Meaningful nulls.** `time_to_open` / `time_to_recover` are null *because of a real outcome*
> (the breaker never tripped, or the system never recovered), not random missingness. Do **not**
> mean-impute them. Either carry a companion boolean (`cb_opened`, `recovered`) or use an explicit
> sentinel — decide this in feature engineering before model training, not after.

---

## How the two models use these columns

- **Decision Tree recommender** — features = the 6 independent variables; target = a label derived
  from `blast_radius` (e.g. `safe` if `blast_radius ≤ τ`). Given a desired fault/topology, it
  recommends a CB config. Interpretability is the reason it was chosen over deep learning.
- **Isolation Forest anomaly detector** — fit on the (scaled) outcome columns to flag
  config/outcome combinations that behave unexpectedly (e.g. a "safe-looking" config that produced a
  large blast radius). `StandardScaler` before fitting.

## Source of truth for outcome values

Each measured column maps 1:1 to a Prometheus metric scraped during the run (Jay's stack). The
`blast_radius` metric in particular **must** fire and be scrapable before any full sweep — confirm
this in the Week 2 metrics-exposure check.
