# Tasks

## D11 — Throttle fault type (done)

- [x] **Removed everywhere.** No throttle data exists in any usable archive (only the
      unusable, pre-timing-collector `master_dataset_v1_prefix.csv` has it), and its
      slow-call mechanism was judged redundant with `LATENCY`'s. Dropped from the real
      harness (`experiments/runner.py`/`fault_injector.py`), the ML schema
      (`ml/preprocessing.py`'s `FAULT_TYPES`, `ml/generate_synthetic_data.py`'s fault
      dicts), and every doc that stated the real-sweep grid size (486 -> 324 configs
      across 2 fault types instead of 3), including `data/experiment_matrix.csv`'s
      planning rows (648 -> 486). Historical references to `master_dataset_v1_prefix.csv`'s
      actual 486-row size were left alone — that's a fact about an archive, not the
      live design. Pushed to `remove/d11-throttle-fault-type`.

## D12 — window_type -> recovery leak (open)

- [ ] **The Aug-15 leak is real.** `analysis/window_type_recovery_leak.py` confirms
      TIME's `time_to_recover` runs 2.06-3.68x COUNT's at every matched `wait_duration`,
      reproducing near-identically across all three archived datasets. Decomposing into
      anchor (`time_to_open`) vs. excess shows TIME's excess grows with `wait_duration`
      (19 -> 35s) while COUNT's stays flat (~1.5s) — not explainable by the
      anchor-timing shift alone.

- [ ] **But it can't be pinned down yet.** The precise HALF_OPEN->CLOSED metric needed
      to isolate the actual mechanism requires `data/cb_transitions.jsonl`, which
      doesn't exist in any checked-in archive. `hypotheses.md` §4.1 and decision-log
      entry `D-006` now say so honestly, downgrading H3's negative control from
      "cleared" to "untested pending the transition sidecar," instead of leaving a
      claim that was never actually tested.

      **Next step:** re-run `experiments/runner.py` in a way that retains
      `data/cb_transitions.jsonl` (a sweep spanning both window types at matched
      `wait_duration`), then re-run `python analysis/window_type_recovery_leak.py
      current` — it picks up the sidecar automatically and produces a real verdict
      (`LEAK_CONFIRMED_ON_HALF_OPEN_LEG` / `CONFIRMED_ANCHOR_SHIFT_ONLY_DISSOCIATION_HOLDS`
      / `AMBIGUOUS`) instead of `MECHANISM_UNTESTED_NO_SIDECAR`. Then fill in the
      `hypotheses.md` §4.1 / `D-006` placeholders with the real result.
