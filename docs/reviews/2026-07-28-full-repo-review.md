# CascadeShield — Full Repository Review (2026-07-28, run 0)

- Reviewed at HEAD `0f961c3`
- Scope: full walk of `experiments/`, `ml/`, `services/`, `dashboard/`, `data/`, `infra/`.
- `python -m py_compile` run on all 12 `.py` files → **all compile clean**.
- Areas classified in `docs/reviews/CODEBASE_NOTES.md` for pruning on later runs.

## Summary

Overall the harness and ML pipeline are in good shape and unusually well
documented. The blast-radius scale contract (`BLAST_RADIUS_SCALE = 1.0`,
`runner.get_blast_radius()` normalising the Java `0–100` to a `0.0–1.0`
fraction) is internally consistent across `runner.py`, `preprocessing.py`,
`generate_synthetic_data.py`, and the dashboard. The 17-column dataset contract
holds end to end (2916 rows = 486 configs × 2 env × 3 replicates; header matches
`DATASET_HEADERS` and `SCHEMA_COLUMNS`).

The one finding that materially matters is a **schema-doc vs code contradiction
on `DEFAULT_TAU`** whose stated rationale is not just stale but *inverted*
relative to the data. Everything else is minor.

---

## Findings

### M1 — `DATA_DICTIONARY.md` states the wrong `DEFAULT_TAU` and an inverted rationale — MEDIUM
- **Where:** `data/DATA_DICTIONARY.md:89–92` vs `ml/preprocessing.py:98`
- **Problem:** The data dictionary — the schema-contract document — says:
  > **τ = 0.1** (`DEFAULT_TAU` in `preprocessing.py`) … the earlier `τ = 0.5`
  > would have collapsed most rows into a single "all safe" class (untrainable).

  But the code sets `DEFAULT_TAU = 0.5` (`preprocessing.py:98`), and its own
  comment (lines 86–97) gives the opposite justification. I verified against
  `data/master_dataset.csv` (2916 rows, blast_radius ∈ [0.059, 0.99]):
  - `tau=0.1` → **19 safe / 2897 unsafe** (degenerate near-constant label; this is the untrainable one)
  - `tau=0.5` → **769 safe / 2147 unsafe** (usable split)

  So the dictionary is wrong twice: (a) it names the constant as 0.1 when the
  code is 0.5, and (b) it claims 0.5 collapses to "all safe" when in fact 0.1
  collapses to "all unsafe." `ml/README.md:79` correctly documents `default τ=0.5`,
  so the dictionary is the outlier.
- **Impact:** Anyone tuning the classifier or trusting the schema doc would pick
  the exact value the code was deliberately calibrated *away* from, reproducing
  the degenerate-split failure this branch's work exists to fix.
- **Fix:** Update `DATA_DICTIONARY.md:89–92` to `τ = 0.5`, and correct the
  rationale to match `preprocessing.py` (tau=0.1 collapses to near-all-unsafe on
  this branch's continuous synthetic distribution; tau=0.5 yields the balanced,
  trainable split). Do not change the code.

### L1 — Duplicate, un-wired order/inventory service track — LOW
- **Where:** `services/service-a-order/`, `services/service-b-inventory/` vs `services/order-service/`, `services/inventory-service/`
- **Problem:** Two parallel implementations of order + inventory exist. Only
  `order-service` / `inventory-service` are wired into
  `infra/docker-compose.yml`; `service-a-order` / `service-b-inventory` are not
  referenced by compose, the runner, or any Python. Per `plans/mentor-report.md`
  they are Soham's "business-logic track" intended to fold into the mesh in
  Week 2 (attaching `@CircuitBreaker` to `InventoryClient.reserve()`).
- **Impact:** Not dead per se — a planned track — but today it is an unbuilt,
  unexercised second source of truth for the same domain. Easy to edit the wrong
  one. `services/README.md` still documents the `service-a`/`service-b` pair as
  *the* services (ports 8081/8082), which now collides with the mesh services'
  own 8081/8082 mapping.
- **Fix:** Either mark the `service-a/b` tree clearly as a not-yet-integrated
  WIP in `services/README.md`, or track its integration so the duplication is
  temporary and intentional. No code change required this run.

