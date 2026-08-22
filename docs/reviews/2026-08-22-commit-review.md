# Commit Review — 2026-08-22 (run 2, commit-only mode)

Scope: commits in the last 24 hours (window: 2026-08-21 21:35 UTC → 2026-08-22 21:35 UTC). Focus areas: `experiments/`, `ml/`, `services/`.

## Commits inspected

`git log --since="24 hours ago" --pretty=oneline` returned a single commit:

| Commit | Author | Subject |
| --- | --- | --- |
| `2652131` | (review bot) | chore(review): automated review 2026-08-21 (run 2) — skipped (own automated commit, docs/reviews only) |

No new source commits landed in the last 24 hours. The only commit in the window touches `docs/reviews/` exclusively (`2026-08-21-commit-review.md`) and is this routine's own output from the previous run.

## Findings

None. No source code changed in the review window.

## Notes

- The last substantive source commit remains `eb10d48` ("feat: update dataset schema to include mode and permitted_calls_half_open, and refine blast radius normalization", authored 2026-08-17 19:52 UTC), which is well outside this window and was reviewed in `docs/reviews/2026-08-17-commit-review.md`. Not re-reviewed here.
- Outstanding findings from prior reviews (e.g. the `CB_EVENT_BUFFER_SIZE` vs `EVENT_BUFFER_SIZE` "must match application.yml" contract discrepancy in `experiments/runner.py` noted on 2026-08-17) remain open — no commit in this window addressed them.
- Numerous feature/fix branches exist on the remote (e.g. `feat/dataset-schema`, `feat/compute-phi`, `feat/effective-horizon`, `fix/measurement-validity`, `integrate/measurement-validity-into-main`, `feat/harness-measurement-fixes`, `feat/soham-day1-day2-formalization-and-audit`, `feat/interior-breaker-transitions`, `fix/breaker-state-reset-precondition`), but none have merged to `main` within this window, so they are out of scope for commit-only review. If any of these merge, they will surface in the next day's commit review.
