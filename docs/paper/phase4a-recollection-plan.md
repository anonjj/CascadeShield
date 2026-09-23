# Phase 4A — re-collection plan (PLAN ONLY, nothing here has been run)

Everything in this file is a **PLANNING INPUT, NOT AN H3 RESULT**. No p-value, ratio or
dispersion figure below is a finding about H3, and none of it belongs in paper text.

Phase 3 headline analysis is blocked: Phase 2 found **zero** VERIFIED CLEAN (post-D25) H3
rows, so the clean H3 analysis waits on the Phase 4B collection this plan describes.

## 1. Exact floors — computed from `exact_tests.py`, not assumed

Single stratum, two-sided (`exact_p_floor`, doubled):

| n per arm | one-sided | two-sided |
|---|---|---|
| 3v3 | 0.05 | **0.10** |
| 4v4 | 0.0143 | **0.0286** |
| 5v5 | 0.00397 | **0.00794** |
| 6v6 | 0.00108 | **0.00216** |

**A single-stratum 3v3 design cannot reach p<0.05 at all** — its floor is 0.10.

ONE stratified cluster permutation test (`stratified_p_floor`); assignments **multiply**
across strata:

| strata | n per arm | total assignments | two-sided floor |
|---|---|---|---|
| {15,30} | 3v3 | 400 | 5.00e-03 |
| {15,30} | 4v4 | 4,900 | 4.08e-04 |
| {15,30} | 5v5 | 63,504 | 3.15e-05 |
| {15,30} | 6v6 | 853,776 | 2.34e-06 |
| {5,15,30} | 3v3 | 8,000 | 2.50e-04 |
| {5,15,30} | 4v4 | 343,000 | 5.83e-06 |
| {5,15,30} | 5v5 | 16,003,008 | 1.25e-07 |
| {5,15,30} | 6v6 | 788,889,024 | 2.54e-09 |

**Implementation constraint.** `stratified_cluster_permutation_test` enumerates the full
Cartesian product and has **no Monte Carlo fallback** (its docstring says so explicitly).
Designs at {5,15,30}x5v5 and above are not computable as the code stands. {5,15,30}x4v4
(343,000) is a one-off cost for a single analysis run and is fine.

**Validity conditions.** The stratified rank-sum assumes the effect points the **same way in
every stratum**; a design whose direction flips between $D_w$ levels violates it and the
pooled statistic becomes uninterpretable. The test also **cannot be pooled with pre-D25
data** — RUN_LEVEL_CLEAN_PRE_D25 rows are a separate tier and must never be mixed in.

## 2. Power by Monte Carlo over the repo's stratified test

**A Monte Carlo estimate under an assumed effect and variance model is not proof of a
probability.** Ratios are hypothetical scenarios, not findings.

**The permutation floor is the exact test's resolution, not its power.** A design whose floor
is 5.83e-06 has not "achieved" anything; it can merely *express* a p-value that small if the
data warrant it. Do not read a low floor as evidence.

### Implementation and timing

One stratified test, repo implementation, measured: {15,30}x3v3 = 0.3 ms (400 assignments);
{5,15,30}x3v3 = 4.0 ms (8,000); {15,30}x5v5 = 30.3 ms (63,504); {5,15,30}x4v4 = **163.8 ms**
(343,000). At 163.8 ms, 10,000 simulations of Option C would take 27.3 min per scenario cell.

So the simulation runs against a **precomputed-null** implementation, proven exactly
equivalent. Absent ties, the per-stratum rank-sum null is the multiset
`{sum(S) - e1 : S an n1-subset of {1..n}}`, which depends only on (n1, n2) and not on the
data; the joint null over independent strata is its convolution, computable once per design
instead of re-enumerated per simulation. Only the observed statistic depends on the data.
Equivalence was verified against `stratified_cluster_permutation_test` on **84 fixed-seed
cases across 7 designs**, matching `p_value` to 1e-12, the statistic to 1e-9, and
`total_assignments` exactly. Ties would invalidate the shortcut, so they are detected and
asserted absent (continuous draws make them probability-zero). Result: 46.8 us/test, ~3500x
faster; 10,000 sims in 0.47 s.

### Scenarios

**N = 10,000 simulations per scenario, seed 20260920, 3 replicates/config, total runtime
292.6 s.** Every probability carries a Clopper-Pearson 95% interval. A cell at 10000/10000 is
reported with its 95% lower bound, never as a bare "1.000".