### L2 — Dashboard "trip rate" proxy (`blast_radius > 0`) is trivially 1.0 on synthetic data — LOW
- **Where:** `dashboard/data_loader.py:57–62,70–79` (`compute_summary_stats`, `trip_rate_pivot`)
- **Problem:** Trip rate is computed as `(blast_radius > 0).mean()`, intended as
  "fraction of runs where any CB opened." But `generate_synthetic_data.py` clips
  blast_radius to a floor (`np.clip(..., 0.03, 0.99)`; observed min 0.059), so
  **every** synthetic row is `> 0` and trip rate is a constant 1.0 — including
  rows where `time_to_open` is null (breaker never opened). The true
  breaker-opened signal is `time_to_open.notna()`, which
  `preprocessing.build_outcome_frame` already uses for the `cb_opened` flag.
- **Impact:** The fig2 heatmap / summary "trip_rate_frac" column is
  uninformative on synthetic data and disagrees with the `cb_opened` semantics
  used elsewhere. On real data (where blast can be a true 0.0) it works.
- **Fix:** Base trip rate on `time_to_open.notna()` (consistent with `cb_opened`)
  rather than `blast_radius > 0`, or document that the `> 0` proxy only holds for
  real (non-floored) data.

### L3 — Regressor target bypasses the `blast_radius_fraction` scaling seam — LOW
- **Where:** `ml/decision_tree.py:68,102` (`y_blast = df["blast_radius"].astype(float)`) and `ml/closed_loop_demo.py` predicted values
- **Problem:** The classifier labels route through `make_labels` →
  `blast_radius_fraction` (divides by `BLAST_RADIUS_SCALE`), but the regressor
  target reads the raw column directly. Today `BLAST_RADIUS_SCALE = 1.0`, so raw
  == fraction and there is **no active bug**. But the whole point of the
  `blast_radius_fraction` seam (per its docstring) is that "every consumer routes
  through one place if the source scale ever changes." The regressor is the one
  consumer that doesn't — if the scale ever reverts to 0–100, the classifier and
  regressor targets would silently diverge by 100×.
- **Fix:** Have the regressor target also go through `blast_radius_fraction(df)`
  so both models share the one scaling seam.

### L4 — `recommend()` returns `top_k − 1` alternatives — LOW (likely intentional)
- **Where:** `ml/decision_tree.py:174` — `"alternatives": candidates[1:top_k]`
- **Problem:** With the default `top_k=3`, `candidates[1:3]` yields 2
  alternatives; combined with `best` that is 3 configs total. If `top_k` is meant
  to be "number of alternatives," this is off by one; if it means "total configs
  surfaced," it's correct but undocumented.
- **Fix:** Clarify the `top_k` contract in the docstring, or use
  `candidates[1:top_k+1]` if `top_k` alternatives were intended.

## Non-issues verified (no action)

- **Blast-radius scale contract** consistent across `runner.py` (÷100 at source),
  `preprocessing.BLAST_RADIUS_SCALE=1.0`, synthetic generator (emits 0–1
  directly), and dashboard labels. Drift guard in `blast_radius_fraction` warns
  if a value exceeds 1.0.
- **Dataset column contract**: `runner.DATASET_HEADERS`,
  `generate_synthetic_data.SCHEMA_COLUMNS`, `preprocessing.SCHEMA_COLUMNS`, and
  `data/master_dataset_schema.csv` all agree (17 columns, same order). `runner`
  refuses to append when a stale header is detected.
- **Meaningful-null handling** for `time_to_open` / `time_to_recover` is
  consistent: harness guards against the impossible `time_to_open=null +
  time_to_recover=non-null` combo; synthetic generator mirrors it; preprocessing
  encodes companion booleans instead of imputing.
- **Isolation-forest truth merge** keys on `(experiment_id, environment,
  replicate)`, which uniquely identifies a row (experiment_id encodes the full
  config). 1:1 merge is safe.
- **StratifiedKFold reuse** in the regressor CV loop calls `cv.split(...)` fresh
  each iteration, so no exhausted-generator bug.

## Follow-up for future (commit-only) runs

From run 2 onward this routine reviews only recent commit diffs. Watch for:
schema/`DATASET_HEADERS` edits, `DEFAULT_TAU` / `BLAST_RADIUS_SCALE` changes,
and any edit that touches only one of the two order/inventory service trees.
