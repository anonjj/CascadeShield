# Tasks

## A2 — `--inject-point` CLI arg (done)

- [x] **Both hardcodes replaced.** `inject_fault()`'s latency branch (`inventory-service-proxy`,
      unconditional) and the crash-branch's sweep-mode retarget (`crash_target =
      "inventory-service-proxy" if mode == "sweep" else None`) both collapsed into one
      `inject_point` param, threaded CLI -> `main()` -> `run_experiment_run()` ->
      `inject_fault()`. `--inject-point {order-service-proxy, inventory-service-proxy,
      payment-service-proxy, notification-service-proxy, shared-db-service-proxy}`
      (choices matching `fault_injector.setup_default_proxies()`'s proxy names, argparse
      rejects anything else). Unset (`None`) preserves every existing default exactly:
      latency -> inventory-service-proxy, crash -> payment-service-proxy (sweep mode's
      inventory-service-proxy retarget still applies when unset), so no existing call
      site's behavior changes. An explicit `--inject-point` wins over the sweep-mode
      default. Verified via py_compile, a precedence self-test (4 cases: unset/non-sweep,
      unset/sweep, explicit override on sweep, explicit on non-sweep), and an argparse
      smoke test (valid choice runs, invalid choice rejected with the choice list).
      Needed for D4's supplementary check (does the mechanism hold at an injection point
      other than the historical default).

## D7 — λ is a single value, and it is the variable your theory is about (in progress)

- [x] **Code ported and wired up.** `--mode occupancy` added to `experiments/runner.py`:
      54 configs (36 TIME_BASED cells: 3λ×3window×4n_min, + 18 COUNT_BASED control
      cells: 2λ×3window×3n_min), writing to its own `data/occupancy_dataset.csv`
      (`OCCUPANCY_DATASET_HEADERS = DATASET_HEADERS + ["occupancy_ratio", "inert"]` —
      master schema untouched). Ported from the unmerged `origin/experiment/occupancy-ratio`
      branch (already designed, 3 commits from Aug 17-19) rather than redesigned from
      scratch, but manually re-integrated against everything that changed in `runner.py`
      since — D9's dict-based `log_results`, D11's throttle removal, D12's sweep mode.
      Fixed two real bugs found while porting: (1) the original put the new columns
      directly in the shared `DATASET_HEADERS`, which would have header-mismatched the
      already-collected 34-col `data/master_dataset.csv`; (2) the original changed
      `compute_load_plan()`'s TIME_BASED duration formula *unconditionally*, silently
      making full/canary sweeps run ~10x longer — now gated to occupancy-mode configs
      only. Verified via py_compile, config-count checks, and a temp-path `log_results`
      smoke test (correct `occupancy_ratio` math, correct tri-state `inert`, correct
      `-M/-L` experiment_id suffixing). Pushed to `feat/d7-occupancy-lambda-sweep`.

- [ ] **Not yet done: an actual Docker end-to-end run.** No live mesh/Toxiproxy in this
      environment, so `--mode occupancy` has never actually been run against the real
      services — only verified at the Python-logic level. **Plan: run on the codespace,
      bundled with the other pending live-stack tests.** Smoke test first:
      `python3 experiments/runner.py --mode occupancy --fault latency --topology linear
      --limit 1` — before committing to the full 54-config × replicates run.

- [x] **`data/DATA_DICTIONARY.md` documentation — done, scoped to match precedent.**
      Checked first: `injected_toxicity` (D12's structurally identical sweep-mode
      column) was never given a full column-spec section there either — the dictionary
      is scoped to the master ML-training schema, and mode-specific extension columns
      live in `runner.py`'s own code comments to avoid a second, driftable schema copy.
      Added a short pointer paragraph instead (which file, which mode, which two new
      columns, why) rather than duplicating the schema.

- [x] **Unrelated bug found while in this file — now fixed.** `CB_EVENT_BUFFER_SIZE` was
      emitted as **2000** into every generated `infra/.env`, not the documented/expected
      **50** every service's `application.yml` defaults to (flagged HIGH severity by
      `docs/reviews/2026-08-17-commit-review.md` 9 days ago, never fixed). No rationale
      for 2000 existed anywhere (checked `git log -S`), so reverted rather than propagated:
      deleted the dead `EVENT_BUFFER_SIZE=2000` constant, `.env` template points back at
      `CB_EVENT_BUFFER_SIZE=50`. Affected every mode's runs, not just occupancy's.

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
