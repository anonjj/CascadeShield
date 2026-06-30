# Week 1 Implementation Plan — Jay's Part (Gateway + Service C/D + Docker Compose)

**Source:** Calendar event "🛠️ Jay — Week 1: Gateway + Service C/D + Docker Compose" (Jun 7–13)
**Repo:** `/Users/jayjoshi/Documents/Capstone project` (CascadeShield)
**Audience:** This plan is written for a lower-cost model to execute task-by-task. Each task is self-contained, has exact commands, and a binary DONE check. Execute tasks in order unless marked `[parallel-ok]`.

---

## Current state (already done — do NOT rebuild)

- All 6 Spring Boot 3.2.5 / Java 17 services exist under `services/`:
  `gateway-service` (8080), `order-service` (8081), `inventory-service` (8082),
  `payment-service` (8083), `notification-service` (8084), `shared-db-service` (8085).
- Mapping to calendar names: Gateway=gateway-service, A=order, B=inventory, C=payment, D=notification (+shared-db).
- Resilience4j 2.2.0 CircuitBreaker is wired with env-var overrides (`CB_*`) in every caller service's `application.yml`.
- `infra/docker-compose.yml` is committed: all 6 services + Postgres + DynamoDB Local + Toxiproxy + Prometheus + Grafana, with `JAVA_OPTS=-Xmx512m -Xms256m -XX:+UseG1GC` on every service.
- Service-to-service calls route through Toxiproxy ports 8661–8665; `experiments/fault_injector.py` has `ToxiproxyClient.initialize_proxies()` (run with `python3 experiments/fault_injector.py`) that creates all 5 proxies.
- `experiments/runner.py` exists (one uncommitted 1-line help-text fix: 54→162 runs).

## Ground rules for the executing model

1. **Do not** refactor working code, rename services, change ports, or alter the CB parameter env-var contract (`CB_SLIDING_WINDOW_SIZE`, `CB_SLIDING_WINDOW_TYPE`, `CB_FAILURE_RATE_THRESHOLD`, `CB_WAIT_DURATION_OPEN`, `CB_PERMITTED_CALLS_HALF_OPEN`). Downstream weeks depend on these exact names.
2. **Do not** add Resilience4j `@Retry` anywhere — retries are explicitly OFF in the baseline (decision D5, Week 2 plan).
3. Fix-forward only: if a verification step fails, make the smallest change that makes it pass, and record what you changed.
4. All git work happens on a feature branch (Task 1). Never commit to `main` directly.
5. If Docker is not running, start Docker Desktop first (`open -a Docker` and wait for `docker info` to succeed).
6. Keep a running log of results in `plans/week1-verification-log.md` (create it in Task 1): one section per task, with command output snippets for each DONE check.

---

## Task 1 — Create feature branch + verification log

```bash
cd "/Users/jayjoshi/Documents/Capstone project"
git checkout -b week1-jay-verification
```
Create `plans/week1-verification-log.md` with a heading per task (T1–T8).

**DONE when:** `git branch --show-current` prints `week1-jay-verification` and the log file exists.

## Task 2 — Compile all 6 services `[parallel-ok across services]`

For each service in `services/*`, verify it compiles. Prefer Docker (no local Maven needed):

```bash
cd "/Users/jayjoshi/Documents/Capstone project/infra"
docker compose build gateway-service order-service inventory-service payment-service notification-service shared-db-service
```

If a service fails to compile, fix only the compilation error (missing import, typo, bad YAML) — no redesigns.

**DONE when:** `docker compose build` exits 0 for all 6 services.

## Task 3 — Boot the full stack and initialize Toxiproxy

```bash
cd "/Users/jayjoshi/Documents/Capstone project/infra"
docker compose up -d
docker compose ps        # wait until postgres/dynamodb/toxiproxy are healthy, all services Up
cd .. && python3 experiments/fault_injector.py   # creates the 5 proxies
```

Note: services call each other through Toxiproxy ports 8661–8665, so the linear chain will FAIL until the proxies exist. Initializing proxies right after `up` is required, not optional.

**DONE when:** `docker compose ps` shows all 9 containers Up, and `curl -s localhost:8474/proxies` lists all 5 proxies (`order-service-proxy` … `shared-db-service-proxy`).

## Task 4 — Health endpoints on all 6 services

```bash
for p in 8080 8081 8082 8083 8084 8085; do
  echo "== $p =="; curl -s localhost:$p/actuator/health | head -c 300; echo
done
```

