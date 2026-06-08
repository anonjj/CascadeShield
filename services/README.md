# CascadeShield — Service A (Order) & Service B (Inventory)

Week 1 deliverable: two Spring Boot 3.3 / Java 21 services on the Linear Chain
path `A → B`. Plain REST + service-to-service call + Actuator. **No Resilience4j
yet** — that is Week 2, and it bolts onto `InventoryClient.reserve()` only.

| Service | Module | Port | Role |
|---------|--------|------|------|
| A | `service-a-order` | 8081 | Upstream caller. `POST /orders` reserves stock in B. |
| B | `service-b-inventory` | 8082 | Downstream leaf. Owns stock, in-memory store. |

## Run locally
```bash
# terminal 1 — start B first (A depends on it)
cd service-b-inventory && mvn spring-boot:run

# terminal 2
cd service-a-order && mvn spring-boot:run
```

## Smoke test
```bash
curl localhost:8082/inventory/SKU-1001
curl -X POST localhost:8081/orders -H 'Content-Type: application/json' \
     -d '{"sku":"SKU-1001","quantity":3}'
curl localhost:8081/actuator/health
curl localhost:8081/actuator/info
```

## Response contract (matters for the experiment harness)
| Scenario | HTTP | Counts as CB fault? |
|----------|------|---------------------|
| Order placed | 201 | — |
| Insufficient stock / unknown SKU | 409 / 404 | **No** (business outcome) |
| Bad request body | 400 | **No** |
| Service B down / timeout / 5xx | 503 | **Yes** |

## Seeded stock (Service B)
`SKU-1001`=50, `SKU-1002`=20, `SKU-1003`=0 (kept empty for 409 testing).

## Configuration (env-var overridable — needed for Docker/Toxiproxy later)
| Variable | Default | Purpose |
|----------|---------|---------|
| `SERVER_PORT` | 8081 / 8082 | service port |
| `SERVICES_INVENTORY_BASE_URL` | `http://localhost:8082` | where A finds B (→ Toxiproxy during faults) |
| `INVENTORY_CONNECT_TIMEOUT_MS` | 1000 | A→B connect timeout |
| `INVENTORY_READ_TIMEOUT_MS` | 2000 | A→B read timeout (bounded so latency faults are measurable) |

## Next (Week 2)
- Add `resilience4j-spring-boot3` + `micrometer-registry-prometheus`.
- Annotate `InventoryClient.reserve()` with `@CircuitBreaker(name="inventory", fallbackMethod=...)`.
- Expose `/actuator/prometheus`; confirm CB state + latency + TPS scrape cleanly.
