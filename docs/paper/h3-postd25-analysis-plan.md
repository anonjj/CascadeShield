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

"Censored" means `half_open_probe_timed_out == True` for that row. The primary rule above —
**drop** censored replicates — is paired with a pre-registered imputation sensitivity analysis
in **§3.2**, because dropping them is not neutral.

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

### 3.2 Censoring sensitivity — impute at the probe deadline *(2026-09-20 amendment)*

**Direction of the primary rule's bias, stated before any data.** A censored replicate is
right-censored: its true `time_to_recover` is **at least** the probe deadline, it is simply
unobserved beyond it. Those are the largest values in the distribution. Dropping them means
the config mean is taken only over replicates that recovered *before* the deadline, i.e. over
the truncated lower part of the distribution. **The primary rule therefore biases every
affected config's mean DOWNWARD — recovery looks faster than it was.** The bias grows with
that config's censoring rate, so if censoring is differential between arms, the more-censored
arm's means are pulled down further, which can manufacture *or* mask an arm difference. This
is not a small-print caveat; it is the reason the sensitivity analysis below is mandatory
rather than optional.

**The sensitivity rule.** Re-run the entire primary analysis with one change: each censored
replicate takes the value `half_open_probe_deadline_s(wait_duration)` = `3 * wait_duration
+ 60` — **75 s** at $D_w$=5, **105 s** at $D_w$=15, **150 s** at $D_w$=30 — and the config
mean is the arithmetic mean of all **3** replicates. Nothing else changes: same test, same
strata, same unit, same §4 exclusions, same §7 validity check.

Why the deadline and not something larger. It is the **smallest value consistent with the
censoring event** — the run is known to have not closed by then, and nothing in the data
bounds it above. So:

```
drop-censored mean   <=   impute-at-deadline mean   <=   true mean
```

with equality throughout only when nothing is censored. The proof of the first inequality is
immediate: every uncensored value is strictly below the deadline, so replacing a dropped
replicate with the deadline can only raise the mean. **Both rules are lower bounds on the
truth; the imputed one is the tighter of the two.** Neither is unbiased, and no claim is made
that the imputed value is the replicate's real recovery time.

Three consequences, all pre-registered:

1. **Configs excluded by the primary rule re-enter.** A 0/3-uncensored config is EXCLUDED by
   the §3 table but takes the value `3 * wait_duration + 60` here. Per-arm, per-stratum $n$
   therefore differs between the two analyses, so **the sensitivity analysis reports its own
   recomputed exact floor**, never the primary's.
2. **Ties are expected and are not tie-broken.** Within a stratum the imputed value is a
   single constant, so two configs with the same censoring pattern can land on identical
   values. `_ranks()` assigns average ranks, as §3 already specifies. Ties are counted and
   reported, and §3.1's `Power simulation applicability: NOT ESTABLISHED` applies to the
   sensitivity analysis whenever they occur.
3. **Both results are reported side by side, always** — not only when they disagree. If they
   disagree in direction or in significance at the pre-registered level, **that disagreement
   is itself the reported finding**, and neither result is presented as the answer. The
   primary remains the primary; the sensitivity does not silently replace it.

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
   value and is not re-tuned after the smoke run — see **§9**. What the rate is measured
   over, and why it is a noisier instrument in the COUNT arm, is **§9.1**; the per-arm
   exclusion reporting and the trigger for a no-lambda-exclusion sensitivity analysis are
   **§9.2**.

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

### 5.1 Fallback when `time_to_recover` is null *(2026-09-20 amendment)*

A blank `time_to_recover` means the run never observed a closure, so there is no measured
recovery interval to add. **The horizon then uses `half_open_probe_deadline_s(wait_duration)`
= `3 * wait_duration + 60` in its place** — **75 s** at $D_w$=5, **105 s** at $D_w$=15,
**150 s** at $D_w$=30:

```
end = fault_cleared_at
    + (time_to_recover  if measured  else  3 * wait_duration + 60)
    + 5 s
```

Why this value and not 0. `analysis/gateway_poll_verify.py` previously substituted `0.0`,
which **shortened** the horizon to `fault_cleared_at + 5 s` — making the coverage requirement
trivially easy to satisfy for exactly the runs whose evidence is weakest, and in the opposite
direction to the "err long" rule stated above. The deadline is the longest interval the
harness could still have been watching for a closure, so substituting it keeps the requirement
strictest where the measurement failed. It is the same constant §4 rule 4 already uses, so no
new number enters the plan.

