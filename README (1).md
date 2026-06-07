# CascadeShield

> **Empirical Resilience Engineering Study** — How Resilience4j circuit breaker configurations affect cascading failure blast radius across a distributed microservice mesh.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Java](https://img.shields.io/badge/Java-17-orange.svg)](https://adoptium.net/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.x-brightgreen.svg)](https://spring.io/projects/spring-boot)
[![Resilience4j](https://img.shields.io/badge/Resilience4j-2.2-blue.svg)](https://resilience4j.readme.io/)
[![AWS ECS Fargate](https://img.shields.io/badge/AWS-ECS%20Fargate-FF9900?logo=amazonaws)](https://aws.amazon.com/fargate/)
[![Status: Active Research](https://img.shields.io/badge/Status-Active%20Research-yellow.svg)]()

---

## Overview

CascadeShield is a structured empirical study examining how Resilience4j circuit breaker parameter configurations influence the **blast radius** of cascading failures in a six-service Spring Boot microservice mesh. The study sweeps **486 parameter combinations** across three distinct fault classes and three service topologies, combining infrastructure-level chaos engineering with an ML-driven configuration recommender.

The **primary novelty claim** is a systematic `COUNT_BASED` vs `TIME_BASED` sliding window comparison under controlled fault conditions — a dimension largely absent from existing Resilience4j literature.

---

## Research Questions

1. Which circuit breaker parameters most significantly affect blast radius under latency, crash, and throttle faults?
2. Does `COUNT_BASED` or `TIME_BASED` sliding window produce tighter blast radius containment, and does the answer vary by fault class?
3. How does topology (Linear Chain vs Fan-Out vs Shared Dependency Mesh) interact with circuit breaker sensitivity?
4. Can a Decision Tree recommender trained on controlled experiments generalise to cloud-deployed equivalents within a ±15% divergence tolerance?

---

## Architecture

### Service Mesh (6 Services)

```
[Gateway Service]
      │
      ├──► [Order Service]
      │         │
      │         ▼
      │    [Inventory Service]
      │         │
      │         ▼
      │    [Payment Service]
      │         │
      │         ▼
      │    [Notification Service]
      │
      └──► [Shared DB Service]
```

All services are Spring Boot 3.x with Resilience4j 2.2 wired in. Each circuit breaker is configured entirely via environment variables — no code changes are needed between parameter sweep runs.

### Topology Progression

| Phase | Topology | Description |
|---|---|---|
| 1 | **Linear Chain** | Hard gate — must pass before proceeding |
| 2 | **Fan-Out** | Gateway fans out to multiple downstream services |
| 3 | **Shared Dependency Mesh** | Multiple services share a common dependency |

### ML Layer

```
experiment_log.csv
      │
      ├──► Isolation Forest       (anomaly detection on experiment results)
      │
      └──► Decision Tree          (config recommender, max_depth ≤ 6)
                │
                └──► AWS Lambda endpoint  (real-time recommendation API)
```

---

## Parameter Sweep

### Circuit Breaker Parameters (Independent Variables)

| Parameter | Values Swept |
|---|---|
| `failureRateThreshold` | 25%, 50%, 75% |
| `slidingWindowSize` | 5, 10, 20 |
| `waitDurationInOpenState` | 5s, 15s, 30s |
| `slidingWindowType` | `COUNT_BASED`, `TIME_BASED` |
| `permittedCallsInHalfOpenState` | 3, 5, 10 |

**Total combinations: 486** (3 × 3 × 3 × 2 × 3 × 3 fault classes)

### Fault Classes (Injected via Toxiproxy / AWS FIS)

| Fault Class | Mechanism | Tool |
|---|---|---|
| **Latency** | Upstream delay injection | Toxiproxy |
| **Service Crash** | Container kill | Toxiproxy / AWS FIS |
| **Managed Service Throttle** | DB connection limit / AWS FIS | AWS FIS |

### Dependent Variables (Measured per Run)

| Metric | Description |
|---|---|
| `blast_radius` | % services in OPEN or degraded state at peak fault |
| `time_to_open` | Latency from fault injection to first CB trip |
| `time_to_recover` | Time from peak fault to full mesh recovery |
| `error_rate` | % failed requests during fault window |
| `throughput_loss` | Drop in req/s vs pre-fault baseline |

---

## Dataset Schema

All experiment results are logged to `data/master_dataset.csv`:

```
topology, fault_type, failure_rate_threshold, sliding_window_size,
sliding_window_type, wait_duration_ms, permitted_calls_half_open,
blast_radius, time_to_open_ms, time_to_recover_ms, error_rate, throughput_loss
```

---

## Infrastructure

### Local (Docker Compose)

- All 6 Spring Boot services + Toxiproxy sidecar
- Prometheus + Grafana for metrics collection
- DynamoDB Local + Postgres
- Gatling 3.10 for load generation (bursty and sustained profiles)
- **JVM cap:** `-Xmx512m -Xms256m` on all services (enforced, not advisory)

### Cloud (AWS ECS Fargate)

- ECS Fargate task definitions mirroring local Docker Compose services
- AWS FIS (Fault Injection Simulator) for crash and throttle fault classes
- **Canary runs** (15–20 configs) mandatory before any full 486-run sweep
- **Divergence tolerance:** ±15% between controlled and AWS results; breach triggers investigation before proceeding

---

## Experiment Protocol

```
1. Lock environment
   ├── Pin all Docker image digests
   ├── Pin Resilience4j patch version
   └── Pin Gatling simulation files

2. Canary run (15–20 configs)
   └── Validate ±15% divergence band (local vs AWS)

3. Full sweep — Linear Chain topology
   ├── Latency fault class  (162 runs)
   ├── Crash fault class    (162 runs)
   └── Throttle fault class (162 runs)

4. Gate check before topology expansion
   └── Linear Chain complete + ML models trained

5. Repeat for Fan-Out and Shared Dependency Mesh
```

---

## ML Pipeline

### Anomaly Detection (Isolation Forest)

- Input: all 6 dependent variables per run
- Output: `anomaly_score` flagging statistically unusual experiment outcomes
- Saved as: `models/isolation_forest.pkl`

### Configuration Recommender (Decision Tree)

- Input features: topology, fault_type, and all 5 CB parameters
- Target: `blast_radius`
- Constraints: `max_depth ≤ 6`, 5-fold cross-validation, train vs test accuracy logged
- Interpretability requirement: model must produce a readable decision path
- Deployed as: **AWS Lambda endpoint** (`POST /recommend`)
- Saved as: `models/decision_tree.pkl`

> Deep learning was explicitly ruled out due to small dataset size and the interpretability requirement for the research paper.

---

## Repository Structure

```
CascadeShield/
├── services/
│   ├── gateway-service/
│   ├── order-service/
│   ├── inventory-service/
│   ├── payment-service/
│   ├── notification-service/
│   └── shared-db-service/
├── infra/
│   ├── docker-compose.yml
│   ├── prometheus/
│   ├── grafana/
│   └── cdk/                    # AWS CDK stack
├── experiments/
│   ├── runner.py               # Parameterised experiment runner
│   ├── fault_injector.py       # Toxiproxy / FIS wrapper
│   └── configs/                # 486-combination config matrix
├── data/
│   ├── master_dataset.csv
│   ├── drift_dataset.csv
│   └── feature_importance.csv
├── ml/
│   ├── isolation_forest.py
│   ├── decision_tree.py
│   ├── lambda_handler.py       # Recommender Lambda endpoint
│   └── models/
│       ├── isolation_forest.pkl
│       └── decision_tree.pkl
├── analysis/
│   ├── eda.ipynb
│   └── figures/                # Paper-ready PNG exports
└── docs/
    └── paper/                  # IEEE paper draft
```

---

## Key Design Decisions & Guardrails

| Decision | Rationale |
|---|---|
| Linear Chain is a hard gate | Validates the measurement pipeline before adding topology complexity |
| COUNT_BASED vs TIME_BASED is the primary novelty | Absent from existing Resilience4j empirical literature |
| Decision Tree over deep learning | Dataset too small; interpretability required for research paper |
| ±15% divergence band | Acceptable infrastructure nondeterminism threshold between Docker Compose and Fargate |
| Canary runs mandatory | Prevents wasting a full 486-run sweep if environment divergence is too high |
| JVM capped at -Xmx512m -Xms256m | Ensures fair comparison across all services; prevents memory asymmetry from skewing results |

---

## Observability Stack

| Tool | Role |
|---|---|
| Prometheus | Scrapes `/actuator/prometheus` from all 6 services |
| Grafana | Live CB state dashboard + blast radius metric |
| Spring Actuator | Exposes CB state (`CLOSED` / `OPEN` / `HALF_OPEN`), failure rate, call counts |
| Gatling | Load profiles — bursty (spike) and sustained (ramp) |

The blast radius metric is a custom Actuator aggregator: **% of services in OPEN or degraded state at peak fault window**.

---

## Getting Started

### Prerequisites

- Java 17+
- Docker + Docker Compose
- Python 3.10+ (for experiment runner and ML pipeline)
- AWS CLI (for cloud validation phase)

### Local Setup

```bash
git clone https://github.com/anonjj/CascadeShield.git
cd CascadeShield

# Start the full local stack
docker compose up -d

# Verify all services are healthy
curl http://localhost:8080/actuator/health

# Run a canary sweep (15 configs)
python experiments/runner.py --mode canary --fault latency

# Run a full sweep (162 configs per fault class)
python experiments/runner.py --mode full --fault latency
```

### Grafana Dashboard

Navigate to `http://localhost:3000` — the circuit breaker state and blast radius dashboards are pre-provisioned.

---

## Research Deliverables

- [ ] `data/master_dataset.csv` — 486-run experiment log
- [ ] `models/isolation_forest.pkl` — trained anomaly detector
- [ ] `models/decision_tree.pkl` — trained config recommender
- [ ] `data/feature_importance.csv` — parameter sensitivity ranking
- [ ] `data/drift_dataset.csv` — local vs AWS divergence analysis
- [ ] `analysis/figures/` — paper-ready figures (architecture, heatmaps, feature importance, topology comparison)
- [ ] IEEE paper — results and analysis sections

---

## Team

### Soham — Backend, Resilience & ML Engineer
B.Tech Computer Engineering, NMIMS Navi Mumbai (2024–25)

- Spring Boot services: Order, Inventory, Payment, Notification (Services A & B in the mesh)
- Resilience4j integration — CB wiring, env-var overrides, state transition verification
- ML pipeline — Isolation Forest anomaly detector, Decision Tree recommender, AWS Lambda endpoint
- Experiment data — dataset schema design, preprocessing pipeline, EDA, heatmaps
- IEEE paper — ML methodology, results, and analysis sections

### Jay — Platform, Observability & Chaos Engineer
B.Tech Computer Engineering, NMIMS Navi Mumbai (2024–25)

- Spring Boot services: Gateway, Service C, Service D
- Infrastructure — `docker-compose.yml`, all 6 services + Toxiproxy sidecar, Postgres, DynamoDB Local, JVM cap enforcement
- Observability stack — Prometheus scraping all services, Grafana dashboard (CB state, blast radius, error rate, TPS, p99 latency panels)
- Chaos engineering — Toxiproxy fault injection (latency, crash, throttle), `run_experiment.py` automation runner
- AWS cloud deployment — CDK stack, ECS Fargate (Gateway + C + D), CloudWatch, X-Ray, S3 result logging, SNS alerts
- IEEE paper — architecture, implementation, monitoring, and chaos engineering chapters; all architecture and workflow diagrams

**Coordination point:** Jay's `run_experiment.py` is a hard dependency for Soham's overnight batch sweeps. Service ownership is non-overlapping; AWS deployment scope mirrors the local split.

---

## License

[MIT](LICENSE)