Also verify Prometheus metrics endpoints respond: `curl -s localhost:8080/actuator/prometheus | head -5` (repeat for any one downstream service).

If a service reports DOWN, inspect `docker compose logs <service>` and fix the root cause (most likely: datasource config on order/inventory, or DynamoDB endpoint on payment).

**DONE when:** all 6 `/actuator/health` return `"status":"UP"`.

## Task 5 — End-to-end communication (the Week 1 gate)

Test all three topology endpoints on the gateway:

```bash
curl -s -w '\n%{http_code}\n' localhost:8080/api/v1/linear
curl -s -w '\n%{http_code}\n' localhost:8080/api/v1/fanout
curl -s -w '\n%{http_code}\n' localhost:8080/api/v1/mesh
```

Expected: HTTP 200 with JSON showing the downstream chain results (gateway → order → inventory → payment → notification, plus shared-db calls). A 503 with `"error":"service_unavailable"` means a hop is broken — trace it via each service's logs and fix.

**DONE when:** all three endpoints return 200 and the response bodies show successful downstream results (no `"error"` keys).

## Task 6 — Circuit breaker smoke test (CLOSED → OPEN → HALF_OPEN)

1. Confirm baseline state: `curl -s localhost:8080/actuator/circuitbreakers` → `orderServiceCB` is `CLOSED`.
2. Inject a fault using the existing tooling (disable the order proxy to simulate a crash):
   ```bash
   python3 -c "
   from experiments.fault_injector import ToxiproxyClient
   ToxiproxyClient().set_proxy_enabled('order-service-proxy', False)"
   ```
   (Run from repo root; if the import path fails, use `cd experiments && python3 -c "from fault_injector import ..."`.)
3. Hammer the gateway ~20 times: `for i in $(seq 20); do curl -s -o /dev/null localhost:8080/api/v1/linear; done`
4. Check state is `OPEN`, wait >15s (the default `CB_WAIT_DURATION_OPEN`), send one request, check `HALF_OPEN`.
5. Re-enable the proxy (`set_proxy_enabled('order-service-proxy', True)`), send ~6 requests, confirm back to `CLOSED`.
6. Record each observed state transition in the log with timestamps.

**DONE when:** all three states were observed via `/actuator/circuitbreakers` and the breaker recovered to CLOSED.

## Task 7 — Prometheus scrape check `[parallel-ok with Task 6]`

```bash
curl -s 'localhost:9090/api/v1/targets' | python3 -m json.tool | grep -E '"health"|"job"'
```

**DONE when:** all 6 service targets show `"health": "up"` in Prometheus. If a target is missing, add it to `infra/prometheus/prometheus.yml` (scrape path `/actuator/prometheus`) and `docker compose restart prometheus`.

## Task 8 — Commit the Week 1 deliverables

The entire `services/` directory is currently **untracked** — this is the main missing calendar deliverable ("docker-compose.yml committed with all 6 services"). Also include the 1-line `experiments/runner.py` fix and the plan/log files.

```bash
cd "/Users/jayjoshi/Documents/Capstone project"
git add services/ experiments/runner.py plans/
git commit -m "feat: add all 6 Spring Boot services with Resilience4j CB, verified compose stack end-to-end"
```

Before committing, check there are no build artifacts: `find services -name target -type d` must be empty (Docker builds inside containers, so it should be). If not empty, add a `.gitignore` with `target/` first.

**DONE when:** `git status` is clean on branch `week1-jay-verification` and the commit contains all 6 service directories.

---

## Final acceptance checklist (maps 1:1 to calendar deliverables)

- [ ] Gateway running (T4, T5)
- [ ] Service C (payment) running (T4)
- [ ] Service D (notification) running (T4)
- [ ] docker-compose.yml + all 6 services committed (T8)
- [ ] All containers start and communicate correctly (T3, T5)
- [ ] Soham's Service A (order) + B (inventory) integrate cleanly in the stack (T5)
- [ ] JVM caps `-Xmx512m -Xms256m -XX:+UseG1GC` active (verify via `docker inspect gateway-service | grep JAVA_OPTS`)
- [ ] Bonus (team-event item): CB state transitions confirmed (T6) — this also pre-clears part of the Week 2 gate

## Notes for parallelizing across agents (Antigravity IDE)

- T2 can be split per-service across agents (independent builds).
- T6 and T7 can run in parallel once T5 passes.
- T3–T5 must be serial on one machine (shared Docker stack — do not let two agents restart containers concurrently).
