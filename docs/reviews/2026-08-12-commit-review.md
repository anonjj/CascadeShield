# Commit Review — 2026-08-12 (run 2, commits-only mode)

**Mode:** commits-only (permanent, `run_count >= 2`).
**Window:** last 24h, ending 2026-08-12 21:35 UTC (i.e. commits since 2026-08-11 21:35 UTC).
**HEAD:** `34f2af9` (`main`).

## Commits in window

`git log --since="24 hours ago"` returns exactly one commit:

| Commit | Time (UTC) | Subject | Reviewable? |
|--------|-----------|---------|-------------|
| `34f2af9` | 2026-08-11 21:39 | `chore(review): automated review 2026-08-11 (run 2)` | No — this routine's own previous review commit; docs-only (`docs/reviews/2026-08-11-commit-review.md`, +107 lines). Nothing to review. |

No substantive source changes to `experiments/`, `ml/`, or `services/` landed inside the 24h window. The last code-bearing commits (`0681fe0`, `228f75c`, `096f9b3`, `14f514f`, `fad8751`) all landed 2026-08-11 13:42–18:30 UTC — just **outside** the window (the most recent, `0681fe0`, at 18:29, ~3h before the cutoff).

## Out-of-window spot check — `0681fe0` (most recent code commit)

Since the in-window commit carried no code, I spot-checked the freshest substantive commit that touches `experiments/` and `ml/`: `fix(harness): add fault_type=NONE no-fault control condition`. Touches `data/DATA_DICTIONARY.md`, `data/experiment_matrix.csv`, `experiments/runner.py`, `ml/preprocessing.py`.

**Verdict: clean — no findings.** Notable checks:

- **Case contract holds (the most likely bug class here).** `runner.py:773` writes `fault_type.upper()` into the CSV, and the CB-transition sidecar (`runner.py:602`) does the same, so the dataset stores `"NONE"` (uppercase). `ml/preprocessing.py:132` filters `df["fault_type"] != "NONE"` — same casing. The lowercase `--fault none` CLI token is only ever used as a dict key in `inject_fault`/`make_experiment_id` before the `.upper()` normalization, so there is no lower/upper split between the writer and the reader.
- **Matrix schema/scale consistent.** `experiment_matrix.csv` now has 162 `NONE` rows = 54 configs × 3 topologies (`FAN_OUT`, `LINEAR_CHAIN`, `SHARED_DEP_MESH`), exactly mirroring the `LATENCY`/`CRASH`/`THROTTLE` blocks (648 rows total). No column-count drift; header contract intact.
- **`inject_fault("none")` is a genuine no-op** (`runner.py:275`) that explicitly does not fall through to the unknown-type `else`, so a control replicate leaves every Toxiproxy proxy clean for the whole window — a real healthy baseline, as intended.
- **Runtime floor enforced, not advisory** (`runner.py`, `main()`): `--fault none` with `--replicates < MIN_NONE_FAULT_REPLICATES` (10) exits non-zero before touching Docker.
- **`NONE` correctly excluded from `FAULT_TYPES`.** It is dropped in `load_dataset()` rather than one-hot-encoded, which avoids an all-zero encoding indistinguishable from an unrecognised category; phi is meant to be computed from the raw CSV `NONE` rows directly.
- `python -m py_compile experiments/runner.py ml/preprocessing.py` — passes.

## Summary

Nothing actionable this run. The only commit in the 24h window is this routine's own prior review (docs-only), and the most recent real code change (`0681fe0`) reviews clean across the target categories (correctness, schema/scale, dataset column contract, broken Python, cross-module consistency).
