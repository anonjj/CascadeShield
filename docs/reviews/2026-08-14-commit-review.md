# Commit Review — 2026-08-14

**Mode:** commits-only (run_count ≥ 2, permanent). No full-repo scan; `CODEBASE_NOTES.md` not touched.

**Window:** `git log --since="24 hours ago"` at HEAD `737e767` (UTC 2026-08-14 21:35).

## Commits in window

| Hash | Author | Summary |
|------|--------|---------|
| `737e767` | Jay Joshi | Merge PR #23 (remove duplicate order/inventory service track) |
| `fbf222a` | Jay Joshi | chore(services): remove duplicate unwired order/inventory service track |
| `a01e654` | Jay Joshi | Merge PR #22 (runner `--limit` flag) |
| `9401855` | Jay Joshi | feat(harness): add `--limit` flag for single-run smoke tests |
| `183cf60` | Claude | prior automated review (run 2) — self-authored, skipped |

Two substantive changes to review: `9401855` (harness code) and `fbf222a` (pure deletion). Merge commits carry no independent content.

---

## `9401855` — feat(harness): `--limit` flag (`experiments/runner.py`)

Adds `apply_run_limit(run_list, limit)` returning `run_list[:limit]`, applied in `main()` **after** `build_shuffled_run_list`, with `total_runs` re-derived from the truncated list.

**Assessment: correct.** `py_compile` passes. The post-shuffle placement is the right call and matches the commit rationale — truncating before the shuffle would repeatedly sample the same low-index configs (a biased subset), whereas slicing the shuffled list yields a genuine random N-run subset. `total_runs = len(run_list)` is reset immediately after truncation (runner.py:1365), so every downstream consumer — the `Run X of total_runs` progress print (1382), all `write_status` payloads (1374/1385/1398/1410), and the final `SWEEP COMPLETED` line (1405) — reports the truncated count consistently. `run_status.json` stays coherent with what actually ran. No schema, `DEFAULT_TAU`, `blast_radius`, or dataset-column contract is touched.

### Findings

- **`experiments/runner.py:1363-1364` — negative `--limit` silently truncates instead of erroring — severity: low.**
  `--limit` is `type=int` with no lower bound, and `apply_run_limit` does a bare Python slice. `--limit -1` → `run_list[:-1]` runs *all but the last* config rather than raising; `--limit -5` drops the last 5. A user fat-fingering a sign gets a silently-wrong-sized sweep with no warning (the truncation print would read `truncated to <len-1> run(s)`, which looks plausible). `--limit 0` → empty list → a 0-run "sweep" that completes with `SWEEP COMPLETED: 0/0` and writes a `completed` status having done nothing — degenerate but harmless.
  **Fix:** guard for `limit < 1` where the flag is consumed (runner.py:1363), e.g. `if args.limit is not None and args.limit < 1: parser.error("--limit must be >= 1")`. Cheap and removes both foot-guns.

No correctness, dead-code, or cross-module issues in this change.

---

## `fbf222a` — chore(services): remove duplicate order/inventory service track

Deletes 677 lines: the entire `services/service-a-order/` and `services/service-b-inventory/` prototype trees plus `services/README.md`. Per the commit body, these were a never-wired Week-1 prototype whose README advertised ports 8081/8082 that collide with the *real* mesh services (`order-service`, `inventory-service`).

**Assessment: clean removal, correctly scoped.** Verified no live code or infra still references the deleted trees:
- No hits for `service-a-order`/`service-b-inventory` in any `*.yml`/`*.yaml`/`*.java`/`*.py`/`*.json` (infra + source).
- The surviving `order-service`/`inventory-service` references in `gateway-service` (`BlastRadiusService.java:30-31`, `GatewayDownstreamService.java`, `GatewayController.java`) and `application.yml` point at the **real mesh services** on 8081/8082 — those are the intended targets, and removing the duplicate track eliminates the port collision the commit describes rather than creating a dangling reference.

### Findings

- **`plans/mentor-report.md:165,253,265` — stale references to the now-deleted track — severity: low (docs only).**
  The deletion left three references to the removed track in `plans/mentor-report.md`, including a "next steps" item (line 265) pointing at `services/service-a-order/src/main/.../client/InventoryClient.java`, a path that no longer exists. `plans/week1-jay-implementation-plan.md` also mentions the ports, but those lines refer to the real `order-service`/`inventory-service` and remain accurate.
  **Fix:** update or drop the three `mentor-report.md` lines so the planning doc doesn't send a reader to a deleted seam. *(Outside `docs/reviews/`; reported only, not modified by this routine.)*

---

## Summary

| # | Location | Issue | Severity |
|---|----------|-------|----------|
| 1 | `experiments/runner.py:1363` | Negative/zero `--limit` silently truncates instead of erroring | low |
| 2 | `plans/mentor-report.md:165,253,265` | Stale references to deleted `service-a-order`/`service-b-inventory` track | low |

No high- or medium-severity issues. Both substantive changes are correct and well-reasoned; the two findings are minor hardening/hygiene items. `experiments/runner.py` compiles cleanly.