| opt | strata | n/arm | ratio | SD x | floor | P(p<0.05) [95% CI] | P(separation) [95% CI] | med p |
|---|---|---|---|---|---|---|---|---|
| A | {15,30} | 3 | 9.0 | 1 | 5.00e-03 | 1.0000 [>=0.9996] | 1.0000 [>=0.9996] | 5.00e-03 |
| A | {15,30} | 3 | 2.0 | 25 | 5.00e-03 | 0.9997 [0.9991,0.9999] | 0.9754 [0.9722,0.9783] | 5.00e-03 |
| A | {15,30} | 3 | 2.0 | 50 | 5.00e-03 | 0.8169 [0.8092,0.8244] | 0.4241 [0.4144,0.4339] | 1.50e-02 |
| A | {15,30} | 3 | 1.5 | 25 | 5.00e-03 | 0.9147 [0.9091,0.9201] | 0.5859 [0.5762,0.5956] | 5.00e-03 |
| A | {15,30} | 3 | 1.5 | 50 | 5.00e-03 | 0.3887 [0.3791,0.3983] | 0.1093 [0.1032,0.1156] | 9.00e-02 |
| B | {5,15,30} | 3 | 2.0 | 50 | 2.50e-04 | 0.9521 [0.9477,0.9562] | 0.2753 [0.2666,0.2842] | 3.25e-03 |
| B | {5,15,30} | 3 | 1.5 | 25 | 2.50e-04 | 0.9873 [0.9849,0.9894] | 0.4465 [0.4367,0.4563] | 1.00e-03 |
| B | {5,15,30} | 3 | 1.5 | 50 | 2.50e-04 | 0.5715 [0.5617,0.5812] | 0.0359 [0.0323,0.0397] | 4.10e-02 |
| **C** | **{5,15,30}** | **4** | **9.0** | **1** | **5.83e-06** | **1.0000 [>=0.9996]** | **1.0000 [>=0.9996]** | **5.83e-06** |
| **C** | **{5,15,30}** | **4** | **2.0** | **25** | **5.83e-06** | **1.0000 [>=0.9996]** | **0.9333 [0.9282,0.9381]** | **5.83e-06** |
| **C** | **{5,15,30}** | **4** | **2.0** | **50** | **5.83e-06** | **0.9900 [0.9879,0.9919]** | **0.1346 [0.1280,0.1414]** | **2.04e-04** |
| **C** | **{5,15,30}** | **4** | **1.5** | **25** | **5.83e-06** | **0.9988 [0.9979,0.9994]** | **0.2823 [0.2735,0.2912]** | **7.58e-05** |
| **C** | **{5,15,30}** | **4** | **1.5** | **50** | **5.83e-06** | **0.7044 [0.6953,0.7133]** | **0.0075 [0.0059,0.0094]** | **1.34e-02** |
| D | {15,30} | 5 | 2.0 | 50 | 3.15e-05 | 0.9828 [0.9801,0.9853] | 0.1655 [0.1583,0.1729] | 5.67e-04 |
| D | {15,30} | 5 | 1.5 | 50 | 3.15e-05 | 0.6607 [0.6513,0.6700] | 0.0136 [0.0114,0.0161] | 1.93e-02 |

Full grid in `data/audit/power_scenarios.txt`.

### The variance input is thin, and this is the main caveat

> The between/within SDs driving every row above come from **3 COUNT and 2 TIME configs at
> $D_w$=5, with 2 replicates each, on one machine**, after excluding one host-sleep artifact.
> That is not a variance estimate anyone should lean on. `SD x25` and `x50` columns exist
> because the empirical value (between-config log SD 0.006) is so small that x1.5 and x2 are
> indistinguishable from x1 -- log(1.5) = 0.405 is ~67x that SD. Treat the x25/x50 rows, not
> the x1 row, as the planning-relevant cases.

There is **no** dispersion estimate at all for COUNT at $D_w$=15 (1 clean config) or $D_w$=30
(**0** clean configs), and TIME variance likely grows with $D_w$ via bounce count.

### Do not buy a smaller floor with more configurations

Adding configs purely to lower the floor is not justified by anything measured here. The
floor is resolution, not power, and Option C's floor is already three orders below 0.05.
**A top-up should be triggered by evidence, not by arithmetic:** specifically, if the Phase 4B
run itself shows a between-config log SD at $D_w$=15 or $D_w$=30 above roughly 0.15 (the point
at which the x25 column starts degrading separation), or if the observed COUNT/TIME direction
is inconsistent across strata -- which would independently invalidate the stratified test.
Decide that from the pilot's own dispersion, not in advance.

