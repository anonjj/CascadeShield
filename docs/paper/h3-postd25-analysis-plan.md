# H3 post-D25 analysis plan — PRE-REGISTRATION

**Frozen on commit.** Nothing in this file may change after Phase 4B data are seen. Its
commit SHA goes in the launch manifest and must predate the first run's `run_timestamp`.
Any deviation discovered later is reported as a deviation, not edited in.

Design decided: **Option C** — LINEAR + LATENCY, `soham-local`, strata $D_w \in \{5,15,30\}$,
4 configs per arm per stratum = 24 configs x 3 replicates = **72 runs**.

---

## 1. Primary metric

**PRIMARY: coarse `time_to_recover`** (CSV column).
**SECONDARY: precise `half_open_to_closed`** (derived from sidecar STATE_TRANSITION timestamps).

Reason. `time_to_recover` is recorded directly on every row by a single code path, is
defined identically for both arms, and — since PR #57 (`be92a37`, 2026-09-16) — is bounded
by a deadline that scales with $D_w$ (`wait + max(30, 2*wait)`) rather than a flat `+10s`,
so it is no longer differentially truncated at high $D_w$. The precise metric is strictly
better instrumented but is only defined when a real `HALF_OPEN_TO_CLOSED` transition lands
in the sidecar, which makes its availability itself outcome-dependent; conditioning the
primary analysis on an outcome-dependent observation is the stronger threat to validity.
The precise metric is reported alongside as a sensitivity check and any disagreement between
them is reported explicitly.

## 2. Primary test

`stratified_cluster_permutation_test` from `analysis/exact_tests.py` — **the same
implementation the power simulation used** — with:

* strata = $D_w \in \{5, 15, 30\}$ (blocking factor, one test, not one per stratum),
* unit = the **configuration** (`experiment_id`), never the row,
* two-sided.

The exact two-sided floor for the planned 4v4-per-stratum, 3-stratum design is **5.83e-06**
(343,000 assignments). The floor is printed next to every p-value. **The floor is the exact
test's resolution, not power or evidence.**

Secondary/sensitivity test: `cluster_permutation_rank_test` (permutes whole configurations
but ranks raw rows). It supports no stratification, so it is run per stratum and reported as
a sensitivity check only. If the two disagree in direction or significance, that is reported.

## 3. Config-level value rule — computationally defined

The test consumes exactly **one value per configuration**. `time_to_recover` is in seconds.
Let a configuration have 3 replicate rows after the §4 exclusions are applied.

| case | config value | notes |
|---|---|---|
| 3/3 replicates uncensored | arithmetic **mean** of the 3 values | the case the power simulation assumed |
| 2/3 uncensored (1 censored) | mean of the **2 uncensored** values; config is **flagged censored-partial** | see §3.1 — this is a deviation from the simulated model |
| 1/3 uncensored | the **single** uncensored value; config flagged censored-partial | same |
| 0/3 uncensored (all censored) | **config is EXCLUDED** from the primary test | cannot produce a value without a censoring-aware estimator |
| one replicate excluded by §4 (host sleep / gateway trip / abort) | mean of the **surviving** replicates, by the rows above | exclusion is applied first, then the row above is chosen by how many remain |
| all 3 replicates excluded by §4 | **config is EXCLUDED** | |
| exact tie between two configs' values | `_ranks()` assigns **average ranks** (already the implementation's behaviour); no tie-break is applied | ties are recorded and reported |

"Censored" means `half_open_probe_timed_out == True` for that row.

**If a stratum ends with fewer than 4 configurations in an arm:** the analysis proceeds with
the reduced $n$ and the **recomputed** floor for the actual arm sizes is reported (never the
planned 5.83e-06). If a stratum ends with **0** configurations in either arm it carries no
label information, is **excluded** from the stratified test, and the test is re-run on the
remaining strata with the floor recomputed. That exclusion is reported as
"insufficient clean data in stratum $D_w$=N", **never** as a null result. If fewer than two
strata survive, the stratified test is not run at all and only descriptives are reported.

### 3.1 Power simulation applicability

The power simulation assumed one value per configuration, no ties, and no censoring.

* If, after §4 exclusions, **every** retained configuration is 3/3 uncensored and no ties
  occur, the simulated scenarios apply as written.
* **Otherwise — any censored-partial configuration, any excluded configuration, or any tie —
  write: `Power simulation applicability: NOT ESTABLISHED`.** The old numbers are not carried
  over. Re-establishing it requires re-running the simulation with the realised design:
  the actual per-arm, per-stratum configuration counts; a replicate-count distribution
  matching the realised one (so a config summarising 2 replicates has the variance of a
  2-replicate mean, not a 3-replicate mean); and, if a censoring-aware value rule is ever
  adopted instead of the table above, a null model that generates censoring at the realised
  rate. That re-simulation is a new artifact with its own seed and N, reported as such.

## 4. Exclusion rules

Applied in this order, before any value is computed:

1. **Aborted runs** — `precondition_ok != True` (READINESS_TIMEOUT, PRECONDITION_FAIL).
   These carry no measurement and have no sidecar record. Counted separately as
   **unverifiable**, never as clean and never as tripped.
