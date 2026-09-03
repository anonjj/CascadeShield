# `leg_failure_rates` Blends Two Circuit Breakers Per Service

**Found:** 2026-09-04, while validating the canary-matrix executor (`research/canary-matrix-executor`)
**Regenerate the evidence:** `python3 experiments/diagnose_leg_blend.py` (live mesh required)
**Decision-log entry:** D17 (`docs/paper/decision-log.md`)
**Status:** finding confirmed with live-mesh evidence; fix not yet designed or applied

---

## The question this had to answer

A `canary_matrix.py` smoke-test row recorded `order-service`'s `leg_failure_rates` at
**0.4870** — suspiciously close to 0.50, and nearly identical to a completely unrelated number
already sitting in `docs/paper/decision-log.md` (D-001): *"order-service, max rate **0.4867**
across 320 leg observations."* Two independent datasets, collected weeks apart, landing within
0.0003 of each other, both just under a 0.50 threshold that matters a great deal to this
project's containment metric. That's not the kind of thing to wave off as coincidence.

The question: is this a real property of the system (order-service genuinely never fails more
than ~49% of its calls, for some physical reason), or is it an artifact of how the metric
itself is computed?

**It's an artifact — confirmed, not inferred, with live-mesh evidence.**

---

## The mechanism

`runner.py`'s `_get_cb_metric_count()` reads a Resilience4j actuator metric like this:

```python
def _get_cb_metric_count(base_url, metric, kind):
    """Sum of a resilience4j circuit-breaker COUNT metric across a service's CB instances,
    filtered by kind, via its actuator metrics endpoint."""
    url = f"{base_url}/actuator/metrics/{metric}?tag=kind:{kind}"
    ...
```

Its own docstring says it: **"Sum ... across a service's CB instances."** The query filters
only by outcome (`successful`/`failed`/`not_permitted`) — never by *which* circuit breaker.

Every subject in this project except `notification-service` owns **two** circuit breakers: one
guarding its call to the "next" service in the chain, and one guarding its call to
`shared-db-service`. Their controllers call both, unconditionally, once per request, regardless
of what happened to the first call:

```java
try { downstreamService.callInventory(); } catch (...) { ... }   // hits the injected fault
try { downstreamService.callSharedDb();  } catch (...) { ... }   // completely unaffected
```

This project has never injected more than one fault at a time, so exactly one of a service's
two downstream edges is ever degraded. The "leg" reading `compute_leg_failure_rates()` produces
is therefore an **unweighted average of one broken breaker and one healthy breaker** — landing
near half the true fault severity, by construction, regardless of how severe the real fault is.

## The evidence

`experiments/diagnose_leg_blend.py` polls `order-service`'s two breakers *separately* (via a
`&tag=name:{cb}` filter the harness itself never uses) alongside the existing blended reading,
across 5 replicates of the same config (TIME_BASED, threshold=50, window=20, wait=15, λ=20,
latency fault on `inventory-service-proxy`, live mesh on the codespace):

| Reading | mean | stdev |
|---|---|---|
| blended `order-service` leg (existing metric) | 0.4010 | 0.0011 |
| `inventoryServiceCB` alone (the faulted edge) | 0.8020 | 0.0021 |
| `sharedDbCB` alone (untouched by this fault) | 0.0000 | 0.0000 |

$0.8020 \div 2 = 0.4010$ — exact to 4 decimal places, with stdev under 0.2% across every
replicate. That's the arithmetic signature of the mechanism above, not sampling noise.

## Why it matters

`real_blast_radius` calls a leg "degraded" when its rate exceeds `REAL_BLAST_LEG_ERROR_THRESHOLD
= 0.50`. Because the blended reading is capped at roughly half the true rate on whichever edge
is actually faulted:

- A leg at **100% true failure** on its faulted edge would still report only **~0.50 blended**
  — sitting *right at* the classification boundary, not clearly above it.
- Anything short of a total outage reports *below* 0.50 and gets classified as "not degraded,"
  regardless of real severity.

This affects **order-service, inventory-service, and payment-service** (each has two breakers).
`notification-service` (one breaker only) is unaffected — consistent with it reading a clean
`0.0000` in every observed row so far.

## D-001 is implicated, not necessarily wrong

D-001 decided to report $\tau_{\text{leg}}$ as a curve over $[0.05, 0.95]$ rather than commit to
a single threshold, specifically because order-service's observed max (0.4867 across 320
observations) sits just under the shipped $\tau=0.50$, making `real_blast_radius` identically
zero everywhere. That curve-vs-value *methodology* is sound regardless of what caused the
ceiling. But its *factual premise* — that 0.4867 represents something close to order-service's
true worst-case severity — was measured through this exact unfixed path. The live evidence above
shows the true per-edge rate can be at least 0.80 under the same conditions that would blend down
to ~0.40. D-001 is not being reopened by this finding; it should be **re-examined** once real
per-edge data exists.

## What fixing this actually requires

Not a one-line patch — a representation decision, because there are three genuinely different
ways to define the corrected metric, each with different tradeoffs:

| Option | What it captures | Cost |
|---|---|---|
| (a) Report only the actually-faulted edge's rate | Cleanest signal, matches "what the fault did" | Needs `inject_point` threaded through to the metric read — it's a runtime fact, not static |
| (b) Report both breakers separately per service | No information lost | Changes `leg_failure_rates`' string format; breaks any downstream parser expecting one rate per service |
| (c) Report the max of a service's breakers | Simple, minimal schema change | Loses which edge actually failed |

This is a measurement-design decision in the same category as $\tau_{\text{leg}}$'s calibration
(D-001) and the D6/D16 cross-machine protocol — it goes through Soham's sign-off before any code
changes, not resolved unilaterally mid-sprint.

## The consequence that matters most: this is not retroactively recoverable

$\tau_{\text{leg}}$ (D-001) could be recomputed after the fact because `leg_failure_rates`' raw
value was already persisted and any threshold could be swept against the existing CSV. This bug
is upstream of what gets persisted at all — `snapshot_cb_calls()` only ever captured the
already-blended per-service sum, never the raw per-breaker counts underneath it.

**Every row already collected — the entire `master_dataset.csv`, every `v1`–`v5` archive — is
permanently blended. There is no way to recover the true per-edge rate from data that already
exists.** A fix only protects data collected *after* it lands, and needs its own dataset-version
boundary (same `vN` treatment `analysis/common.py`'s `DATASETS` registry already uses) so old
and new `leg_failure_rates` values are never silently pooled as if they meant the same thing.

## Isolation from the sweep-execution path

The fix, whenever it's designed, only touches `_get_cb_metric_count()`,
`snapshot_cb_calls()`, `compute_leg_failure_rates()`, and (depending on representation) the
`leg_failure_rates`/`DATASET_HEADERS` schema. Fault injection, circuit-breaker configuration,
resumability, and everything `run_experiment_run()` orchestrates are completely untouched — this
can be built and reviewed on its own branch with zero risk to any in-flight sweep.

## Open, separate item found while writing this up

`docs/paper/decision-log.md`'s D16 is still marked "pending the calibration run itself" — the
D6 cross-machine calibration it calls for has since actually been run (2026-09-02/03) and shows
a large, highly significant, topology-independent machine effect (Welch's t ≈ 110–120 on
`lambda_achieved`, ~8 percentage-point gap, consistent across both LINEAR and FANOUT). D16 needs
its own update citing that verdict. Not the same bug as this one — flagged here only because it
surfaced during the same investigation.
