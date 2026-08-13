# CascadeShield automated commit review — 2026-08-13 (run 2, commits-only mode)

**Mode:** commits-only (run_count ≥ 2). No full-repo scan; review scoped to commits in
the last 24h, focusing on `experiments/`, `ml/`, `services/` (and the new `analysis/`
pipeline files, which are relevant to the ML/measurement stack).

**Window:** 13 commits (5 feature commits + merges), ~6000 insertions.

| commit | summary |
|--------|---------|
| `cd6e773` | feat(analysis): Day-1/2 formalization, leak audit, tau sweep, canary design |
| `4432f13` | feat(harness): record achieved arrival rate + flag rate divergence (runner.py) |
| `5458281` | feat(harness): add effective_horizon derived column (runner.py) |
| `c10141e` | feat(ml): drop `lambda_deviation_flag=True` rows from training (preprocessing.py) |
| `dc9f2e5` | feat(harness): add compute_phi.py — no-fault false-trip rate report |

## Verdict

High quality, well-documented work. **No crash-level bugs, no broken Python, no schema
misalignment introduced this window.** Specifically verified:

- `python -m py_compile` passes on all 11 changed `.py` files.
- `generate_load()`'s return signature changed 3→5 values (`+lambda_achieved, +lambda_cv`);
  **both** call sites (`runner.py:1031` baseline, `runner.py:1093` fault window) were updated
  to the 5-tuple unpack. `warmup_phase` has its own dispatch loop and does not call it. No
  broken unpack.
- `DATASET_HEADERS` (34 columns) exactly matches the 34 values written per row in
  `log_results` — including the trailing constant `""` for `excluded_reason`. No column shift.
