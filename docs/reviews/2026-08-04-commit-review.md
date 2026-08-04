# CascadeShield — Commit Review 2026-08-04 (run 2, commits-only mode)

Mode: **commits-only** (`run_count == 2`). No full-repo scan. Reviewed the code
that landed on `main` in the last 24h and its cross-module contracts.

## Scope

`git log --since="24 hours ago"` on `main` surfaced only merge/review commits:

- `843fc65` Merge origin/main: integrate 5 automated review commits (docs only)
- `0fb9503` Merge `integrate/measurement-validity-into-main` into main
- `5904272` chore(review): automated review 2026-08-03 (run 2) (docs only)

The substantive code arrived via `0fb9503`, which fast-forwarded main from
`81cd794` to include the *measurement-validity* work. Reviewed the net diff
`81cd794..843fc65` for the logic paths (`experiments/`, `ml/`, `services/`).
Net logic changes:

- `experiments/runner.py` — load-fairness sizing (Task 1) + request-level
  `real_blast_radius` / `leg_failure_rates` (Task 2); schema grew 17→19 cols.
- `experiments/fault_injector.py` — `clear_first` param on the two injectors.
- `experiments/validate_gate.py` — new stdlib validation gate (Cramér's V).
- `ml/decision_tree.py` — regressor CV/holdout now grouped by `experiment_id`;
  regressor target routed through `blast_radius_fraction()`.
- `ml/preprocessing.py` — `DEFAULT_TAU` **0.5 → 0.1**; new `blast_radius_fraction()`.
- `ml/test_smoke.py` — new pipeline smoke test (model artifacts now gitignored).
- `services/*/application.yml` — `minimum-number-of-calls` exposed (default 5);
  gateway breakers pinned to a never-open `measurement-plane` config.
- `services/gateway-service/.../BlastRadiusService.java` — dropped `shared-db`
  from the subject set (now 4 nodes).

Verification run this session: `python -m py_compile` on all 15 `.py` files —
**all compile clean**. ML behaviour claims below were reproduced with
numpy/pandas/sklearn (see H1).

---

## Findings

### H1 — `DEFAULT_TAU=0.1` makes the default `train_all.py` (synthetic) classifier degenerate  ·  severity: HIGH
`ml/preprocessing.py:193` (was 0.5, now 0.1); interacts with
`ml/generate_synthetic_data.py:131` and `ml/train_all.py:42`.

**Problem.** The new tau rationale is written for the **real** sweep data, where
`blast_radius` is quantised to quarters `{0, .25, .5, .75, 1.0}` so any tau in
`(0, 0.25)` means "any subject tripped = unsafe". That reasoning is correct *for
that distribution*. But the **default** training entrypoint,
`python ml/train_all.py` (no `--no-generate`), regenerates **synthetic**
`master_dataset.csv` via `generate_synthetic_data.py`, which still emits a
**continuous** distribution `np.clip(latent + noise, 0.03, 0.99)` — unchanged in
this window. At `tau=0.1` almost every synthetic row is "unsafe", collapsing the
classifier labels, exactly the failure mode the *removed* comment documented.

**Reproduced this session** (numpy 2.4 / pandas 3.0 / sklearn 1.9), training the
real `decision_tree.train()` on freshly generated synthetic data:

| tau | class_balance (safe / unsafe) | cv_f1_macro | test_acc |
|-----|------------------------------|-------------|----------|
| 0.5 (old) | 769 / 2147 | **0.852** | 0.872 |
| 0.1 (new) | **19 / 2897** | **0.446** | 0.742 |

`cv_f1_macro=0.446` on a binary task is a near-useless classifier (test_acc 0.742
is *below* the 0.993 majority-class base rate). This is a real regression of the
documented default workflow.

**Why the new smoke test doesn't catch it.** `ml/test_smoke.py:29` trains from the
*committed* `data/master_dataset.csv` — the 81-row real, quarter-quantised sweep —
where `tau=0.1` is fine. It never runs `train_all.py` / synthetic generation, so
the degeneracy is invisible to the added test. The two code paths disagree on the
data scale `DEFAULT_TAU` assumes.

**Fix (pick one, and state the intent in the constant's comment):**
1. If the project has pivoted to real data only — stop `train_all.py` defaulting to
   synthetic (make `--generate` opt-in), or have `generate_synthetic_data.py` emit
   the same quarter-quantised `blast_radius` the real harness now produces; **or**
2. Keep synthetic as a supported path — carry a data-scale-aware tau (e.g. derive
   the split from the distribution, or keep `tau=0.5` for the continuous synthetic
   source and `0.1` for the quantised real source) rather than one global constant.

Either way, add a smoke assertion that the classifier class balance on the
*default* pipeline data isn't near-constant (e.g. minority class ≥ some floor), so
a future tau/scale mismatch fails a test instead of silently shipping a dead model.

### M1 — Schema contract drift: `master_dataset_schema.csv` and `DATA_DICTIONARY.md` lag the 19-col dataset  ·  severity: MEDIUM
`data/master_dataset_schema.csv` (17 cols), `data/DATA_DICTIONARY.md`.

`runner.py`'s `DATASET_HEADERS` and the actual `data/master_dataset.csv` are now
**19 columns** (all 81 rows consistent — verified), adding `real_blast_radius` and
`leg_failure_rates`. But:
- `master_dataset_schema.csv` still ends at `throughput_loss` (**17 cols**) — and
  `dashboard/data_loader.py:4` explicitly cites this file as the schema-drift
  canary, so leaving it stale defeats its stated purpose.
- `DATA_DICTIONARY.md` documents `real_blast_radius` in prose but **never documents
  `leg_failure_rates`** (the `"svc:rate;svc:rate"` column).

No runtime breakage — `ml/preprocessing.py:101` only checks for *missing* required
columns, and `data_loader.py` reads columns defensively — so this is a
documentation/contract-integrity issue, not a crash. **Fix:** append the two
columns to `master_dataset_schema.csv` and document `leg_failure_rates` (format,
units, `""`=none-observed sentinel) in `DATA_DICTIONARY.md`.

### M2 — `real_blast_radius` reads 0.0 for latency faults with ~90% gateway error rate  ·  severity: MEDIUM
`experiments/runner.py:71` (`REAL_BLAST_LEG_ERROR_THRESHOLD = 0.50`); visible in
committed data.

The last committed rows show this concretely, e.g.
`LIN-LAT-TIM-...`: `error_rate=0.9000`, `throughput_loss=0.9039`, yet
`real_blast_radius=0.0000` because the worst per-leg rate
(`order-service:0.4500`) sits just under the hardcoded `TAU_LEG=0.50`. The code
itself flags this as an **OPEN QUESTION** ("threshold to be signed off"), so it's
a known design risk rather than a defect — but the sweep is now **baking that
unsigned-off threshold into the persisted dataset**. Mitigating factor: the raw
`leg_failure_rates` column is persisted precisely so `real_blast_radius` can be
recomputed at another `TAU_LEG` without re-running. **Recommendation:** resolve the
sign-off in `docs/proposals/blast-radius-redefinition.md` before this column is
consumed downstream, and note in `DATA_DICTIONARY.md` that `real_blast_radius` is
`TAU_LEG`-dependent and provisional.

### L1 — Stale column count in `log_results` docstring  ·  severity: LOW
`experiments/runner.py:412` — docstring says "18-col schema"; the schema is
**19 columns** (two were added, from 17). Off-by-one. Fix the number.

### L2 — `train_all.py` prints "17-col dataset"  ·  severity: LOW
`ml/train_all.py:55` prints `master_dataset.csv (17-col dataset; swap for real
sweep output)`; the real sweep output is now **19-col**. Update the banner.

### L3 — `clear_first` toxic-stacking is dead/incomplete code  ·  severity: LOW
`experiments/fault_injector.py:54,76`. Both `inject_latency` and
`inject_bandwidth_limit` gained a `clear_first` param, and the docstrings describe
a stacked "bandwidth + latency throttle profile that actually trips the slow-call
detector." But **no caller passes `clear_first=False`** — `runner.py`'s
`inject_fault` throttle path (line ~184) still does a single
`inject_bandwidth_limit`. The feature is added but never wired in. Either finish
the stacked throttle profile in `inject_fault`, or drop the unused param until it's
needed.

### L4 — `TAU` duplicated in `validate_gate.py`  ·  severity: LOW
`experiments/validate_gate.py:81` hardcodes `TAU = 0.1` to "match
ml/preprocessing DEFAULT_TAU". Stdlib-only constraint means it can't import it, but
the two will silently diverge on the next tau change (and given H1, the "right"
tau is itself in question). At minimum, keep this constant physically adjacent in
review to `DEFAULT_TAU`; ideally load it from a shared, dependency-free config.

---

## Consistency wins landing this window (no action needed)

- `BlastRadiusService.SERVICE_ACTUATOR_URLS` (4 nodes) now matches `runner.py`'s
  `CB_METRIC_TARGETS` (4 nodes) — both blast-radius definitions range over the same
  subjects and quantise to quarters. Resolves the prior gateway/harness node-set
  mismatch.
- Regressor CV + holdout grouped by `experiment_id` (`GroupKFold` /
  `GroupShuffleSplit`) fixes the earlier `test_r2=1.0 / test_mae=0.0` replicate
  leak; effective-n is now reported as configs, and `test_smoke.py` pins it.
- `minimum-number-of-calls` exposed (default 5, ≤ smallest window) so short/
  TIME_BASED windows can actually reach breaker evaluation.
- Gateway breakers pinned never-open (`measurement-plane`), removing the edge-CB
  confound from the sweep.

## Minor robustness note (not a finding)

`ml/decision_tree.py` uses `n_splits = min(5, n_groups)` and then
`GroupKFold(n_splits=n_splits)`. If a dataset ever has a single distinct
`experiment_id` (`n_groups == 1`), `GroupKFold` raises. Not reachable on current
data (many configs); worth a one-line guard if tiny datasets become possible.
