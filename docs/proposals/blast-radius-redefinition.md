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
counters scraped from each service's actuator `/actuator/metrics` endpoint immediately
**before** and **after** the fault window. Per leg, over the window delta:

```
leg_failure_rate  = (failed + not_permitted) / (successful + failed + not_permitted)
leg is "degraded" iff leg_failure_rate > TAU_LEG
blast_radius_B    = (# degraded legs) / (# observed legs) * 100
```

where `successful`/`failed` come from `resilience4j.circuitbreaker.calls{kind=…}` and
`not_permitted` from `resilience4j.circuitbreaker.not.permitted.calls`. `not_permitted`
calls (short-circuited by an OPEN breaker) are counted as damage — see the canary evidence
in §6. `ignored` calls (business 4xx rejections) are excluded; slow-but-completed calls
remain `successful` (a slow success is still a completed request).

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

Let `S` = the **four CB-bearing downstream subject services**: order, inventory, payment,
notification. `shared-db` is excluded (leaf, no CB) and — as of the gateway-CB-confound
finding — **the gateway is also excluded** (it is the measurement plane, not a subject; see
§7, which supersedes the earlier §6 decision to include it). This matches
`BlastRadiusService.SERVICE_ACTUATOR_URLS`, so both blast-radius metrics range over the same
4 nodes. For node `s`, over the fault window `[t_before, t_after]`:

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

### 6. Canary evidence (2026-07-26, `--mode canary --fault latency --topology linear`)

A first canary of 15 runs on branch `fix/measurement-validity` settled the `not_permitted`
question empirically:

- **Task 1 confirmed fixed**: TIME_BASED breakers now trip (legacy `blast_radius` = 20 for
  both COUNT_BASED and TIME_BASED; previously TIME_BASED was 0 across all 243 full-sweep
  rows). Duration-driven load + a reachable `minimum-number-of-calls` resolved the artifact.
- **`not_permitted` must be counted**: with the first formula (`failed / (successful +
  failed)`), `real_blast_radius` read **0.0 on all 15 runs despite gateway error rates of
  70–94%**. Under a latency fault the pre-trip calls are slow-but-successful and the
  post-trip calls are `not_permitted` (not `failed`), so failures were invisible. The
  formula above now counts `failed + not_permitted`, which reflects the real propagation.
  → **Decision taken: `not_permitted` counts as damage.**
- **The leg set must include the gateway.** Even after counting `not_permitted`, a second
  canary still read 0. A live counter diagnostic under the latency fault showed the failure
  lands entirely on the **gateway's** outbound breaker (Δnot_permitted = 115) while the five
  downstream services showed ~10 successful / 0 failed / 0 rejected each — because once the
  gateway CB opens it stops calling downstream, so the deeper nodes look healthy. The
  original leg set (downstream services only) therefore missed the whole signal.
  → **Decision taken: include the gateway's caller-side breakers in the leg set.**

**Remaining open decision:** `TAU_LEG` value (§4 options 1–4) still needs sign-off — but it is
now **non-blocking**. The runner persists the raw per-leg failure rates in a `leg_failure_rates`
column (`svc:rate;svc:rate`, each 0–1) alongside the scalar `real_blast_radius`. `real_blast_radius`
can therefore be recomputed at any `TAU_LEG` straight from the CSV (verified: tau=0.5→0.333,
tau=0.1→0.667 on the same row), so a threshold chosen after the sweep does **not** require
re-running the 486 configs.

Secondary questions:
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

---

## 7. Gateway CB confound — node set corrected to 4 downstream subjects (SUPERSEDES §6)

The first 162-run LATENCY sweep produced a **degenerate** result: `blast_radius` was `0.2` in
156/162 runs (`0.0` in the other 6) and `real_blast_radius` was `0.2` in 158/162 — no swept CB
parameter moved the outcome.

**Root cause.** `gateway-service`'s outbound breakers used `base-config: default`, which reads
the swept `CB_*` env vars and has `slow-call-duration-threshold: 2s`. The gateway observes the
**summed** latency of the whole chain (gateway → order → inventory, where the 3000 ms toxic
sits), so it crosses the slow-call threshold before any interior breaker does. With
`minimum-number-of-calls: 5` it opens after ~5 calls and fast-fails locally, **starving the rest
of the chain of traffic**. Evidence: `leg_failure_rates` showed gateway at 0.70–0.96 while order,
inventory, payment and notification were all *exactly* 0.0000 (present in the dict, not skipped —
so they were exercised and every call succeeded). Blast radius saturated at one node.

**Decisions (supersede §6's "include the gateway"):**
1. **Gateway removed from the sweep.** Its three breakers now use a hardcoded
   `measurement-plane` config (`minimum-number-of-calls: 1000000`, `failure-rate-threshold: 100`,
   `slow-call-rate-threshold: 100`, `slow-call-duration-threshold: 60s`) so the gateway breaker
   **never opens**. The gateway is the measurement plane, not an experimental subject; only the
   five downstream services remain driven by the swept `CB_*` config.
2. **Both metrics measure the same 4 nodes.** The denominator for `blast_radius`
   (`BlastRadiusService`) and `real_blast_radius` (`runner.py` `CB_METRIC_TARGETS`) is now the
   four CB-bearing downstream subjects: order, inventory, payment, notification. `shared-db` is
   dropped (leaf, no CB) and the gateway is excluded from the denominator (diagnostics only).
   Blast radius now ranges over `{0, 0.25, 0.5, 0.75, 1.0}`.

**Data impact.** The 5-service sweep is archived read-only as
`data/master_dataset_v2_latency_5svc.csv` and is **not comparable** to any post-change run. The
column names are unchanged, so `runner.log_results`' stale-header guard would NOT catch a mixed
append — the next sweep must start a fresh `data/master_dataset.csv`; the two are never pooled.
