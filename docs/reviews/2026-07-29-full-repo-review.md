# CascadeShield — Full Repository Review (2026-07-29, run 1)

- Reviewed at HEAD `21b9ae7`.
- Mode: **second run — full review of active areas, pruned via `CODEBASE_NOTES.md`.**
- `python -m py_compile` run on all 12 `.py` files → **all compile clean**.

## What changed since the run-0 review (`0f961c3`)

`git diff --stat 0f961c3..HEAD` shows the **only** changes on `main` since the
first review are under `docs/reviews/` (the run-0 output itself + the
`.review_state.json` bump). **No source file changed.** Every stagnant item in
`CODEBASE_NOTES.md` was checked with `git log <last_reviewed>..HEAD -- <path>`
and returned zero commits, so all were skipped per the pruning rule (see the
"Stagnant items skipped" table below). The active areas (`experiments/`, `ml/`,
`dashboard/`, `data/`, `services/gateway-service/`) were nonetheless re-walked
in full.

Because the reviewed source is byte-identical to run 0, the five findings from
`2026-07-28-full-repo-review.md` **all still stand, unchanged and unfixed.**
They are restated below with re-verification, not re-discovered.

## Summary

The harness and ML pipeline remain in good shape. The blast-radius scale
contract is intact end to end: the Java `BlastRadiusService.calculateBlastRadius()`
returns `degraded/total*100.0` (0–100 percent), `runner.get_blast_radius()`
normalises `raw/100.0` → 0.0–1.0 at the source, `preprocessing.BLAST_RADIUS_SCALE=1.0`
is a no-op divide, and `generate_synthetic_data.py` emits 0.0–1.0 directly — all
consistent. The 17-column dataset contract holds (2916 rows = 486 configs × 2 env
× 3 replicates; header matches `DATASET_HEADERS` / `SCHEMA_COLUMNS`).

The one finding that materially matters is unchanged: the **`DATA_DICTIONARY.md`
vs code contradiction on `DEFAULT_TAU`** (M1), still open.

---

## Findings (all carried over from run 0, re-verified — none fixed)

### M1 — `DATA_DICTIONARY.md` states the wrong `DEFAULT_TAU` and an inverted rationale — MEDIUM (STILL OPEN)
- **Where:** `data/DATA_DICTIONARY.md:89–92` vs `ml/preprocessing.py:98`
- **Status:** Unchanged since run 0. `DATA_DICTIONARY.md:89` still reads
  **"τ = 0.1 (`DEFAULT_TAU` in `preprocessing.py`) … the earlier τ = 0.5 would
  have collapsed most rows into a single 'all safe' class (untrainable)"**,
  while `preprocessing.py:98` sets `DEFAULT_TAU = 0.5` and its own comment
  (lines 86–97) gives the opposite justification.
- **Re-verified against `data/master_dataset.csv`** this run (2916 rows,
  blast_radius ∈ [0.0593, 0.99]):
  - `tau=0.1` → **19 safe / 2897 unsafe** (degenerate near-constant label — this is the untrainable one)
  - `tau=0.5` → **769 safe / 2147 unsafe** (usable split)

  So the dictionary is still wrong twice: (a) it names the constant as 0.1 when
  the code is 0.5, and (b) it claims 0.5 collapses to "all safe" when in fact
  0.1 collapses to near-all-unsafe. `ml/README.md:79` correctly documents
  `default τ=0.5`, so the dictionary remains the outlier.
- **Impact:** Anyone tuning the classifier or trusting the schema doc picks the
  exact value the code was deliberately calibrated *away* from, reproducing the
  degenerate-split failure this branch's work exists to fix.
- **Fix:** Update `DATA_DICTIONARY.md:89–92` to `τ = 0.5` and correct the
  rationale to match `preprocessing.py`. Do not change the code.

### L1 — Duplicate, un-wired order/inventory service track — LOW (STILL OPEN)
- **Where:** `services/service-a-order/`, `services/service-b-inventory/` vs `services/order-service/`, `services/inventory-service/`
- **Status:** Unchanged (both trees at their run-0 hash `e75c0ee`; no commits
  since). Only `order-service` / `inventory-service` are wired into
  `infra/docker-compose.yml`; the `service-a`/`service-b` pair remains a
  planned-but-unbuilt second source of truth for the same domain, and
  `services/README.md` still documents the `service-a`/`service-b` pair with a
  port mapping (8081/8082) that collides with the mesh services'.
- **Fix:** Mark the `service-a/b` tree clearly as not-yet-integrated WIP in
  `services/README.md`, or track its integration. No code change required.

