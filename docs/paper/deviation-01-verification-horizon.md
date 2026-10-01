# DEVIATION 01 — the §5 observation horizon makes the TIME arm unverifiable

**Status: recorded during collection, before any verification count was computed under any
alternative horizon.** This note is committed first, on purpose. Everything it proposes is
stated here before the numbers that would make one choice look better than another exist.

The pre-registration (`docs/paper/h3-postd25-analysis-plan.md`, frozen at
`3e4ad1e5d0596883bbd35604828d0d2db39a9eb2`) is **not edited**. §7 of this note proves it.

---

## 1. What was found, and when

Found on **2026-09-21**, during the Phase 4B sweep launched at `2026-09-21T17:08:03Z`, at
**run 20 of 72**, about **45 minutes** into a ~2-hour collection. The sweep was left running;
nothing was started, stopped or restarted.

**Every TIME run was `NOT_VERIFIED`. Every COUNT run was `VERIFIED_CLEAN`.** Perfectly
correlated with the arm — which is the one way a verification rule must never fail, because
§4 rule 3 excludes every run that is not `VERIFIED_CLEAN` from the primary analysis.

At the snapshot used for this note (19 reconciled rows):

| arm | 1 aborted | 2 gw trip | 3 not VERIFIED | 4 implausible | 5 lambda | clean |
|---|---|---|---|---|---|---|
| COUNT | 0 | 0 | **0** | 0 | 0 | **9** |
| TIME | 0 | 0 | **10** | 0 | 0 | **0** |

Rule 3 was the only rule firing, in one arm only.

**No outcome column was read.** `time_to_recover` and `wait_duration` were used *only* as
inputs to the §5 horizon arithmetic and the §4.4 threshold test; no value from
`time_to_recover`, `time_to_open`, `blast_radius`, `error_rate`, `throughput_loss`,
`real_blast_radius`, `leg_failure_rates`, `half_open_probe_timed_out`, `lambda_achieved`,
`lambda_cv`, `effective_horizon`, `readiness_wait_s`, `warmup_duration_s`, `cb_state_pre` or
`buffered_calls_pre` was printed, inspected or summarised, then or since.

**It is not a contamination finding.** At the same snapshot:

* **0** gateway transitions of any kind across all post-baseline sidecar records,
* **0** gateway `CLOSED_TO_OPEN`,
* **0** non-CLOSED gateway states across ~2,400 poll ticks,
* **0** orphan rows, **0** duplicate keys, **0** keys at the re-attempt cap.

The data being collected is clean. The rule that decides whether we are *allowed to say so*
is what fails.

---

## 2. Mechanism, with the evidence

### 2.1 The runner's timestamp order

Established by reading `experiments/runner.py` (read-only; the file was not modified while the
runner was live):

| # | line | event |
|---|---|---|
| 1 | `runner.py:1265` | `fault_injected_at = _now_iso()` — before the load |
| 2 | `runner.py:1384` | `fault_cleared_at = _now_iso()` — fault removed |
| 3 | `runner.py:1402` | `observer.observe_recovery(...)` — the only open-ended phase |
| 4 | `runner.py:1442` → `:1125` | `log_results(...)` stamps `run_timestamp` — **the run's own end** |
| 5 | `runner.py:1449` | `observer.log(...)` appends the sidecar record |
| 6 | next run | `update_containers()` force-recreates the six services — **the gateway JVM goes down on purpose** |

So the run is *over* at step 4. Everything after it belongs to the next run's setup.

### 2.2 The horizon reaches past step 4 — by an amount that differs between arms

§5 sets `end = fault_cleared_at + time_to_recover + 5 s`, and deliberately over-covers:
`time_to_recover` is measured from `cb_open_at`, not from `fault_cleared_at`, so adding it to
`fault_cleared_at` adds more than the real recovery interval. Measured over the 19 rows, the
over-coverage past `fault_cleared_at` is:

| arm | over-coverage past `fault_cleared_at` |
|---|---|
| COUNT | **11.6 – 21.6 s** |
| TIME | **28.1 – 70.3 s** |