If `time_to_recover` is null **and** `wait_duration` is unusable, the horizon is **undefined**
and the run is `NOT_VERIFIED`. It is never treated as a zero-length recovery.

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

*Sections 9-11 were added by the first 2026-09-20 amendment, and §3.2, §5.1, §9.1, §9.2 and
§10.1 by the second, both **before any Phase 4B run**. See the launch manifest for the
superseded and final commit SHAs. Nothing above was rewritten: the amendments add rules and
state, in place, which earlier text they qualify.*

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

### 9.1 What `lambda_achieved` is actually measured over *(2026-09-20 amendment)*

Established from the code before any data, because the answer is not symmetric between arms.

`lambda_achieved` is computed **only from the fault-phase load call** (`runner.py:1326`); the
20-request pre-fault baseline call at `runner.py:1259` discards its rate. Inside
`generate_load` (`runner.py:656-663`):

```
span             = last dispatch timestamp - first dispatch timestamp
lambda_achieved  = (n_dispatched - 1) / span        ==  1 / mean inter-dispatch interval
lambda_cv        = stdev(intervals) / mean(intervals)
```

`n_dispatched` and the dispatch window come from `compute_load_plan`, which sizes the two arms
**completely differently** — COUNT_BASED by call count, TIME_BASED by seconds. At
`LOAD_RATE_RPS` = 10 req/s (`interval_s` = 0.1 s) the Option C grid gives:

| arm | configs | requests | dispatch window | intervals in the estimate |
|---|---|---|---|---|
| COUNT, W=5 and W=10 | 8 of 12 | `max(3W, 15, 40)` = **40** | **4.0 s** | **39** |
| COUNT, W=20 | 4 of 12 | **60** | **6.0 s** | **59** |
| TIME | all 12 | `10 * (W + D_w + 10)` = **200-600** | **20-60 s** | **199-599** |

**So the two arms' lambda estimates are not comparable instruments.** Since
`lambda_achieved` = 1/(mean of $n-1$ intervals), its relative standard error is
$\mathrm{CV}/\sqrt{n-1}$:

| arm | relative SE per unit of `lambda_cv` |
|---|---|
| COUNT | **0.130 - 0.160** |
| TIME | **0.041 - 0.071** |

**The COUNT arm's rate estimate is 2.3x to 3.9x noisier than the TIME arm's, for identical
underlying jitter.** Two mechanisms make it worse, and one makes it better — all three are
recorded here because the net sign cannot be predicted:

* **(worse) `span` is a difference of two order statistics.** One delayed dispatch at either
  end moves it. A single 0.5 s stall shifts `lambda_achieved` by **-11.4%** at $n$=40 (three
  quarters of the way to the 15% gate on its own) versus **-2.5%** at $n$=200 and **-0.8%**
  at $n$=600. A stall the length of one fault latency (3.0 s) shifts it **-43%** at $n$=40 and
  only **-13.1%** at $n$=200.
* **(worse) the gate is tight in absolute terms.** Tripping it needs a mean inter-dispatch
  interval above 117.65 ms or below 86.96 ms — i.e. a sustained **+17.6 ms / -13.0 ms** per
  interval. Windows' default timer granularity is 15.6 ms, and `time.sleep(0.1)` overshoots
  one-sidedly, so this is not a comfortable margin for either arm — but only COUNT lacks the
  sample size to average it away.
* **(better) COUNT's two smallest configs cannot queue at all.** `concurrency` is
  `ceil(10 * 3.0 * 1.5)` = **45** workers, and the W=5/W=10 COUNT configs dispatch only **40**
  requests, so no request ever waits for a free worker. Every other config in the grid (COUNT
  W=20 at 60 requests, all 12 TIME configs at 200-600) exceeds the pool and *can* have
  dispatch timestamps deferred by thread-pool queueing, which is the mechanism
  `lambda_achieved` exists to detect. **8 of 12 COUNT configs are structurally immune to the
  failure the gate looks for; all 12 TIME configs are exposed to it.**

