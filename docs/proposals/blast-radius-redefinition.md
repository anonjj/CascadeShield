# Proposal: Redefine "blast radius" as request-level failure, not breaker state

**Status:** Draft for review — needs sign-off from Jay (metrics/Prometheus) and the mentor.
**Branch:** `fix/measurement-validity`
**Scope:** adds a *second* metric alongside the existing one. Nothing is deleted; both are
written to every row so the two definitions can be compared on the same runs.

---

## 1. The two definitions

### Definition A — legacy: "% of services with an OPEN circuit breaker" (CB state)

Implemented in `BlastRadiusService.java`. The gateway polls each downstream service's
`/actuator/health` and counts the fraction whose circuit breaker reports `CIRCUIT_OPEN`:

```
blast_radius_A = (# services with >=1 OPEN breaker) / (total services) * 100
```

Written to the existing `blast_radius` column. **Unchanged by this proposal.**

### Definition B — proposed: "% of legs actually failing requests" (request outcomes)

Measured by the runner (`experiments/runner.py`) from Resilience4j **call-outcome**
counters — `resilience4j.circuitbreaker.calls{kind=successful|failed}` — scraped from each
service's actuator `/actuator/metrics` endpoint immediately **before** and **after** the
fault window. For each leg we take the delta over the window:

```
leg_error_rate      = failed / (successful + failed)          # over the fault window only
leg is "degraded"   iff leg_error_rate > TAU_LEG
blast_radius_B      = (# degraded legs) / (# observed legs) * 100
```

Written to the **new** `real_blast_radius` column. A leg is only counted if it was actually
exercised during the window (calls > 0) and measurable in both snapshots; if no leg is
observable the value is left **null** (`""`), never a fabricated `0.0`.

---

## 2. Why the CB-state definition is misleading

- **It measures the breaker's state, not the damage.** A service can fail every single
  request while its breaker is still `CLOSED` (e.g. the failure rate hasn't crossed the
  threshold yet, or `minimumNumberOfCalls` was never reached) and still score **0%**.
- **An OPEN breaker is arguably the system *working*.** Fast-failing to contain a fault is
  the intended behaviour. Definition A can therefore paradoxically report a *larger* blast
  radius when the breakers are doing their job, and a *smaller* one when they fail silently.
- **It is a point-in-time sample.** It reads whatever state happens to exist at the sampling
  instant; a breaker that opened and re-closed before sampling is invisible.
- **Empirically it produced a degenerate result.** In the 486-run sweep, every TIME_BASED
  run scored `blast_radius = 0` and all propagation was confined to COUNT_BASED — an
  artifact of windows never filling (see the companion Task 1 fix and
  `minimum-number-of-calls`), not a property of time-based breakers.

Definition B measures the thing the project actually claims to study: **how far real request
failure propagates through the mesh under a fault.**

---

## 3. Exact formula (Definition B)

Let `S` = set of downstream services with a circuit breaker (order, inventory, payment,
notification; shared-db is a leaf with no CB). For service `s`, over the fault window
`[t_before, t_after]`:

```
Δsuccess(s) = successful_after(s) - successful_before(s)
Δfailed(s)  = failed_after(s)     - failed_before(s)
observed(s) = Δsuccess(s) + Δfailed(s)

legs_observed = { s in S : observed(s) > 0 }
legs_degraded = { s in legs_observed : Δfailed(s) / observed(s) > TAU_LEG }

real_blast_radius = |legs_degraded| / |legs_observed| * 100     if |legs_observed| > 0
                  = null                                         otherwise
```

Reported as a percentage (0–100) so it is directly comparable to the legacy `blast_radius`
column on the same run.

---

## 4. Open question for sign-off

**What is `TAU_LEG` — the per-leg error-rate threshold above which a leg counts as
"degraded"?** Currently a placeholder `REAL_BLAST_LEG_ERROR_THRESHOLD = 0.50` in
`runner.py`. Options to decide:

1. **Fixed 0.50** — "a leg is degraded if more than half its calls failed." Simple,
   symmetric, but arbitrary.
2. **Tie it to the CB `failure-rate-threshold`** (30/50/70, already swept) — a leg is
   degraded when it exceeds the same rate the breaker itself uses. Internally consistent,
   but then the metric co-varies with a swept parameter.
3. **`TAU_LEG = 0`** — any observed failure at all makes a leg degraded (most sensitive;
   turns `real_blast_radius` into "fraction of legs with any failure").
4. **Report the raw per-leg error rates** and defer thresholding to analysis time, so the
   cutoff isn't baked into the dataset.

Secondary questions:
- **Should `kind=not_permitted` calls** (rejected because the breaker was already OPEN)
  count as failures, be excluded, or be tracked as a third category? Current code ignores
  them (only successful/failed), which may undercount damage when a breaker is open.
- **Crash faults**: when a downstream proxy is fully disabled, the *caller's* outgoing
  calls fail (captured here) but the crashed service receives no traffic. Confirm we are
  reading the caller-side CB metrics on every leg (we are, since each caller owns the CB),
  and that this matches how Jay's Prometheus stack attributes the failures.

---

## 5. Compatibility / impact

- Additive: new `real_blast_radius` column appended to `DATASET_HEADERS` (18 columns).
- The runner refuses to append to a CSV whose header doesn't match, so it will **not**
  corrupt the existing `data/master_dataset.csv` (17 cols) — a fresh full sweep would
  start a new file. The legacy `blast_radius` column and its meaning are untouched.
- `ml/preprocessing.py` matches columns by name and ignores extras, so it keeps working;
  wiring `real_blast_radius` into the models is a separate, later decision.
