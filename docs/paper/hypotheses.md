# CascadeShield — Formalization

**Owner:** Soham More · **Frozen:** Day 1 (Mon 10 Aug 2026) · **Status:** contract

This file becomes Section I and Section III of the paper. It is the reference for every
hypothesis, metric and figure. Anything in the paper that does not trace back to §1 gets cut.

---

## 1. The subject of study

> A circuit breaker's sliding window is a **failure-rate estimator**. Its two configurations —
> count-based and time-based — are two estimators with different sampling properties, not two
> settings of one parameter. CascadeShield characterizes those properties and their consequences
> for detection latency, recovery latency, and fault containment.

This framing is what separates the paper from a parameter sweep. A sweep asks which setting is
better; this asks what the settings *measure*, and shows that the answer depends on a variable
(arrival rate) that neither setting exposes to the operator.

---

## 2. Notation

| Symbol | Meaning | Unit | Source |
|---|---|---|---|
| $\lambda$ | request arrival rate at a breaker's protected call site | req/s | **achieved** rate measured by the harness, not requested |
| $W$ | `slidingWindowSize` under COUNT_BASED | calls | swept |
| $T$ | `slidingWindowSize` under TIME_BASED | seconds | swept |
| $H$ | effective horizon — $H = W$ (COUNT) or $H = \lambda T$ (TIME) | calls | derived |
| $\theta$ | `failureRateThreshold` | fraction | swept $\{0.30, 0.50, 0.70\}$ |
| $n_{\min}$ | `minimumNumberOfCalls` | calls | pinned at 5 |
| $D_w$ | `waitDurationInOpenState` | s | swept $\{5, 15, 30\}$ |
| $p_f$ | induced failure probability at the injection point | fraction | fault config |
| $t_{\text{open}}$ | detection latency: fault onset → breaker OPEN | s | `time_to_open` |
| $t_{\text{rec}}$ | recovery latency: fault clear → breaker CLOSED | s | `time_to_recover` |
| $B$ | containment / blast radius | fraction of subjects | `blast_radius`, `real_blast_radius` |
| $\rho_i$ | per-leg failure rate for service $i$ | fraction | `leg_failure_rates` |
| $\tau_{\text{leg}}$ | per-leg threshold for $B_{\text{real}}$ | fraction | **swept, not pinned** — see §5 |
| $\phi$ | false-trip rate — P(breaker opens \| no fault injected) | fraction | null-fault arm |

### 2.1 Why $H$ is the only fair basis for comparison

$W$ and $T$ are both called `slidingWindowSize` and are both integers, which invites treating
them as one parameter on one scale. They are not. A COUNT window of $W$ calls and a TIME window
of $T$ seconds observe the same number of samples only when

$$H = W = \lambda T.$$

At $\lambda = 80$ req/s, comparing $W = 20$ against $T = 20$ s compares a 20-call horizon
against a 1600-call horizon. Any difference in detection latency between them is a difference in
sample size, not in estimator behaviour. **Every COUNT-vs-TIME contrast in the paper is reported
at matched $H$**, and the nominal comparison is shown only as the thing being argued against.

$\lambda$ therefore has to be a measured factor rather than a fixed condition, which is why the
whole design turns on the Day-2 canary.

---

## 3. Hypotheses