## 3. Design options

Run-time basis: **3.62 min/run**, measured from the Phase 1 canary (868s of continuous poller
coverage over 4 runs, including container recreate, readiness wait and warmup). Those were
all $D_w$=30; shorter $D_w$ will be faster, so these estimates are conservative.

| option | strata | configs/arm | configs | runs (3 rep) | est. time | two-sided floor |
|---|---|---|---|---|---|---|
| A | {15,30} | 3 | 12 | 36 | ~2.2 h | 5.00e-03 |
| B | {5,15,30} | 3 | 18 | 54 | ~3.3 h | 2.50e-04 |
| **C** | **{5,15,30}** | **4** | **24** | **72** | **~4.3 h** | **5.83e-06** |
| D | {15,30} | 5 | 20 | 60 | ~3.6 h | 3.15e-05 |

**Recommendation: Option C**, at a cost of ~4.3 h on one machine and 72 runs. Reasons: it is
the only option that puts $D_w$=30 back in play with real COUNT configs (Phase 2 found 0 clean
COUNT configs there, in both batches), it meets the brief's "at least 4-5 configs per arm per
$D_w$", its floor is three orders below 0.05 so the floor stops being the binding constraint,
and at 343,000 assignments it stays inside what the current implementation can enumerate.
Option A is the cheap fallback but its 2-strata/3-per-arm floor of 5.0e-03 leaves little
headroom, and it abandons $D_w$=5 entirely.

`--only-ids` lists for all four options are in the Checkpoint 3 report; Option C's is:

```
LIN-LAT-CNT-T50-W5-D5,LIN-LAT-TIM-T50-W5-D5,LIN-LAT-CNT-T50-W10-D5,LIN-LAT-TIM-T50-W10-D5,
LIN-LAT-CNT-T50-W20-D5,LIN-LAT-TIM-T50-W20-D5,LIN-LAT-CNT-T70-W10-D5,LIN-LAT-TIM-T70-W10-D5,
LIN-LAT-CNT-T50-W5-D15,LIN-LAT-TIM-T50-W5-D15,LIN-LAT-CNT-T50-W10-D15,LIN-LAT-TIM-T50-W10-D15,
LIN-LAT-CNT-T50-W20-D15,LIN-LAT-TIM-T50-W20-D15,LIN-LAT-CNT-T70-W10-D15,LIN-LAT-TIM-T70-W10-D15,
LIN-LAT-CNT-T50-W5-D30,LIN-LAT-TIM-T50-W5-D30,LIN-LAT-CNT-T50-W10-D30,LIN-LAT-TIM-T50-W10-D30,
LIN-LAT-CNT-T50-W20-D30,LIN-LAT-TIM-T50-W20-D30,LIN-LAT-CNT-T70-W10-D30,LIN-LAT-TIM-T70-W10-D30
```

## 4. Matching — what is and is not matched

Arms are matched on **threshold, $D_w$, topology, fault type and load conditions**. They are
**not** matched on window size, and no table may imply otherwise:

> `slidingWindowSize` is **calls** under COUNT_BASED and **seconds** under TIME_BASED.
> `LIN-LAT-CNT-T50-W10-D15` and `LIN-LAT-TIM-T50-W10-D15` share a label, not a quantity.

Window size is swept within each arm to span that arm's own range, and is a within-arm
covariate, never a cross-arm pairing key.

## 5. Gateway provenance at launch

The pre-existing gateway image in Phase 1 was 2 weeks old and predated the D25 fix — the
`master_dataset_v3_gateway_not_rebuilt.csv` failure mode, which has already cost this project
one dataset. Before any run:

1. `docker compose -f infra/docker-compose.yml up -d --build`
2. Record `docker images --format '{{.ID}}' infra-gateway-service`
3. Record `docker inspect gateway-service --format '{{.Image}}'`
4. **Verify (2) and (3) are the same image**, and that it was built from the current commit.
5. Record the image ID and `git rev-parse HEAD` alongside the run log.

There is no `git_commit` column in the dataset (the 48-column `master_dataset_schema.csv` stub
declares one; `runner.py` has never emitted it), so harness provenance for these runs exists
only if it is recorded out-of-band at launch.

