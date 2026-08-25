# Tasks

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