| ID | Hypothesis | Status entering Day 1 | Decided by |
|---|---|---|---|
| **H1** | At matched horizon $H$, COUNT and TIME have indistinguishable **mean** $t_{\text{open}}$ but significantly different **variance** | Not yet tested. The existing contrast (TIME 9.43 ± 5.41 vs COUNT 5.22 ± 2.19) is at *nominal* window size — the comparison §2.1 argues is invalid | Day 2 canary |
| **H2** | There exists a crossover $\lambda^*$ below which TIME_BASED cannot trip within the fault window | New. Nothing in the repo varies $\lambda$ | Day 2 canary |
| **H3** | Window parameters drive $t_{\text{open}}$ and not $t_{\text{rec}}$; $D_w$ drives $t_{\text{rec}}$ and not $t_{\text{open}}$ (double dissociation) | Evidence in hand ($t_{\text{rec}}$ = 16.95 / 27.85 / 49.31 s across $D_w$ = 5/15/30, negative control on $t_{\text{open}}$ at 7.39 / 7.35 / 7.49). Leak audit clears it — see §4. Additionally stress-tested directly against window_type, see §4.1 (`analysis/out/window_type_recovery_leak.json`) | Day 3 analysis |
| **H4** | Competing containment definitions rank configurations differently ($\tau_{\text{Kendall}} < 1$, significantly) | **Supported on Day 1** from the persisted leg vectors, with no new runs — see §5 | ✅ Day 1 |
| **H5** | Blast-radius resolution is topology-dependent: $\text{Var}(B) = 0$ on chain topologies, $> 0$ where parallel reachable subjects exist | Half proven. The LINEAR half is done and the mechanism is now explicit (§5.3). Needs the FAN_OUT contrast | Day 4 sweep |
| **H6** | A uniformly configured edge breaker suppresses interior breaker engagement (gateway shadowing) | Evidence exists in the archived 162-run data (gateway leg 0.70–1.00 in every row, interior legs 0.0000 in 154 of 162) but the condition was **removed** by the `measurement-plane` isolation block | Day 3, if time |

**H1 + H2 are the novelty. H3 + H5 are the floor.** If the Day-2 canary kills H1/H2, the
fallback is Paper B (construct validity), which §5 has already moved substantially forward.

### 3.1 What each hypothesis is a claim *about*

Stated explicitly because reviewers of empirical papers check whether the test matches the claim:

- **H1 is a variance claim.** It is tested with Brown–Forsythe on $\text{Var}(t_{\text{open}})$
  directly, not inferred from overlapping confidence intervals on means. The accompanying
  Welch's $t$ on the means can only ever *fail to reject* equality; the paper reports the CI on
  the difference and says the data are consistent with equality. It never says means are equal.
- **H2 is an existence claim** about a threshold in $\lambda$. It is supported by a monotone
  trip-rate curve that crosses from failing to reliable, bracketed between two sampled
  $\lambda$ rungs. The design samples $\lambda$ geometrically, so $\lambda^*$ is reported as an
  interval, never as a point estimate.
- **H3 is an interaction claim** (a $2\times2$ dissociation), so it needs both the positive
  effect and the negative control to hold. A significant effect on $t_{\text{rec}}$ alone is
  half of H3 and is reported as half.
- **H4 and H5 are claims about the metric**, not about the system. They survive even if H1 and
  H2 fail, which is precisely why they are the fallback.

---

## 4. Instrument status entering Day 2

From `analysis/leak_audit.py` (full write-up in `docs/paper/leak-audit.md`):

| Dataset | Rows | Verdict |
|---|---|---|
| `master_dataset_v1_prefix.csv` | 486 | **Unusable for H3.** `time_to_open` / `time_to_recover` are 100% null — the collector was a stub. No leg vector either. Cannot be audited and cannot be analysed. |
| `master_dataset_v2_latency_5svc.csv` | 162 | 1 state leak, 1 recovery hang, both quarantined. The H3 slice survives. |
| `master_dataset_v3_gateway_not_rebuilt.csv` | 92 | Timing usable; **`blast_radius` unusable** — a constant offset in 95.7% of rows. |
| `master_dataset.csv` (current) | 80 | 1 state leak, quarantined. 79 analysable. |

**The breaker-state leak is rare, not endemic: 2 rows across 334 timed rows (0.6%).** The Day-1
risk that "the July 30 detection-latency numbers move and H3 must be recomputed" did not
materialise. H3 stands on the archive, recomputed with the two quarantined rows excluded.

Two findings displaced it, and both matter more:

1. **$t_{\text{open}}$ is bimodal under TIME_BASED.** At $W = 5$ the current dataset puts nine
   runs near 3.5 s and eleven near 6.3 s with *nothing* in between, reproducing across four
   distinct configurations and across three separate datasets. This is a discretisation of the
   dependent variable, not contamination. **It bears directly on H1**: if TIME_BASED
   $t_{\text{open}}$ is mode-switching rather than continuous, a COUNT-vs-TIME variance gap may
   be a mixing proportion rather than a sampling property, and the Day-2 read-out has to
   distinguish those before H1 can be claimed.