## 6. Unique keys

The Phase 2 audit found two key collisions that silently manufactured verification. Avoid
both:

- **Never reuse canary `experiment_id`s in a sweep's key space.** The Phase 1 canary used
  `LIN-LAT-CNT-T70-W20-D30` / `LIN-LAT-TIM-T70-W20-D30` at replicates that already exist in
  `master_dataset.csv` on the same machine; only `mode` separated them.
- **Never reuse replicate indices across collection passes.** `master_dataset_d21_recollect.csv`
  holds 45 rows over 36 distinct `(experiment_id, replicate, machine_id)` keys because two
  passes on 2026-09-16 both numbered replicates 1-2. Use continuous replicate indices across
  the whole collection, or carry a pass tag.

## 7. Classification of new runs

- **VERIFIED CLEAN** = collected after the D25 pin + complete sidecar record + zero gateway
  `CLOSED_TO_OPEN`.
- **Aborted runs** (CSV row written, no sidecar, because `observer.log` is reached only on a
  completed run) are counted **separately as unverifiable**. They are neither clean nor
  tripped and must not be folded into either.

## 8. Machine options — trade-offs only, not a choice

| machine | for | against |
|---|---|---|
| `soham-local` | Ran the Phase 1 canary; provenance already established this session; no idle-stop | Laptop sleep is a real, observed failure mode here — the host-sleep artifacts (704.6s, 1703.4s) came from exactly this class of event; competes with desktop use for ~4.3 h |
| Codespace | No sleep risk from a closed lid; consistent CPU | VM restart kills the job **and** Docker (CLAUDE.md records this); historically produced the `codespace` rows that have **no sidecar in this repo**; target-rate delivery under shared CPU is unverified for this workload |
| Jay's machine (`jay-mac`) | Produced every sidecar currently in the repo, so its pipeline is known to emit them; the only machine with demonstrated end-to-end sidecar capture | Not available in this session; its two batches are the ones carrying all 20 known gateway trips, i.e. its historical runs are the contaminated ones (pre-D25, not a fault of the machine) |

Whichever is chosen, run **one machine start to finish** — the D6 calibration that would
license pooling across machines is itself 36/36 unverified. The runner is resumable by
`(experiment_id, replicate)` for `precondition_ok=True` rows, so an interrupted run can be
continued on the same machine without re-running completed work.

## 9. Output and preservation

- Sidecar goes to `data/cb_transitions.jsonl` (the **non-canary** path) — `--mode full` does
  this automatically.
- `data/cb_transitions.jsonl` is gitignored; commit it with `git add -f`, per CLAUDE.md, or
  the run is wasted.
- Commit **each machine's** sidecar separately so provenance stays attributable.
- If two canary invocations are run for any reason, **snapshot `data/canary_runs.csv` and
  `data/canary_cb_transitions.jsonl` between them** — `runner.py:1686-1691` unlinks both at
  the start of every canary invocation.

## 10. Launch checklist

1. At repo root.
2. Gateway image verified per §5; image ID and commit recorded.
3. Toxiproxy proxies created: `python experiments/fault_injector.py` — expect all 5 proxies
   created and reset.
4. Wait ~60 s, then `curl -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1/linear`
   returns **200**.
5. `--limit 1` canary: `wc -l data/canary_runs.csv` == **2** (1 header + 1 row), and its
   sidecar record shows **no** gateway `CLOSED_TO_OPEN`.
6. Snapshot the canary files before the real run (§9).
7. Launch the real sweep detached; verify the output file grows within ~2 minutes.
8. Resumable runner — re-invoking continues rather than restarting.

## 11. FANOUT is not covered

The Phase 1 canary was **LINEAR-only**. It does **not** establish gateway isolation for
FANOUT. Before any FANOUT sweep, a dedicated FANOUT canary is required:

- freshly rebuilt gateway image, verified per §5;
- a FANOUT route actually exercised;
- **all** gateway breakers that route touches monitored (LINEAR exercised only
  `orderServiceCB`; `inventoryServiceCB` and `paymentServiceCB` recorded zero events, so they
  are untested, not shown clean);
- the same 1 s state polling plus `bufferedCalls`, plus the sidecar check;
- complete observation-horizon coverage;
- zero gateway `CLOSED_TO_OPEN`.

**If that is not verified, stop** — do not run a FANOUT sweep on the strength of the LINEAR
canary.
