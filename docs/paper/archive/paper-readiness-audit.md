# CascadeShield — paper-readiness audit

**Date:** 2026-09-29 · **Scope:** everything needed to turn the capstone into a defensible
paper · **Inputs:** `PAPER_BRIEF.md`, `PAPER_DRAFT_NOTES.md` (supplied), `main` at `2f88b28`,
every unmerged branch on `origin`, the datasets, the service source, and the Resilience4j
jars (disassembled with `javap`).

This is an audit, not a draft. Every number marked **(re-checked)** was recomputed from the
committed data or bytecode for this audit; the commands are in the appendix.

---

## 0. Headline

1. **The recovery-leak result measures the harness, not the breaker.** In all 145 sidecar
   records (Phase 4B plus the older set), every failed recovery attempt (a "bounce") started
   while the injected fault was still on, and every successful one started after it was
   cleared — 123 of 123 and 134 of 134, no exceptions. The harness keeps the fault on for the
   whole load plan, and that plan is ~3 s after the trip for COUNT_BASED but 20–48 s for
   TIME_BASED. Resilience4j 2.2.0's HALF_OPEN state always uses a fresh count-based buffer,
   whatever the window type (bytecode). **§V-D cannot be written as a window-type effect, and
   the "same estimator argument applied to recovery" framing has no support.** This needs a
   team decision (§13).
2. **The lead result (ρ asymmetry) and the two-directions framing are solid** — re-checked
   against the data, and now also against the library bytecode. Two wording errors in the
   brief need fixing (ρ < 1 claim; "version-specific" claim).
3. **The brief is already out of date.** It predates D26 (the Phase 4B re-collection,
   2026-09-22) and still quotes the 80-assignment p = 0.025 test, which D26 replaced.
4. **Most "done" items are not on `main`.** Figure 1, Figure 2, the verified bibliography, the
   novelty check, the config audit and Phase 4B all sit on six unmerged branches, with
   clashing decision-log numbers. One of them publicly names third-party repositories.
5. **The config-audit numbers (821 / 740 / 0.4) need reconciling before use.** The pipeline
   behind them reads camelCase keys only and skips inheritance; an earlier pipeline on the
   same 1,141 hits gave 447 instances / median 0.5. "740 repos" is the search index, not the
   repos that contributed instances (310).

---

## 1. Current research story

### 1.1 The story as it stands

