# D11 (port) — remove THROTTLE from `main` as well

> Backed up from the local Claude Code plan-mode file
> (`~/.claude/plans/enumerated-greeting-ladybug.md`), which lives outside git and isn't
> durable across machines/connectivity drops. This is the exact plan approved via
> `ExitPlanMode`; execution had not started as of this backup. Not yet done as of this
> commit — see D7/D12 in `task.md` for what's actually landed on this branch so far.

## Context

D11 (throttle fault-type removal) was already decided and fully implemented on our dev
line — commit `29f7da6` on `worktree-session-handoff` — but was never proposed to `main`,
which still has `throttle` as a live `--fault` choice. The user now wants that same
removal ported to `main`, adding a mechanistic justification to verify: throttle's
injection (`inject_bandwidth_limit`, 1 KB/s on `shared-db-service-proxy`) doesn't exercise
a scientifically distinct trip path from `latency` — both just produce a slow call, and
every service's `application.yml` already sets `slow-call-duration-threshold: 2s` /
`slow-call-rate-threshold`, so Resilience4j's own slow-call-rate path (not the
failure-rate path) trips on either fault identically. **Verified true** — read every
service's `application.yml` and `fault_injector.py`; throttle's mechanism reduces to
"produce a call slower than 2s," which is exactly what `latency`'s 3000ms delay already
does. There is no code in `runner.py` or the CB config that treats throttle-induced
slowness differently from latency-induced slowness. This directly reinforces D11's
original rationale ("redundant with LATENCY's slow-call mechanism") rather than replacing
it — worth stating in the ported commit message as additional, independently-verified
evidence.

**Why this matters for the sweep the user is about to run:** `main` currently still
advertises `--fault throttle` as valid, and if left in, a `--mode full` sweep on `main`
would default to iterating 3 fault types (486 runs) instead of 2 (324), burning real
Codespace compute on a fault type already decided to be dropped and never producing usable
data historically. This is exactly the "committing extra sweep time for it" the user
flagged.

## Where this lands

PR #24 (`merge/a1-a3-a5-harness-gaps` → `main`, already open, not yet merged) currently
has a deliberate carve-out comment in `experiments/runner.py` keeping `throttle` alive
*because D11 was explicitly out of scope for that merge*. Since D11 is now in scope,
adding it as a new commit on the same open branch is simpler and avoids a second PR
fighting the first over the identical `--mode`/`--fault` argparse lines. **Plan: cherry-pick
`29f7da6` onto `merge/a1-a3-a5-harness-gaps`, resolve the conflicts, update PR #24's
description, and re-push the same PR** (not a separate branch/PR).

## Verified via `git merge-tree` (read-only dry run, no working-tree changes made)

Simulated `git merge-tree 5ddda75 origin/merge/a1-a3-a5-harness-gaps 29f7da6` (base = D11's
actual parent commit) to find every real conflict before touching anything. D11 touches 12
files; **7 auto-merge cleanly** (`README.md`, `data/experiment_matrix.csv`,
`experiments/fault_injector.py`, `make_figures.py`, `ml/README.md`,
`ml/closed_loop_demo.py`, `ml/preprocessing.py`) — no action needed beyond taking the
cherry-pick's result. **5 are flagged "changed in both"**, but only one has an actual
`<<<<<<<` conflict marker:

