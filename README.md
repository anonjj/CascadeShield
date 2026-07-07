# CascadeShield

> **Empirical Resilience Engineering Study** — How Resilience4j circuit breaker configurations affect cascading failure blast radius across a distributed microservice mesh.

[![Java](https://img.shields.io/badge/Java-17-orange.svg)](https://adoptium.net/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.2.5-brightgreen.svg)](https://spring.io/projects/spring-boot)
[![Resilience4j](https://img.shields.io/badge/Resilience4j-2.2.0-blue.svg)](https://resilience4j.readme.io/)
[![Toxiproxy](https://img.shields.io/badge/Toxiproxy-2.9.0-red.svg)](https://github.com/Shopify/toxiproxy)
[![Status: Active Research](https://img.shields.io/badge/Status-Active%20Research-yellow.svg)]()

CascadeShield is a controlled experimental platform: a six-service Spring Boot mesh, a Toxiproxy fault-injection layer, a Prometheus/Grafana observability stack, and a Python sweep harness that together measure how circuit breaker parameter choices change the **blast radius** of a cascading failure. The platform sweeps **162 circuit breaker configurations × 3 fault classes = 486 runs** per topology and logs every run to a master CSV that feeds an ML pipeline (Isolation Forest anomaly detection + Decision Tree config recommender).

The **primary novelty claim** is a systematic `COUNT_BASED` vs `TIME_BASED` sliding-window comparison under controlled fault conditions — a dimension largely absent from existing Resilience4j empirical literature.

---

## 1. System Architecture & High-Level Flow

### 1.1 Component Topology

```
                        ┌─────────────────────────────────────────────────┐
                        │              Python Experiment Harness          │
                        │   runner.py ──── fault_injector.py (Toxiproxy   │
                        │      │                 REST client, :8474)      │
                        └──────┼──────────────────────┼───────────────────┘
                               │ load (HTTP)          │ toxics (HTTP)
                               ▼                      ▼
┌──────────┐  :8080   ┌──────────────┐       ┌──────────────┐
│  Client/ │ ───────► │   Gateway    │       │  Toxiproxy   │  5 proxies:
│  Runner  │          │   Service    │       │  (sidecar)   │  :8661–:8665
└──────────┘          └──────┬───────┘       └──────┬───────┘
                             │ http://toxiproxy:8661│
                             ▼                      │ forwards to real
                      ┌──────────────┐              │ container ports
                      │ Order :8081  │◄─────────────┘
                      └──────┬───────┘
                             │ :8662 (via toxiproxy)
                             ▼
                      ┌──────────────┐     ┌─────────────────┐
                      │ Inventory    │     │ Shared-DB :8085 │◄── called by
                      │   :8082      │     └─────────────────┘    Order,
                      └──────┬───────┘            ▲               Inventory,
                             │ :8663              │ :8665         Payment
                             ▼                    │               (shared
                      ┌──────────────┐            │               dependency
                      │ Payment      │────────────┘               mesh edge)
                      │   :8083      │
                      └──────┬───────┘
                             │ :8664
                             ▼
                      ┌──────────────┐
                      │ Notification │  (leaf — no downstream calls)
                      │   :8084      │
                      └──────────────┘

   Observability: Prometheus (:9090) scrapes /actuator/prometheus on all 6
   services every 2s → Grafana (:3000) renders CB state, blast radius,
   TPS, p99 latency, and 5xx error-rate panels.
   Data stores: Postgres (:5432, Order/Inventory) and DynamoDB Local
   (:8000, Payment) are provisioned in compose for later persistence work.
```

### 1.2 The Critical Design Move: Every Inter-Service Call Routes Through Toxiproxy

No service calls another service directly. The compose file injects downstream URLs as environment variables that point at **Toxiproxy listen ports**, not at real containers:

| Caller | Env Var | Toxiproxy Port | Real Upstream |
|---|---|---|---|
| Gateway | `ORDER_SERVICE_URL=http://toxiproxy:8661` | 8661 | `order-service:8081` |
| Order | `INVENTORY_SERVICE_URL=http://toxiproxy:8662` | 8662 | `inventory-service:8082` |
| Inventory | `PAYMENT_SERVICE_URL=http://toxiproxy:8663` | 8663 | `payment-service:8083` |
| Payment | `NOTIFICATION_SERVICE_URL=http://toxiproxy:8664` | 8664 | `notification-service:8084` |
| Order / Inventory / Payment | `SHARED_DB_SERVICE_URL=http://toxiproxy:8665` | 8665 | `shared-db-service:8085` |

This means a fault on any single hop is injected by adding a "toxic" (latency, bandwidth limit) or disabling a proxy — **without touching, restarting, or instrumenting the victim service**. The service under test experiences the fault exactly as it would experience a real network degradation.

One deliberate exception: the Gateway's **BlastRadiusService** polls each service's `/actuator/health` via direct container names (`http://order-service:8081`, ...), bypassing Toxiproxy. This is intentional — the measurement plane must observe the *true* circuit breaker state of each service, not a view distorted by the very fault being injected.

### 1.3 End-to-End Request Trace (`GET /api/v1/linear`)

1. **Ingress.** The load generator (in `runner.py`) fires `GET http://localhost:8080/api/v1/linear`. Spring MVC routes it to `GatewayController.linear()`.
2. **Gateway → Order.** The controller delegates to `GatewayDownstreamService.callOrder()`. This method is annotated `@CircuitBreaker(name = "orderServiceCB")` — Resilience4j's Spring AOP aspect intercepts the call. If the breaker is `CLOSED` or `HALF_OPEN` (with permits remaining), the call proceeds; if `OPEN`, a `CallNotPermittedException` is thrown in microseconds without any network I/O.
3. **The wire.** `RestTemplate` (3s connect / 8s read timeout) sends `GET http://toxiproxy:8661/api/v1/order`. Toxiproxy applies any active toxics (e.g., +3000ms latency) and forwards to `order-service:8081`.
4. **Order fans down.** `OrderController.order()` makes **two CB-wrapped calls** through `OrderDownstreamService`: `callInventory()` (`inventoryServiceCB`, via :8662) and `callSharedDb()` (`sharedDbCB`, via :8665). Each is independently try/caught — one failing hop degrades the response (HTTP 503 with a partial body) without aborting the other.
5. **The chain continues.** Inventory → Payment (`paymentServiceCB`) + Shared-DB; Payment → Notification (`notificationServiceCB`) + Shared-DB. Notification and Shared-DB are leaves — they respond `200 {"service": ..., "status":"ok"}` with no downstream calls.
6. **Failure accounting on the way up.** Each intermediary marks its response 503 if any downstream hop failed. The CB on each hop records the outcome: an exception or a slow call (>2s, configured via `slow-call-duration-threshold`) counts toward the sliding window's failure rate. When the failure rate over the window exceeds `failureRateThreshold`, that breaker flips `CLOSED → OPEN`.
7. **Egress.** The Gateway returns `200 {"topology":"linear","result":...}` or `503 {"topology":"linear","error":"service_unavailable","cause":"..."}`. The runner's load generator counts the outcome and measures latency.
8. **Measurement.** After the load phase, the runner calls `GET /api/v1/blast-radius`; the Gateway's `BlastRadiusService` polls all 5 downstream health endpoints, counts services with at least one `CIRCUIT_OPEN` breaker (unreachable services also count as degraded), and returns `degraded/total × 100`.

### 1.4 The Three Topology Endpoints

| Endpoint | Pattern | What It Studies |
|---|---|---|
| `GET /api/v1/linear` | Gateway → Order → Inventory → Payment → Notification (serial chain) | Fault propagation depth — how far upstream a single downstream fault cascades |
| `GET /api/v1/fanout` | Gateway calls Order, Inventory, Payment in parallel (`CompletableFuture` over a dedicated `ExecutorService`) | Failure independence — one slow/open hop must not block sibling calls |
| `GET /api/v1/mesh` | Fan-out + every intermediary also hits Shared-DB (:8665) | Shared-dependency amplification — one throttled common dependency degrading many callers at once |

### 1.5 Experiment Execution Lifecycle (one sweep run)

```
runner.py main()
 ├── setup_default_proxies() + reset_all()        # Toxiproxy precondition
 ├── generate_combinations(mode)                  # 5 canary configs or 162 full-sweep configs
 └── for each config:
      1. write_env_file(config)                   # CB_* vars → infra/.env
      2. update_containers()                      # docker compose up -d --no-deps --force-recreate
      │                                           # (aborts run on non-zero exit)
      3. wait_for_healthy(60s)                    # poll gateway /actuator/health for "UP"
      4. inject_fault(fault_type)                 # latency 3000ms / crash / throttle 1KB/s
      5. generate_load(50 req, 5 threads)         # measure TPS, error rate, avg latency
      6. get_blast_radius()                       # gateway aggregator endpoint
      7. toxiproxy.reset_all()                    # restore healthy mesh
      8. log_results(...)                         # append row to data/master_dataset.csv
```

The CB parameters flow: `runner.py` → `.env` file → compose variable substitution (`${CB_FAILURE_RATE_THRESHOLD:-50}`) → container environment → Spring's relaxed property binding → `resilience4j.circuitbreaker.configs.default.*` in each service's `application.yml`. **Zero code changes or image rebuilds between the 486 runs** — only container recreation with new env values.

---

## 2. Granular File-by-File Technical Deep Dive

### 2.1 `services/gateway-service/` — Mesh Entry Point + Measurement Plane

#### `GatewayApplication.java`
* **Purpose:** Standard `@SpringBootApplication` bootstrap.
* **Mechanics:** Component-scans `com.cascadeshield.gateway`; auto-configuration wires Spring MVC (embedded Tomcat on :8080), Actuator, Micrometer's Prometheus registry, and Resilience4j's Spring Boot 3 starter.
* **Key dependencies:** `spring-boot-starter-web`, `resilience4j-spring-boot3`, `spring-boot-starter-aop` (without AOP, the `@CircuitBreaker` annotation is silently inert — see §4.4).

#### `config/RestTemplateConfig.java`
* **Purpose:** Owns the single `RestTemplate` bean with **non-negotiable bounded timeouts**.
* **Mechanics:** `SimpleClientHttpRequestFactory` with `connectTimeout=3000ms`, `readTimeout=8000ms`. The 8s read timeout is deliberately calibrated *above* the 3s injected latency fault: a latency-faulted call must **complete slowly** (so the CB's slow-call tracking counts it at the 2s `slow-call-duration-threshold`) rather than be killed by the client timeout. If the read timeout were below 3s, the latency fault class would be indistinguishable from the crash fault class — every fault would manifest as an exception.
* **Key dependencies:** None beyond Spring core. Uses the JDK `HttpURLConnection` factory — no connection pooling library (see trade-offs, §3.6).

#### `controller/GatewayController.java`
* **Purpose:** Exposes the three topology endpoints plus the blast-radius measurement endpoint.
* **Mechanics:**
  * `linear()` — single delegated call to `callOrder()`; try/catch maps any exception (including `CallNotPermittedException` from an open breaker) to `503 {"error":"service_unavailable","cause":<ExceptionClassName>}`. Exposing the exception *class name* in the body lets the experiment harness distinguish "breaker open" (`CallNotPermittedException`) from "timeout" (`ResourceAccessException`) post-hoc.
  * `fanout()` — submits the three downstream calls as `CompletableFuture.supplyAsync(...)` on an `ExecutorService`, then joins. Failure isolation per branch: each future's exception is caught and embedded in its slice of the response map rather than failing the whole request.
  * `/blast-radius` — delegates to `BlastRadiusService`; returns `{"blastRadius": <0–100>}`.
* **Key dependencies:** `GatewayDownstreamService` (CB-wrapped order call), `BlastRadiusService`, raw `RestTemplate` + `@Value`-injected direct URLs for the fan-out branches.

#### `service/GatewayDownstreamService.java`
* **Purpose:** The Gateway's single CB seam.
* **Mechanics:** One method, `callOrder()`, annotated `@CircuitBreaker(name = "orderServiceCB")`. **Deliberately no `fallbackMethod`**: a fallback would convert failures into successes and silently zero out the error-rate dependent variable. The exception must propagate so the controller's 503 mapping and the load generator's failure counter both see it.
* **Key dependencies:** `RestTemplate` bean; `downstream.order-service-url` property (env-var overridable).

#### `service/BlastRadiusService.java`
* **Purpose:** Computes the study's **primary dependent variable** — % of services degraded.
* **Mechanics:** Iterates a hardcoded list of 5 direct (non-Toxiproxy) actuator URLs. For each: `GET /actuator/health`, parse with Jackson `ObjectMapper`, walk `components.circuitBreakers.details`, and flag the service if any breaker reports `status == "CIRCUIT_OPEN"`. An *unreachable* service (connection refused — e.g., genuinely crashed) also increments the degraded count via the catch block: unreachability is the worst-case degradation. Returns `degraded/total × 100.0`.
* **Why this works:** Each service sets `register-health-indicator: true`, so Resilience4j publishes per-breaker state into the Actuator health tree. Crucially, `allow-health-indicator-to-fail: false` keeps the *overall* service status `UP` even when a breaker is open — so an open breaker doesn't cascade into orchestration-level "unhealthy" while still being visible in `details` for this aggregator to read.
* **Key dependencies:** `RestTemplate`, Jackson (transitively from `spring-boot-starter-web`).

#### `src/main/resources/application.yml`
* **Purpose:** Port (8080), downstream URLs (env-var first, sensible defaults), Resilience4j config, Actuator exposure.
* **Mechanics — the Resilience4j block is the heart of the experiment:**
  ```yaml
  resilience4j.circuitbreaker.configs.default:
    sliding-window-type: ${CB_SLIDING_WINDOW_TYPE:COUNT_BASED}     # swept
    sliding-window-size: ${CB_SLIDING_WINDOW_SIZE:10}              # swept
    failure-rate-threshold: ${CB_FAILURE_RATE_THRESHOLD:50}        # swept
    wait-duration-in-open-state: ${CB_WAIT_DURATION_OPEN:15s}      # swept
    permitted-number-of-calls-in-half-open-state: ${CB_PERMITTED_CALLS_HALF_OPEN:5}  # swept
    automatic-transition-from-open-to-half-open-enabled: true
    slow-call-duration-threshold: 2s        # latency fault injects 3s → counted slow
    slow-call-rate-threshold: ${CB_FAILURE_RATE_THRESHOLD:50}
  ```
  All five independent variables bind to env vars with the *same names across all services*, so one `.env` file reconfigures the whole mesh atomically. `automatic-transition-from-open-to-half-open-enabled: true` means the `OPEN → HALF_OPEN` transition happens on a timer without requiring a probe call — making `time_to_recover` measurable even under zero load.
* **Actuator exposure:** `health, prometheus, circuitbreakers, circuitbreakerevents, info, metrics` — `circuitbreakerevents` gives a per-transition audit log used to verify `CLOSED → OPEN → HALF_OPEN` empirically.

#### `Dockerfile`
* **Purpose:** Reproducible two-stage build.
* **Mechanics:** Stage 1 (`maven:3.9-eclipse-temurin-17`): `COPY pom.xml` + `mvn dependency:go-offline` **before** `COPY src` — Docker layer caching makes dependency downloads a one-time cost; source changes only re-run `mvn package`. Stage 2 (`eclipse-temurin:17-jre`): copies only the fat jar. `ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]` — the shell-form indirection is required so `$JAVA_OPTS` (the `-Xmx512m -Xms256m -XX:+UseG1GC` cap from compose) is expanded at container start; exec-form would pass the literal string.
* **Key dependencies:** `pom.xml`, compose-provided `JAVA_OPTS`.

#### `pom.xml`
* **Purpose:** Build definition. Spring Boot parent 3.2.5, Java 17.
* **Dependencies and why each exists:** `spring-boot-starter-web` (MVC + Tomcat), `spring-boot-starter-actuator` (health/metrics endpoints), `micrometer-registry-prometheus` (exports Micrometer metrics in Prometheus exposition format at `/actuator/prometheus`), `resilience4j-spring-boot3` 2.2.0 (CB implementation + auto-config + Micrometer binding — this is what makes `resilience4j_circuitbreaker_state` appear in Prometheus), `spring-boot-starter-aop` (AspectJ proxying for the `@CircuitBreaker` annotation).

### 2.2 `services/order-service/`, `inventory-service/`, `payment-service/` — Chain Intermediaries

These three are structurally isomorphic; describing one describes all three. Each owns **two circuit breakers**: one for its next-hop chain call, one for its Shared-DB call.

| Service | Endpoint | CB #1 (chain) | CB #2 (shared dep) |
|---|---|---|---|
| order | `GET /api/v1/order` | `inventoryServiceCB` → :8662 | `sharedDbCB` → :8665 |
| inventory | `GET /api/v1/inventory` | `paymentServiceCB` → :8663 | `sharedDbCB` → :8665 |
| payment | `GET /api/v1/payment` | `notificationServiceCB` → :8664 | `sharedDbCB` → :8665 |

#### `controller/*Controller.java` (each)
* **Purpose:** Single REST endpoint implementing the "degrade, don't die" contract.
* **Mechanics:** Builds a `LinkedHashMap` response body (insertion-ordered → deterministic JSON for snapshot comparison). Each downstream call is wrapped in its **own** try/catch; a failure stores `{"error":"unavailable","cause":<ExceptionClassName>}` under that hop's key and sets `failed = true`, but the *other* call still executes. Returns `503` if any hop failed, `200` otherwise. This is what makes partial degradation visible in the data: a response can carry one healthy result and one failure simultaneously.

#### `service/*DownstreamService.java` (each)
* **Purpose:** The only classes in the mesh allowed to perform network I/O to other services; each network hop = exactly one CB-annotated method.
* **Mechanics:** `@CircuitBreaker(name = "...")` per method, no fallbacks (same rationale as the Gateway). Named CB instances inherit `base-config: default` in `application.yml` — instance granularity means Prometheus reports state per-edge (`resilience4j_circuitbreaker_state{name="sharedDbCB", job="order-service"}`), which is what lets Grafana render the propagation wave as a state timeline.

#### `config/RestTemplateConfig.java`, `application.yml`, `Dockerfile`, `pom.xml`
* Identical in structure to the Gateway's (ports 8081/8082/8083, respective downstream URLs). The compose file additionally injects `SPRING_DATASOURCE_URL` (order, inventory → Postgres) and `AWS_DYNAMODB_ENDPOINT` (payment → DynamoDB Local) for the upcoming persistence phase; no JPA/DynamoDB SDK dependency is wired yet, so these are inert today by design — infrastructure was provisioned ahead of need to avoid a compose-topology change mid-experiment.

### 2.3 `services/notification-service/`, `shared-db-service/` — Leaf Services

#### `controller/NotificationController.java` / `SharedDbController.java`
* **Purpose:** Terminate the call graph. `GET /api/v1/notification` and `GET /api/v1/shared-db` return a constant `200 {"service": ..., "status":"ok"}`.
* **Mechanics:** Deliberately trivial — **zero downstream dependencies and zero internal state** means any failure observed at these nodes is, with certainty, the fault we injected on their inbound proxy. They are the controlled baseline of the experiment.
* **`application.yml`:** No Resilience4j block (nothing to protect), but full Actuator + Prometheus exposure so they still participate in blast-radius and metrics collection.

### 2.4 `services/service-a-order/`, `service-b-inventory/` — Business-Semantics Track (Soham's Week 1)

A second, richer implementation of the Order→Inventory edge that runs *outside* the compose mesh (plain `mvn spring-boot:run`, ports 8081/8082). The mesh services above are deliberately semantics-free conduits for fault propagation; this pair exists to develop the **business-error vs infrastructure-error taxonomy** that Week 2's CB integration depends on. Documented in `services/README.md`.

#### `service-a-order/client/InventoryClient.java` — *the most important class in this track*
* **Purpose:** The single seam wrapping every outbound call to Service B; the planned attachment point for `@CircuitBreaker(name="inventory")` in Week 2.
* **Mechanics:** Uses Spring 6's fluent `RestClient`. The two catch blocks encode the study's central measurement-correctness rule:
  * `HttpClientErrorException` (4xx) → rethrown as `InventoryRejectedException` carrying B's original status. **A business rejection (409 insufficient stock, 404 unknown SKU) must never count as a CB failure** — otherwise legitimate out-of-stock responses would inflate measured blast radius and corrupt the dataset.
  * `RestClientException` (5xx / `ResourceAccessException` for timeouts & connection-refused) → `InventoryUnavailableException`. This is the *only* path the breaker should trip on.
* **Key dependencies:** `RestClient` bean from `RestClientConfig`, the two custom exceptions, `ReserveRequest/ReserveResponse` records.

#### `service-a-order/config/RestClientConfig.java`
* **Purpose:** Builds the `RestClient` with externalized base URL (`services.inventory.base-url`) and explicit timeouts (1s connect / 2s read, both property-overridable).
* **Mechanics:** Bounded read timeout is justified in-code: "an unbounded client would hang forever under a latency fault, which would make `time_to_open` unmeasurable."

#### `service-a-order/exception/` (3 files)
* `InventoryRejectedException` (carries the downstream `HttpStatusCode`), `InventoryUnavailableException` (wraps cause), and `GlobalExceptionHandler` — an `@RestControllerAdvice` mapping: unavailable → 503 `ProblemDetail` (RFC 7807), rejected → mirrors B's original status rather than masking it, validation failures → 400 with the first field error. Deterministic status codes are what allow the harness to classify outcomes from the wire alone.

#### `service-a-order/service/OrderService.java`, `controller/OrderController.java`, `model/*` (4 records)
* `POST /orders` (`@Valid`-validated) → `OrderService.placeOrder()` → `InventoryClient.reserve()` → on success mints `ORD-<uuid8>` and returns `CONFIRMED` with 201. Models are Java records — immutable, zero boilerplate, structural equality for free.

#### `service-b-inventory/service/InventoryService.java`
* **Purpose:** Stock ledger with thread-safe reservation semantics.
* **Mechanics:** `ConcurrentHashMap<String, Integer>` seeded via `@PostConstruct` (`SKU-1001`=50, `SKU-1002`=20, `SKU-1003`=0 — the zero-stock SKU exists specifically to exercise the 409 business path). `reserve()` does check-then-`merge(sku, -quantity, Integer::sum)`; in-memory by design so Service B has **zero external dependencies** — any fault observed during experiments is unambiguously the injected one, never a flaky database. (The check/merge pair is not a single atomic unit — acceptable here because the store is an experiment fixture, not an inventory system of record; noted in §4.6.)
* **`controller/InventoryController.java`:** `GET /inventory/{sku}` and `POST /inventory/reserve`; exceptions handled by its own `GlobalExceptionHandler` (404 / 409 / 400 `ProblemDetail`s).
* **`test.http`:** Editor-executable smoke requests covering the happy path and all three business-error paths.

### 2.5 `experiments/` — The Sweep Harness (Python, stdlib-only)

#### `fault_injector.py`
* **Purpose:** Typed client for Toxiproxy's admin REST API (`:8474`); the *only* code that talks to Toxiproxy.
* **Mechanics (`ToxiproxyClient`):**
  * `_request()` — single chokepoint over `urllib.request` (5s timeout). 2xx → parsed JSON; HTTP errors → raises with the response body embedded (Toxiproxy returns JSON error details); URL errors (daemon down) → logged + re-raised. Centralizing transport here means retry/auth/logging changes touch one method.
  * `create_proxy()` — idempotent: GET-checks existence before POST, so re-running initialization against a live Toxiproxy is safe.
  * `set_enabled(name, False)` — the **crash** fault: the proxy stops accepting connections, producing connection-refused upstream, indistinguishable from a dead process.
  * `inject_latency()` / `inject_bandwidth_limit()` — POST a `latency` (3000ms) or `bandwidth` (1 KB/s) toxic on the downstream stream; both call `clear_toxics()` first so toxics never stack across runs.
  * `reset_all()` — POST `/reset`, then belt-and-braces re-enables every proxy and clears toxics individually.
  * `setup_default_proxies()` — creates the 5-proxy map (ports 8661–8665 → real services). **Must run after every Toxiproxy container start** — proxies live in Toxiproxy's memory only.
  * `__main__` block: running `python3 experiments/fault_injector.py` initializes the proxy environment — step one of every experiment session.
* **Key dependencies:** Python stdlib only (`urllib`, `json`) — zero pip installs to run the harness on a fresh machine.

#### `runner.py`
* **Purpose:** Orchestrates the full sweep: config generation → environment mutation → health gating → fault injection → load → measurement → CSV append.
* **Mechanics, function by function:**
  * `PARAM_VALUES` — the experiment matrix: 3 thresholds × 3 window sizes × 3 wait durations × 2 window types × 3 half-open permit counts = **162 configs**; `generate_combinations()` produces either this full Cartesian product or 5 hand-picked canary configs (both extremes both window types + midpoint) for cheap pipeline validation.
  * `write_env_file()` — renders the config as `CB_*` vars into `infra/.env`, which compose substitutes at container-create time.
  * `update_containers()` — `docker compose up -d --no-deps --force-recreate <6 services>`. `--force-recreate` because env changes alone don't trigger recreation; `--no-deps` so Postgres/DynamoDB/Toxiproxy/Prometheus survive across the 162 recreations (restarting Toxiproxy would wipe proxies and orphan the run). Checks the compose exit code and aborts the run on failure — a half-recreated mesh must never produce a CSV row.
  * `wait_for_healthy()` — polls the Gateway's `/actuator/health` for `"status":"UP"` (60s budget, 2s interval). A run that never goes healthy is skipped and logged, not recorded.
  * `inject_fault()` — maps fault class → injection: `latency` (3s on inventory proxy), `crash` (disable payment proxy), `throttle` (1 KB/s on shared-db proxy). Each fault class targets a *different* mesh depth deliberately: mid-chain, deep-chain, and shared-dependency respectively.
  * `generate_load()` — 50 requests, 5-thread `ThreadPoolExecutor`, 50ms submission pacing; per-request latency captured under a `threading.Lock`; computes TPS, error %, mean latency. (Known measurement caveat on the TPS window — see §4.7.)
  * `get_blast_radius()` — wraps the Gateway aggregator call; returns `None` (not `0.0`) on failure so "measurement failed" is distinguishable from "mesh fully healthy."
  * `log_results()` — appends to `data/master_dataset.csv` (13 columns: timestamp, mode, topology, fault, the 5 swept params, blast radius, TPS, error rate, mean latency), writing the header only on first creation. Append-only: a crashed sweep loses no completed rows and can be resumed.
  * `main()` — argparse (`--mode canary|full`, `--fault latency|crash|throttle`, `--topology linear|fanout|mesh`), verifies Toxiproxy reachability before anything else, then loops configs and reports `success_runs/total`.
* **Key dependencies:** `fault_injector.ToxiproxyClient`, Docker CLI on PATH, the compose file path resolved dynamically from `__file__` (no hardcoded absolute paths — runs from any checkout).

### 2.6 `infra/` — Runtime Topology as Code

#### `docker-compose.yml`
* **Purpose:** The entire local environment: 6 app services + 5 infrastructure services on one bridge network (`cascadeshield-net`).
* **Mechanics worth defending:**
  * **Health-gated startup ordering.** Postgres (`pg_isready`), DynamoDB Local (HTTP probe asserting the `MissingAuthenticationToken` body — `GET /` on DynamoDB returns 400 with that token when alive, a probe that works across versions where `/shell/` was removed), Toxiproxy (`/toxiproxy-cli list`, exec-form because the distroless image has no shell). All six Spring services declare `depends_on: toxiproxy: condition: service_healthy` (plus their datastore where relevant) — the mesh cannot boot into a half-wired state.
  * **Spring Boot healthchecks.** Each app container probes its own actuator: `wget -qO- http://localhost:<port>/actuator/health | grep -q '"UP"'`, `start_period: 60s` (JVM + Spring context warm-up), 10s interval, 5 retries. Body-grep rather than `--spider` because BusyBox `wget --spider` exits 0 on any HTTP response including 5xx.
  * **JVM caps.** Every service: `JAVA_OPTS=-Xmx512m -Xms256m -XX:+UseG1GC`. Equal, *enforced* memory across services removes heap-size asymmetry as a confound; the whole 11-container stack fits a 16GB laptop for overnight sweeps.
  * **CB parameter plumbing.** Each CB-bearing service maps the five `CB_*` variables with compose-level defaults (`${CB_SLIDING_WINDOW_SIZE:-10}`) so `docker compose up` works standalone, while `runner.py`'s generated `.env` overrides them per run.

#### `infra/prometheus/prometheus.yml`
* **Purpose:** Six static scrape jobs (one per service, container-DNS targets) at `metrics_path: /actuator/prometheus`.
* **Mechanics:** `scrape_interval: 2s` — far below Prometheus's 15s default, because experiment runs last tens of seconds and the dependent variables (`time_to_open`, `time_to_recover`) need sub-5s resolution to be meaningful. The cost (storage, scrape load) is trivial at 6 targets.

#### `infra/grafana/provisioning/`
* **`datasources/datasource.yml`** — Prometheus at `http://prometheus:9090`, proxy access, default, non-editable (dashboards-as-code; no hand-edited drift).
* **`dashboards/dashboards.yml` + `dashboards_config/cb_dashboard.json`** — file-provisioned "CascadeShield Resilience Dashboard", 5 panels:
  1. **Mesh Blast Radius** (gauge) — `gateway_service_blast_radius or (sum(resilience4j_circuitbreaker_state{state="open"}) / 5 * 100)`; the `or` gives a PromQL-derived fallback if the custom metric is absent. Thresholds green <30 / yellow 30–70 / red >70.
  2. **Circuit Breaker States** (state-timeline) — `resilience4j_circuitbreaker_state` by `{{job}} - {{name}} - {{state}}`; this is the panel where you *watch the cascade propagate* breaker by breaker.
  3. **Throughput** — `sum(rate(http_server_requests_seconds_count[10s])) by (job)`.
  4. **P99 Latency** — `histogram_quantile(0.99, ...buckets...) * 1000`.
  5. **5xx Error Rate** — 5xx-rate / total-rate × 100 per job.

### 2.7 Repository Root

| File | Purpose |
|---|---|
| `.gitignore` | Excludes Maven `target/`, jars, IDE files, `__pycache__`, `.env` (generated per-run, never committed), and `data/` (the dataset is an experiment artifact, regenerated by sweeps) |
| `services/.gitignore` | Defense-in-depth `target/` exclusion scoped to the Java tree |
| `.mailmap` | Canonicalizes commit identities for `git shortlog` |
| `capstone_full_plan.docx` | The 10-week research plan (phases, gates, decision log D1–D6) |
| `services/README.md` | Service A/B track documentation: run instructions, response contract, seeded stock, env-var table |

### 2.8 `dashboard/` — Post-Hoc Results Viewer

* **Purpose:** A local Flask app that turns `data/master_dataset.csv` into a browsable results view (fault_type × window_type blast-radius heatmaps, breaker trip-rate, summary stats) — the successor to a lost, never-committed ad-hoc matplotlib script. Run with `python dashboard/app.py`, serves on `http://127.0.0.1:5050`.
* **Mechanics worth defending:** `data_loader.py` never hardcodes a column list or an enum of expected values — it reads whatever's actually in the CSV via pandas and derives filter options from the DataFrame's real distinct values. This is deliberate: `data/master_dataset_schema.csv` and `ml/preprocessing.py`'s `TOPOLOGIES`/`WINDOW_SIZES` constants have both drifted from the real sweep output before, so the dashboard is built to be immune to that class of bug rather than to assume the docs are current.
* **Scope:** post-hoc results only (a completed sweep's CSV). Live run-progress monitoring is a separate, not-yet-built phase; Grafana (`infra/grafana/`) remains the tool for watching an active run's Prometheus metrics.

---

## 3. Trade-Off Analysis & Architectural Decisions

### 3.1 Toxiproxy interception vs in-process fault injection (e.g., Chaos Monkey for Spring Boot)
**Chosen:** A Toxiproxy sidecar owning every inter-service hop.
**Alternative rejected:** `chaos-monkey-spring-boot`, which injects latency/exceptions via AOP inside the JVM.
**Why:** (1) *Measurement purity* — an in-process injector shares the JVM with the code under measurement; its assault aspects sit on the same call stack the CB aspect instruments, so you can no longer claim the CB observed a genuine network fault. Toxiproxy faults are real TCP-level events: actual delayed bytes, actual refused connections. (2) *Uniformity* — one fault API covers latency, partition, and bandwidth classes identically on every edge; the in-process tool can't model bandwidth throttling at all. (3) *Cloud symmetry* — the Toxiproxy abstraction maps cleanly onto AWS FIS for the cloud-validation phase; an in-JVM injector has no FIS equivalent, which would have forced two different fault models across environments and invalidated the local-vs-cloud divergence comparison.

### 3.2 Environment-variable CB configuration vs Spring Cloud Config / per-config images
**Chosen:** All five swept parameters as env vars resolved by compose from a generated `.env`.
**Alternatives rejected:** A config server (Spring Cloud Config + `@RefreshScope`), or baking each config into an image tag.
**Why:** A config server adds a seventh service whose own availability becomes a confound inside a fault-injection study — and `@RefreshScope` hot-reload of Resilience4j configs has murky semantics for in-flight sliding windows (does the window reset? partially carry over?). Container recreation gives each run a **bit-identical cold start**: fresh window, fresh metrics, fresh JVM — the strongest possible run-to-run isolation. 162 images would be build-pipeline absurdity. The recreation cost (~30s/run) is paid in wall-clock during unattended overnight batches, which is the cheapest currency available.

### 3.3 `@CircuitBreaker` annotations without fallbacks
**Chosen:** Every CB method lets exceptions propagate; controllers map them to 503.
**Alternative rejected:** `fallbackMethod` returning cached/default responses (the standard production pattern).
**Why:** This is an instrument, not a product. A fallback converts downstream failure into upstream 200, which would: zero out the measured error rate, hide the fault from the load generator, and decouple HTTP-level observations from CB state. The whole causal chain under study — *fault → failures accumulate → window threshold breached → breaker opens → fast-fail* — must remain visible at the HTTP layer. The deliberately preserved exception class name in the 503 body (`CallNotPermittedException` vs `ResourceAccessException`) keeps "breaker is protecting" distinguishable from "fault is hitting" in the raw data.

### 3.4 Six small mostly-stateless services vs fewer/richer services
**Chosen:** Six near-trivial services; business semantics developed separately in the service-a/service-b track.
**Why:** Every line of business logic in a mesh service is a potential confound (its own latency variance, its own failure modes). The mesh services are *calibrated network conduits* — leaves return constants, intermediaries do nothing but propagate. Meanwhile the experiment needs ≥5 downstream services for blast radius to have useful resolution (each degraded service = 20 percentage points). The business track (A/B) develops the 4xx-vs-5xx exception taxonomy that gets folded into the mesh in Week 2 — the `InventoryClient` seam exists precisely so that fold-in touches one class.

### 3.5 Python stdlib harness vs Gatling/JMeter/Locust as the driver
**Chosen:** `runner.py` with a built-in `ThreadPoolExecutor` load generator; zero pip dependencies.
**Alternative considered:** Gatling (it remains the planned tool for the formal load-profile phase: bursty vs sustained traffic shapes).
**Why for now:** The sweep driver's hard requirements are orchestration (compose, env files, Toxiproxy, CSV), not sophisticated load shaping — 50 paced requests suffice to charge a 5–20-call sliding window and observe a trip. A Gatling-per-run integration (JVM spin-up, simulation compilation, report parsing) would add ~30s and a parsing layer to each of 486 runs before the measurement pipeline itself was validated. The architecture anticipates the upgrade: `generate_load()` is one function with a clean `(throughput, error_rate, latency)` return contract — swapping in a Gatling invocation changes one call site.

### 3.6 `RestTemplate` + `SimpleClientHttpRequestFactory` vs WebClient/connection pooling
**Chosen:** Blocking `RestTemplate` over the JDK's `HttpURLConnection`, no pool.
**Alternative rejected:** Reactive `WebClient`, or Apache HttpClient pooling.
**Why:** The study models the classic thread-per-request servlet architecture **because that is the architecture where cascading failure is most violent** — a slow downstream pins Tomcat worker threads, and thread exhaustion is itself a propagation mechanism worth measuring. A reactive stack would change the failure physics (no thread pinning) and make results inapplicable to the majority of real Spring estates. No connection pool for the same reason: pool exhaustion semantics would add a second, confounding saturation mechanism on top of the CB behavior being isolated. (`service-a-order` uses the newer `RestClient` — same blocking semantics, modern fluent API — proving the seam pattern is transport-agnostic.)

### 3.7 Blast radius via actuator polling vs Prometheus-side computation
**Chosen:** A custom Gateway aggregator (`BlastRadiusService`) polling health endpoints on demand.
**Alternative rejected:** Computing it purely in PromQL from `resilience4j_circuitbreaker_state` (the Grafana gauge actually carries this as a fallback expression).
**Why:** The runner needs a *synchronous, point-in-time* reading at a precise moment in the run lifecycle (immediately post-load). A PromQL evaluation is bounded by scrape staleness (up to 2s here) and would couple the harness to Prometheus's availability; the direct poll reads each service's actual current state with one HTTP round-trip per service and works even if the observability stack is down. The dashboard keeps the PromQL variant for continuous visual monitoring — two consumers, two appropriately different mechanisms.

### 3.8 CSV append vs a real database for results
**Chosen:** Append-only `data/master_dataset.csv`.
**Why:** The dataset's consumers are pandas/scikit-learn (CSV-native), the write rate is one row per ~60s, and append-only means a crashed overnight sweep preserves all completed rows with no recovery procedure. A database adds operational surface inside a study whose entire methodology depends on environmental minimalism. The schema is fixed and versioned in code (`DATASET_HEADERS`).

### 3.9 Static Prometheus targets vs service discovery
**Chosen:** Six hardcoded `static_configs` targets.
**Why:** The topology is closed and known at design time; compose DNS names are stable. Docker SD (`docker_sd_configs`) would add config complexity to solve a dynamism problem this system intentionally does not have. Cloud-phase ECS will use its own discovery mechanism — that bridge gets built where it exists.

---

## 4. Edge Cases, Concurrency, & Robustness

### 4.1 Business errors must never trip breakers (the 4xx/5xx firewall)
The single most important correctness rule in the codebase. `InventoryClient` (service-a track) catches `HttpClientErrorException` (4xx) *before* the general `RestClientException` (5xx/timeout/refused) and rethrows it as `InventoryRejectedException` — a type the Week 2 CB config will exclude via `ignore-exceptions`. Without this, every legitimate 409 out-of-stock response would count toward the failure rate, breakers would trip on healthy traffic, and the measured blast radius would be fiction. The exception *hierarchy ordering* in the catch blocks is load-bearing: `HttpClientErrorException` is a `RestClientException` subtype, so the specific catch must come first.

### 4.2 Slow-call vs dead-call duality
The latency fault (3s) and the timeout budget (8s read) are deliberately ordered `slow-call-threshold (2s) < injected latency (3s) < read timeout (8s)`. Latency-faulted calls therefore **complete successfully but slowly**, tripping breakers via `slow-call-rate-threshold`; crash-faulted calls fail via exception, tripping breakers via `failure-rate-threshold`. The two fault classes exercise **two distinct trip mechanisms** of the same breaker — which is exactly the comparison the research questions demand. Invert any of these constants and the fault classes collapse into one.

### 4.3 Partial degradation, not binary failure
Every intermediary controller try/catches each downstream hop independently and returns a body containing per-hop results even on 503. The mesh thus exhibits *graded* degradation — e.g., Order reporting `inventory: ok, sharedDb: unavailable` under the throttle fault. Blast radius gains resolution from this: a service can be "degraded" (one open breaker) while still partially serving.

### 4.4 The silent-AOP failure mode, preempted
Resilience4j's annotation model fails *silently* if AOP proxying is absent — calls simply execute unprotected. Three layered defenses: `spring-boot-starter-aop` is explicitly declared in every CB-bearing `pom.xml` (not assumed transitively); `register-health-indicator: true` makes every breaker visible in `/actuator/health` (a missing breaker in the health tree is an immediate red flag); and the Grafana state-timeline panel shows every expected breaker instance per service — an absent series is caught by eyeball during the smoke phase, before any data run.

### 4.5 Run-to-run isolation in the harness
* **Stale-config protection:** `--force-recreate` guarantees env changes take effect; the compose exit code is checked and a failed recreation aborts the run *before* any measurement.
* **Health gating:** no load is generated until the Gateway reports `UP`; un-healthy runs are skipped and counted, never logged as data.
* **Toxic hygiene:** every injection clears existing toxics first; every run ends with `reset_all()`; `setup_default_proxies()` is idempotent. Toxics cannot leak across runs.
* **Failed-measurement sentinel:** `get_blast_radius()` returns `None` on timeout/unreachability rather than `0.0` — a failed measurement is never silently recorded as "perfectly healthy mesh."

### 4.6 Concurrency inventory
| Site | Mechanism | Notes |
|---|---|---|
| Gateway fan-out | `CompletableFuture` over `ExecutorService` | Branch failures isolated per-future; one open breaker can't block siblings |
| Load generator | `ThreadPoolExecutor(5)` + `threading.Lock` over shared counters/latency list | All shared mutation under one lock; GIL alone deliberately not relied upon |
| Inventory stock (service-b) | `ConcurrentHashMap` + `merge()` | Per-key atomic decrement; the *check*-then-merge pair is not one atomic unit — a documented, accepted race for an experiment fixture (the fix, `compute()` with the guard inside, is noted for the Week 2 hardening pass) |
| Resilience4j sliding windows | Internal lock-free ring buffers (library-managed) | One more reason annotation-driven CBs beat a hand-rolled implementation |
| Healthcheck/orchestration | Compose `service_healthy` conditions | Startup races (app before Toxiproxy; app before its datastore) eliminated at the orchestrator level |

### 4.7 Known limitations (tracked, deliberate, on the fix list)
Stated plainly because an architecture report that hides its known defects is worthless:
1. **TPS measurement window** (`runner.py generate_load`): the current pacing-overhead subtraction over-corrects when requests complete faster than the 50ms submission interval (fast-fail scenarios), inflating reported TPS; the fix — timestamping the last completion inside `send_request` under the existing lock — is queued for the Week 2 hardening pass. Error rate and latency columns are unaffected.
2. **`None` blast radius reaches the CSV as an empty cell** and the run still counts as successful; consumers must treat blank as "measurement failed," and the run should arguably be marked failed instead.
3. **A Toxiproxy error now raises through the sweep loop** (`_request` no longer swallows HTTP errors — correct in direction, but `run_experiment_run` lacks a per-run try/except, so one transient 409 can abort a multi-hour batch rather than skipping one run).
4. **Healthcheck body-grep** (`grep -q '"UP"'`) matches the substring anywhere in the health JSON; it behaves correctly today only because Spring returns 503 (empty `wget -qO-` output) for DOWN — probing `/actuator/health/liveness` is the cleaner endgame.

### 4.8 Failure-handling strategy, layer by layer
```
Layer            Failure                       Strategy
─────            ───────                       ────────
Wire             Slow / refused / dropped      Bounded timeouts (3s/8s) — nothing waits forever
CB               Failure/slow rate > threshold Fast-fail (CallNotPermittedException), timed half-open probe
Service          Downstream hop failed         Per-hop try/catch → 503 + partial body + cause class
Measurement      Aggregator unreachable        Unreachable counts as degraded; runner gets None, not 0.0
Harness          Compose failed / not healthy  Run aborted/skipped, counted, never logged as data
Harness          Sweep crash mid-batch         Append-only CSV → completed rows survive, resume by re-run
Orchestration    Container starts out of order service_healthy gating + 60s start_period
```

---

## Appendix A — Experiment Matrix

| Parameter | Values Swept |
|---|---|
| `failureRateThreshold` | 30, 50, 70 (%) |
| `slidingWindowSize` | 5, 10, 20 |
| `waitDurationInOpenState` | 5s, 15s, 30s |
| `slidingWindowType` | `COUNT_BASED`, `TIME_BASED` |
| `permittedCallsInHalfOpenState` | 3, 5, 10 |

**162 configurations × 3 fault classes (latency / crash / throttle) = 486 runs per topology.**

## Appendix B — Quick Start

```bash
git clone https://github.com/anonjj/CascadeShield.git && cd CascadeShield

# 1. Boot the full stack (6 services + Postgres + DynamoDB + Toxiproxy + Prometheus + Grafana)
cd infra && docker compose up -d && cd ..

# 2. Initialize Toxiproxy proxies (required after every toxiproxy container start)
python3 experiments/fault_injector.py

# 3. Smoke-test the mesh
curl -s localhost:8080/actuator/health          # {"status":"UP",...}
curl -s localhost:8080/api/v1/linear            # full-chain 200
curl -s localhost:8080/api/v1/blast-radius      # {"blastRadius":0.0}

# 4. Canary sweep (5 configs, validates the pipeline)
python3 experiments/runner.py --mode canary --fault latency

# 5. Full sweep (162 configs — run overnight)
python3 experiments/runner.py --mode full --fault latency --topology linear

# 6. Browse the results instead of staring at the terminal
cd dashboard && pip install -r requirements.txt && python app.py
# → http://127.0.0.1:5050

# Dashboards: Grafana at http://localhost:3000 (admin/admin), Prometheus at :9090
```

## Appendix C — Roadmap (per the 10-week research plan)

* **Week 2:** `@CircuitBreaker` onto `InventoryClient.reserve()` (the prepared seam); experiment matrix v2 ratification; dataset schema lock (`window_fill_time_s`, null sentinels, blast-radius τ).
* **Weeks 3–4:** 486-run Topology 1 sweep + window-type×traffic sub-study + healthy false-positive-rate set; Isolation Forest + Decision Tree (max_depth ≤ 6, 5-fold CV) training.
* **Weeks 5–7:** AWS CDK stack, ECS Fargate canary (±15% divergence gate), full cloud sweep via Fargate Spot.
* **Weeks 8–10:** Topology 2/3 comparative runs, IEEE paper.

## Team

**Soham** — Backend, Resilience & ML Engineer: Order/Inventory business services, Resilience4j integration, dataset schema, ML pipeline, paper methodology.
**Jay** — Platform, Observability & Chaos Engineer: Gateway + mesh services, Docker Compose stack, Prometheus/Grafana, Toxiproxy fault injection, experiment runner, AWS deployment.

## License

MIT
