## D-006 · Canonical 47-column schema freeze (restructure re-run)

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
