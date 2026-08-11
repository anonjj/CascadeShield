# CascadeShield — Commit Review 2026-08-11 (run 2, commits-only mode)

Mode: **commits-only** (`run_count == 2`). No full-repo scan. Reviewed only the
code that landed on `main` in the last 24h.

## Scope

`git log --since="24 hours ago"` on `main` (window ≈ 2026-08-10 21:35 UTC →
2026-08-11 21:35 UTC, HEAD `4fa1e92`) surfaced four merged feature PRs — the
first substantive code to land since 2026-08-04. Non-merge commits reviewed:

- `fad8751` fix(harness): breaker-state-reset precondition before each run (PR #12)
- `14f514f` fix(ml): drop `precondition_ok=False` rows before training (PR #12)
- `096f9b3` fix(harness): JIT warmup discard phase before baseline/fault load (PR #13)
- `228f75c` fix(harness): randomize run order to break the treatment/drift confound (PR #14)
- `0681fe0` fix(harness): add `fault_type=NONE` no-fault control condition (PR #15)

Touched source: `experiments/runner.py`, `ml/preprocessing.py`,
`dashboard/data_loader.py`, plus data-contract files (`data/DATA_DICTIONARY.md`,
`data/master_dataset_schema.csv`, `data/experiment_matrix.csv`).

## Verification performed

- `python -m py_compile` on all changed `.py` files → **clean**.
- `pyflakes experiments/runner.py ml/preprocessing.py dashboard/data_loader.py`
  → **clean** (no undefined names, no unused imports).
- Confirmed all newly-referenced functions are actually defined
  (`wait_for_readiness`, `warmup_phase`, `reset_all_breakers`,
  `check_breaker_precondition`, `snapshot_breaker_event_counts`,
  `build_shuffled_run_list`) — a runtime `NameError` py_compile would not catch.
- Confirmed the `wait_for_healthy` → `wait_for_readiness` rename is complete
  (no lingering references anywhere in the tree).
- **Schema contract intact**: `DATASET_HEADERS` in `runner.py` (28 cols) matches
  `data/master_dataset_schema.csv` (28 cols) column-for-column, in order.
- **`blast_radius` scale / `DEFAULT_TAU` unchanged**: `BLAST_RADIUS_SCALE`,
  `blast_radius_fraction()`, and `DEFAULT_TAU = 0.1` are untouched by these
  commits; no scale drift introduced.

## Findings

Overall these are high-quality, well-motivated changes with clear rationale
comments and matching data-dictionary/schema updates. No high- or
medium-severity correctness bugs found. Two potential-defect areas were
investigated in depth and cleared:

### Cleared (investigated, not bugs)

- **`fault_type=NONE` case mismatch — NOT a bug.** `argparse` accepts lowercase
  `--fault none`, but `log_results` writes `fault_type.upper()`
  (`experiments/runner.py:773`), so the CSV stores `"NONE"`. The preprocessing
  filter `df["fault_type"] != "NONE"` (`ml/preprocessing.py:135`) therefore
  matches correctly. `make_experiment_id`'s `fault_map` also maps `"none" → "NON"`
  consistently. Confirmed consistent end to end.
- **`precondition_ok != False` CSV round-trip — NOT a bug.** Verified empirically
  against pandas 3.0.5: a column of `csv.writer`-emitted `True`/`False` (with or
  without blank rows mixed in) is parsed back to real Python `bool` objects
  (bool dtype when no blanks, object dtype holding `bool`+`nan` when blanks are
  present). The `!= False` filter (`ml/preprocessing.py:124`) drops the intended
  rows in both cases. No silent no-op.

### Low severity

1. **Unlogged early-abort paths leave no dataset row — inconsistent with the
   new abort-logging convention.** `experiments/runner.py:818` (Docker-compose
   failure), `:874` (baseline throughput ≤ 0 / mesh unhealthy pre-fault), and
   `:882` (fault-injection exception) all `return False` **without** calling
   `log_results`. PRs #12/#14 established the opposite convention for the two
   new abort paths (`READINESS_TIMEOUT`, `PRECONDITION_FAIL`), which now write a
   row carrying `precondition_ok=False` **and** `run_order_seed`/`run_index`.
   The randomize-run-order commit's stated invariant — "every row, including
   aborts, has a definite position in the sequence" — thus holds only for those
   two paths; a config that dies at Docker-up / zero-baseline / fault-injection
   still vanishes from the dataset with no trace and no run-order provenance.
   This is pre-existing behavior for those three paths, but the new convention
   makes the gap more visible and worth closing for auditability.
   *Fix:* give these three paths a `log_results(... precondition_ok=False,
   precondition_fail_reason="DOCKER_FAIL"/"BASELINE_ZERO"/"FAULT_INJECT_FAIL",
   run_order_seed=..., run_index=...)` call, matching the readiness/precondition
   pattern. (Severity: **low** — affects failure-audit completeness, not the
   correctness of recorded rows.)

2. **Stale run-count comments/help after NONE became a 4th fault type.**
   `data/experiment_matrix.csv` now holds 648 rows (162 each for LATENCY / CRASH
   / THROTTLE / **NONE**), but three inline descriptions still say "3 faults /
   486 total": `experiments/runner.py:118`, `:1067`, and the `--mode` argparse
   help at `:1101` ("162 runs per fault type; 486 total across 3 faults").
   Since `NONE` is only collected via a dedicated `--fault none` run (gated at
   `--replicates >= MIN_NONE_FAULT_REPLICATES = 10`) and is not part of a normal
   3-fault `full` sweep, "486" still describes that sweep — but the text is now
   ambiguous/incomplete about the control condition. *Fix:* note the NONE control
   as a separate `--fault none` run in the help/comment. (Severity: **low**,
   documentation only.)

## Notes for the next run

- First substantive-code day since 2026-08-04. The measurement-validity /
  experimental-rigor track (warmup, run-order randomization, breaker-reset
  precondition, no-fault control) has now fully landed on `main` across PRs
  #12–#15.
- No `CODEBASE_NOTES.md` update in this mode (commits-only), per routine spec.
- Remaining open remote branches not yet merged to `main` (out of scope until
  merged): `feat/dataset-schema`, `feat/exception-hierarchy-and-runner-fix`,
  `feat/load-plan-target-lambda`, `fix/gateway-cb-exception-split-and-fanout-cbs`,
  `integrate/measurement-validity-into-main`.
- Suggested follow-up if the Low-1 finding is actioned: the three unlogged abort
  paths and the two logged ones should share a single helper so the abort-row
  contract can't drift again.
