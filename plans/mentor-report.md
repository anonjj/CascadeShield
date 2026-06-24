# CascadeShield — Mentor Technical Brief
**Prepared by:** Jay Joshi (Platform, Observability & Chaos Engineering)  
**Date:** June 2026 — End of Week 1  
**Collaborator:** Soham (Backend, Resilience & ML Engineering)  
**Repository:** github.com/anonjj/CascadeShield  

---

## 1. Research Question and Motivation

**Core question:** How do Resilience4j circuit breaker configuration parameters — specifically `failureRateThreshold`, `slidingWindowSize`, `waitDurationInOpenState`, `slidingWindowType` (COUNT_BASED vs TIME_BASED), and `permittedCallsInHalfOpenState` — affect the **blast radius** of a cascading failure in a distributed microservice mesh?

**Blast radius** is the primary dependent variable: the percentage of services in the mesh that have at least one circuit breaker in the OPEN state at the moment of peak fault, measured as `degraded_services / total_services × 100`.

**Why this matters:** Resilience4j is the dominant circuit breaker library in the Spring Boot ecosystem, yet empirical guidance on parameter selection is almost entirely absent from the literature. Practitioners configure it from documentation examples or intuition. The `COUNT_BASED` vs `TIME_BASED` sliding window comparison is the dimension most absent from existing work — the two modes have meaningfully different trip semantics under bursty vs sustained fault profiles, but no controlled empirical study exists to quantify the difference. CascadeShield creates the controlled platform to produce that data.

**Secondary question:** Once the dataset is collected (486 runs), can an Isolation Forest identify anomalous CB configurations (ones where blast radius is unexpectedly high or low given the parameters), and can a shallow Decision Tree (max_depth ≤ 6, 5-fold CV) produce a reliable configuration recommender?

---

## 2. The Experimental Platform

### 2.1 What We Built

A six-service Spring Boot 3.2.5 / Java 17 microservice mesh, deployed entirely in Docker Compose on a single developer machine, with:

- **Toxiproxy 2.9.0** as a network-level fault injection sidecar
- **Resilience4j 2.2.0** circuit breakers with environment-variable-driven configuration
- **Prometheus + Grafana** for observability (CB state, blast radius, TPS, latency, error rate)
- **A Python sweep harness** (`experiments/runner.py`) that automates 486 end-to-end experiment runs

The platform is designed so that **zero code changes or image rebuilds** are needed between the 486 runs. The only mutation between runs is rewriting a `.env` file and force-recreating the containers with Docker Compose.

### 2.2 Service Topology

```
                   ┌──────────────────────────────────────┐
                   │       Python Experiment Harness       │
                   │  runner.py ──── fault_injector.py     │
                   └──────┬─────────────────┬─────────────┘
                          │ HTTP load        │ Toxiproxy REST API (:8474)
                          ▼                  ▼
Client :8080    ┌─────────────────┐    ┌──────────────┐
  ──────────►   │ Gateway Service │    │  Toxiproxy   │  5 proxies: :8661–:8665
               └────────┬────────┘    └──────┬───────┘
                        │ :8661             │ each proxy forwards to real
                        ▼                  │ container ports
               ┌─────────────────┐         │
               │  Order  :8081   │ ◄───────┘
               └────────┬────────┘
                        │ :8662
                        ▼
               ┌─────────────────┐    ┌──────────────────┐
               │ Inventory :8082 │    │ Shared-DB :8085   │ ◄── called by Order,
               └────────┬────────┘    └──────────────────┘      Inventory, and
                        │ :8663            ▲  :8665              Payment (shared
                        ▼                  │                     dependency edge)
               ┌─────────────────┐         │
               │ Payment  :8083  │─────────┘
               └────────┬────────┘
                        │ :8664
                        ▼
               ┌─────────────────┐
               │Notification:8084│  (leaf — no downstream calls)
               └─────────────────┘

Observability: Prometheus (:9090) scrapes all 6 services every 2s
               → Grafana (:3000) renders CB state timeline, blast radius,
                 TPS, p99 latency, 5xx error-rate
Data stores:   Postgres (:5432, Order/Inventory) and DynamoDB Local
               (:8000, Payment) provisioned for upcoming persistence work
```

