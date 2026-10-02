# CascadeShield — reproducibility manifest

What produces each claim the paper makes, what's committed, what governs it in
`docs/paper/decision-log.md`, and what a third party actually needs to reproduce it. Built
2026-10-02, against `main` at the commit this file is itself committed in.

This file is itself a claim about the repo's current state — if a script moves, is renamed,
or its output changes, update this table in the same commit. Do not let it drift the way
`STATUS.md` drifted on the H3 row for two weeks (D30's bookkeeping note).

---

## Claims and their artifacts

| Claim | Script | Committed output | Dataset(s) | Governing decision(s) | Reproducible from |
|---|---|---|---|---|---|
| **ρ asymmetry** — TIME_BASED shows a clean crossover at ρ=1, COUNT_BASED shows none (0/54 ever inert) | `analysis/occupancy_asymmetry_figure.py` | `analysis/out/occupancy_asymmetry.json`, `figures/fig8_occupancy_asymmetry.{png,pdf}` | `data/occupancy_dataset.csv` | D18 | **Committed data only.** Load the dataset, run the script. |
| **The two-directions result** — `minimumNumberOfCalls` unsatisfiable under TIME_BASED, unenforceable under COUNT_BASED | Same mechanism as ρ asymmetry (D18); gateway-isolation verification that the COUNT_BASED side wasn't measurement-plane-contaminated is D23's live fault run, not a committed script output — see D23's entry for the verification method | `analysis/out/occupancy_asymmetry.json` (same file; this claim is a reading of it, not a separate computation) | `data/occupancy_dataset.csv` | D18, D23 | **Committed data only** for the asymmetry itself. D23's gateway-isolation claim (zero `CLOSED_TO_OPEN` events on a real fault run) is **not** independently re-checkable from committed data alone — it rests on a one-time live run reported in the decision log, not a re-runnable script against a committed dataset. |
| **R2 and the recovery null** — H3's recovery-side control passes under equal fault exposure; the 2026-09-22 "H3 falsified"/"recovery leak" reading is retracted as a harness fault-exposure artifact | `analysis/r2_equal_exposure_analysis.py` (self-tested) | `analysis/out/r2_equal_exposure_analysis.json` | `data/r2_equal_exposure.csv`, `data/r2_cb_transitions.jsonl`, `data/audit/r2_sweep_poll.jsonl` (the independent gateway witness) | D28 (diagnosis), D29 (confirmatory result) | **Committed data only.** `python3 analysis/r2_equal_exposure_analysis.py` reproduces every number in D29 from the three committed files above, no network, no mesh. |
| **Config audit, reconciled** — 1,057 instances / 626 files / 537 blobs / 384 of 740 repositories; the corpus measures propagation (one parameter pair is 433 instances across ~3–5 template lineages), not independent practice | `analysis/config_audit_parser.py` (16 self-tests) + `analysis/config_audit_v2_report.py` | `analysis/out/config_audit_v2_report.json`, `audits/corpus_fingerprint.json` (the sorted list of 991 distinct content blob shas, the 4 search queries, and the scrape date — no repo identifiers) | **Not committed** — see "Not reproducible" below | D30 | **Not reproducible from the repo alone**, but **verifiable**: a fresh search's blob-sha set can be diffed against `audits/corpus_fingerprint.json` to show exactly how the corpus has drifted, without this repo ever naming a repository. Requires a fresh GitHub code search, a token, and a per-blob re-fetch by sha; see below for exactly why. |
| **Breaker-state hygiene** — `cb_state_pre` CLOSED and `buffered_calls_pre` 0 on all 10 breakers, all 360 runs (3,600 per-breaker observations, zero exceptions) | No dedicated script — a direct property of two columns in the committed dataset, checked ad hoc (`pandas`/`csv` groupby over `cb_state_pre`/`buffered_calls_pre`, 10 breakers × 360 rows) | None named; the claim is the raw column values themselves | `data/master_dataset.csv` | Not tied to a single numbered decision; it's the run-hygiene precondition `experiments/runner.py`'s `setup_and_check_precondition()` enforces on every run, read back from the dataset it produced | **Committed data only.** Load `master_dataset.csv`, check `cb_state_pre`/`buffered_calls_pre` on all rows. Scope note carried over from `PAPER_BRIEF.md`: this is load-start hygiene, it says nothing about mid-run state. |
| **λ fidelity** — 38/300 canary runs missed target λ by >15%, worst 35.3%; H1/H2 are read off `lambda_achieved`, never `lambda_target` | `analysis/canary_readout.py` | `analysis/out/canary_readout.json` | `data/canary_matrix_runs.csv` (300 run results), `data/canary_matrix.csv` (360-row design file — the only source of the `arm` column) | D-004 (Day-2 Gate) | **Committed data only.** `python3 analysis/canary_readout.py` — the `--dataset` default now correctly points at the committed `data/canary_matrix_runs.csv` (fixed 2026-10-02; it previously defaulted to a gitignored, non-canonical `data/canary_runs.csv`). **Diagnosed and fixed, 2026-10-02: a real bug, not a documentation gap.** `data/canary_matrix_runs.csv` never carries an `arm` column; `h2_base_arm()`'s base-arm filter silently no-opped when `arm` was absent, pooling the `matched_horizon` arm into what's supposed to be base-only (verified exactly: 120 base + 60 matched_horizon = 180, the fresh-run discrepancy first noticed). Fixed two ways: `load_canary()` now joins `arm` in from `data/canary_matrix.csv` on `(run_index, replicate)` for every caller, and `h2_base_arm()` now raises instead of silently skipping its filter if `arm` is still absent or has no `base` rows. **The originally-committed `analysis/out/canary_readout.json` was correct throughout** — a fresh run after the fix reproduces it byte-for-byte (confirmed via `git diff`, zero lines). Not regenerated; nothing to regenerate. The committed output was produced on 2026-09-05 with the `arm` join applied in-session but never committed to `canary_readout.py` itself, so the repo held a correct output its own script could not reproduce until this commit. |

---

## Not release artifacts

`PAPER_BRIEF.md` and `PAPER_DRAFT_NOTES.md` are working documents, not release artifacts.
Both now carry a header saying so (added in this commit). They contain unverified literature
candidates (e.g. the Pashko et al. bibliography entry, explicitly flagged uncitable),
in-progress self-criticism dated through several sessions, and framing later superseded in
`decision-log.md` (kept in place and labeled, per this repo's append-only convention, not
deleted). Do not cite either file as a source of verified numbers — `decision-log.md` and the
committed `analysis/out/*.json` files are the source of truth; these two are the audit trail
for *why* the brief says what it currently says.

---

## Environment

| Component | Version | Source |
|---|---|---|
| Java | 17 | `cascadeshield-parent/pom.xml` |
| Spring Boot | 3.2.5 | `cascadeshield-parent/pom.xml` (`spring-boot-starter-parent`) |
| Resilience4j | 2.2.0 | `cascadeshield-parent/pom.xml` (`resilience4j.version`) |
| `minimumNumberOfCalls` default | `main` pins **5** (`${CB_MINIMUM_CALLS:5}` in every service's `application.yml`). An abandoned, never-merged branch (`feat/harness-measurement-fixes`, deleted 2026-10) used a different default, **10** (its own `CB_MIN_CALLS` env var) — main's value of 5 is the one actually used for every collected dataset. | Every `services/*/src/main/resources/application.yml` |
| Toxiproxy | 2.9.0 | `infra/docker-compose.yml` (`ghcr.io/shopify/toxiproxy:2.9.0`) |
| Docker Engine | **Not recorded anywhere in the repo, for either host.** A real gap, flagged rather than guessed. `jay-mac` is known to run Docker in a VM (arm64; `docs/paper/r2-equal-exposure-plan.md` §8), which is a host-architecture fact, not a version. | — |
| Python | 3.9 — `analysis/common.py`'s own module docstring states "Python 3.9 compatible" as a constraint on every analysis script; `analysis/recovery_fault_timing_check.py` and the `deviation-02-horizon-simplification.md` correction note both work around specific Python-3.9 stdlib behavior (`fromisoformat`'s fractional-seconds parsing). **No `requirements.txt` or pinned-version file is committed** — a real gap, flagged rather than guessed. | `analysis/common.py` module docstring |

### Collection hosts

| Host | Architecture | Used for |
|---|---|---|
| `soham-local` | x86 | Phase 4B (D26's re-collection) |
| `jay-mac` | arm64, Docker in a VM | R2 (D28/D29's equal-exposure confirmatory run) |

### Gateway image digests — different builds, not directly comparable

| Collection | Image digest | Built |
|---|---|---|
| Phase 4B (`soham-local`) | `sha256:ce110c0a0bfbc290e735fe810f4bb5a60b2ef84ad5e63c0b627a0b90cecbabfc` | 2026-09-19T22:14:43Z |
| R2 (`jay-mac`) | `sha256:c281f7db011e9176bf98f3ae325d3ff01deaa64cc5de73f42bcc2961883ca6b2` | 2026-09-18T13:19:21+05:30 |

Both postdate D25 (the measurement-plane fix) by source inspection, but **the differing
digest means that cannot be verified from the digest alone** — only by reading each image's
packaged `application.yml` (`data/audit/r2_image_manifest.json`'s own stated limitation). R2's
numbers are not compared to Phase 4B's in absolute terms anywhere in the paper for exactly
this reason (`docs/paper/r2-equal-exposure-plan.md` §8).

### D16 cross-machine calibration evidence

`data/audit/d16_calibration/` holds the three small (3-row) smoke-test CSVs that fed D16
("Cross-machine confounding", closed, `MACHINE_EFFECT_NEGLIGIBLE`) — preserved from three
now-deleted branches (`data/d6-calibration-codespace`, `-codespace-v2`, `-soham`). Nothing in
`decision-log.md` or `STATUS.md` cites these by filename; they're D16's actual raw evidence,
kept for provenance, not because anything currently depends on them.

---

## What is NOT reproducible from the repo, and why

**The config audit (D30).** `audits/.cache/hits.jsonl` and `audits/.cache/repos.jsonl` —
**correcting an assumption in this task's own brief: neither file is committed.** Both are
gitignored, confirmed by `git ls-files` returning nothing for either path. A third party has
two gaps to close, not one:
1. **Regenerating the hit list itself** requires a fresh GitHub code search (the 4 queries are
   documented in `analysis/config_audit_parser.py`'s source lineage and
   `analysis/lambda_star_ecdf.py`), authenticated with a token — and GitHub's search index
   changes over time (repos deleted, renamed, re-starred), so a fresh search is not guaranteed
   to return the identical 1,141 hits the 2026-09-17 scrape did.
2. **Even given the original hit list**, re-fetching file content requires a token and a
   per-blob GET by git blob sha against GitHub's Git Data API — read-only, but still a network
   dependency this repo cannot discharge on its own.

A fresh search **will** return a drifted corpus — that's expected, not a failure mode to work
around. `audits/corpus_fingerprint.json` is committed for exactly this: the 4 search query
strings verbatim, the 2026-09-17 scrape date, and the sorted list of all 991 distinct content
blob shas (plus hit/repo counts as numbers only). A third party re-runs the same 4 queries,
collects the resulting blob shas, and diffs that set against the committed one — showing
precisely which blobs are new, which have disappeared (deleted/renamed source repos), and
which are unchanged, without this repo ever naming a third-party repository in the comparison.

Both steps exist because the raw scrape contained real third-party credentials (an OpenRouter
API key, a Google OAuth client ID+secret — caught by GitHub's own push protection on an
earlier attempt to commit it). Only the anonymized, aggregate output
(`analysis/out/config_audit_v2_report.json`) is committed; no repo name, path, or blob sha is.

**Live mesh sweeps** (Phase 4B, R2, the canary matrix, the occupancy sweep). These need the
six-service Docker Compose mesh running, Toxiproxy configured, and real wall-clock time — not
re-derivable from any committed file. What's committed is each sweep's *output*, not the
capability to re-run it identically; a fresh run would be a new, differently-timestamped
collection, not a reproduction of the existing one.
