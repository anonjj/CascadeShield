# CascadeShield — writing brief

**For:** drafting the paper, deadline 2026-09-24 night
**Supersedes:** `PAPER_DRAFT_NOTES.md` for writing purposes. That file is the
audit trail — 31 sections of corrections, several superseding each other. Use it
only to check *why* something is the way it is. **This file is what to write.**

Everything here is verified. Numbers not in this file should not appear in the
paper without checking them first.

---

## 1. The paper in one paragraph

A circuit breaker's sliding window is not a tuning parameter but a **failure-rate
estimator**. Its two configurations — count-based and time-based — are two
estimators with different sampling properties, not two values of one parameter.
We show this asymmetry has consequences the library's own configuration surface
hides: `minimumNumberOfCalls` is *unsatisfiable* under one window type and
*unenforceable* under the other, and a breaker can be structurally unable to open
while reporting healthy.

**Retracted 2026-10-01 (D29):** "and window type leaks into recovery — a stage of
the state machine it should not reach" is no longer part of the claim. A
pre-registered equal-exposure confirmatory run (R2) showed the apparent recovery
difference was a harness fault-exposure artifact (D28), not a window-type effect;
see §2 and §VI below. Do not reintroduce a recovery-leak claim into §1 or the
abstract.

**Title (working):** The Sliding Window as a Failure-Rate Estimator: A
Construct-Validity Study of Circuit-Breaker Window Configuration in Resilience4j

**Scope:** Resilience4j 2.2.0 on Spring Boot 3. Version-specific behaviour
verified against the pinned jar with `javap`. Do not generalise to circuit
breakers as a class.

---

## 2. Verified numbers — the only ones to use

### Dataset
| | |
|---|---|
| `master_dataset.csv` | **360 rows, 36 columns**, LATENCY-only |
| Composition | LINEAR 198, FANOUT 162 |
| Schema variants | base 36; sweep 37 (`injected_toxicity`); occupancy 38 (`occupancy_ratio`, `inert`) |
| CRASH rows | **absent by design** — excluded, see §6 |

### Run hygiene (strongest claim in the paper)
| | |
|---|---|
| `cb_state_pre` | CLOSED on all 10 breakers, all 360 runs |
| `buffered_calls_pre` | 0 on all 10 breakers, all 360 runs |
| Total | **3,600 per-breaker observations, zero exceptions, zero exclusions** |
| Scope | **load-start only** — says nothing about mid-run state |

### ρ / occupancy (D18) — the lead result
| | |
|---|---|
| Design | 54 configs (36 TIME, 18 COUNT control) × 3 replicates, LINEAR + LATENCY |
| Completion | 162/162, zero aborts, zero `lambda_deviation_flag`, zero exclusions |
| TIME_BASED | 108 rows: 30 inert, 78 tripped |
| TIME inert | all ρ ≤ **0.4996** |
| TIME tripped | all ρ ≥ **0.9967** |
| TIME range sampled | ρ ∈ [0.1249, 79.79] — no overlap anywhere |
| COUNT_BASED | 54 rows, **zero inertness**, ρ ∈ [0.025, 4.0] |
| Independent check (D19) | trip rate 0.722 [0.583, 0.861] over 36 configs; conditional `time_to_open` 9.89 s [8.16, 11.79], cluster-bootstrapped — reproduces D18 exactly |
| λ sampled | up to 20 req/s (the {5,20,80,320} range belongs to the *canary*, a different arm) |

### Recovery gap — RETRACTED as a window-type/library finding (D28/D29, see §3 and §VI)