COUNT's over-coverage expires while the run is still finishing. TIME's does not — it runs on
into step 6.

### 2.3 The failing seconds are the next run's container recreate

The failing ticks carry `RemoteDisconnected`, `ConnectionAbortedError` and `URLError` — the
gateway JVM going away, not a slow or overloaded gateway:

```
753  circuitbreakers: RemoteDisconnected      39  prometheus: URLError
753  prometheus:      RemoteDisconnected      38  prometheus: ConnectionAbortedError
 35  circuitbreakers: URLError                35  circuitbreakers: ConnectionAbortedError
```

And for **every one of the 11 TIME runs**, the first in-horizon error tick lands **8–9 s after
that run's own `run_timestamp`**:

```
TIME  LIN-LAT-TIM-T50-W10-D5   rep3   first in-horizon error at run_timestamp +8s
TIME  LIN-LAT-TIM-T50-W20-D30  rep1                                          +9s
TIME  LIN-LAT-TIM-T50-W20-D15  rep1                                          +9s
TIME  LIN-LAT-TIM-T50-W10-D30  rep2                                          +9s
TIME  LIN-LAT-TIM-T50-W5-D30   rep1                                          +9s
TIME  LIN-LAT-TIM-T50-W20-D5   rep2                                          +9s
TIME  LIN-LAT-TIM-T50-W5-D5    rep1                                          +9s
TIME  LIN-LAT-TIM-T50-W5-D15   rep2                                          +9s
TIME  LIN-LAT-TIM-T50-W10-D15  rep2                                          +9s
TIME  LIN-LAT-TIM-T50-W20-D30  rep3                                          +8s
TIME  LIN-LAT-TIM-T50-W5-D5    rep3                                          +9s
```

Not one of them falls before the run ended. Every failing second is a second in which the run
being verified had already finished and the gateway had been switched off by the harness.

Per-run, the issues were `MISSING_TICK, POLL_ERROR`, ~10 uncovered seconds each, 88 uncovered
seconds in total across the 10 failing runs.

### 2.4 Error-tick density

```
inside run horizons :  160 error ticks / 1040 ticks   (15.4 %)
outside             :  671 error ticks / 1241 ticks   (54.1 %)
```

The 54.1 % outside is the recreate windows behaving exactly as §11 predicted. The 15.4 %
inside is the tails that §11 said could not exist.

---

## 3. Which pre-registered statements this falsifies

**§11, falsified for the TIME arm.** It states:

> *"The poller also covers the inter-run container-recreate gaps, during which the gateway JVM
> is down and ticks will show errors. Those seconds are **outside** every run's §5 horizon, so
> they cannot make a run `NOT_VERIFIED`."*

True for COUNT. False for TIME, in 11 of 11 cases observed. §11 asserted a property of the
horizon that was never checked against the horizon's own arithmetic.

**§5's reasoning, falsified in its general form.** It states:

> *"…adding it to `fault_cleared_at` **over-covers**. That is deliberate: the horizon gates a
> coverage *requirement*, so erring long makes the requirement stricter, not looser."*

"Stricter" is true but incomplete. Erring long makes the requirement stricter **by an amount
proportional to `time_to_recover`**, and `time_to_recover` is the dependent variable. So the
strictness of the verification gate is a function of the outcome being measured, and — because
the two arms differ in that outcome — the gate is **differentially strict between arms**. A
verification rule whose severity depends on the measurement it is verifying cannot do its job.
That is the real defect; the recreate window is only what makes it bite.

Note this is a *structural* statement about the rule, not a claim about which arm recovers
faster. It follows from the horizon formula and the observed over-coverage ranges alone.

---

## 4. The corrected rule

```
start = fault_injected_at                                  (sidecar record)         [unchanged]
end   = min(
          fault_cleared_at + (time_to_recover, or the §5.1 fallback) + 5 s,   [the §5 horizon]
          run_timestamp                                    (CSV column)  [the run's own end]
        )
```