2. **Gateway `CLOSED_TO_OPEN`** — any run whose sidecar record contains a transition with
   `service == "gateway"` and `state_transition == "CLOSED_TO_OPEN"` is excluded.
3. **Poller coverage failure** — any run not VERIFIED_CLEAN under §6 is excluded from the
   primary analysis and reported in its own category.
4. **Host-sleep / implausible-duration artifacts** — a row is excluded when
   `time_to_recover > half_open_probe_deadline_s(wait_duration)`, i.e.
   **`3 * wait_duration + 60`** seconds (`experiments/breaker_observer.py`,
   `half_open_probe_deadline_s`). Derivation: it is the harness's own hard ceiling for the
   half-open probe loop, calibrated against 26 real closures that all landed 1.8-2.8s after
   entering HALF_OPEN; a value beyond it cannot be a real recovery. Concretely: **75s** at
   $D_w$=5, **105s** at $D_w$=15, **150s** at $D_w$=30. This rule is what catches the known
   704.6s and 1703.4s laptop-sleep rows.
5. **Lambda deviation** — rows with `lambda_deviation_flag == True` (achieved arrival rate
   missing target by more than `LAMBDA_DEVIATION_THRESHOLD`) are excluded from the primary
   analysis and reported separately. `lambda_deviation_flag` is `None`, not `False`, when the
   rate could not be measured; `None` is treated as **not excluded but flagged**, since
   "couldn't measure" is not "deviated". The threshold is frozen at the runner's own
   value and is not re-tuned after the smoke run — see **§9**.

Every exclusion is counted and reported by arm x stratum. Exclusion counts are reported
before any p-value.

## 5. Gateway observation horizon

Stated now, before any data:

```
start = fault_injected_at                      (sidecar record for that run)
end   = fault_cleared_at                       (sidecar record for that run)
      + time_to_recover                        (CSV column for that run)
      + 5 s                                    (HORIZON_MARGIN_S)
```

`time_to_recover` is measured from `cb_open_at`, not from `fault_cleared_at`, so adding it to
`fault_cleared_at` **over-covers**. That is deliberate: the horizon gates a coverage
*requirement*, so erring long makes the requirement stricter, not looser. A second of the
horizon counts as covered if some poll tick lies within **1.6 s** of it.

## 6. Verification rule for a run

A run is **VERIFIED_CLEAN** only if **all** hold:

* its sidecar record shows no gateway `CLOSED_TO_OPEN`, **and**
* every polled gateway state inside the §5 horizon is `CLOSED`, **and**
* the independent poller has **complete coverage** of that horizon.

**Incomplete coverage means NOT_VERIFIED even when the sidecar is clean.** Four failure modes
are distinguished and reported separately: `POLL_ERROR`, `MISSING_TICK`, `GATEWAY_NOT_CLOSED`,
`POLLER_STOPPED` (`analysis/gateway_poll_verify.py`).

Gateway status comes **only** from the sidecar and the independent poller. `cb_state_pre` is
a pre-load snapshot and is not evidence about mid-run state. The D21 censoring columns record
half-open probe censoring and are not evidence about gateway trips.

The poller is itself a load source on the gateway. Its duty cycle is pre-registered in
**§11** so that load is identical for both arms.

## 7. Validity condition — checked before any p-value is quoted

The stratified rank-sum statistic is only interpretable if the effect points the **same way
in every stratum**. Before quoting any p-value:

1. compute each stratum's own signed statistic (the implementation already returns it
   per-stratum as `StratumInfo.observed_statistic`);
2. report the sign for all three strata;
3. **if the signs are not all the same, the pooled p-value is not quoted.** The per-stratum
   results are reported instead, with the inconsistency stated as the finding.

This check is reported whether it passes or fails.

## 8. Claim scope

The inference this design supports, stated in full:

* **LINEAR topology only, LATENCY fault only.** Nothing here speaks to FANOUT or CRASH.
* **One machine** (`soham-local`), so no cross-machine generalisation. The D6 calibration
  that would license pooling machines is itself unverified (Phase 2).
* **Database state is not reset between runs.** `update_containers()` force-recreates the six
  application services but not `postgres` or `dynamodb-local`, so accumulated DB state and
  connection-pool state persist across all 72 runs.
* **Configuration coverage is T50 at window sizes 5/10/20 plus a single T70/W10 probe per
  stratum.** The inference is therefore mainly **COUNT vs TIME across window sizes at T50**;
  the T70 probe is one point, not a threshold sweep, and no threshold effect is claimed.
* **Window size is not matched across arms** — `slidingWindowSize` is *calls* under
  COUNT_BASED and *seconds* under TIME_BASED. Arms are matched on threshold, $D_w$, topology,
  fault type and load conditions only.
* **Per-stratum Kaplan-Meier medians are descriptive secondary output only.** No inferential
  claim is made from them, and no per-cell p-value is reported as a result.
* Results apply to the post-D25 gateway configuration only and are never pooled with
  pre-D25 rows, including the `RUN_LEVEL_CLEAN_PRE_D25` tier.

---