2. **`blast_radius` in the v3 archive is a constant.** 95.7% of its rows report a subject OPEN
   whose own leg recorded zero failures — one subject reading degraded in every run. This is the
   real reason `validate_gate.py` passed at Cramér's V = 0.196: the label was near-constant.

### 4.1 H3's negative control, stress-tested directly against window_type (D12)

H3's published numbers ($t_{\text{rec}}$ = 16.95/27.85/49.31 s across $D_w$ = 5/15/30) show a
$D_w$ effect — they do not, by themselves, rule out window_type also contaminating
$t_{\text{rec}}$. `analysis/window_type_recovery_leak.py` runs that check directly ("D12" is
this investigation's own working label, distinct from this section's `D-00X` decision-log
numbering and from the unrelated "Day N" sprint-day shorthand used elsewhere in the repo).

**Coarse check** (`time_to_recover` as currently collected — OPEN to left-OPEN, not OPEN to
CLOSED; see the script's docstring for why): TIME's median $t_{\text{rec}}$ is 2.06–3.68x
COUNT's at every matched $D_w$ on the current archive (79 rows), and the same shape
reproduces on `master_dataset_v2_latency_5svc.csv` (2.07–3.52x) and
`master_dataset_v3_gateway_not_rebuilt.csv` (2.06–3.70x) — real and consistent, not noise
from one sweep.

Decomposing $t_{\text{rec}}$ into $t_{\text{open}}$ (anchor) and excess ($t_{\text{rec}} -
D_w$) separates two effects: TIME opens ~3s later than COUNT at every $D_w$ (a flat anchor
shift — plausible and non-buggy, since TIME_BASED windows accumulate over wall-clock seconds
rather than a fixed call count, so trip timing can legitimately differ from COUNT_BASED under
identical load). But TIME's excess **grows** with $D_w$ (19.1s → 20.2s → 35.1s across
$D_w$=5/15/30 on the current archive) while COUNT's stays flat (~1.5–1.7s, pure poll
overhead) — a pattern a constant anchor shift alone cannot produce.

**Precise check** (true HALF_OPEN→CLOSED duration, from `data/cb_transitions.jsonl`'s real
Resilience4j state transitions): **not computable on data in hand.**
`data/cb_transitions.jsonl` is real-runs-only and gitignored, and was not retained from the
sweep behind the current archive (or the v2/v3 archives). The script's join/derivation logic
is fully implemented and exercised via `--self-test` against a synthetic fixture, but produces
no real verdict until a `experiments/runner.py` run retains the sidecar.

**H3's negative control on $t_{\text{rec}}$ is downgraded from "cleared" to "untested against
this specific mechanism, pending a re-run that retains the transition sidecar."** The coarse
ratio above is consistent with either a genuine recovery-side leak or a pure detection-anchor
shift, and the two cannot be told apart without the precise metric. (The mechanism originally
suspected — "HALF_OPEN re-evaluation goes back through the TIME_BASED window" — is not
architecturally plausible for Resilience4j 2.2.0, the version this repo pins: HALF_OPEN always
uses its own fixed-size ring buffer sized `permittedNumberOfCallsInHalfOpenState`, independent
of `slidingWindowType`. If the precise metric ever finds a real HALF_OPEN→CLOSED effect, it is
a different mechanism than the one originally suspected.)

---

## 5. $\tau_{\text{leg}}$ is a sensitivity analysis, not a constant

`real_blast_radius` reads 0.0 in all 80 current rows. That is a calibration failure, not a
property of the system: $\tau_{\text{leg}}$ was pinned at 0.50 when the legs were bimodal, and
after the rebuild the only leg that fires at all (order-service) tops out at **0.4867** — just
below the threshold. The metric is constant by construction.

`leg_failure_rates` was persisted so this could be fixed without re-running anything.
`analysis/tau_sweep.py` recomputes $B_{\text{real}}(\tau)$ over $\tau \in [0.05, 0.95]$.

### 5.1 The result (Figure 7)