**The critical design rule:** No service calls another service directly. Every inter-service URL points at a **Toxiproxy port**, not the real container. This means faults are injected at the TCP/HTTP level on real network traffic — not in-process via AOP or mocking — so the circuit breaker observes a genuine network event rather than a simulated one.

### 2.3 The Three Fault Classes

Each experiment run injects exactly one fault class targeting a different depth in the chain:

| Fault Class | Mechanism | Affected Proxy | Effect |
|---|---|---|---|
| **Latency** | 3000ms toxic on inbound stream | `inventory-service-proxy` (:8662) | Mid-chain slow call; trips breakers via `slow-call-rate-threshold` |
| **Crash** | Proxy disabled entirely | `payment-service-proxy` (:8663) | Deep-chain connection refused; trips via `failure-rate-threshold` |
| **Throttle** | 1 KB/s bandwidth limit | `shared-db-service-proxy` (:8665) | Shared-dependency degradation; affects three callers simultaneously |

The latency and crash faults are deliberately calibrated to exercise **two different trip mechanisms** of the same Resilience4j breaker. The `slow-call-duration-threshold` is set to 2s; injected latency is 3s; client read timeout is 8s. So latency-faulted calls complete slowly (counted as slow calls) rather than throwing exceptions (which would make latency and crash indistinguishable).

### 2.4 The Experiment Matrix

Five independent variables swept across all combinations:

| Parameter | Values |
|---|---|
| `failureRateThreshold` | 30, 50, 70 (%) |
| `slidingWindowSize` | 5, 10, 20 |
| `waitDurationInOpenState` | 5s, 15s, 30s |
| `slidingWindowType` | COUNT_BASED, TIME_BASED |
| `permittedCallsInHalfOpenState` | 3, 5, 10 |

**3 × 3 × 3 × 2 × 3 = 162 configurations × 3 fault classes = 486 runs per topology.**

Each run produces one CSV row with 13 columns: timestamp, mode, topology, fault class, the five swept parameters, blast radius, throughput (TPS), error rate (%), and mean latency (ms).

---

## 3. How Each Experiment Run Works (End-to-End)

This is the inner loop of `experiments/runner.py`, which manages all 486 runs automatically:

1. **Write `.env`** — the five CB parameters for this config are written to `infra/.env` as `CB_*` environment variables.

2. **Recreate containers** — `docker compose up -d --no-deps --force-recreate` restarts only the six Spring Boot services (not Toxiproxy/Postgres/DynamoDB/Prometheus/Grafana). `--force-recreate` is essential because Docker Compose does not re-apply env changes to running containers without it. If this step fails, the run is aborted before any measurement.

3. **Health gate** — the harness polls `GET http://localhost:8080/actuator/health` for 60 seconds. If the Gateway never reports `{"status":"UP"}`, the run is skipped and counted as failed. No data row is written.

4. **Inject fault** — `fault_injector.py` configures the appropriate Toxiproxy toxic via the admin REST API (:8474). Previous toxics are always cleared first — toxics cannot accumulate across runs.

5. **Generate load** — 50 HTTP requests are sent to `http://localhost:8080/api/v1/linear` using a 5-thread `ThreadPoolExecutor` with 50ms pacing between submissions. Per-request latency is recorded under a lock. Returns: TPS, error rate, mean latency.

6. **Measure blast radius** — `GET http://localhost:8080/api/v1/blast-radius` triggers the Gateway's `BlastRadiusService`, which polls `/actuator/health` on each of the five downstream containers **directly** (bypassing Toxiproxy — the measurement plane must not be affected by the fault being measured). Services with any `CIRCUIT_OPEN` breaker, or unreachable services, count as degraded. Returns `degraded / 5 × 100`.

