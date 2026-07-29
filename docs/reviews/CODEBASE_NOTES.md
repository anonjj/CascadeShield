# CascadeShield — Codebase Review Notes

Purpose: classify each top-level area as **active** (core logic, reviewed in
full every run) or **stagnant** (boilerplate that rarely changes — deep-reviewed
once, then skipped on later runs unless its files changed since the
`last_reviewed` commit). The automated review routine consults this file to
prune work on subsequent runs.

- Repo HEAD at first review: `0f961c3`
- First full review: `2026-07-28` (run 0)
- Second full review: `2026-07-29` (run 1) at HEAD `21b9ae7`. Only `docs/reviews/`
  changed since run 0 — no source moved, so every stagnant item below was checked
  with `git log <last_reviewed>..HEAD -- <path>`, all returned 0 commits, and all
  were skipped. Classifications and `last_reviewed` hashes are therefore unchanged
  from run 0. Active areas were re-walked in full; findings M1–L4 all still open.

## Active areas (review in full every run)

These carry the fault-injection harness and ML pipeline logic — the code most
likely to change and to harbor correctness/schema bugs.

| Path | Why active |
|------|-----------|
| `experiments/` | Fault-injection harness (`runner.py`, `fault_injector.py`). Measurement logic, dataset write path, blast-radius sampling. |
| `ml/` | ML pipeline: preprocessing/schema contract, decision tree, isolation forest, synthetic data, Lambda, closed-loop demo. Holds `DEFAULT_TAU`, `BLAST_RADIUS_SCALE`, the encoded-feature contract. |
| `dashboard/` | `app.py` / `data_loader.py` — aggregation + rendering logic tied to the dataset schema. |
| `data/` | Dataset + schema contract (`DATA_DICTIONARY.md`, `master_dataset.csv`, `master_dataset_schema.csv`, `experiment_matrix.csv`). Schema is the cross-module contract. |
| `services/gateway-service/` | Not pure boilerplate: `BlastRadiusService` + `GatewayController` implement the topology routes and the blast-radius aggregator `runner.py` depends on. Treat as active. |

## Stagnant areas (deep-reviewed once; skip if unchanged since `last_reviewed`)

Spring Boot microservices that are structural scaffolding for the mesh. Each is
a thin controller + downstream client + exception pair with near-identical
shape across services. Reviewed once at the hashes below.

Run-1 status column records the second-run pruning check (`git log <last_reviewed>..HEAD`).

| Path | last_reviewed | Run-1 (2026-07-29) | Notes |
|------|---------------|--------------------|-------|
| `services/order-service/` | `82f01d3` | skipped — unchanged | Downstream node in the mesh. Boilerplate controller/service/exceptions. |
| `services/inventory-service/` | `82f01d3` | skipped — unchanged | Latency-fault target. Boilerplate. |
| `services/payment-service/` | `82f01d3` | skipped — unchanged | Crash-fault target. Boilerplate. |
| `services/notification-service/` | `82f01d3` | skipped — unchanged | Leaf node; health-checked by `runner.wait_for_healthy`. Boilerplate. |
| `services/shared-db-service/` | `f8d0f2a` | skipped — unchanged | Throttle-fault target (shared dependency). Boilerplate. |
| `services/service-a-order/` | `e75c0ee` | skipped — unchanged | **Parallel "business-logic" track (Soham), NOT wired into `infra/docker-compose.yml`.** Duplicate order impl vs `services/order-service`. See finding L1. |
| `services/service-b-inventory/` | `e75c0ee` | skipped — unchanged | Parallel track pair for `service-a-order`. Not in the mesh. See finding L1. |
| `infra/` | `f7af13a` | skipped — unchanged | docker-compose, Prometheus/Grafana provisioning. Config, not logic. |
| `make_figures.py` | `07fb846` | skipped — unchanged | One-off figure generator. Rarely changes. |

## Classification rule for later runs

For each stagnant item, run `git log <last_reviewed>..HEAD -- <path>`:
- **No commits** → skip deep review, note "skipped — stagnant, unchanged since `<hash>`".
- **Commits present** → review fully, reclassify as active if it now carries real logic, and bump `last_reviewed` to HEAD.