Coverage tolerance is **1.6 s, unchanged** (`COVERAGE_TOLERANCE_S`). §5.1's fallback is
unchanged: a null `time_to_recover` uses `half_open_probe_deadline_s(wait_duration)` =
`3 * wait_duration + 60`, and a null `time_to_recover` with no usable `wait_duration` leaves
the horizon undefined → `NOT_VERIFIED`.

### 4.1 Verification that `run_timestamp` is the right bound

**It is written after `observe_recovery`.** `observer.observe_recovery(...)` is `runner.py:1402`;
`log_results(...)`, which stamps `run_timestamp`, is `runner.py:1442`. So the bound cannot
truncate the recovery observation it is meant to contain.

**It uses the same clock and timezone as the poll ticks.**

| | source | expression |
|---|---|---|
| `run_timestamp` | `runner.py:1125` | `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())` |
| `fault_injected_at` / `fault_cleared_at` | `runner.py:1028` (`_now_iso`) | same call |
| poll tick `t` | `gateway_poll_verify.py:105` | `time.time()` |
| poll tick `iso` | `gateway_poll_verify.py:108` | `dt.datetime.utcfromtimestamp(t0)` |

Both sides read the same process-independent system wall clock through Python's `time` module,
and both express it in **UTC** — `time.gmtime()` on one side, `utcfromtimestamp` on the other.
`parse_ts` maps the literal `Z` to `+00:00`, so no timezone conversion is involved anywhere.

**One bounded asymmetry, disclosed rather than corrected.** `strftime` **truncates** to the
second; the poll tick keeps a float epoch. So the recorded `run_timestamp` can be up to **1.0 s
earlier** than the instant `log_results` actually ran, which makes the corrected horizon up to
1.0 s *shorter* than the true run end — i.e. very slightly **looser**, not stricter. It is
bounded by 1 s against a coverage tolerance of 1.6 s. No compensating constant is added,
because choosing a constant now, with the failing runs already identified, is exactly the kind
of tuning this note exists to prevent.

### 4.2 Justification

* **No load is sent after the run ends.** `generate_load` has returned, the fault is cleared,
  and `observe_recovery` has finished, before `run_timestamp` is stamped. There is nothing left
  that could drive the gateway breakers.
* **The next recreate takes the gateway down on purpose.** `update_containers()` stops and
  recreates the six application services. Requiring the poller to observe a `CLOSED` gateway
  during a window in which the harness has deliberately switched the gateway off is requiring
  evidence that cannot exist — and a breaker that is not running cannot trip.
* **Applied identically to both arms.** The rule names no arm, no window type and no stratum.
  It is `min(a, b)` of two quantities every run has.

### 4.3 What the corrected rule does NOT forgive

A poll error, a missing tick, a `GATEWAY_NOT_CLOSED` observation or a `POLLER_STOPPED`
condition occurring **before** the run's own end still makes the run `NOT_VERIFIED`, exactly as
§6 requires. The correction removes a window that should never have been in scope; it does not
weaken the standard inside the window that should.

---

## 5. Honest disclosure — this choice was not blind

**This rule was chosen after seeing that every TIME run was `NOT_VERIFIED` and that the first
in-horizon error tick falls after `run_timestamp`.** That is the definition of a
data-contingent analytic choice, and calling it anything else would be dishonest. It is a
deviation from a frozen pre-registration, recorded as one, and it does not carry the epistemic
weight of the pre-registered rule.

What limits the damage, stated so a reader can judge it rather than take it on trust:

* **It is structural, not tuned.** The bound is "the run's own end", an event the harness
  already records for its own reasons. It has no free parameter — no margin, no threshold, no
  constant that could have been turned until the answer improved. The one place a constant
  *could* have been added (the 1 s truncation, §4.1) was deliberately left uncorrected.
* **It is arm-symmetric by construction.** `min(§5 horizon, run_timestamp)` mentions no arm,
  window type or stratum. It happens to bind more often in the TIME arm precisely *because*
  the defect was arm-correlated; that asymmetry is in the disease, not the cure.