**Everything in this subsection as previously written (stratified permutation on the
pre-D25 gateway-contaminated Phase 4B data, "complete separation," p=0.025, "COUNT_BASED
never bounces — structural," "a time-based window retains fault evidence into recovery")
is retracted. Do not quote the table or mechanism that used to be here.** The apparent
window-type recovery difference was traced (D28) to the harness clearing the injected
fault at a time that depended on window type — not to any Resilience4j behaviour — and a
pre-registered equal-exposure confirmatory run (R2, D29) confirms it: with fault exposure
held equal, both arms bounce exactly once in every run and recovery medians agree within
the pre-registered 1 s threshold at every $D_w$ (0.040s/0.029s/0.101s, same order of
magnitude as each arm's own between-config noise). This is now **construct-validity
material for §VI**, not a Results-section window-type effect — see the new §VI entry
below. Numbers: decision-log.md D29.

### Topology negative (H5)
Var(B) = 0 on **both** LINEAR and FANOUT under LATENCY. 162/162 rows each side,
exactly one leg firing. **Structural null** — exact zero variance across 324 runs,
not underpowered.

### Config audit (D25 Lead 3 / D30)

**Retracted 2026-10-02 (D30).** "821 instances, 740 repos," "median λ* = 0.4, robust
across five groupings," "Deduplicated (48 configs) median ≈ 0.55," and "38–63% at
λ* = 0.4 depending on grouping" are all superseded — neither 821 nor the earlier 447
figure was a correctly-parsed count, and the dual-estimand framing above was built on
the wrong one. Do not quote any of the four rows above; the table below replaces them.

| | |
|---|---|
| Corpus | **1,057 instances**, 626 file occurrences, 537 distinct blobs, **384 contributing repositories** of 740 searched, re-fetched by git blob sha from the 2026-09-17 scrape (content-addressed, byte-identical to the original) |
| Instance-level median λ* | **0.4 req/s** — same at every grouping (instance/config-dedup/file/repo/blob-level); the estimand choice no longer moves the headline the way the retracted 0.4-vs-0.55 framing implied |
| **The finding is composition, not the median (D30).** 1,057 instances collapse to **66 distinct parameter pairs**. One pair (`minimumNumberOfCalls=4, slidingWindowSize=10`) alone is **433 instances (41%)**, across only 181 blobs and roughly 3–5 structural template lineages (shared `eureka`/datasource key-shapes, byte-distinct files, different service names) — not 433 independent configuration choices. Instance-level counts measure **propagation**, not independent practice: Q3 moves from 0.5 (instance-level) to 0.97 (repo-level) once the duplication weight is removed. |
| Maximum | **λ* = 20** — 5 s window, `minimumNumberOfCalls` unset → library default 100. 14 instances, 5 repositories (was 9/3 before the reconciliation) |

**No tutorial/non-tutorial split (D30, dropped).** The flag was a substring match on
repo name/path against 17 keywords — not stars, not content, not structure. It caught
only 13/433 (3%) of the dominant duplicated cluster and is inverted relative to what it
claims: the instances it did **not** flag duplicate at 3× the rate of the ones it did.
Do not use a tutorial/non-tutorial split anywhere in the paper. If teaching material
needs to be distinguished from production configuration, say in §VII that it could not
be reliably separated — do not re-introduce the keyword heuristic to do so.

**Report at repository level and by distinct parameter pair, not instance-level alone.**
Instance-level is a legitimate secondary view (it is literally how widely a
configuration spread) but should be labelled as the propagation view, not presented as
the headline.

**Never name a repository.** Describe the λ*=20 case by configuration shape.
Raw config content was not retained because the corpus contained credentials —
say so in methods; it answers the reproducibility question before it is asked.

### Control
False-trip rate φ = **0.000**, 95% CI [0.000, 0.031], n=120 null-fault runs.

### Power
Cohen's *d* ≈ 3.07 at 3 replicates; 1.12 s on `time_to_open`, 5.46 s on
`time_to_recover`. **This describes the main sweep only** — the recovery result
uses configurations as units, a different design whose MDE was never computed.
Scope the sentence explicitly.

### Machine effects
D16 cleared cross-host splitting for **timing DVs only** (Cliff's δ ≈ 0.02).
`lambda_achieved` shows a substantial host effect. `leg_failure_rates` was
**never calibrated** — relevant to containment.

### λ fidelity
38 of 300 canary runs (12.7%) missed target λ by >15%; worst 35.3%; **zero** off
at λ=5 and 20, 23 off at λ=80, 15 at λ=320. H1/H2 read `lambda_achieved`, never
`lambda_target` — say so.

---

## 3. Decisions already made — do not reopen

| Decision | Position |
|---|---|
| **H3** | **Retracted 2026-10-01 (D29), supersedes the row below.** The 2026-09-22 "falsified prediction" / "recovery leak" call (kept for the record directly below) was itself based on gateway-contaminated and then fault-exposure-confounded data (D23, D28). A pre-registered equal-exposure run (R2) shows H3's recovery-side negative control **passes**: window type does not reach recovery. Report the original Phase 4B difference as a harness construct-validity defect (§VI), not as a current window-type finding. Never write "the recovery leak," "COUNT_BASED never bounces, structurally," or "a time-based window retains fault evidence into recovery" as current claims. *Historical, superseded: "Falsified prediction. It predicted window parameters drive `t_open` and not `t_rec`. Both window type and window size affect `t_rec`, so its own negative control fails. Report the effect as 'the recovery leak.' Never write 'H3 confirmed/supported' or `LEAK_CONFIRMED`." — this was the 2026-09-22 position; see decision-log.md D28/D29 for why it reversed.* |
| **H4** | Absorb into §VI as a scope clause; do not give it a Results subsection. Its τ evidence is degenerate on single-leg data and its earlier figures are unusable. *(A memory note says "descriptive observation" — absorption is the better version of the same call; pick one and move.)* |
| **CRASH arm** | Excluded, stated alongside THROTTLE. Two reasons: saturates at 1.0000 regardless of window type; injection point confounded with fault type (README documents this as deliberate design). |
| **Novelty** | "First **systematic empirical characterisation** with live instrumented evidence," **not** first observation. Fallback pre-committed before the search ran. |
| **ρ leads Results** | Scope growth permitted by D-004, not a reopening. |
| **Venue** | IEEEtran conference, 9 pages inclusive. |
| **Authorship** | Soham More, Jay Joshi. Prof. Negi in acknowledgments, not the author block. |

---

## 4. Do not write these

Every one is retracted, superseded or fabricated.

- **"The recovery leak," "H3 falsified," "COUNT_BASED never bounces, structurally,"
  "a time-based window retains fault evidence into recovery"** — retracted 2026-10-01
  (D29). The Phase 4B recovery difference was a harness fault-exposure artifact (D28),
  confirmed not a window-type effect by a pre-registered equal-exposure run (R2). Report
  as §VI construct-validity material instead.
- The stratified-permutation table (p=0.025, "complete separation," Cliff's δ=−1.0 on
  the pre-D25 recovery comparison) and the P1/P2/P3 bounce mechanism built on it — both
  computed on data later shown to be gateway-contaminated and then fault-exposure-
  confounded. Do not quote either.
- τ = **0.238**, **0.891**, **0.0189** — pre-fix, confounded, degenerate
- p = **0.0005**, p = **0.0014**, **"36/36 uncensored"** — row-level, retracted
- The H3 COUNT progression **2.04 → 9.83 → 14.99** — tracks gateway contamination, not $D_w$
- The **~9.8 s unexplained residual** and the two-component framing — dissolved
- Pre-fix H3 ratios **8.9×–14.3×**, **9.0×–10.35×** — censored data
- **"The gateway structurally cannot trip"** — false for COUNT_BASED
- **"FANOUT's fan-out happens inside order-service"** — the gateway fans out directly
- **"0.5 median / 31% / 447 configs across 192 repos"** — earlier snapshot
- **"Zero overlap"** on containment — the live file shows overlap (COUNT max 0.3667 > TIME min 0.2686); use Cliff's δ = −0.987 instead
- **"τ = 0.50 was calibrated when the distribution was bimodal"** — fabricated
- The "information exists but not where the decision is made" thesis — fits 1 of 6
- Any Monte Carlo p as an equality — always `p < 5e-5 (20,000 resamples)`

---

## 5. Section plan

### §I Introduction (~1 p)
The estimator framing. $W = \lambda T$: a count window of $W$ calls and a time
window of $T$ seconds observe the same sample count only when $W = \lambda T$, and
$\lambda$ is invisible at the configuration surface. Contributions list.

**Strongest opening available** — the three-source significance argument:
practitioners report the symptom (Resilience4j issues #1731, #1349, discussion
#1815); the config audit shows the pattern appears in public configurations at
repository level, not merely as a copied instance (384 repositories, D30 — see §2's
"Config audit" table and its 2026-10-02 reconciliation note); the experiments show
the mechanism.

### §II Related work (~0.75 p)
From `docs/paper/references.bib` (17 verified entries). **ResilienceBench**
(Aderaldo et al., SPE) is the closest sibling — same methodology class, sweeps
retry/workload parameters, **holds window type fixed**. Name it and say what it
does not vary.

### §III System under study (~1 p)
Six services, Spring Boot 3, Resilience4j 2.2.0, `-Xmx512m`, Docker Compose,
Toxiproxy, Prometheus/Grafana. **Ten breakers:**

| Service | Breakers |
|---|---|
| gateway | `orderServiceCB`, `inventoryServiceCB`, `paymentServiceCB` |
| order | `inventoryServiceCB`, `sharedDbCB` |
| inventory | `paymentServiceCB`, `sharedDbCB` |
| payment | `notificationServiceCB`, `sharedDbCB` |
| notification | `sharedDbCB` |

Place this table near §VI's blending paragraph too — every service but
notification owns two breakers, which makes D17's defect self-evident.

**Topology — get this right:** LINEAR is a chain. **FANOUT fans out at the
gateway** — `GatewayController.fanout()` calls order, inventory and payment
directly and in parallel via `CompletableFuture`. They are parallel children of
the *gateway*, not of order-service.

Exception policy: 4xx → `DownstreamRejectedException`, ignored; 5xx/timeout →
`DownstreamUnavailableException`, recorded.

THROTTLE excluded by construction (429 → business rejection → breaker ignores it).
CRASH excluded, two reasons above.

**Gateway isolation, with the caveat:** the `measurement-plane` profile intended
to make the gateway untrippable but never pinned `sliding-window-size` or
`sliding-window-type`, so for COUNT_BASED the effective gate was
`min(1000000, slidingWindowSize)` and the gateway did trip mid-run in some
configurations. Fixed (D25, forward-only), verified by reading the config out of
the packaged jar and by a live fault run with zero gateway `CLOSED_TO_OPEN`.

### §IV Methodology (~1.5 p)
Notation table. Why $H$ is the only fair comparison basis; matched-horizon
coverage is a **diagonal band**, not the full plane (1 s resolution floor below,
window ceiling above λ=80).

Run hygiene — use the 3,600-observation sentence, and **name the two leakage modes
separately**: `cb_state_pre` rules out an OPEN breaker carrying over,
`buffered_calls_pre` rules out a CLOSED breaker holding stale failures. Scope to
load-start.

Statistical treatment: Mann-Whitney + Cliff's δ; cluster bootstrap by
configuration; censored DVs as rate + conditional timing, never imputed;
Kaplan-Meier + log-rank where distributional comparison is needed; **exact
permutation at small n**, with the floor `1/C(k₁+k₂, k₁)` on **cluster** counts.

**State the two deliberate deviations** — `h1_matched_horizon` never migrated off
Welch's t (its numbers back a closed decision); and the cluster-vs-row issue,
now closed. A reviewer reading the repo will find both.

Multiple comparisons: effect sizes primary, p confirmatory; hypotheses
pre-registered in `hypotheses.md`; headline claims rest on structural results
(exact zero variance, complete separation, zero inertness) that no correction
touches.

Exclusions, **two sentences, no narrative**:
> Four runs were excluded as wall-clock artifacts from host suspension, flagged by
> automated ceiling rules rather than inspection. The ceilings derive from the
> harness's own observation deadline rather than from the observed distribution,
> and were validated against all 26 completed recovery episodes with no
> violations; an independent extraction path subsequently re-derived the same
> excluded records.

Power: the 3.07 sentence, scoped to the main sweep.

### §V Results (~2.5 p)

**§V-A ρ asymmetry** — the lead. Numbers in §2. **The asymmetry is the finding,
not the threshold**: a crossover at ρ=1 alone is near-arithmetic; what is not
obvious is that the same arithmetic predicts the same for count-based and is
cleanly wrong. Mechanism confirmed by live per-call trace — evaluation begins the
instant `bufferedCalls` hits window capacity, never near the configured minimum;
the gate is applied at the runtime metrics layer, not the config object.

**The two-directions framing** — this is the strongest sentence in the paper:

| | `minimumNumberOfCalls` is… | Failure mode |
|---|---|---|
| TIME_BASED | honoured exactly | **unsatisfiable** — a breaker meant to protect cannot open |
| COUNT_BASED | capped by window capacity | **unenforceable** — a breaker meant to be disabled opens anyway |

One parameter, two opposite failure modes, selected by a neighbouring enum, with
live evidence for both halves. **You cannot disable a count-based Resilience4j
breaker by raising `minimumNumberOfCalls`** — setting it to 10⁶ looks decisive and
does nothing. Figure 1.

**§V-B Containment** — ⚠️ **blocked.** `analysis/out/` predates the current
dataset. If `tau_sweep.py` and `order_leg_containment.py` cannot be re-run in
time, **scope this out** rather than quoting stale numbers. If they can: report
Cliff's δ = −0.987 with a bootstrap CI and acknowledge the overlap. Do not write
"zero overlap."

**§V-C Topology negative** — H5. Structural null. The fault targets a single edge
regardless of how many parallel paths exist, so fan-out's capacity for multi-leg
propagation is never exercised.

**§V-D removed as a current Results subsection (2026-10-01, D29).** The recovery
comparison that used to sit here is retracted as a window-type finding (§2, §3) and
moves to §VI as a construct-validity/instrumentation-defect case (defect 8 below) —
it does not belong in Results because, under the pre-registered equal-exposure
confirmatory run, no window-type recovery effect survives. Do not restore the
p=0.025 / Cliff's δ=−1.0 sentence to §V; that comparison was run on data later shown
to be confounded by unequal fault exposure (D28) and is superseded by R2 (D29),
which found equivalence within the pre-registered 1s threshold at every $D_w$. If
§V needs a one-line pointer for flow, use: "The apparent recovery difference raised
in an earlier collection pass is addressed in §VI as a harness defect, not reported
here as a result."

**§V-E Config audit** — numbers in §2. This is the paper's only evidence about
software outside the lab. Quote one configuration **by shape**, never by repo.
**Narrowed 2026-10-02 (D30):** do not frame this as "where public configurations sit
relative to the gate" — report at repository level and by distinct parameter pair,
and state the claim as *a small number of widely-copied configurations sit near the
gate*, not as independent practitioner convergence. A copied configuration propagates
its defect — the same construct-validity argument the paper makes elsewhere (§VI), on
a different mechanism (corpus composition, not instrumentation). No tutorial/
non-tutorial split (D30 dropped it; see §2).

**§V-F Control** — φ = 0.000.

### §VI Metric evolution as construct validity (~1.25 p)
**One of the paper's contributions, not an apology.** Eight defects (updated
2026-10-01, D29 — was seven), and the framing holds eight for eight: each was
invisible in aggregate statistics and visible only in the full distribution, full
parameter surface, or raw event record.

1. **Constant blast radius** — zero variance, visible in the distribution
2. **τ = 0.50 dead zone** — visible in the parameter surface; on the *first*
   measurement the max leg rate was 0.4867 and τ=0.50 already sat above the entire
   support. **It never worked** — there was no degradation
3. **Blended breakers (D17)** — summing call counts across a service's two
   breakers halved true severity. Also retroactively implicates (2): blended values
   are capped at 0.5 by construction, so the dead zone may be the bug
4. **Throughput confound (D20)** — the measurement window is sized by the IVs.
   Use the fingerprint table: COUNT flat to 0.011 across both IVs (0.728), TIME
   sliding monotonically (0.894; 0.925/0.896/0.863 by window size). **The +0.166
   between-type gap is exactly the contaminated number.** Not repairable — only
   the ratio was persisted
5. **Probe-window ceiling (D21)** — a flat ~4 s probe budget that did not scale
   with $D_w$, so censoring rose with $D_w$ by construction. **This one
   manufactured an effect in the wrong direction**, and replication would have
   reproduced it more precisely. The tell was not statistical: every affected
   record showed exactly two events then silence
6. **Gateway isolation (D23)** — a hardcoded 10⁶ gate silently capped by a window
   size nobody set
7. **Sub-floor p-values** — statistics computed on more independent units than the
   design contained. Appeared four times before being caught
8. **Recovery fault-exposure confound (D28/D29)** — the harness cleared the injected
   fault only after its load call returned, and that call was sized by the independent
   variable (window type/size), so COUNT_BASED and TIME_BASED arms were exposed to the
   fault for different durations after OPEN. This produced a recovery difference that
   looked exactly like a window-type property — COUNT_BASED "never bounced," TIME_BASED
   "retained fault evidence" — and was reported that way on 2026-09-22 before the
   confound was found. **Distinct from defects 1-7: not closed by inspection alone.**
   The exposure-timing mechanism was diagnosed (D28) and modeled
   (`recovery_exposure_model.py`, reproduces Phase 4B's bounce count in 72/72 runs and
   recovery time within 0.6s window-type-blind), then confirmed by a dedicated
   pre-registered confirmatory experiment (R2, D29) that held fault exposure equal and
   found no window-type recovery effect survives (medians agree within the
   pre-registered 1s threshold at every $D_w$). Report the double reversal explicitly:
   apparent falsification (2026-09-22) → shown confounded (D28, 2026-09-29) → confirmed
   artifact, control passes (R2/D29, 2026-10-01). This is the paper's strongest §VI
   example precisely because it required a live experiment, not just a code read, to
   close — the same self-referential point §VI already makes about defects 1-7 applies
   with more force here: two researchers who already knew to distrust aggregate
   statistics still read a confound as a finding for nine days.

**The self-referential fact — do not bury it:** two researchers who had already
discovered, verified and published the ρ mechanism still wrote a configuration
that fell to it, and did not notice for seven weeks.

**Closing paragraph** — ties §VI to §V-A:
> A count-based breaker configured with `minimumNumberOfCalls = 10⁶` reports that
> configuration faithfully while silently ignoring it. A time-based breaker at
> ρ < 1 reports CLOSED throughout while being structurally unable to open. A
> metric with zero variance reports a clean number while carrying no information.
> A p-value of 0.0082 reports significance while being arithmetically impossible.
> Every one fails by reporting normally. The absence of an error signal is the
> failure mode.

**H4's scope clause goes here**, not in Results:
> The ranking comparison between competing containment definitions requires
> configurations that differ in how many legs fire. The latency-only dataset
> provides one firing leg throughout, so the rank correlation is degenerate by
> construction rather than by measurement.

### §VII Threats to validity (~0.75 p)
Apply the **disclosure budget rule**: findings earn narrative, chores get a
clause. Count the admissions before submitting.

- **Construct:** window size not unit-comparable (the paper's premise); gateway
  shadowing (H6) untestable as instrumented — and note D23 showed the isolation
  was incomplete for COUNT_BASED, so H6's testability verdict is **open, not
  re-decided**
- **Internal:** fault type confounded with target service and chain depth —
  documented as deliberate design, so cite your own rationale; breaker state
  leakage ruled out **by measurement**; cross-machine effects, with `leg_failure_rates`
  never calibrated
- **External:** one library, one version — and the evaluation-gating behaviour is
  **version-specific**, verified with `javap` against the pinned jar. This turns
  objection #8 from a limitation into a finding. Six services on one host; claims
  are about application-layer semantics, not absolute performance
- **Statistical:** large effects only; structural vs underpowered nulls
  distinguished, only the former presented as findings
- **Reproducibility:** repo public, dataset committed. **Still open:** a third of
  the dataset (COUNT × $D_w$ ∈ {15,30}) has unverified gateway isolation. If the
  re-collection does not land, use:
  > Isolation of the measurement plane was verified by configuration dump and live
  > fault injection for runs collected after the fix. For earlier runs in the
  > count-based arm at wait durations of 15 s and 30 s, per-run verification is
  > unavailable, since the transition sidecar does not extend to that collection.
  > Results in that stratum are reported with that limitation stated; the
  > time-based arm is unaffected, as the defect is structurally confined to
  > count-based windows.

### §VIII Conclusion (~0.5 p)
The asymmetry; what did not hold (topology); the metric-evolution argument.

### Abstract, title, contributions — **write last**, from the finished Results.

---

## 6. Figures

| # | Status | Content |
|---|---|---|
| 1 | ✅ done | Trip outcome vs ρ, log x, by window type, ρ=1 line, inert runs at a sentinel below a broken axis |
| 2 | ✅ done | λ* ECDF, quartiles marked, λ*=20 annotated by shape |
| 3 | ❌ drop | Recovery decomposition — needs data that will not arrive |
| 4 | ❌ drop | State machine diagram — nice, not necessary |

---

## 7. Known gaps to state, not hide

- A third of the dataset has unverified gateway isolation (wording above)
- `leg_failure_rates` never machine-calibrated; a ~2×/1× ratio splits by
  collection batch, unexplained
- Codespace-collected runs have no retrievable transition sidecar
- H6's testability verdict open
- `/mesh` and `/fanout` share identical gateway-controller code; the intended
  distinction is downstream
- MDE for the cluster design never computed