The **systematic** component (mean sleep overshoot) is the same in both arms — same
`interval_s`, same loop — so it does not by itself create a differential. The **sampling**
component does, in the COUNT arm's disfavour; the **queueing exposure** does, in the TIME
arm's disfavour. Which dominates is an empirical question this design cannot settle in
advance, which is exactly why §9.2 exists rather than a prediction.

### 9.2 Lambda exclusion reporting and the sensitivity trigger *(2026-09-20 amendment)*

**(a) Exclusion counts by arm are reported before any p-value.** For each arm, and for each
arm x stratum cell, report: runs excluded by rule §4.5 (`lambda_deviation_flag == True`), runs
flagged-but-retained (`lambda_deviation_flag` is `None`), and runs retained clean — as counts
and as rates over the 36 runs per arm. These appear in the results **above** the test output,
not in an appendix.

**(b) The sensitivity trigger, with the margin stated now.** Let $r_\mathrm{C}$ and
$r_\mathrm{T}$ be the lambda-exclusion rates in the COUNT and TIME arms, each over that arm's
36 runs. A **sensitivity analysis with rule §4.5 switched off entirely** — every run retained
regardless of `lambda_deviation_flag`, everything else identical — is run and reported
alongside the primary whenever **either**:

> **(i) $|r_\mathrm{C} - r_\mathrm{T}| > 0.10$** — a difference of more than 10 percentage
> points, equivalently **4 or more runs out of 36**; **or**
>
> **(ii) $\max(r_\mathrm{C}, r_\mathrm{T}) > 0.20$** — either arm losing more than
> 7 of its 36 runs, whatever the balance.

Why 10 points. The resolution of a 36-run arm is 1/36 = 2.78 points, so the margin must be a
small multiple of that to mean anything. Under a null of equal true exclusion probability
$p \le 0.10$ in both arms, the standard deviation of $r_\mathrm{C} - r_\mathrm{T}$ is at
most $\sqrt{2p(1-p)/36}$ = 7.07 points, so a 10-point margin is about 1.4 SD: **it will fire
occasionally on noise, and that is the intended direction of error.** The sensitivity analysis
costs a paragraph; a differential exclusion that silently reshapes the comparison costs the
result. Criterion (ii) exists because a large *balanced* exclusion rate means rule §4.5 is
doing a lot of work in both arms, which is worth bounding even when it is doing it evenly.

Both criteria are evaluated and their values reported **whether or not** either fires. If a
sensitivity analysis is triggered, it is reported next to the primary with its own recomputed
exact floor (retaining excluded runs changes the per-arm, per-stratum configuration counts),
and **any disagreement in direction or significance is reported as the finding** — the primary
is not quietly preferred.

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

### 10.1 Re-collection cap *(2026-09-20 amendment)*

**At most 2 re-attempts per `(experiment_id, replicate)` key — 3 attempts in total.**

* **Every attempt is counted and reported**, per key, including keys that succeeded on the
  first attempt. The ledger is derived, not kept by hand: one quarantine event writes exactly
  one `data/audit/phase4b_orphans_<timestamp>.csv`, so a key's attempt number is
  `1 + (number of distinct orphans files it appears in)`. Two rows of one `DUPLICATE_KEY` pair
  live in the same file and therefore consume **one** re-attempt, not two.
* **A key still unusable after 2 re-attempts stays EXCLUDED and is reported as such** — class
  `AT_REATTEMPT_CAP`. It is not quarantined a third time, not re-collected, and never quietly
  retried. Its exclusion is reported alongside the §4 exclusion counts, by arm x stratum, with
  the reason each attempt failed.
* `analysis/phase4b_reconcile.py` enforces this: a capped key is classified before any other
  unusable-row class, so it cannot be re-collected by way of `DUPLICATE_KEY` or `ORPHAN_ROW`,
  and its row is **left in the CSV** — which is what stops the runner rescheduling it, since
  `load_completed()` treats a `precondition_ok=="True"` row as done.

**One honest limitation.** That mechanism does not cover a capped key whose row has
`precondition_ok != True`: `load_completed()` only skips `True` rows, so a resume **would**
retry it. The runner has no per-attempt state and is read-only for this phase, and neither
editing the dataset nor editing the runner is in scope. Such keys are therefore reported to
the operator with an explicit warning, and the cap is enforced by stopping the resume. If a
capped aborted key is nevertheless re-run, that is recorded and reported as a **deviation**,
not absorbed.

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