### L2 — Dashboard "trip rate" proxy (`blast_radius > 0`) is trivially 1.0 on synthetic data — LOW (STILL OPEN)
- **Where:** `dashboard/data_loader.py:59,78` (`compute_summary_stats`, `trip_rate_pivot`)
- **Status:** Unchanged. Trip rate is still `(blast_radius > 0).mean()`, but
  `generate_synthetic_data.py:131` clips blast to `[0.03, 0.99]` (observed min
  0.0593), so every synthetic row is `> 0` and trip rate is a constant 1.0 —
  including rows where `time_to_open` is null (breaker never opened). The true
  breaker-opened signal is `time_to_open.notna()`, which
  `preprocessing.build_outcome_frame` already uses for `cb_opened`.
- **Fix:** Base trip rate on `time_to_open.notna()` (consistent with `cb_opened`),
  or document that the `> 0` proxy only holds for real (non-floored) data.

### L3 — Regressor target bypasses the `blast_radius_fraction` scaling seam — LOW (STILL OPEN)
- **Where:** `ml/decision_tree.py:68,102` (`y_blast = df["blast_radius"].astype(float)`); `ml/closed_loop_demo.py:56` reads the regressor directly
- **Status:** Unchanged. Classifier labels route through `make_labels` →
  `blast_radius_fraction` (the one scaling seam), but the regressor target reads
  the raw column. With `BLAST_RADIUS_SCALE = 1.0` there is **no active bug**, but
  if the source scale ever reverts to 0–100 the classifier and regressor targets
  would silently diverge by 100×.
- **Fix:** Route the regressor target through `blast_radius_fraction(df)` too so
  both models share one seam.

### L4 — `recommend()` returns `top_k − 1` alternatives — LOW (likely intentional; STILL OPEN)
- **Where:** `ml/decision_tree.py:174` — `"alternatives": candidates[1:top_k]`
- **Status:** Unchanged. With default `top_k=3`, `candidates[1:3]` yields 2
  alternatives (3 configs total incl. `best`). Off-by-one if `top_k` means
  "number of alternatives"; correct but undocumented if it means "total configs
  surfaced." `lambda_handler.py:70` forwards a caller-supplied `top_k`, so the
  contract is externally visible.
- **Fix:** Clarify the `top_k` contract in the docstring, or use
  `candidates[1:top_k+1]` if `top_k` alternatives were intended.

## Non-issues re-verified (no action)

- **Blast-radius scale contract** consistent across `BlastRadiusService.java:55`
  (×100 at source), `runner.get_blast_radius()` (÷100), `preprocessing.BLAST_RADIUS_SCALE=1.0`,
  the synthetic generator (emits 0–1), and dashboard labels. `blast_radius_fraction`
  drift-guards values > 1.0.
- **Dataset column contract**: `runner.DATASET_HEADERS`,
  `generate_synthetic_data.SCHEMA_COLUMNS`, `preprocessing.SCHEMA_COLUMNS`, and
  `data/master_dataset_schema.csv` all agree (17 columns, same order; verified
  2916 rows / 17 cols this run). `runner.log_results` refuses to append on a
  stale header.
- **Meaningful-null handling** for `time_to_open` / `time_to_recover` consistent
  across harness, synthetic generator, and preprocessing (companion booleans,
  no imputation; impossible open=null+recover=non-null combo guarded in both
  `runner.run_experiment_run` and `simulate_outcomes`).
- **Isolation-forest truth merge** keys on `(experiment_id, environment,
  replicate)` — a unique row key; 1:1 merge safe.
- **StratifiedKFold reuse** in the regressor CV loop calls `cv.split(...)` fresh
  each iteration — no exhausted-generator bug.

## Stagnant items skipped this run (unchanged since `last_reviewed`)

| Path | last_reviewed | Result |
|------|---------------|--------|
| `services/order-service/` | `82f01d3` | skipped — stagnant, unchanged since `82f01d3` |
| `services/inventory-service/` | `82f01d3` | skipped — stagnant, unchanged since `82f01d3` |
| `services/payment-service/` | `82f01d3` | skipped — stagnant, unchanged since `82f01d3` |
| `services/notification-service/` | `82f01d3` | skipped — stagnant, unchanged since `82f01d3` |
| `services/shared-db-service/` | `f8d0f2a` | skipped — stagnant, unchanged since `f8d0f2a` |
| `services/service-a-order/` | `e75c0ee` | skipped — stagnant, unchanged since `e75c0ee` (see L1) |
| `services/service-b-inventory/` | `e75c0ee` | skipped — stagnant, unchanged since `e75c0ee` (see L1) |
| `infra/` | `f7af13a` | skipped — stagnant, unchanged since `f7af13a` |
| `make_figures.py` | `07fb846` | skipped — stagnant, unchanged since `07fb846` |

## Follow-up for future (commit-only) runs

From run 2 onward this routine reviews only recent commit diffs. Watch for:
schema/`DATASET_HEADERS` edits, `DEFAULT_TAU` / `BLAST_RADIUS_SCALE` changes,
a fix landing on any of M1–L4, and any edit that touches only one of the two
order/inventory service trees.