- `ml/preprocessing.py`'s new `lambda_deviation_flag` filter is correct: `.astype(str)
  .str.strip().str.lower() == "true"` drops only confirmed-True rows; NaN→`"nan"` and
  `"False"` are kept, matching the stated "absence of measurement ≠ absence of deviation".
- All new lambda/effective_horizon columns are read defensively (`if col in df.columns`), so
  the current 20-column on-disk `data/master_dataset.csv` (which pre-dates them but still
  carries all 17 `SCHEMA_COLUMNS`) still loads fine through `load_dataset`.
- `canary_matrix.py`'s `experiment_id` horizon-tag (`-MH{H}`) genuinely disambiguates the
  collisions its docstring describes; every emitted row carries all `FIELDS` after the
  `setdefault` pass, so `DictWriter` cannot `KeyError`.
- Dashboard trip-rate change (`blast_radius > 0` → `time_to_open.notna()`) is internally
  consistent across `compute_summary_stats`, `trip_rate_pivot`, and the `app.py` label, and
  correctly sidesteps the synthetic generator's 0.03 blast floor. `time_to_open` is present
  in the dataset.

Findings below are one MEDIUM design trap, one MEDIUM pre-existing issue the new analysis
surfaces, and three LOW doc/hygiene items.

---

## Findings

### 1. [MEDIUM] CB event ring buffer (50) is too small for the new high-λ canary matrix — STATE_TRANSITION sidecar will silently under-report at high arrival rate

- **Where:** `services/*/application.yml` new line `event-consumer-buffer-size:
  ${CB_EVENT_BUFFER_SIZE:50}` and `infra/docker-compose.yml` `CB_EVENT_BUFFER_SIZE:-50`
  (commit `cd6e773`); `experiments/canary_matrix.py:56` `LAMBDAS = [5, 20, 80, 320]`
  (commit `cd6e773`); consumed by `experiments/runner.py:_fetch_breaker_events` /
  `collect_new_transitions` (lines ~690–740, ~1021, ~1234).
- **Problem:** the actuator `/circuitbreakerevents` ring buffer holds **all** CB event
  types (SUCCESS / ERROR / slow-call / NOT_PERMITTED / STATE_TRANSITION) for a breaker, and
  `_fetch_breaker_events` filters to STATE_TRANSITION only **after** fetching what's still in
  the buffer. `snapshot_breaker_event_counts()` runs once pre-fault and
  `collect_new_transitions()` once at window-end. At the canary matrix's high rates
  (up to 320 req/s), thousands of SUCCESS/ERROR events per fault window overflow the 50-slot
  buffer many times over, evicting the early `CLOSED→OPEN` transition long before the
  end-of-window poll. The result recorded to `cb_transitions.jsonl` is "no transition,"
  which is indistinguishable from a breaker that genuinely never opened.
- **Scope / mitigation (why MEDIUM, not HIGH):** this does **not** corrupt the primary
  master_dataset DVs — `time_to_open` and `blast_radius` are stamped by the blast-radius
  **sampler thread** (`cb_open_at[0]`), not by these events (runner.py:1056–1078, 1160). The
  eviction only degrades the diagnostic `cb_transitions.jsonl` sidecar, and nothing in
  `analysis/` currently consumes that sidecar. The buffer size is env-overridable
  (`CB_EVENT_BUFFER_SIZE`).
- **Fix:** for any high-λ sweep, set `CB_EVENT_BUFFER_SIZE` to comfortably exceed a full
  window's event count (≈ λ · window_duration + margin), and/or poll/drain events mid-window
  instead of only at the boundary; failing that, document that the transition sidecar is
  unreliable above some λ so a "clean" sidecar at 320 req/s isn't mistaken for "breaker
  never tripped."

### 2. [MEDIUM, pre-existing — newly surfaced by this window's analysis] `REAL_BLAST_LEG_ERROR_THRESHOLD = 0.50` makes `real_blast_radius` identically 0 on current data

- **Where:** `experiments/runner.py:253` (`REAL_BLAST_LEG_ERROR_THRESHOLD = 0.50`; the
  constant dates to `93b0b75`, 2026-07-26 — **not** changed this window). Surfaced by the
  new `analysis/tau_sweep.py` output, `analysis/out/tau_sweep.json`.
- **Problem:** `real_blast_radius_from_rates` counts legs whose per-leg failure rate exceeds
  tau. The tau_sweep readout notes the largest observed per-leg failure rate is **0.4867**,
  so at the pinned tau=0.50 `real_blast_radius` is **0 for every run** — a constant,
  uninformative column.
- **Mitigation (why MEDIUM):** the raw per-leg rates are persisted in the `leg_failure_rates`
  column, so `real_blast_radius` is fully recomputable post-hoc at any tau with no re-run;
  the new `analysis/tau_sweep.py` is exactly the tool for choosing a defensible tau (the
  sweep exercises 0.05–0.95).
- **Fix:** lower `REAL_BLAST_LEG_ERROR_THRESHOLD` per the tau_sweep guidance (a value below
  the largest observed leg rate, e.g. in the 0.05–0.45 band), or treat `real_blast_radius`
  as a post-hoc-derived quantity rather than reporting the pinned-tau column as primary.

### 3. [LOW] Schema column count in commit messages and `log_results` docstring is off by one

- **Where:** commit `4432f13` body ("32-col schema"), commit `5458281` body ("33-col"),
  and `experiments/runner.py:886` docstring ("33-col schema").
- **Problem:** `DATASET_HEADERS` actually has **34** columns — the messages/docstring omit
  the pre-existing trailing `excluded_reason`. The row write is correctly aligned at 34
  values, so this is purely cosmetic (no data impact), but the stated count is wrong and
  future readers may chase a phantom off-by-one.
- **Fix:** state 34 (or "33 measured + `excluded_reason`") in the docstring.

### 4. [LOW] `compute_phi.py` `config_key` docstring says "6-tuple" but returns a 5-tuple

- **Where:** `experiments/compute_phi.py:80–88`.
- **Problem:** the docstring reads "The 6-tuple that identifies a swept config (topology +
  the 5 CB knobs)," but the function returns 5 elements — `topology`, `window_type`,
  `threshold`, `window_size`, `wait_duration` — omitting `permitted_calls_half_open`. The
  downstream unpack (`for phi, trips, total, (topo, wt, thr, ws, wd) in rows_out`) is
  self-consistent with the 5-tuple, and grouping is unaffected because
  `permitted_calls_half_open` is constant (5) across the sweep — so no functional bug, only
  an inaccurate count/description.
- **Fix:** correct the docstring to "5-tuple (topology + 4 CB knobs; permitted_calls is
  constant)," or add `permitted_calls_half_open` to the key for forward-compatibility if that
  knob is ever swept.

### 5. [LOW / informational] Stale on-disk `data/master_dataset.csv` (20-col) vs new 34-col `DATASET_HEADERS`

- **Where:** `data/master_dataset.csv` (20 columns) vs `experiments/runner.py` `DATASET_HEADERS` (34).
- **Behavior:** on the next real sweep, `log_results` hits its header-mismatch guard and
  **refuses to append** ("…Refusing to append… Move or rename the stale file first"),
  returning without writing. This is the guard working **as designed** — it prevents silent
  column shift — not a bug. The ML load path is unaffected: the 20-col file still contains
  all 17 `SCHEMA_COLUMNS`, and every new column is read with an `in df.columns` guard.
- **Action:** none required in code. Operationally, rename/move the stale dataset before the
  next sweep so runner can start the new 34-col schema file.

---

_Automated review. Commits-only mode; `CODEBASE_NOTES.md` intentionally untouched._