1. **`experiments/runner.py`** — **real conflict**, exactly where expected: the
   `--mode`/`--fault` argparse block I hand-edited in `a014d4c` (kept `throttle`, added
   the "out of scope" comment). Resolution: drop `throttle` from `--fault` choices, delete
   the now-stale "kept deliberately" comment, keep `occupancy` in `--mode` choices, and
   restore D11's "324 total across 2 faults" wording in the `--mode` help text (undoing my
   earlier manual "486/3 faults" patch, which only existed because D11 wasn't in scope
   yet). Every other hunk in this file (the `PARAM_VALUES` comment, `inject_fault`'s
   throttle branch, `fault_map`, a docstring comment, `generate_combinations`' comment)
   applies cleanly — untouched by the A1/A3/A5 cherry-picks, so no actual clash.
2. **`data/DATA_DICTIONARY.md`** — flagged but **no conflict markers** in the dry run;
   D11's hunks (lines ~60-98, ~425) and Soham's post-merge edits (RESTRUCTURE blockquote,
   `minimum_number_of_calls` row, 47-col schema paragraph, occupancy section) sit in
   different regions of the file. Expect this to apply with at most a trivial
   line-offset nudge — verify by reading the file after the cherry-pick, not by
   hand-resolving blind.
3. **`ml/generate_synthetic_data.py`** — same story, no actual markers, expect clean
   apply (drops `THROTTLE` from `FAULT_CODE`/`FAULT_BASE`/`WT_INTERACTION`/
   `FAULT_ERROR_ADJ` and the narrative).
4. **`ml/models/time_to_open_tree_rules.txt`** and **5.
   `ml/models/time_to_recover_tree_rules.txt`** — **real conflicts**, and these are
   *generated* artifacts (decision-tree dumps), not something to hand-patch. D11's own
   commit message says these were "regenerated from the throttle-free generator," not
   manually edited. Same plan here: after resolving 1-3 above, run whatever `ml/train_all.py`
   (or the specific retraining command D11 used) regenerates them, and let regeneration
   overwrite the conflicted files rather than resolving their `<<<<<<<` markers by hand.

## Implementation steps

1. On `merge/a1-a3-a5-harness-gaps` (already checked out once this session — reuse it),
   `git cherry-pick -x 29f7da6`.
2. Resolve `experiments/runner.py`'s conflict as described above (drop `throttle`, delete
   the stale comment, restore "2 faults/324 total" wording).
3. Let the DATA_DICTIONARY.md / generate_synthetic_data.py conflicts resolve (git may
   need `git checkout --theirs`/manual accept-both since they're flagged, even without
   markers) — then **read the resulting files** to confirm no duplicated/garbled text
   before trusting them.
4. Regenerate `ml/models/time_to_open_tree_rules.txt` and
   `ml/models/time_to_recover_tree_rules.txt` via the project's existing training entry
   point (`ml/train_all.py`) rather than hand-resolving their conflict markers.
5. `git add`, `git cherry-pick --continue`.
6. Verify, mirroring D11's own original verification (same repo, same checks, just on
   `main`'s tree now): `py_compile` every touched `.py` file; `--help` shows `--fault`
   without `throttle` and rejects `--fault throttle`; `generate_combinations()` config
   counts unchanged (54/5/4); `python3 ml/generate_synthetic_data.py` (or equivalent)
   produces 324×2×3 = 1,944 rows; `python3 ml/test_smoke.py` passes; add a short note to
   the mechanistic-redundancy finding (slow-call-threshold verification) either in the
   cherry-picked commit's trailer or as a small follow-up doc line — do not silently drop
   evidence the user explicitly asked to verify.
7. Push the updated branch: `git push origin merge/a1-a3-a5-harness-gaps` (fast-forward,
   same PR #24 — no new PR needed). Update the PR #24 description to note D11 is now
   included and why (mechanistic-redundancy verification, extra-sweep-time avoidance).
8. Return to `worktree-session-handoff`.

### Critical files
- `experiments/runner.py` (the one real conflict — `--mode`/`--fault` argparse block)
- `data/DATA_DICTIONARY.md`, `ml/generate_synthetic_data.py` (expected-clean, verify by
  reading after cherry-pick)
- `ml/models/time_to_open_tree_rules.txt`, `ml/models/time_to_recover_tree_rules.txt`
  (regenerate, don't hand-merge)
- `ml/train_all.py` (regeneration entry point), `ml/test_smoke.py` (post-merge check)

**Done when:** PR #24 has `throttle` removed from `main`'s harness/ML pipeline exactly as
D11 already did on the dev line, all of D11's original verification checks pass again on
this tree, the mechanistic (`slow-call-rate-threshold`) redundancy finding is recorded
somewhere durable (not just this conversation), and nothing outside D11's original
12-file footprint plus the one merge-conflict resolution is touched.