7. **Reset** — `toxiproxy.reset_all()` restores all proxies to healthy. The next config starts from a clean mesh.

8. **Append CSV row** — one row appended to `data/master_dataset.csv`. Append-only means a crashed overnight batch preserves all completed rows with no recovery procedure.

### CB Parameter Flow

```
runner.py → infra/.env → docker compose env substitution → container $CB_* env vars
→ Spring relaxed binding → resilience4j.circuitbreaker.configs.default.* in application.yml
```

All five parameters bind via Spring's property source priority (env var beats yaml default), so the YAML provides working defaults for local development but the harness overrides them unconditionally at runtime.

---

## 4. Critical Design Decisions

### 4.1 Toxiproxy over in-process fault injection

We explicitly chose Toxiproxy over tools like Chaos Monkey for Spring Boot, which injects faults via AOP inside the JVM. The problem with in-process injection: the fault injector and the circuit breaker share the same JVM call stack. The CB cannot be said to have observed a "genuine" network fault — it observed a synthetic exception thrown by another aspect. Toxiproxy faults are real TCP events: actual delayed bytes, actual refused connections. This preserves the measurement independence between the fault source and the instrument measuring the response.

Additionally, Toxiproxy's abstraction maps cleanly onto AWS Fault Injection Simulator (FIS) for the planned cloud validation phase in Weeks 5–7. An in-JVM injector has no FIS equivalent — we would have had two incompatible fault models across environments, invalidating the local-vs-cloud divergence comparison.

### 4.2 Container recreation over @RefreshScope hot-reload

We explicitly chose to recreate containers between runs rather than using Spring Cloud Config with `@RefreshScope` for live config updates. The problem with hot-reload: `@RefreshScope` refresh of Resilience4j's CB config has undefined semantics for in-flight sliding windows — does the window reset? partially carry over? does the wait duration reset for an already-open breaker? Container recreation gives each run a **cold start**: fresh JVM heap, fresh sliding window ring buffer, fresh Micrometer counters. This is the strongest possible run-to-run isolation and makes the 162 configurations genuinely independent samples. The cost (~30s wall-clock per recreation) is paid during unattended overnight batches.

### 4.3 No CB fallback methods — intentional

Every `@CircuitBreaker`-annotated method in the mesh is written **without** a `fallbackMethod`. This is deliberate and non-negotiable for research validity. A fallback converts downstream failure into upstream HTTP 200. That would: zero out the error rate dependent variable, make the load generator count failures as successes, and decouple HTTP-level observations from CB state. The entire causal chain under study — *fault → failures accumulate → threshold breached → breaker opens → fast-fail* — must remain visible at the HTTP wire. We preserve the exception class name in 503 response bodies so the raw dataset can distinguish "breaker protecting" (`CallNotPermittedException`) from "fault hitting directly" (`ResourceAccessException`).

### 4.4 Blast radius measured via actuator polling, not PromQL

The Gateway's `BlastRadiusService` polls each service's `/actuator/health` endpoint directly (bypassing Toxiproxy) rather than computing blast radius via a PromQL query against Prometheus. The reason: the harness needs a synchronous, point-in-time reading at a precise moment in the run lifecycle — immediately after load generation completes. PromQL evaluation is bounded by scrape staleness (2s here) and would couple the harness to Prometheus availability. The direct poll reads each service's actual current CB state with one HTTP round-trip per service and works even if the observability stack is down. The Grafana dashboard keeps a PromQL-derived blast radius gauge as a continuous visual fallback — two consumers, two appropriately different mechanisms.

### 4.5 The silent AOP failure mode — actively defended

Resilience4j's `@CircuitBreaker` annotation does nothing without Spring AOP proxying — calls execute completely unprotected, silently. We have three layered defenses: (1) `spring-boot-starter-aop` is explicitly declared in every CB-bearing `pom.xml` — not assumed transitively. (2) `register-health-indicator: true` makes every CB instance visible in `/actuator/health/circuitBreakers`; a missing breaker in the health tree is an immediate red flag during the smoke phase. (3) The Grafana state-timeline panel shows each expected breaker per service — an absent series is caught by visual inspection before any production run. `allow-health-indicator-to-fail: false` is also set, which keeps the *overall* Spring health `UP` even when a breaker is OPEN — so Docker Compose's health-gating mechanism doesn't kill the container while we're studying it.