*Sections 9-11 were added by the 2026-09-20 amendment, before any Phase 4B run. See the
launch manifest for the superseded and final commit SHAs.*

## 9. Lambda gate — frozen threshold, applied identically to all 72 runs

The arrival-rate gate is the **runner's own** `LAMBDA_DEVIATION_THRESHOLD`, imported from
`experiments/constants.py`, whose value is **0.15**. It is frozen at that value for the whole
of Phase 4B and is **not** adjusted after the smoke run's observed lambda, nor after any part
of the sweep. Tuning a gate to the data it will gate is how an exclusion rule becomes a
result.

The implemented test is `compute_lambda_deviation_flag` (`experiments/runner.py:539`):

```
lambda_deviation_flag = abs(lambda_achieved - lambda_target) / lambda_target > 0.15
```

**It is two-sided.** A row is retained iff

```
0.85  <=  lambda_achieved / lambda_target  <=  1.15
```

so over-delivery beyond +15% is excluded on the same footing as under-delivery beyond -15%.
(A one-sided reading, `lambda_achieved / lambda_target >= 0.85`, is the lower half of this
rule only and is **not** what the harness computes or what this plan applies.)

Consequences, all pre-registered:

* `lambda_target` for every Phase 4B run is `LOAD_RATE_RPS` = 10 req/s (`runner.py:270`);
  it is not swept.
* The gate is applied **identically to all 72 runs**, both arms, all three strata. There is
  no per-arm, per-stratum or per-window-type threshold.
* The flag is computed by the runner at write time and read from the CSV column; the
  analysis does not recompute it, so the gate cannot drift between collection and analysis.
* `None` (rate unmeasurable) remains "not excluded but flagged", per §4 rule 5.
* If the smoke run's lambda deviates, that is information about the **host**, to be resolved
  before the sweep launches (or accepted and reported). It is never grounds for moving the
  threshold.

## 10. Re-collection and quarantine

Aborted, orphaned and gate-failing runs are re-collected at **the same
`(experiment_id, replicate)` key**, and only after that key's existing row has been
**quarantined** — moved out of the dataset into `data/audit/phase4b_orphans_<timestamp>.csv`
by `analysis/phase4b_reconcile.py --apply`, which also writes a hashed backup of the CSV.
Nothing is hand-edited, and nothing is overwritten in place.

Quarantine is what makes re-collection possible at all:
`resumable_runner.load_completed()` keys resumption on `(experiment_id, replicate)` and
treats any row with `precondition_ok == "True"` as done, so a row that is present but
unusable permanently blocks its own cell. Removing the row is the only thing that makes the
runner reschedule that key.

Four quarantine classes, each counted separately and never merged:

| class | meaning |
|---|---|
| `ORPHAN_ROW_ABORTED` | `precondition_ok != True`; no sidecar record was ever written (`observer.log` is reached only on a completed run). The §4.1 **unverifiable** category |
| `ORPHAN_ROW` | the run completed but no sidecar record matches it on experiment_id + replicate + machine_id + mode + time window |
| `DUPLICATE_KEY` | two or more rows share `(experiment_id, replicate)`; which one is real cannot be determined, so **all** of them are quarantined and the cell is re-collected |
| gate-failing | excluded by §4 rules 2-5 (gateway trip, poller coverage, implausible duration, lambda). Re-collected the same way |

**The number of runs re-collected is reported**, by arm x stratum x class, alongside the
exclusion counts required by §4 and before any p-value. A re-collected key is reported as
re-collected; it is not silently presented as a first-attempt measurement. The sidecar is
append-only and is **never** rewritten by quarantine, so the orphaned record stays on record
as evidence and is excluded by the post-sweep check's in-scope filter rather than deleted.

The sweep's `--seed` is unchanged across a re-collection, so the run order of the remaining
cells is the one the original shuffle assigned.

## 11. Poller duty cycle is constant across arms

`analysis/gateway_poll_verify.py poll` runs as **one continuous session for the whole
sweep** — started before the first run and stopped after the last — at a fixed ~1 s cadence
against the gateway's actuator endpoints. It is not started or stopped per run, per arm or
per stratum.

This is a design requirement, not an implementation detail. The poller issues two HTTP GETs
per tick against the gateway, so it is itself a (small) load source on the measured service.
If it ran only during COUNT_BASED runs, or only for the runs where a trip was suspected, its
load would be **confounded with the arm**, and any COUNT-vs-TIME difference would be partly
a difference in how hard the gateway was being scraped. Running it throughout makes that load
a constant of the experiment, shared identically by both arms and all three strata.

Two consequences that are accepted in advance:

* The poller also covers the inter-run container-recreate gaps, during which the gateway JVM
  is down and ticks will show errors. Those seconds are **outside** every run's §5 horizon,
  so they cannot make a run `NOT_VERIFIED`; this is the same re-cut the Phase 1 canary
  README records, applied prospectively rather than after the fact.
* A poller restart mid-sweep breaks the "one continuous session" property. If it happens it
  is recorded, the affected runs are classified `POLLER_STOPPED` by §6, and they are
  re-collected under §10 rather than analysed.
