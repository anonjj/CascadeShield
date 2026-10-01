# Phase 2 — gateway-contamination audit

Companion to `analysis/audit_gateway_contamination.py`. Outputs live under `data/audit/`
(gitignored). This note records method and findings only; it edits no existing claim.

## What counts as evidence

Gateway status comes **only** from the `cb_transitions` sidecar. `cb_state_pre` is a pre-load
snapshot and is not evidence about mid-run state. The D21 censoring columns
(`half_open_probe_timed_out`, `half_open_probe_deadline_s`) record half-open probe censoring
and are not evidence about gateway trips.

No gateway circuit-breaker trip was observed within the verified observation horizon under
either swept window type across the Phase 1 canary runs (n=4, LINEAR only, post-fix gateway
image `bdc2fff79e75`). Evidence preserved under `data/audit/canary_2026-09-20/`.

## Two timeline boundaries

| boundary | commit | timestamp |
|---|---|---|
| events-buffer fix, `CB_EVENT_BUFFER_SIZE` 50 → 5000 | `0494dd06` | 2026-08-27T17:16:00+05:30 |
| D25 gateway `measurement-plane` pin | `d1c6a481` | 2026-09-18T13:20:50+05:30 |

The buffer commit's own message is "was silently dropping CLOSED_TO_OPEN". A sidecar record
collected before it may have had a gateway `CLOSED_TO_OPEN` evicted from the 50-entry ring
before the harness polled, so absence of a trip in such a record is **not verified**.

Full value history of `CB_EVENT_BUFFER_SIZE` as written into `infra/.env`:

| window | value | commit |
|---|---|---|
| from 2026-08-04 | 50 | `6618f3d` |
| 2026-08-18 → 2026-08-26 | 2000 (via a shadowing `EVENT_BUFFER_SIZE`) | `eb10d489` |
| 2026-08-26 → 2026-08-27 | 50 | `f64e8a9` |
| 2026-08-27 onward | 5000 | `0494dd06` |

Sidecar writing began at `6618f3d` (2026-08-04). Today `observer.log(...)` is called
unconditionally at the end of every completed run for **all** modes (`runner.py:1449`); only
the destination differs (`canary` → `canary_cb_transitions.jsonl`, everything else →
`cb_transitions.jsonl`). Runs that abort before that point (readiness timeout, precondition
fail) produce a CSV row but **no** sidecar record.

## Join key

The brief's proposed key, `experiment_id + replicate + machine_id`, is **not unique** in every
dataset. `master_dataset_d21_recollect.csv` holds 45 rows over only 36 distinct such keys —
9 collisions, because `replicate` was reused across two collection passes on 2026-09-16
(~06:47 and ~14:05) with genuinely different measurements.

The key actually used is `experiment_id + replicate + machine_id + mode`, disambiguated by
`run_timestamp` proximity to the sidecar's `fault_injected_at` (tolerance 1800s) and assigned
**one-to-one**, so a sidecar record is never counted as evidence about two runs.

Two false-match classes were found and closed while building this, both of which had silently
manufactured verification that does not exist:

1. **Mode collision.** The Phase 1 canary reused `LIN-LAT-CNT-T70-W20-D30` and
   `LIN-LAT-TIM-T70-W20-D30` at replicates that also exist in `master_dataset.csv` on the same
   machine. Without `mode` in the key, those four post-D25 canary records attached to pre-D25
   sweep rows and produced four spurious `VERIFIED_CLEAN` rows.
2. **Cross-machine fallback.** `master_dataset.csv` carries `codespace` / `soham-local` /
   `jay-mac` / `jay-overnight-rerun` rows, while the in-repo sidecar is 72/73 `jay-mac`. A
   sole-candidate fallback ignoring `machine_id` attached `jay-mac` gateway evidence to other
   machines' runs (36 rows). The fallback is now permitted only when one side genuinely lacks
   `machine_id`.

## D24 reproduction

D24's stated clean-slice table reproduces **exactly**, and the slice is identifiable: it is the
**2026-09-16 batch** (the D21 re-collection), 36 sidecar records → 34 observations after the
two host-sleep-artifact exclusions.

| $D_w$ | COUNT-clean | COUNT-tripped | TIME |
|---|---|---|---|
| 5 | 6 | 0 | 5 |
| 15 | 2 | 4 | 5 |
| 30 | 0 | 6 | 6 |

**Discrepancy, not reconciled here.** A second, independent batch exists in the same sidecar —
the **2026-09-14 batch**, 36 records → 36 observations, corresponding to `master_dataset.csv`'s
36 `jay-mac` rows — which D24 did not use:

| $D_w$ | COUNT-clean | COUNT-tripped | TIME |
|---|---|---|---|
| 5 | 6 | 0 | 6 |
| 15 | 2 | 4 | 6 |
| 30 | 0 | 6 | 6 |

The second batch reproduces the same contamination *pattern* (zero COUNT trips at $D_w$=5, 4/6
at $D_w$=15, 6/6 at $D_w$=30), which corroborates D24's qualitative conclusion. But it means
D24's cell counts describe roughly half the sidecar evidence available at the time. Pooled,
COUNT-clean is n=12 at $D_w$=5 and n=4 at $D_w$=15, still n=0 at $D_w$=30.

This does not make the pooled set usable as "clean": both batches predate the D25 pin, so every
row in them is at best *sidecar-shows-no-trip, pre-D25* — not verified.

## Censoring columns (D21)

| | rows |
|---|---|
| carry `half_open_probe_*` natively | **46** (45 in `master_dataset_d21_recollect.csv`, 1 in `canary_runs.csv`) |
| would need inference from `cb_transitions.jsonl` | 5080 (all other rows under `data/`) |

Inference is feasible **only** where a sidecar record exists and is complete — at most 72
`jay-mac` records plus the Phase 1 canary. For every `codespace` and `soham-local` row it is
not feasible from anything in this repo: there is no sidecar for those machines here.

## Stale artifacts (listed, not touched)

- `data/master_dataset_schema.csv` — 48 columns, 0 data rows, header-only. Nothing writes it;
  `get_dataset_path()` has no case for it. It carries 13 columns the runner does not emit and
  is missing 3 it does. D8's prose says "47", which matches neither this file nor the code.
  `runner.DATASET_HEADERS` is **38**; `master_dataset.csv` is **36** (38 minus the two D21
  columns). `CLAUDE.md`'s "36" refers to the CSV, not to `DATASET_HEADERS` as it states.
- **Two canary invocations overwrite each other.** `runner.py:1686-1691` unlinks *both*
  `data/canary_runs.csv` and `data/canary_cb_transitions.jsonl` at the start of every canary
  invocation. A `--limit 1` smoke test followed by the real run destroys the smoke test's
  evidence; two arms run as separate invocations destroy the first arm's. For the Phase 4
  launch checklist: snapshot between invocations, or run both arms in one invocation.