| $\tau_{\text{leg}}$ | mean $B_{\text{real}}$ | 95% CI | runs with $B_{\text{real}} > 0$ |
|---|---|---|---|
| 0.05 – 0.20 | 0.2500 | [0.2500, 0.2500] | 100% |
| 0.25 | 0.2406 | [0.2253, 0.2500] | 96.2% |
| 0.30 | 0.1844 | [0.1437, 0.2233] | 73.8% |
| 0.35 | 0.1625 | [0.1152, 0.2073] | 65.0% |
| 0.40 | 0.1437 | [0.0937, 0.1921] | 57.5% |
| 0.45 | 0.1031 | [0.0586, 0.1494] | 41.2% |
| **0.50 – 0.95** | **0.0000** | [0.0000, 0.0000] | **0%** |

The metric has resolution on a **20-percentage-point band, $\tau \in [0.25, 0.45]$**, and is
degenerate on both sides of it — saturated at 0.25 below, identically zero above. The pinned
value sits exactly at the upper edge of the dead zone.

Reporting the curve rather than a chosen value is what turns a calibration failure into a
result. A threshold that must be chosen is a researcher degree of freedom, and the honest
response to one is to show the whole surface.

### 5.2 H4 is supported (Day 1, zero new experiments)

Ranking the 26 configurations by mean $B_{\text{real}}$ at each live threshold and correlating
the rankings pairwise:

- **10 of 10 threshold pairs rank configurations differently**, minimum Kendall's
  $\tau_b = 0.238$.
- Every comparison **against the shipped $\tau = 0.50$ is undefined**, because that threshold
  ranks all 26 configurations identically at zero. "The shipped metric cannot rank anything" is
  the finding, and it is reported rather than dropped as a NaN.

H4 was scheduled for Day 5 and expected to be degenerate on LINEAR. It is neither.

### 5.3 H5's LINEAR half, with the mechanism attached

Across all 320 leg observations in the current dataset, **exactly one service ever fires:
order-service.** Every other subject records 0.0000 in every run. $\text{Var}(B) = 0$ on the
chain is therefore not a null result to be explained away — it is structural. A chain exposes
one reachable subject downstream of the injection point, so the containment metric has exactly
two attainable values and no resolution at all.

This is the strongest available form of the H5 claim, and it makes the FAN_OUT contrast a
genuine test rather than a repetition: FAN_OUT is the only topology in the system where $B$ can
physically take a value other than 0 and 0.25.

### 5.4 Retiring the quartized metric in favor of the continuous leg vector (D3 / D-007)

§5.3 already shows the mechanism: on LINEAR, exactly one leg (order-service) ever fires, so
$B$ and $B_{\text{real}}$ have exactly two attainable values on every row collected so far —
binarizing a per-leg rate that was never bimodal to begin with. `analysis/order_leg_containment.py`
checks whether the underlying continuous signal — `order_leg`, the raw
`leg_failure_rates["order-service"]` value — is worth reporting on its own rather than through
that binarization.

**It is.** On the current archive (79 rows, `analysis/out/order_leg_containment.json`):

| window_type | window_size | $n$ | mean order\_leg |
|---|---|---|---|
| COUNT_BASED | 5 | 21 | 0.2798 |
| COUNT_BASED | 10 | 12 | 0.3330 |
| COUNT_BASED | 20 | 8 | 0.4160 |
| TIME_BASED | 5 | 20 | 0.4688 |
| TIME_BASED | 10 | 9 | 0.4665 |
| TIME_BASED | 20 | 9 | 0.4708 |