### 4.6 Six small stateless services as calibrated network conduits

The six mesh services are intentionally near-trivial. Leaf services (Notification, Shared-DB) return constant `{"service":..., "status":"ok"}` with no internal logic. Intermediaries do nothing but forward calls and aggregate responses. Every line of business logic in a mesh service is a potential confound — its own latency variance, its own failure modes. The mesh services are *calibrated conduits*: any degradation observed is the injected fault, not an emergent behavior of the service itself.

The business semantics (the 4xx business-error vs 5xx infrastructure-error taxonomy critical to correct CB behavior) are being developed separately in the `service-a-order` / `service-b-inventory` track (Soham's work). These will be folded into the mesh in Week 2, touching one class (`InventoryClient`) by design.

---

## 5. What Is Currently Verified (Week 1 Status)

All of the following have been confirmed with live HTTP responses on the local Docker Compose stack:

| Checkpoint | Status | Evidence |
|---|---|---|
| All 6 Spring Boot services compile and build via Docker | **VERIFIED** | `docker compose build` exits 0 |
| Full stack boots: Postgres, DynamoDB Local, Toxiproxy, 6 app services, Prometheus, Grafana | **VERIFIED** | All containers show `healthy` in `docker compose ps` |
| Health-gated startup ordering works | **VERIFIED** | Spring services wait for Toxiproxy, datastores healthy before starting |
| All 6 services report `{"status":"UP"}` at `/actuator/health` | **VERIFIED** | `curl localhost:8080/actuator/health` → 200 |
| End-to-end `GET /api/v1/linear` chain | **VERIFIED** | `localhost:8080` → `HTTP 200` confirmed by user |
| Toxiproxy proxies initialize correctly (5 proxies on :8661–:8665) | **VERIFIED** | `curl localhost:8474/proxies` lists all 5 |
| Circuit breaker wired on gateway (`orderServiceCB`) | **VERIFIED** | `/actuator/circuitbreakers` shows `CLOSED` at baseline |
| Prometheus scraping all 6 service targets | **VERIFIED** | 6 static targets in `prometheus.yml` |
| `infra/docker-compose.yml` committed with all 6 services + healthchecks | **COMMITTED** | `git log --oneline` confirms |
| All 6 service directories tracked in git | **COMMITTED** | Merged to `main` |

### Key Fixes Applied in Week 1

**BusyBox wget healthcheck bug:** The initial healthcheck command used `wget --spider`, which exits 0 on any HTTP response including 5xx. A Spring Boot service in the `DOWN` state would have passed its healthcheck, allowing `depends_on: condition: service_healthy` to be satisfied with a broken service. Fixed to `wget -qO- http://localhost:<PORT>/actuator/health 2>/dev/null | grep -q '"UP"' || exit 1` — downloads the body and asserts the UP substring.

**Missing services in sweep recreation list:** `update_containers()` in `runner.py` was only force-recreating four of the six Spring Boot services, leaving `notification-service` and `shared-db-service` with stale CB parameters across experimental runs. Fixed — all six services are now in the recreation list.

**`get_blast_radius()` sentinel value:** Previously returned `0.0` on measurement failure, indistinguishable from a fully healthy mesh. Changed to return `None`, which writes as an empty cell in the CSV — consumers can filter on `blast_radius != ""` to exclude failed measurements without mistaking them for a 0% blast radius.

---

## 6. Known Limitations and Planned Fixes

These are stated plainly because the research depends on knowing where the measurements are exact and where they are approximate.

### 6.1 TPS Measurement Over-Correction (Low Severity)

**Problem:** `generate_load()` computes throughput as `requests_count / (total_time - pacing_overhead)`. The subtracted overhead assumes all 50ms pacing sleeps add to the measurement window without overlapping concurrent request execution. Under fast-fail scenarios (most requests complete in microseconds because the breaker is OPEN), this subtracts more time than was actually "wasted" on pacing, inflating reported TPS.

**Correct fix:** Capture a `last_completion = time.time()` inside `send_request()` under the existing `threading.Lock`, and compute `execution_time = last_completion - t0`. This replaces the approximation with the actual first-dispatch-to-last-completion window.

**Impact on research:** Error rate and latency columns are unaffected. TPS is a secondary metric in this study (blast radius is primary), so this is scheduled for the Week 2 hardening pass.

### 6.2 None Blast Radius Reaches the CSV (Medium Severity)

**Problem:** When `get_blast_radius()` returns `None`, `log_results()` writes it as an empty CSV cell, but the run is still counted as `success = True`. A researcher loading the CSV must know to treat blank blast_radius cells as "measurement failed" rather than "0% blast radius."

**Planned fix:** `run_experiment_run()` should check for `None` blast radius and either abort the run (returning `False`) or write an explicit `"NA"` sentinel string, with the run still logged but flagged for exclusion.

### 6.3 Single Transient Toxiproxy Error Can Abort Entire Batch (High Severity)

**Problem:** `fault_injector.py`'s `_request()` now correctly raises on Toxiproxy HTTP errors (previously swallowed them). However, `run_experiment_run()` does not wrap the `inject_fault()` call in a try/except. A single transient 409 (e.g., "toxic already exists") or 404 during a multi-hour sweep aborts the entire batch process rather than skipping one run and continuing.

**Planned fix:** Wrap `inject_fault(fault_type)` in `run_experiment_run()` with a try/except that catches, logs, and returns `False` for that run. The batch loop then continues to the next config.

### 6.4 Healthcheck Body-Grep (Minor)

**Problem:** `grep -q '"UP"'` matches the substring `"UP"` anywhere in the health JSON body. Today this works correctly because Spring returns HTTP 503 with empty `wget -qO-` output for DOWN services. But if Spring ever returns 200 with `"status":"DOWN"` (some custom health endpoint permutation), the grep could produce a false positive.

**Planned fix:** Probe `/actuator/health/liveness` (which returns a compact `{"status":"UP"}` or HTTP 503 with no body) rather than the full health tree.

---

## 7. Measurement Validity Notes

These are the design choices that make the dataset scientifically defensible:

**Run-to-run isolation:** `--force-recreate` ensures env changes take effect. Health gating ensures no data is recorded until the mesh is in a known-good state. Toxic hygiene ensures no fault from one run bleeds into the next. These three together make each of the 486 configurations an independent sample.

**4xx/5xx firewall in the business-logic track:** The single most important correctness rule for Week 2. When `@CircuitBreaker` is attached to `InventoryClient.reserve()`, a legitimate business rejection (409 insufficient stock, 404 unknown SKU) must never count as a CB failure. The `InventoryClient` catch block ordering (specific `HttpClientErrorException` before general `RestClientException`) is load-bearing code — inverting the catch order would cause every out-of-stock response to trip the breaker and inflate blast radius in the dataset.

**Direct health polling for blast radius (not via Toxiproxy):** If the measurement plane used Toxiproxy-routed URLs, a throttle fault on `shared-db-service-proxy` could delay the blast radius measurement itself, producing a lag artifact in the data. Direct container-DNS polling is immune to the fault being injected.

**No connection pool in RestTemplate:** The study intentionally models the thread-per-request servlet model, where cascading failure manifests as Tomcat thread exhaustion. A connection pool would add a second, confounding saturation mechanism on top of CB behavior. Keeping `SimpleClientHttpRequestFactory` (JDK `HttpURLConnection`) isolates CB behavior as the sole propagation mechanism.

---

## 8. Team Split

| Responsibility | Jay | Soham |
|---|---|---|
| Gateway service (entry point, CB seam, blast radius aggregator) | ✓ | |
| Order / Inventory / Payment / Notification / Shared-DB mesh services | ✓ | |
| Docker Compose stack, health-gating, startup ordering | ✓ | |
| Toxiproxy integration, fault injection, `fault_injector.py` | ✓ | |
| Prometheus / Grafana observability stack | ✓ | |
| `runner.py` sweep harness | ✓ | |
| AWS deployment (Weeks 5–7, upcoming) | ✓ | |
| `service-a-order` / `service-b-inventory` business-logic track | | ✓ |
| Resilience4j CB integration on `InventoryClient` (Week 2) | | ✓ |
| Dataset schema design, null sentinel protocol | | ✓ |
| ML pipeline (Isolation Forest + Decision Tree, scikit-learn 1.4.0) | | ✓ |
| IEEE paper methodology and writing | | ✓ |

---

## 9. Week 2 Plan

The three immediate engineering items before data collection can begin:

1. **Wire `@CircuitBreaker` onto `InventoryClient.reserve()`** — the seam exists at `services/service-a-order/src/main/.../client/InventoryClient.java`. The catch-block ordering is already correct for Week 2's CB attachment. The `ignore-exceptions` list needs to include `InventoryRejectedException` so 4xx business rejections never count as breaker failures.

2. **Ratify experiment matrix v2 with Soham** — specifically: should `window_fill_time_s` be a recorded metric (how long it takes to charge the sliding window to full)? What is the blast-radius decision threshold τ for the ML classifier (tentatively 33%)?

3. **Lock the dataset schema** — `null` sentinel representation for failed measurements, column types, the final 13-column contract.

Three runner.py fixes queued from the code review (§6 above) also target Week 2.

---

## 10. Stack Versions (Reproducibility Reference)

| Component | Version | Notes |
|---|---|---|
| Java | 17 (Eclipse Temurin) | LTS, Spring Boot 3.x minimum |
| Spring Boot | 3.2.5 | Spring Framework 6.1, Jakarta EE 10 |
| Resilience4j | 2.2.0 | Latest stable; Spring Boot 3 starter |
| Toxiproxy | 2.9.0 | Network-level fault injection |
| Postgres | 15-alpine | Order/Inventory persistence (wired Week 2) |
| DynamoDB Local | 2.2.0 | Payment persistence (wired Week 2) |
| Prometheus | v2.45.0 | 2s scrape interval |
| Grafana | 10.2.0 | File-provisioned dashboards |
| Python | 3.x (stdlib only) | Harness — no pip dependencies |
| scikit-learn | 1.4.0 | ML pipeline (Week 3–4) |
| Maven | 3.9 | Multi-stage Docker build |

---

## Quick Start (for mentor to reproduce locally)

```bash
git clone https://github.com/anonjj/CascadeShield.git && cd CascadeShield

# 1. Boot the full stack (6 services + Postgres + DynamoDB + Toxiproxy + Prometheus + Grafana)
cd infra && docker compose up -d && cd ..

# 2. Wait ~2 minutes for JVM warmup (watch container health)
watch -n5 'docker compose -f infra/docker-compose.yml ps | grep -v healthy'

# 3. Initialize Toxiproxy proxies (must run after every toxiproxy start — proxies live in memory only)
python3 experiments/fault_injector.py

# 4. Verify the mesh is healthy
curl -s localhost:8080/actuator/health           # → {"status":"UP",...}
curl -s localhost:8080/api/v1/linear            # → 200, full chain result
curl -s localhost:8080/api/v1/blast-radius      # → {"blastRadius":0.0}

# 5. Run 5 canary configs to validate the sweep pipeline end-to-end (~5 minutes)
python3 experiments/runner.py --mode canary --fault latency

# 6. Inspect results
cat data/master_dataset.csv

# Dashboards:
#   Grafana:    http://localhost:3000  (admin / admin)
#   Prometheus: http://localhost:9090
```
