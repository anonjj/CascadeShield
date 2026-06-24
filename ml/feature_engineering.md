# CascadeShield — Feature Engineering

**Status:** Started (Week 1). Encoding + scaling strategy is **finalised in Week 2**, alongside the
schema lock. This file records decisions as they're made so nothing is reconstructed from memory later.

## Inputs

- Raw table: `data/master_dataset_schema.csv` (see `data/DATA_DICTIONARY.md` for column contracts).
- One row per `(experiment_id, environment, replicate)`.

## Decisions locked in Week 1

1. **Independent vs dependent split is fixed.**
   - Features (model inputs): `topology`, `fault_type`, `window_type`, `threshold`,
     `window_size`, `wait_duration`.
   - Outcomes (targets / anomaly inputs): `blast_radius`, `time_to_open`, `time_to_recover`,
     `error_rate`, `throughput_loss`.
   - Provenance (never a feature): `experiment_id`, `environment`, `replicate`, `run_timestamp`.
     `environment` is a *grouping* variable for divergence analysis, not a training feature, so the
     recommender does not learn LOCAL-vs-AWS shortcuts.

2. **Categorical encoding (planned).**
   - `topology`, `fault_type` → one-hot.
   - `window_type` → single binary column (`window_type_is_time`).

3. **Scaling (planned).**
   - `StandardScaler` on numeric columns before the Isolation Forest.
   - Decision Tree needs no scaling (split-based), but encoding still applies.

## Open items for Week 2 (must resolve before lock)

- [ ] **`window_size` cross-type comparability.** Raw value means calls (COUNT) or seconds (TIME).
      Options: (a) keep raw + let `window_type_is_time` interact, (b) add a derived
      `window_size_normalised`, (c) split into two columns. Pick one and document the rationale.
- [ ] **Meaningful nulls in `time_to_open` / `time_to_recover`.** Choose: companion boolean flags
      (`cb_opened`, `recovered`) vs explicit sentinel. Do **not** mean-impute.
- [ ] **Decision Tree target definition.** Fix the `blast_radius` threshold τ that separates
      `safe` / `unsafe`, or switch to multi-class buckets. Justify the cutoff.
- [ ] **Replicate aggregation.** Train on per-replicate rows, or on per-config mean? If mean,
      carry the variance as a feature/diagnostic.
- [ ] **Class balance.** Check the `safe`/`unsafe` ratio once the canary runs land; decide on
      class weighting if skewed.

## Notes

- EDA (distributions, correlation heatmaps, per-fault-class blast-radius maps) begins once the
  first canary batch (15–20 configs) has populated real rows.
