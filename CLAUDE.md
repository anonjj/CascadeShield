# CascadeShield — session context

**Read [`STATUS.md`](STATUS.md) first.** It says where the project is: what's done, what's
blocked, what's next, and which numbers are safe to quote. Do not re-derive project state from
`docs/paper/decision-log.md` (664 lines) — read `STATUS.md`, then go to the decision log only
for the *why* behind a specific decision.

This repo is a circuit-breaker fault-injection research harness backing a paper by Jay Joshi
and Soham More. Most work here is **measurement**, so a wrong number is worse than no number.

## Sources of truth (these have actively misled past sessions)

| Question | Authoritative answer |
|---|---|
| How many columns is the dataset schema? | **36** — `DATASET_HEADERS` in `experiments/runner.py`. `data/DATA_DICTIONARY.md` has drifted and still describes a never-implemented 48-column D8 schema |
| Which datasets exist, and how many rows should each have? | `analysis/common.py`'s `DATASETS` dict. Note `data/occupancy_dataset.csv` is **not** registered there |
| Which file is the live dataset? | `data/master_dataset.csv` — currently **324 rows, LATENCY-only**. A stray `master_dataset.csv` at the **repo root** is *not* it |
| Is an `analysis/out/*.json` number current? | Usually **no** — 7 of 8 predate the 2026-09-06 CRASH-strip. Re-run before quoting |
| What's the current state of `main`? | `git fetch origin` and look. It moves faster than any session's memory of it |
| Where is the backlog? | `STATUS.md`'s *Remaining work* table. "B" numbers in older commits (B5, B8) refer to a board that no longer exists and was never in the repo — historical record only, don't chase them |

## Conventions

- **Branch per unit of work**, PR via `gh pr create`. **Never merge or push directly to `main`.**
- Use a **`git worktree`** when the local checkout has unrelated uncommitted work.
- Changes to measurement functions need **live-mesh verification**, not just unit reasoning.
- Decision records are **appended, never rewritten** — add `**Update (YYYY-MM-DD).**` rather
  than editing history away.

## Running experiments — footguns that have cost real data

1. **`export DATASET_PATH_OVERRIDE=<file>` before every run**, and verify the file appears ~2
   minutes after launch. `get_dataset_path()` silently falls through to `master_dataset.csv`
   for modes it has no case for. This has misfiled data twice.
2. **Long sweeps run detached:** `nohup python3 -u … > run.log 2>&1 & disown`. An SSH drop won't
   kill it; a **codespace VM restart kills the job *and* Docker**. After a restart:
   `docker compose -f infra/docker-compose.yml up -d --build`, then confirm
   `curl http://localhost:8474/proxies` returns JSON before relaunching.
3. **`data/cb_transitions.jsonl` is gitignored** — commit it with `git add -f` when an analysis
   depends on it, or the run is wasted.
4. Sweeps are **resumable** by `(experiment_id, replicate)` for rows with
   `precondition_ok=True`. A fix that doesn't change `experiment_id` will be silently skipped
   on re-run — remove the stale rows first.

## Stack, in one paragraph

Six Spring Boot services behind a gateway, all inter-service traffic routed through a Toxiproxy
sidecar so faults are injected on the wire without touching the victim service. Resilience4j
circuit breakers are reconfigured per run through `infra/.env` and container recreation — no
rebuilds. Prometheus and Grafana exist for **live human observation only**; the dataset comes
from `runner.py` polling each service's `/actuator/metrics` directly and never touches
Prometheus.