| Element | Current understanding |
|---|---|
| **Problem** | Resilience4j exposes the sliding window (COUNT_BASED: last W calls; TIME_BASED: last T seconds) and `minimumNumberOfCalls` (n_min) as ordinary tuning knobs. They are not interchangeable: the window is the sample the breaker estimates its failure/slow-call rate from, and its sample size is fixed by configuration (count) or set by traffic, λT (time). |
| **Motivation** | A breaker that silently cannot open, or cannot be disabled, fails without any error signal. Practitioners report the symptoms (Resilience4j #1731, #1349, discussion #1815). |
| **Gap** | Controlled evaluations of resilience libraries (ResilienceBench / Aderaldo et al., SPE) vary retry, workload and open-state settings but hold window type fixed; model-based work is not live-instrumented. No controlled, live characterisation of window type × n_min was found (search limits in §7). |
| **Research questions (as they should now be stated)** | RQ1: when can each window type evaluate and open, as a function of occupancy ρ? RQ2: does n_min mean the same thing under both window types? RQ3: where do public TIME_BASED configurations sit relative to the inertness boundary (λ*)? RQ4 (original H3): does window configuration affect recovery? |
| **Hypotheses** | H1 (variance at matched horizon) untestable; H2 (λ* crossover) null in the canary; **H2b** (ρ < 1 → inert, any window type) confirmed for TIME, falsified for COUNT; H3 (double dissociation) — see §3.4; H4 absorbed into §VI; H5 structural null; H6 open. |
| **Design** | Six Spring Boot services, 10 breakers, Toxiproxy on every hop, 3 s LATENCY toxic on the inventory proxy. Main sweep: 54 configs per topology (threshold 30/50/70 × W 5/10/20 × D_w 5/15/30 × 2 window types), LINEAR + FANOUT. Occupancy sweep (D18): 54 configs × 3. Canary: 300 runs incl. 120 null-fault. Phase 4B (D26): 72 recovery runs, gateway-verified. |
| **Variables** | IVs: window type, W/T, n_min, λ, threshold, D_w, topology. DVs: inert (never opened), `time_to_open`, `time_to_recover` (from OPEN), `half_open_to_closed`, `order_leg`, blast radius B (retired), false-trip φ, λ*. |
| **Datasets** | `master_dataset.csv` (360), `occupancy_dataset.csv` (162, unregistered on `main`), `canary_matrix_runs.csv` (300), `phase4b_postd25.csv` (72, branch only), `cb_transitions.jsonl` (sidecar), audit extraction CSV (branch only). |
| **Major findings** | (1) ρ asymmetry; (2) n_min is unsatisfiable under TIME and unenforceable under COUNT; (3) public configs cluster at λ* ≈ 0.4–0.5 req/s (pending reconciliation); (4) no false trips; (5) H5 null by construction; (6) seven — now eight — silent measurement defects. |
| **Methodological lessons** | Every defect "reported normally": clean-looking numbers with no error signal. Cluster-level inference; exact permutation floors; machine-checked exclusion ceilings; live instrumentation beat source-reading twice. |
| **Limitations** | One library/version family, one fault type, one injection point, laptop-class hosts, topology fully confounded with host, pre-D25 gateway stratum unverified, load plans sized by the IVs. |
| **Contribution (defensible today)** | A controlled, live, bytecode-verified characterisation of Resilience4j's minimum-sample gate under both window types, its two opposite failure modes, a public-configuration audit, and a construct-validity catalogue of silent measurement defects. |

### 1.2 How it evolved

| Stage | What happened | Status |
|---|---|---|
| **Paper A** "The window is an estimator" (H1 variance, H2 λ* crossover) | Killed by the Day-2 canary: trip rate flat at 1.00 (n_min pinned at 5 kept ρ ≥ 1 everywhere); H1's horizons never overlapped | Abandoned |
| **Paper A′** rescue | Same flat trip rate | Abandoned |
| **Paper B** (D-004, 2026-09-08) construct validity: H3 + H4 + H5 + metric evolution | H4's evidence became degenerate/blend-contaminated → absorbed; H5 null; H3 went through four versions (§3.4) | Partly survives as §VI |
| **H2b / D18** — H2 restated in dimensionless ρ | Clean TIME crossover; COUNT never inert → became the lead | **Current core** |
| **D23 → D25** gateway isolation defect and fix | Supplied the "unenforceable" half | **Current core** |
| **Current hybrid** | Paper A's estimator title + Paper B's construct-validity frame | Coherent only if the recovery claim is dropped or reframed |

### 1.3 Is the chain coherent?

`problem → gap → RQ → hypothesis → method → evidence → result → contribution`

| Link | Verdict |
|---|---|
| Problem → gap | OK, but the gap rests on one literature search with stated limits and three missing literatures (§7). |
| Gap → RQs | **Weak.** The RQs the paper answers (RQ1–RQ3) are not the ones `hypotheses.md` pre-registered as the spine. H2b was registered before the D7 sweep (good — and it was partly falsified), but RQ2 and RQ3 are post hoc. Say so plainly; do not present them as pre-registered. |
| RQ → method | OK for RQ1/RQ2. **Broken for RQ4:** the load plan couples fault duration to window type (§3.4). |
| Method → evidence | ρ: strong. Two directions: strong. Audit: parser issue. Recovery: confounded. |
| Evidence → "window is an estimator" | **Partial.** The evidence shows the estimator's *minimum-sample gate* differs. It does not show bias/variance differences (H1 was never testable). |
| Result → contribution | Coherent after removing "window type leaks into recovery" from the one-paragraph summary, abstract and contributions. |

---

## 2. What the two files are, and how to use them

| Source | Use it for | Do not use it for |
|---|---|---|
| **`PAPER_BRIEF.md`** | Section plan, decided positions (authorship, venue class, CRASH exclusion, H4 absorption), approved sentence templates, the "do not write" list | Recovery numbers (superseded by D26, and D26 is itself now in question), "740 repos", "version-specific gating", "ρ < 1 cannot open", the 5.46 s MDE, the deadline (2026-09-24 has passed) |
| **`PAPER_DRAFT_NOTES.md`** | *Why* each decision was made; what was retracted and when | Any number, unless the brief or this audit also carries it. Sections supersede each other (§12.3 → §19; §22.4 → D26; §26.3's 447/192 → T8) |
| **Repo `main`** | Code, the 360-row dataset, the occupancy dataset, decision log to D25 | Current status: `STATUS.md` still says H3 "confirmed", H4 "supported", CRASH "blocks writing" |
| **Unmerged branches** | D26 (Phase 4B), D27 (novelty), T2 bibliography, Figures 1–2, config audit | Must be merged and renumbered before the paper can cite a commit (§10, V4) |

**Rule going forward:** re-issue the brief (task W1) after the recovery decision, so there is
again exactly one writing authority.

---

## 3. Current verified findings

### 3.1 Re-checked for this audit

| Claim | Result |
|---|---|
| `master_dataset.csv` 360 × 36, LATENCY only, LINEAR 198 / FANOUT 162 | ✅ (re-checked) |
| Design units | 108 configurations; 90 with 3 replicates, 18 LINEAR configs with 5 (D13 top-up) — unbalanced, state it |
| Run hygiene | ✅ 3,600 of 3,600 per-breaker readings CLOSED, 3,600 of 3,600 with 0 buffered calls |
| Hosts | **FANOUT = 162/162 codespace; LINEAR = soham-local 159, jay-mac 36, jay-overnight-rerun 3.** Topology is fully confounded with host |
| D18 ρ numbers | ✅ all of them: 162/162, 0 flags; TIME 30 inert / 78 tripped; inert ρ ≤ 0.4996; tripped ρ ≥ 0.9967; COUNT 0/54 inert, ρ 0.025–4.0; λ ∈ {5, 10, 20}; λ achieved within 1.5 % of target |
| Unit of the ρ result | Inertness is identical across replicates in 36/36 TIME configs → **10 of 36 TIME configs inert, 26 trip; 18 of 18 COUNT configs trip** |
| Where the TIME boundary lies | **No design point between nominal ρ = 0.5 and 1.0.** 21 tripped rows (7 configs) sit at measured ρ 0.9968–0.9992, i.e. *below* 1 |
| n_min cap in the library | ✅ `CircuitBreakerMetrics`: COUNT → `Math.min(minimumNumberOfCalls, slidingWindowSize)`; TIME → uncapped. **Identical in 1.7.1, 2.2.0 and 2.3.0** |
| HALF_OPEN metrics | `HalfOpenState` uses `CircuitBreakerMetrics.forHalfOpen(permitted, …)`, hard-coded COUNT_BASED of size `permittedNumberOfCallsInHalfOpenState` (5 in every master and Phase 4B row) |
| λ fidelity (canary) | ✅ 38/300 off by >15 %, worst 35.3 %, 0/0/23/15 at λ = 5/20/80/320 |
| False-trip control | ✅ φ = 0/120 — but the 120 runs are **12 configurations × 10 replicates**; the CI [0, 0.031] treats runs as independent |
| Fault model | 3 s latency, 8 s read timeout, 2 s slow-call threshold, `slowCallRateThreshold` = swept failure threshold → **LATENCY trips through the slow-call rate, not the failure rate** |
| Phase 4B (D26) medians | ✅ consistent with `phase4b_postd25.csv` (e.g. COUNT D5 6.73 s, TIME W10 D5 23.61 s) |
| Recovery vs fault timing | **New:** 54/54 Phase 4B bounces began with the fault on (4.3–24.5 s before clearance); 72/72 closes began after (1.1–27.5 s after). Older sidecar: 69/69 and 62/62. Fault stays on after the trip for ~3 s (COUNT) vs 20.3 / 31.4 / 47.9 s (TIME, D_w = 5/15/30, medians). Final successful episode ≈ 3 s in both arms |
| Containment (`order_leg`) | Shows the D20 fingerprint: COUNT flat across D_w (0.10 / 0.09 / 0.19 by W), TIME rising with D_w at every W (e.g. W5: 0.39 → 0.44 → 0.46). Same load-plan dependence |
| Config audit (T8 JSON) | 1,141 hits, 740 repos **in the search index**, 455 files and **310 repos with ≥1 instance**, 821 instances, 48 distinct pairs. Parser reads camelCase keys only and does not resolve `base-config` |
| Bibliography | 16 entries (brief says 17) |

### 3.2 Claim-to-evidence map

| Claim | Evidence chain (experiment → data → unit → metric → analysis → effect) | Fig/Table | Establishes | Does NOT establish / caveat |
|---|---|---|---|---|
| **ρ asymmetry** | D18 occupancy sweep → `occupancy_dataset.csv` → **configuration** (36 TIME, 18 COUNT) → inert yes/no → deterministic tabulation, no test needed → TIME 10/36 inert at every ρ ≤ 0.5, 0/26 at ρ ≳ 1; COUNT 0/18 at ρ down to 0.025. Cross-check: trip rate 0.722 [0.583, 0.861], cluster bootstrap | Fig 1 | A structural, replicate-invariant asymmetry; mechanism verified in bytecode and by a live per-call trace (PR #59) | Where between 0.5 and 1 the TIME boundary sits; LINEAR, LATENCY, D_w = 15, threshold 50, codespace only |
| **COUNT vs TIME two directions** | Bytecode (cap) + D18 trace (n_min 200, W 5 → evaluates at 5) + 18/18 COUNT configs trip with n_min > W + D23 (gateway, n_min = 10⁶, 20 real trips) | Table T3 | The same parameter is unsatisfiable (TIME) or unenforceable (COUNT); stable across 1.7.1–2.3.0 | That practitioners actually try to disable breakers this way (plausible, unevidenced — say "an idiom one might use") |
| **Minimum-call evaluation** | Same as above | T3 | Evaluation starts at `bufferedCalls = min(n_min, W)` for COUNT; at n_min for TIME | The config-time clamp in the builder did not fire on the YAML path — do not claim both clamps operated |
| **Recovery leak** | Phase 4B → 72 runs → configuration (4 per arm per stratum) → `time_to_recover` → stratified cluster permutation → complete separation, p = 2/343,000 (design floor) | — | That, **in this harness**, TIME runs take longer from OPEN to CLOSED | **That window type affects recovery.** Fault stays on 3 s vs 20–48 s after the trip; all bounces happen under active fault |
| **Bounce behaviour** | Sidecar → HALF_OPEN episodes → outcome vs fault state | optional timeline fig | Bounce ⇔ probe under active fault; each bounce costs one D_w plus an episode (P3 slope 1.024 is the OPEN timer) | "COUNT never bounces, structurally" — COUNT's fault had always cleared already |
| **Topology / H5** | Main sweep → 324 runs → B → variance → Var(B) = 0 both sides | none needed | Under a single-proxy LATENCY fault, one experimental leg fires in both topologies | Anything about topology in general; fault never exercises parallel propagation; topology ≡ host |
| **Config corpus / λ*** | GitHub code search → 1,141 hits → instance (primary) → λ* = n_min / T → ECDF → median 0.4 (instance), 0.55 (dedup) | Fig 2, T6 | That public TIME_BASED configs exist whose λ* is well above typical low-traffic rates, and one shape reaches λ* = 20 | Prevalence of inert breakers (no traffic data); numbers until the two parsers agree |
| **False-trip control** | Canary null-fault arm → 120 runs (12 configs) → trip yes/no → proportion | text | No false trips under healthy load at λ = 20/80 | A run-level CI is optimistic; config-level bound is wide |
| **Machine effects** | D16 calibration → timing DVs only → Cliff's δ ≈ 0.02 | text | Negligible host effect on timing DVs (soham-local vs codespace) | `order_leg`, `lambda_achieved` (real host effect); jay-mac never calibrated |
| **λ fidelity** | Canary → 300 runs → `lambda_achieved` | text | Harness misses λ at 80/320; H1/H2 read achieved λ | Irrelevant to ρ (occupancy arm within 1.5 %) — say so |
| **Construct validity** | Decision log D-001, D17, D20, D21, D23, D19/§16/§22, + new recovery confound | Table T4 | Eight silent defects, each invisible in aggregate output | Generality beyond this project |

### 3.3 The central claim

**"The sliding window is a failure-rate estimator, not a tuning parameter."**

- **Supported, as a lens.** The window is the sample; COUNT fixes its size at W, TIME lets
  traffic set it at λT; the library gates evaluation on a minimum sample size and caps that
  gate for COUNT only. All three facts are verified.
- **Not supported as an empirical claim about estimator quality.** No bias, variance or
  sampling-distribution result survives (H1 untestable). Write "their sample size is
  determined differently", not "they have different sampling properties" without that
  qualifier.
- **"Failure-rate"** is narrower than the evidence: every trip in the paper went through the
  *slow-call* rate. Both rates share the window and the gate. Say "failure- and slow-call-rate
  estimate" once in §III, or retitle "outcome-rate estimator".
- **Two opposite failure modes: verified**, with one wording fix: *unsatisfiable* is relative
  to traffic. Write "when fewer than n_min calls can arrive in T seconds (ρ well below 1)",
  not "at ρ < 1" — 21 rows at ρ ≈ 0.997 did open.
- **Strength of wording allowed:** "we show, in Resilience4j (1.7.1–2.3.0 share the code
  path; experiments on 2.2.0), that…" — strong and specific. Not "circuit breakers in general".

### 3.4 H3 — current position

| Question | Answer |
|---|---|
| What H3 predicted | Double dissociation: window parameters drive `t_open` and **not** `t_rec`; D_w drives `t_rec` and not `t_open` |
| What the data showed | Phase 4B (gateway-verified): TIME slower than COUNT in every stratum, complete separation, p at the design floor; KM medians 6.73 vs 23.61 s (D_w 5), 16.33 vs 35.09 s (15), 31.44 vs 65.17 s (30) |
| Team position (2026-09-22) | H3 falsified; the finding is "the recovery leak" |
| **What the new check shows** | The difference comes from the protocol. `compute_load_plan()` keeps the fault on for W + D_w + 10 s (TIME) vs 40–60 calls at 10 req/s (COUNT); `time_to_recover` starts at OPEN. Every bounce started under active fault; every close started after clearance. The final successful episode is ~3 s in both arms. HALF_OPEN ignores window type in the bytecode |
| **Supported or falsified?** | **Neither. H3's recovery-side negative control was not tested**, because the design made fault exposure a function of window type and window size. The library-level evidence is *consistent with* the negative control holding, but that is not a designed test |
| What "recovery leak" means now | A measured property of the harness: recovery time from OPEN inherits the fault-exposure schedule. It is a construct-validity defect (#8), not a library finding |
| Mechanism established | Bounce ⇔ HALF_OPEN probes sent while the fault is on; each bounce costs one D_w plus a ~3 s episode (P3 slope 1.024 is the OPEN timer) |
| Ruled out | Shared root cause with H2b (Lead 2); n_min governing HALF_OPEN (Lead 2); the ~9.8 s residual (D22 update); **"time-based window retains fault evidence into recovery"** (bytecode + sidecar, this audit); "COUNT never bounces structurally" |
| Still uncertain | Recovery under equal fault exposure (untested; predicted: no window-type effect); whether anyone on the team sees a flaw in this check (independent re-run needed) |
| Wording | Never "H3 confirmed/supported". Pending the decision, not "H3 falsified" either. Suggested: *"Our protocol coupled fault duration to window type, so H3's recovery-side control could not be tested; we report the apparent effect as a measurement defect."* |

### 3.5 Topology and breaker map (verified from source)

| Service | Breakers (Resilience4j instance → callee) | Config profile |
|---|---|---|
| gateway | `orderServiceCB` → order, `inventoryServiceCB` → inventory, `paymentServiceCB` → payment | `measurement-plane` (after D25: TIME, 600 s, n_min 10⁶, thresholds 100) |
| order | `inventoryServiceCB` → inventory, `sharedDbCB` → shared-db | swept `default` |
| inventory | `paymentServiceCB` → payment, `sharedDbCB` → shared-db | swept `default` |
| payment | `notificationServiceCB` → notification, `sharedDbCB` → shared-db | swept `default` |
| notification | `sharedDbCB` → shared-db | swept `default` |
| shared-db | none (leaf) | — |

- **LINEAR** (`/api/v1/linear`): gateway → order → inventory → payment → notification; each
  interior service also calls shared-db.
- **FANOUT** (`/api/v1/fanout`): the **gateway** calls order, inventory and payment in
  parallel (3-thread pool, `CompletableFuture`), returns 503 if any fails. Each callee then
  continues its own chain, so inventory is reached both directly and via order.
- **`/mesh`** is `return fanout();` — an alias, not a topology.
- All hops go through Toxiproxy (8661–8665). LATENCY is a 3,000 ms toxic on the
  inventory proxy, which carries **both** order→inventory and (FANOUT) gateway→inventory. The
  experimental breaker it exercises is `order:inventoryServiceCB` in both topologies.
- Postgres 15 and DynamoDB-local run in Compose but no service config references them —
  confirm before listing them in §III.

---

## 4. Superseded or retracted — never return

Everything in the brief's §4 list, plus:

| Item | Why |
|---|---|
| p = 0.025 / "80 assignments" / "~2 s vs ~19 s" / "solid at D_w=5, weak at 15, untestable at 30" | Superseded by D26 (Phase 4B) |
| D26's p = 5.83 × 10⁻⁶ and 3.51× / 2.15× / 2.07× **as evidence of a window-type effect** | Correct numbers, wrong construct (fault exposure) |
| "A time-based window retains fault evidence for its full duration T, so recovery must outlast the window" | Contradicted by bytecode and sidecar |
| "COUNT_BASED never bounces — structural" | Its fault had always cleared first |
| "Window type leaks into recovery — a stage it should not reach" (brief §1) | Same |
| "H3 falsified" as a flat statement | Pending decision; the falsification is confounded |
| MDE 5.46 s on `time_to_recover` | DV confounded |
| "The evaluation-gating behaviour is version-specific (javap)" | Gating is identical in 1.7.1/2.2.0/2.3.0. The version-specific javap finding was the named-profile inheritance behind D23 |
| "A time-based breaker at ρ < 1 … structurally unable to open" | 21 rows at ρ ≈ 0.997 opened |
| "740 repos" as the size of the TIME_BASED corpus | 740 = search index; 310 repos contributed instances |
| 447 / 192 / 0.5 and `audits/out/report.*` | Earlier parser; the report names repositories |
| Containment δ = −0.987 | Carries the load-plan fingerprint; brief already permits scoping out |
| Repo figures `fig1`, `fig2`, `fig3`, `fig7` | Retired DVs / blend-contaminated τ curve |
| `STATUS.md` H3 "Confirmed", H4 "Supported", "FANOUT CRASH blocks writing" | Superseded by later decisions |
| README "blast radius is the primary DV", "324 runs", "orderServiceCB structurally never OPEN" | Stale / false pre-D25 |

---

## 5. Methodology and statistics — closed vs open

| Issue | Status | Detail |
|---|---|---|
| Row vs cluster unit (pseudoreplication) | **Closed** for the recovery test (cluster permutation, D19 §5.2 closed 2026-09-19). **Partial** elsewhere | ρ: report configurations (10/36, 18/18) beside rows. φ: 12 configs × 10 reps — state the unit. Containment CI unit unknown (moot if scoped out) |
| Unattainable p-values | **Closed** | Floor guard on cluster n; Monte Carlo quoted as `p < 5e-5 (20,000 resamples)` |
| Independence across runs | **Partial** | Load-start state clean (3,600/3,600). DB state not reset between Phase 4B runs (D26). Containers recreated per config |
| Replication / sample size | **OK for structural claims** | ρ and two-directions are deterministic per config; no power argument needed |
| Censoring | **Closed** (D19, D21) | Rate + conditional timing; KM where needed |
| Multiple comparisons | **Open (text only)** | One paragraph: effect sizes primary, headline results structural |
| Effect sizes / CIs | **Partial** | ρ needs counts, not p. Trip rate CI exists. Audit needs grouping-sensitivity table |
| Bootstrap design | **Closed** (cluster by config) | — |
| Permutation validity | **Partial** | Exchangeability rests on designed (not randomised) config assignment plus seeded run order — say "design-based test of the sharp null". Moot for recovery if reframed |
| Power / MDE | **Open (wording)** | d ≈ 3.07 describes main-sweep timing DVs, which no headline result now uses. Drop it, or keep one clause for the H5/H2 nulls |
| Host effects | **Open** | Topology ≡ host. D16 covers timing DVs only; `order_leg` and `lambda_achieved` not cleared; jay-mac never calibrated |
| Request-rate fidelity | **Closed for ρ** (≤ 1.5 %); canary only affected | Say both |
| Timing resolution | **Partial** | `time_to_open` from a 0.2 s gateway poll (upward bias); `fault_cleared_at` 1 s; sidecar ns. No headline claim depends on sub-second timing |
| **Confounding: load plan sized by IVs** | **Open — critical, new scope** | Fault duration and measurement window depend on window type, W and D_w. Hits `throughput_loss` (D20, known), `time_to_recover` (new), `order_leg` (new). Does **not** hit inertness or `time_to_open` (fault on from t = 0) |
| Topology / chain depth | **Scope** | One injection point, one depth; H5 null is by construction |
| Fault-type confounding | **Closed by scope** | LATENCY only; CRASH and THROTTLE excluded with stated reasons |
| Slow-call vs failure path | **Open (text)** | State in §III that LATENCY trips via slow-call rate |
| D23 gateway stratum (COUNT × D_w 15/30, master dataset) | **Open, but narrow** | Affects main-sweep COUNT rows only. ρ result is immune: TIME gateway could not trip; every COUNT row tripped anyway, and a gateway trip can only suppress interior trips |

---

## 6. Evidence gaps

| # | Gap | Blocks | Smallest fix |
|---|---|---|---|
| E1 | Recovery comparison confounded by fault exposure | §V-D, §VI, abstract, contributions | Team decision; optionally a confirmatory run with equal post-trip fault exposure |
| E2 | Two audit parsers disagree (447 vs 821 instances; camelCase-only; no inheritance) | §V-E, Fig 2 | One canonical extraction handling both key styles and `base-config`; re-run groupings |
| E3 | λ* = 20 "three independent repos" claim comes from the old parser | §V-E | Re-derive on the canonical extraction; check forks |
| E4 | Containment carries the load-plan fingerprint | §V-B | Scope out (brief permits) |
| E5 | ρ boundary only bracketed in (0.5, 1.0] | §V-A wording | Fix wording (no new runs needed) |
| E6 | Gateway-isolation status of master COUNT × D_w 15/30 | §VII | Use the brief's fallback paragraph; note ρ immunity |
| E7 | H6 testability | §VII | Leave open, one clause |
| E8 | Released artefacts | Reproducibility | Merge, tag, manifest (§10) |

---

## 7. Literature and novelty

**State of the bibliography.** 16 entries on `docs/bibliography-t2` (not 17), DOIs checked
against landing pages in T2. Weak spot: Bansal et al. 2025 (*Innovative Journal of Applied
Science*) is a low-visibility venue — keep it as context only, never load-bearing.
ResilienceBench's "holds window type fixed" came from summaries — **someone must read the
paper's experimental-configuration section** before §II says it.

**Literatures the search did not cover (candidates — verify every field by DOI before citing):**

| Area | Why a reviewer will raise it | Candidates to check |
|---|---|---|
| Failure detectors / accrual detectors | The classic "sliding window of observations as an estimator" in distributed systems — the estimator framing's nearest precedent | Chen, Toueg & Aguilera, *On the QoS of failure detectors* (IEEE TC, 2002); Hayashibara et al., *The φ accrual failure detector* (SRDS 2004) |
| Configuration errors | The paper's "configuration surface hides the hazard" claim and the audit | Yin et al. (SOSP 2011); Xu & Zhou survey (ACM CSUR 2015); Xu et al., "too many knobs" (FSE 2015) |
| Resilience / fault-injection testing | Positions the harness | Gremlin (ICDCS 2016); Filibuster (SoCC 2021); Basiri et al., *Chaos Engineering* (IEEE Software 2016) |
| Mining studies of resilience-pattern use in OSS | Nearest precedent for the config audit | Needs a search; nothing verified yet |
| Statistics | Methods section | Cliff (1993) dominance; Hurlbert (1984) pseudoreplication; Arcuri & Briand (ICSE 2011) |
| Software | Reproducibility | Resilience4j 2.2.0, Spring Boot 3.2.5, Toxiproxy 2.9.0; your own upstream issue resilience4j#2518 |

**Safe related-work claims now:** ResilienceBench is the closest controlled, live evaluation
of these libraries (after reading it); model-based analysis exists (Mendonça et al.);
practitioners report window-type surprises (#1731, #1349, #1815).

**Strongest defensible gap statement:**
> Controlled evaluations of resilience libraries vary retry, workload and open-state
> parameters but hold the window type fixed, and practitioner reports describe window-type
> surprises without their conditions. We characterise the minimum-sample gate of both window
> types under controlled fault injection, confirm it in the library's bytecode, and measure
> where public configurations sit relative to it.

**Novelty wording.** The brief's pre-committed fallback still says "first". Replace it:
> *To our knowledge, no prior study has characterised …* (with the search scope in a footnote)

No "first", no "novel", unless the §7 searches come back empty *and* are documented.

---

## 8. Figures and tables

| ID | Purpose | Source | Variables | Section | Exists? | Action | Need |
|---|---|---|---|---|---|---|---|
| **Fig 1** | ρ asymmetry | `occupancy_dataset.csv`, `analysis/occupancy_asymmetry_figure.py` (branch T4) | ρ (log) × `time_to_open`, inert sentinel, by window type | §V-A | Yes (`fig8_…`) | Small regen: drop in-plot title; caption defines ρ per arm (TIME λT/n_min, COUNT W/n_min) and says "inert at every sampled ρ ≤ 0.5; opened at every sampled ρ ≈ 1 or above"; IEEE column sizing | **Necessary** |
| **Fig 2** | λ* in public configs | T8 script + canonical extraction | λ* ECDF, instance vs dedup, quartiles, λ* = 20 by shape | §V-E | Yes (`fig9_…`) | **Regenerate after E2**; y-label "instances", fix overlapping quartile labels | **Necessary** |
| Fig 3 recovery decomposition | — | — | — | — | — | **Drop** (brief) — and do not revive | — |
| Fig 4 state machine | — | — | — | — | — | Drop (brief) | — |
| Fig R (new) | One TIME and one COUNT run on a timeline: fault on/off, OPEN/HALF_OPEN/CLOSED | Phase 4B sidecar | time × state | §VI | No | Build only if §VI needs it | Optional |
| **T1** | System and breaker map | Source (§3.5) | service, breakers, profile | §III (repeat near §VI's blending item) | Here | Draft | **Necessary** |
| **T2** | Design: every sweep's IVs, levels, runs, hosts | datasets | per sweep | §IV | No | Build | **Necessary** |
| **T3** | Two directions | bytecode + D18 + D23 | window type, n_min semantics, failure mode, evidence | §V-A | Brief has it | Add evidence column | **Necessary** |
| **T4** | Eight construct-validity defects | decision log | defect, what reported normally, where visible | §VI | Partly | Build (add #8) | **Necessary** |
| T5 | Load-plan exposure by arm | `compute_load_plan`, sidecar | arm, plan length, fault-on after trip | §VI | No | Build; unifies D20, containment, recovery | Recommended |
| **T6** | λ* by grouping (instance / file / repo / dedup) | T8 JSON after E2 | n, Q1, median, Q3, max | §V-E | JSON only | Build after E2 | **Necessary** |

Do not use the existing repo figures `fig1`–`fig3`, `fig7`.

---

## 9. Section-by-section readiness

| Section | Status | Exactly what is missing |
|---|---|---|
| Title | READY AFTER VERIFICATION | Drop any recovery implication; decide "failure-rate" vs "outcome-rate" |
| Abstract | BLOCKED BY ANALYSIS/DATA | Recovery decision (E1), audit numbers (E2); write last |
| Contributions | BLOCKED BY ANALYSIS/DATA | E1 changes the list; novelty wording needs §7 |
| Introduction | BLOCKED BY LITERATURE | Gap and novelty sentences; opening (three-source argument) can be drafted, but its "821 instances, median 0.4" needs E2 |
| Related Work | BLOCKED BY LITERATURE | §7 searches; read ResilienceBench |
| Research Gap | BLOCKED BY LITERATURE | Same |
| RQs / Hypotheses | READY AFTER VERIFICATION | H3's status (E1); mark RQ2/RQ3 as post hoc |
| System Under Study | **READY TO DRAFT** | Use §3.5; add slow-call path, timeouts, permitted = 5, shared-db leaf |
| Methodology | READY AFTER VERIFICATION | Load-plan description and its consequence; hygiene sentence (verified); exclusions (two sentences) |
| Experimental Setup | **READY TO DRAFT** | Versions verified; host table (topology ≡ host) |
| Fault Model | **READY TO DRAFT** | 3 s latency at inventory proxy; one experimental breaker exercised; CRASH/THROTTLE exclusions |
| Metrics | READY AFTER VERIFICATION | Drop or re-anchor `time_to_recover`; drop `order_leg` if §V-B is scoped out |
| Statistical Analysis | READY AFTER VERIFICATION | Units per claim; MDE sentence; multiple-comparisons paragraph |
| Results §V-A (ρ) | **READY TO DRAFT** | Apply the wording fixes in §3.3 |
| Results §V-B (containment) | BLOCKED BY ANALYSIS/DATA | Scope out (recommended) |
| Results §V-C (H5) | **READY TO DRAFT** | Frame as a null by construction |
| Results §V-D (recovery) | BLOCKED BY ANALYSIS/DATA | E1 |
| Results §V-E (audit) | BLOCKED BY ANALYSIS/DATA | E2, E3 |
| Results §V-F (control) | **READY TO DRAFT** | State unit (12 configs) |
| Discussion | BLOCKED BY ANALYSIS/DATA | E1 |
| Construct Validity §VI | READY AFTER VERIFICATION | Add defect #8; correct the "version-specific" line; closing paragraph's "ρ < 1" wording |
| Threats to Validity | READY AFTER VERIFICATION | Host confound; load-plan confound; fix external-validity claim (gating is not version-specific) |
| Reproducibility | BLOCKED BY ANALYSIS/DATA | Merge, tag, manifest (P1) |
| Conclusion | BLOCKED BY ANALYSIS/DATA | Write last |
| References | BLOCKED BY LITERATURE | §7 |
| Figures | READY AFTER VERIFICATION (Fig 1) / BLOCKED (Fig 2, E2) | — |
| Tables | READY TO DRAFT (T1–T5) / BLOCKED (T6, E2) | — |

---

## 10. Remaining task inventory

Priority: P0 = before final writing; P1 = before submission; P2 = polish.

### Research / Experimental

| ID | Task | Why it matters | Status | Evidence/input needed | Output | Section | Depends | Pri | Blocks writing? |
|---|---|---|---|---|---|---|---|---|---|
| R1 | Decide the recovery result's disposition | The paper's second-biggest claim may be a harness artefact | Open | This audit, V1's re-run, both authors | Decision-log entry (append-only, e.g. D28): H3 "not testable as designed"; recovery → §VI defect #8; or commission R2 | §I, §V-D, §VI, abstract | V1 | P0 | **Yes** |
| R2 | *(Only if R1 chooses it)* Confirmatory run with equal fault exposure | Turns a confound into a designed test of H3's control | Not started | Harness change: clear the fault at a fixed offset after the first OPEN for both arms; live verification; prediction written first | ~36 runs (2 arms × 3 D_w × 2 W × 3 reps), ~1.5 h one host | §V-D | R1 | P1 | No (paper can go without it) |

### Data / Validation

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| V1 | Independent re-run of the fault-timing check | A result this large needs a second pair of eyes | Script ready: `analysis/recovery_fault_timing_check.py` | Both sidecar files; 3 raw timelines inspected by hand | Confirmed/refuted counts | §V-D, §VI | — | P0 | **Yes** |
| V2 | Reconcile the two config-audit parsers | Only evidence about software outside the lab | Open | Jay's local `audits/.cache/` | One extraction (both key styles, `base-config`), re-run groupings, repo count that contributed instances | §V-E, Fig 2, T6, §I | — | P0 | Yes, for §V-E |
| V3 | Re-derive the λ* = 20 case | Its "independent authors" claim is from the old parser | Open | V2 output, fork check | Shape + count | §V-E | V2 | P1 | No |
| V4 | Integrate branches into `main` | Paper must cite one commit | Open | Merge order; renumber decision-log (config audit "D25" clashes with main's D25; notes' "D26" = D22 update) | Clean `main`; `STATUS.md`/`hypotheses.md` updated | all | R1 | P1 | No |
| V5 | Remove third-party repo names from the public remote | Ethics; corpus contained credentials | Open — **your call** (it rewrites a public branch) | `audits/resilience4j-timebased-config-audit` carries `report.json`/`report.md` with repo names and URLs | Scrubbed or deleted branch | §V-E methods | — | P0 | No |

### Statistics

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| S1 | Statistical reporting pass | Units and scope must match each claim | Open | §5 table | ρ at config level; φ unit; MDE dropped or scoped to nulls; multiple-comparisons paragraph; containment scoped out | §IV, §V | R1 | P0 | No (do while drafting) |

### Literature

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| L1 | Targeted searches for the four uncovered areas (§7) + read ResilienceBench | A reviewer who knows failure detectors or config-error work will otherwise sink the framing | Open | Scholar/DBLP/ACM DL | Rows added to `related-work.md` | §I, §II | — | P0 | Yes, for §I/§II |
| L2 | Finish the bibliography | Every entry DOI-checked | 16 done | L1 results | Verified `references.bib` incl. software and methods refs | refs | L1 | P1 | No |

### Figures / Tables

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Finalise Fig 1 | Lead figure | Exists on branch | Caption per §8 | Regenerated PDF | §V-A | — | P1 | No |
| F2 | Regenerate Fig 2 | Numbers change with V2 | Exists on branch | V2 | Regenerated PDF | §V-E | V2 | P1 | No |
| F3 | Build tables T1–T6 | Carry design and the two-directions claim | T1, T3 drafted here | §3, §8 | LaTeX tables | §III–§VI | T6 needs V2 | P1 | No |

### Writing

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| W1 | Re-issue the brief (v2) | Restore one writing authority | Open | R1, this audit | `PAPER_BRIEF.md` v2 | all | R1 | P0 | **Yes** |
| W2 | Draft §III, §IV, §V-A, §V-C, §V-F | Ready now | Open | §3.5, verified numbers | Draft text | §III–§V | W1 (can start before) | P0 | — |
| W3 | Draft §VI and §VII | Eight defects; corrected threats | Open | R1, T4 | Draft | §VI–§VII | R1 | P0 | — |
| W4 | Draft §V-E | Audit result | Open | V2 | Draft | §V-E | V2 | P1 | — |
| W5 | Draft §II and §I | Needs literature | Open | L1 | Draft | §I–§II | L1 | P1 | — |
| W6 | Conclusion, abstract, title, contributions | Last | Open | All results | Draft | front/back | all | P1 | — |
| W7 | Consistency and disclosure-budget pass | Every number traced to §3.2; chores get a clause | Open | Full draft | Checked draft | all | W6 | P2 | — |

### Reproducibility

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| P1 | Tag + manifest | "Repo is public" ≠ "study is reproducible" | Open | V4 | Tag (e.g. `paper-v1`); manifest: per-claim dataset, row subset, script, commit; versions (Java 17, Spring Boot 3.2.5, R4j 2.2.0, Toxiproxy 2.9.0, Python pins in `ml/requirements.txt`); canary `arm` join recipe; audit extraction limits; data-availability statement | §VII-E | V4 | P1 | No |
| P2 | Fix README, `STATUS.md`, `DATA_DICTIONARY.md` drift | A reviewer reads these first | Open | — | Updated docs | — | V4 | P1 | No |

### Submission / Formatting

| ID | Task | Why | Status | Input | Output | Section | Depends | Pri | Blocks? |
|---|---|---|---|---|---|---|---|---|---|
| X1 | Confirm venue, deadline, review mode | Brief's deadline (2026-09-24) has passed; double-blind would require anonymising the public repo | Open — **your call** | You | Venue, date, page limit, anonymisation plan | all | — | P0 | Sets the budget |
| X2 | Final build | No `\pending{}`/`\verify{}`, ≤ 9 pages | Open | Draft | PDF | — | W7 | P2 | — |

---

## 11. True blockers

**Must happen before writing the final paper:**

1. **V1 + R1 — the recovery decision.** It changes the one-paragraph summary, the abstract,
   the contribution list, §V-D and §VI's count.
2. **W1 — brief v2.** Otherwise drafting follows a document with known-wrong lines.
3. **X1 — venue, deadline, review mode.** Sets page budget and whether the repo must be
   anonymised.

**Must happen before specific sections, not before writing starts:**

- V2 → §V-E, Fig 2, T6, the intro's opening numbers.
- L1 → §I, §II, novelty sentence.

**Can run in parallel with writing:** §III, §IV, §V-A, §V-C, §V-F, T1–T5, Fig 1, V4, V5, P1, P2.

---

## 12. Recommended execution order

```
V1  re-run the fault-timing check together, inspect raw timelines
 → R1  record the recovery decision (decision log, append-only)          [R2 optional]
 → W1  brief v2                                   X1 venue/deadline/review mode (you)
 → in parallel:
      W2  draft §III, §IV, §V-A, §V-C, §V-F + tables T1–T5 + Fig 1
      V2  parser reconciliation (Jay, needs local cache) → V3 → F2 → W4 §V-E
      L1  literature searches → L2 → W5 §II, §I
      V5  scrub repo names from the public branch (your decision)
 → W3  §VI (eight defects) + §VII threats
 → V4  merge branches, renumber decision log → P2 docs → P1 tag + manifest
 → W6  conclusion → abstract → title → contributions
 → W7  consistency + disclosure-budget pass → X2 final build
```

Changed from the default sequence because the recovery finding has to be settled before
anything else, while system/method/ρ sections do not depend on it and can start at once.

---

## 13. The first task to do together

**V1 → R1: confirm or refute the recovery confound, then record the decision.**

1. Run `python analysis/recovery_fault_timing_check.py` on `data/cb_transitions.jsonl` and on
   the Phase 4B sidecar (`git show origin/h3-evidence-audit:data/cb_transitions.jsonl`).
2. Open three raw records by hand (one COUNT, TIME W5 D5, TIME W20 D15) and check that the
   bounces sit before `fault_cleared_at`.
3. Read `compute_load_plan()` and the `toxiproxy.reset_all()` call in `run_experiment_run()`
   together, to confirm the fault stays on for the whole plan.
4. Choose: report recovery as construct-validity defect #8 (no new runs), or also run R2.
5. Append the decision to the decision log and start brief v2.

About an hour, no new data needed.

---

## Appendix — how each check was run

| Check | Command / source |
|---|---|
| Dataset, hygiene, hosts | pandas on `data/master_dataset.csv` (parse `cb_state_pre`/`buffered_calls_pre` per breaker) |
| ρ numbers, config-level unit | pandas on `data/occupancy_dataset.csv`, n_min from the `-M{n}` suffix |
| Library gate | `javap -c -p` on `resilience4j-circuitbreaker-{1.7.1,2.2.0,2.3.0}.jar` from Maven Central, class `internal.CircuitBreakerMetrics` and `CircuitBreakerStateMachine$HalfOpenState` |
| Recovery vs fault timing | `analysis/recovery_fault_timing_check.py` (self-test included) |
| Phase 4B values | `git show origin/h3-evidence-audit:data/phase4b_postd25.csv` |
| Canary λ fidelity and φ | pandas on `data/canary_matrix_runs.csv`; `analysis/out/canary_readout.json` |
| Config audit | `git show origin/analysis/lambda-star-ecdf-t8:analysis/out/lambda_star_ecdf.json` and the script's `_walk`/extract code |
| Topology | `GatewayController.java`, `*DownstreamService.java`, `application.yml`, `infra/docker-compose.yml` |