`order_leg` takes **32 distinct values** (vs. 2 for the quartized metric on the same rows),
increases monotonically with `window_size` under COUNT_BASED (0.28 → 0.33 → 0.42, 95% CI
[0.293, 0.355] pooled), and separates window_type cleanly with **no overlap**: COUNT_BASED's
maximum (0.4167) sits below TIME_BASED's minimum (0.45, 95% CI [0.461, 0.476]) — Cliff's
$\delta = -1.0$ (large). Thresholding that into a 4-point denominator and then defending a
knife-edge $\tau_{\text{leg}}$ (D-001's whole problem) throws away exactly the resolution the
paper needs. **Decision D-007: $B$/$B_{\text{real}}$ are retired as reported outcomes; `order_leg`
is the reported containment signal, see §6 and §7.**

---

## 6. Metrics contract — frozen Day 1, not renegotiable

**Primary DVs:** $t_{\text{open}}$, $t_{\text{rec}}$.

**Secondary DVs:** $\rho_{\text{order}}$ and the per-leg vector (continuous severity), $B$
(containment, quartized), throughput loss, p95/p99 client latency. **D-007 (Day 3+): $B$
retired as a reported outcome — see §5.4 and §7 — $\rho_{\text{order}}$ (`order_leg`) is the
reported containment DV.**

**Control DVs (mandatory):** $\phi$ (false-trip rate under null-fault runs), missed-detection
rate, flap count (OPEN↔CLOSED transitions per run).

**Derived headline figure:** detection latency vs. false-trip rate, plotted as an operating
curve per window type across $\theta$. This is the figure that makes the paper read as detection
theory rather than a parameter sweep.

Rules that hold for the rest of the sprint:

1. Every column added after today requires a `data/DATA_DICTIONARY.md` entry **in the same
   commit**.
2. Every mean carries a bootstrap CI. Every contrast carries an effect size. No $p$-value
   appears without one.
3. The effective sample size is the number of **configurations**, not rows. CIs on pooled
   quantities use the cluster bootstrap in `analysis/common.py`.
4. Nulls in $t_{\text{open}}$ / $t_{\text{rec}}$ are **outcomes**, not missing data. They are
   never mean-imputed; under H2 the null *is* the measurement.
5. Excluded rows are marked with `excluded_reason` and counted in the paper. Nothing is deleted.

---

## 7. Open threats carried into the write-up

Listed here so Section VII is assembled from a running record rather than reconstructed on
Day 6:

- The TIME_BASED bimodality in $t_{\text{open}}$ (§4). Unexplained as of Day 1.
- $B$ and $B_{\text{real}}$ range over **disjoint node sets** in the v2 archive: legacy $B$
  excludes the gateway, $B_{\text{real}}$ includes it. The earlier "canary 3 agrees with legacy"
  reading was a numerical coincidence between two metrics over different nodes.
- The 5→4 denominator change moved $B$'s entire support from $\{0, 0.2, 0.4\}$ to
  $\{0, 0.25, 0.5, 0.75, 1.0\}$. Three successive definitions of the same construct have now
  been applied to the same system; the metric-evolution narrative is Section VII's core.
- **$B$/$B_{\text{real}}$ are retired, not fixed (D-007).** After three node-set redefinitions
  and a shipped $\tau_{\text{leg}}$ that ranks nothing (D-001), the quartized metric is not
  reported as evidence anywhere in this paper. The legacy CB-state `blast_radius` column needs
  no further code change — it has been structurally correct since the gateway-isolation fix —
  and stays in the dataset for reference, but the paper's containment claims rest entirely on
  the continuous `order_leg` signal (§5.4), which has the resolution the quartized metric threw
  away. Stated here plainly rather than left implicit across §4, §5, and D-001.
- **Isolating the gateway removed the only propagation path LINEAR can show.** The
  `measurement-plane` fix (above) was the right call for confound control — an uncontrolled
  gateway breaker would have dominated every result. But §5.3 shows it also means a chain
  topology exposes exactly one subject downstream of the injection point: cascade (more than
  one leg degraded at once) is unobservable on LINEAR **by construction**, not by bad luck.
  Every row in every archive checked (`current`, `v2_latency_5svc`,
  `v3_gateway_not_rebuilt` — confirmed via topology counts) is LINEAR; zero FAN_OUT rows exist
  anywhere. `--topology fanout` is already implemented in `experiments/runner.py` and has never
  been swept. Every cascade-shaped claim in this paper (H5 beyond its LINEAR half, H6) depends
  on that sweep happening — stated here so a reviewer finds it stated, not discovered.
- H6's condition was removed by the `measurement-plane` isolation block. If the arm is run, the
  paper must state it as a **deliberate reconstruction of a removed confound**, not as a
  pre-existing condition. Every current row is `isolated`.
- Matched-horizon coverage is **not** the full $(\lambda, H)$ plane. Whole regions are
  unreachable: $T = W/\lambda$ falls below Resilience4j's one-second resolution above
  $\lambda = 5$, and $W = \lambda T$ exceeds the configurable window ceiling above
  $\lambda = 80$. H1 is testable on a diagonal band, and the paper says so.