* **No outcome column was read** — before the discovery, during it, or in writing this note.
  The diagnosis rests on timestamps, error strings and tick counts.
* **The literal pre-registered result is reported alongside**, always, with its consequence
  stated plainly (§6a). Nothing is replaced; something is added, labelled.
* **This note is committed before any verification count under the corrected horizon is
  computed.** The rule is fixed in the repository's history before the number it produces is
  known. That is the strongest guarantee available this late, and it is the reason for the
  ordering.

What this does **not** buy: it does not restore the pre-registration's protection against
researcher degrees of freedom for this rule. A reader is entitled to discount DEVIATION 01
accordingly, and §6's three-way reporting exists so they can.

---

## 6. Reporting plan — all three, always, side by side

**(a) The literal pre-registered rule.** §5 horizon, §6 verdict, §4 rule 3 exclusion, applied
exactly as frozen at `3e4ad1e`. Its consequence is reported plainly: if the pattern observed at
run 20 holds, the TIME arm is empty in every stratum, §3's zero-configuration clause excludes
all three strata, fewer than two survive, and **the stratified test is not run at all — only
descriptives are reported.** Per §3 that is reported as *"insufficient clean data"*, **never**
as a null result, and never as evidence about H3.

**(b) The corrected-horizon analysis, labelled `DEVIATION 01` everywhere it appears** — every
table, figure caption, p-value and in-text mention. It is not the headline result and is never
presented as the pre-registered one. A run with a poll error or a missing tick **before its own
end** stays `NOT_VERIFIED` here (§4.3). Its exact floor is recomputed for whatever arm and
stratum sizes it actually yields.

**(c) A sensitivity with the poller's error ticks ignored entirely.** A run counts as clean if
its sidecar record shows no gateway `CLOSED_TO_OPEN` **and** no non-CLOSED gateway state was
observed at any point — no coverage-completeness requirement at all. This is the weakest of
the three and is labelled as such; it exists to show how much of any difference between (a) and
(b) is driven by the coverage requirement rather than by any gateway behaviour.

If (a), (b) and (c) disagree in direction or significance, **the disagreement is the reported
finding**, in the same way §1 and §3.2 already require for the precise-metric and
censoring-imputation comparisons.

---

## 7. The pre-registration is not edited

`docs/paper/h3-postd25-analysis-plan.md` is byte-identical to its state at
`3e4ad1e5d0596883bbd35604828d0d2db39a9eb2`:

```
$ git diff --quiet 3e4ad1e5d0596883bbd35604828d0d2db39a9eb2 HEAD -- docs/paper/h3-postd25-analysis-plan.md
$ echo $?
0
```

Blob at HEAD: `199770f9819ae7e52b23edde903bd92d076a9f8f` — the same blob the launch script's
assertion **b** checks on every run, and the same one it checked when this sweep launched.

Nothing in the plan file was changed, and nothing in it will be changed to accommodate this
deviation. The correction lives here, under its own label, and travels with that label into
every place its numbers appear.

---

## 8. Implementation, deferred until the sweep finishes

`analysis/gateway_poll_verify.py` is in use by the **live poller** and is not being modified
while it runs. `analysis/phase4b_postsweep_check.py` will gain a flag, **after** collection
completes, that selects the corrected horizon:

* the **pre-registered** horizon stays the **default**;
* **both** results are always printed, whichever is selected;
* the corrected horizon is reachable only via an explicit flag, and its output is labelled
  `DEVIATION 01`;
* self-tests cover: a run whose only failing ticks fall after `run_timestamp` (clean under the
  corrected rule, `NOT_VERIFIED` under the literal one); a run with a gap **before** its own end
  (`NOT_VERIFIED` under **both**); a run with a non-CLOSED gateway observation (`FAILED` under
  both); the §5.1 null-`time_to_recover` fallback under the corrected rule; and `min()`
  selecting the §5 bound when the §5 horizon ends first.
