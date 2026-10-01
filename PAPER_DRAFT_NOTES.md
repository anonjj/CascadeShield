# Paper draft — provenance, evidence, and handoff notes

**Written:** 2026-09-16 · **Revised:** 2026-09-17 (mechanism investigations; KM correction)
**Describes:** `cascadeshield.tex` (7-page IEEEtran draft)
**Purpose:** so a future session (or a future you) can tell what in that draft is
grounded, what is reconstructed, and what is a guess wearing a confident sentence.

Read this before revising the draft. It is the audit trail the draft itself cannot carry.

> **The draft `.tex` has NOT been updated and is now substantially wrong.**
> Sections 12–16 below say what needs to change. Do not show or submit it first.
> Specifically: §V-D's Table II prints p=0.0005 and "36/36" (both wrong, §13);
> its whole three-level COUNT progression is a confound (§15); and §III-D's
> claim that the gateway "cannot trip" is false for COUNT_BASED (§15).

---

## 0a. What changed on 2026-09-17 (mechanism investigations)

Three investigations landed. Two closed cleanly, one is partial. One correction
to already-published numbers.

- **Lead 1 (H2b mechanism) — confirmed by call-level evidence.** §V-A's claim
  stands; its citation upgrades from inference to a live per-call trace. My
  config-time clamp hypothesis was **wrong** — see §12.
- **Lead 2 (HALF_OPEN gate) — hypothesis killed cleanly.** `permittedNumberOf-`
  `CallsInHalfOpenState` governs, not `minimumNumberOfCalls`. §IV-A's assumption
  was right and is now proven. H2b and H3 do **not** share a root cause.
- **Bounce mechanism (D22) — confirmed, dominant, partial.** COUNT_BASED never
  bounces (0/18); TIME_BASED's bounce count rises with window size. R²=0.862,
  ~6.4 s per bounce, with a ~9.8 s residual still unexplained.
- **KM table corrected: n=34, not 36.** Two lid-sleep records were inside the
  published 36. Medians and ratios unchanged; p-values moved. See §13.
- **D23 — the gateway was never isolated for COUNT_BASED.** The measurement-plane
  block never pins `slidingWindowSize`/`slidingWindowType`, so the gateway's real
  gate is `min(1000000, slidingWindowSize)`. 20 of 73 sidecar records show a real
  mid-run gateway trip. This invalidates H3's published shape and puts a third of
  the main dataset in unknown status. **The largest correction so far — see §15.**
- **A reported p-value is below its own exact floor.** p=0.0082 at n=2 is not
  attainable; the permutation floor is ≈0.036. See §16.
- **Infrastructure verified (§29).** Gateway image confirmed to carry D25 by
  reading the packaged jar. **Correction: all three gateway breakers are on the
  FANOUT path** — the gateway fans out itself, so FANOUT needs all three canaried,
  and §III-A's description of the topology is wrong. `/mesh` is an alias for
  `/fanout`.
- **H3 is a falsified prediction (§28).** H3 predicted window settings would *not*
  affect recovery. They do — so H3 fails by its own negative control. The recovery
  leak is the finding; it must not be written as "H3 confirmed." Needs Soham and
  Jay to agree, and a check of Soham's pre-registered Phase 4B plan.
- **Acceptance audit (§27).** Eight gaps in these notes as a *writing brief*.
  Biggest: **the novelty claim has never been verified** — no systematic prior-art
  search has ever been run against it, and it is the one risk internal rigour
  cannot defend. Also: no fallback wording if the D23 region stays unverified, no
  figure plan, and the quoted MDE does not apply to H3's headline test.
- **H4 absorbed into §VI, not demoted (§26).** "Demote to descriptive" was the
  earlier recommendation and is wrong — an orphan subsection costs space and
  carries no claim. H4's content is §VI's argument; only the Kendall number is
  separate, and it is degenerate. Freed subsection goes to the D25 config audit.
  Includes the CRASH-exclusion companion decision.
- **Disclosure budget (§25).** The paper is accumulating more self-criticism than
  is good for it. §VI's defects are a contribution; host-sleep exclusions are
  hygiene. Corrects the "all four caught by an automated rule" claim — two were
  not — and cuts §IV-E to two sentences.
- **§VI's framing corrected (§24).** The "hidden information" thesis is retracted
  — it fits 1 of 6 own-defects, not 3. The draft's existing distribution/parameter-
  surface framing holds seven for seven, and gains a closing paragraph tying it to
  §V-A: every defect failed *by reporting normally*.
- **Objection #4 fully closed (§23).** `buffered_calls_pre` checked alongside
  `cb_state_pre`: 3,600 per-breaker observations, both clean, zero exceptions.
  Both leakage modes now measured rather than one.
- **Stratified cluster permutation verified (§22).** p = 0.025 confirmed as the
  attainable floor by enumerating all 80 assignments. D19's last "Revisit if"
  closed; no verdict flipped. Floor rule refined: 1/C is the hard floor for any
  permutation test, 2/C the attainable two-sided minimum for a rank-based one.
- **Decision log audited (§20, §21).** §VI had two fabrications and one omission;
  D19 has an **unclosed clustering defect that undercuts the p-floor guard** (§21.1);
  D-004 names H4 load-bearing, which the H4-demote decision contradicts (§21.3).
- **§VI audited against the real decision log (§20).** Two fabricated claims found
  and one omission that **retracts the "lead with the τ curve" advice** — D-001's
  informative band may be an artifact of D17's blending bug. Closes the §6 gap.
- **D26 — H3's mechanism CLOSED (PR #68).** Full chain established; the ~9.8 s
  residual dissolves entirely. Retracts §12.3's two-component framing. **The
  largest positive content change of the session — see §19.**
- **D25 — measurement-plane fixed and live-verified.** D23's mechanism confirmed
  by dump (not my alternative explanation); the defect was confined to one config
  block; fix verified by a real fault run. **Forward-only** — no already-collected
  data is cleaned. See §18.

---

## 0. What changed in the 2026-09-16 revision

- **H3 closed and written up in full** (§V-D, Table II). Was a `\pending{}` block.
- **Metric evolution gained a fifth instance** (§VI) — the probe-window ceiling,
  which is qualitatively different from the other four and is argued as such.
- **Abstract, contributions and conclusion** updated: three results → four;
  "three metric definitions" → "five defects."
- **Statistical treatment** (§IV-E) now states that KM was actually used, and
  documents the wall-clock quarantine.
- **Two placeholders filled** from confirmed tool output: `cb_state_pre` 360/360,
  and the dataset row counts in the abstract.
- **Repo is now public**, so the §1 evidence base is no longer the constraint it was.
- Draft grew 6 → 7 pages. Limit is 9.

---

## 1. What I actually had when I wrote it

### Read directly

| Source | How | Confidence |
|---|---|---|
| `docs/paper/hypotheses.md` (431 lines) | uploaded, read end to end | High |
| `docs/paper/decision-log.md` (852 lines) | uploaded, **listed but never opened** | **None — see §6** |
| `STATUS.md` | pasted | High |
| `README.md` | fetched from the now-public repo | High, but **the README itself is stale — see §6** |
| git log, branches, `gh pr list` | pasted | High |
| `cb_state_pre` / `excluded_reason` value counts | pasted tool output | Highest in the paper |
| H3 Kaplan–Meier readout (36 runs) | pasted, post-PR #57/#58 | High |
| Resilience4j config defaults + validation rule | web, Camel's rendering of `CircuitBreakerConfig` | Medium — **verify in 2.2.0 source** |
| Screenshot: "Ten reviewer objections" | uploaded image | High |
| Project memory of earlier sessions | my own stored notes | Medium — see §6 |

### Still never seen

- **Any dataset.** Not one row of `master_dataset.csv`, `occupancy_dataset.csv`,
  `canary_matrix_runs.csv`, or the standalone recovery dataset.
- **`cb_transitions.jsonl`.** Described in prose only; never a record.
- **`docs/paper/statistical-treatment.md`** (D19), `data/DATA_DICTIONARY.md`,
  `leak-audit.md`, `leg-metric-blending.md`, `decision-log.md`.
- **Source files.** `runner.py`, `analysis/common.py`, `breaker_observer.py`,
  `quarantine.py`, the corrected `half_open_survival.py`. The repo is public now,
  so this is fixable on request rather than a hard limit.
- **The 10 related-work PDFs.** Bibliography is reconstructed — §5.

---

## 2. Claim-by-claim provenance

### Safe to keep

| Draft claim | Source |
|---|---|
| ρ sweep: 54 configs, 162/162, 0 aborts, 0 deviation flags | hypotheses.md §3.2 (D18) |
| TIME: inert ρ ≤ 0.4996, tripped ρ ≥ 0.9967, range [0.1249, 79.79] | hypotheses.md §3.2 |
| COUNT: all tripped, ρ ∈ [0.025, 4.0], zero inertness | hypotheses.md §3.2 |
| Ring-buffer mechanism | hypotheses.md §3.2 + library validation rule |
| H5 not supported, Var(B)=0, 162/162 each side, LATENCY | hypotheses.md §5.5 |
| φ = 0.000 [0.000, 0.031], n=120 | STATUS.md / canary readout |
| MDE d ≈ 3.07; raw 1.12 s / 5.46 s | memory + STATUS (stratified) |
| Machine effect negligible, Cliff's δ ≈ 0.02 | STATUS.md (D16) |
| `cb_state_pre` CLOSED, 360/360, 0 excluded | **pasted tool output** |
| **H3 table: 2.04/19.34, 9.83/21.27, 14.99/35.90; all p=0.0005; 36/36 uncensored** | **pasted KM readout, post-fix** |
| **Probe-window ceiling: fixed ~4.1 s budget, censoring rose with $D_w$** | **pasted diagnosis (PR #57)** |
| Two wall-clock outliers quarantined by RECOVERY_TIMEOUT_HANG | pasted |
| THROTTLE excluded; 429 → rejected → ignored | hypotheses.md + memory |
| Throughput retired (D20) + confound mechanism | hypotheses.md §7 |
| Exception policy 4xx/5xx split | hypotheses.md, README §4.1 |
| Gateway `measurement-plane` isolation | memory — **verify in gateway `application.yml`** |
| Resilience4j 2.2.0; HALF_OPEN uses own buffer | hypotheses.md §4.1 |
| Matched-horizon diagonal band | hypotheses.md §7 |
| D17 blended-breaker defect + max-of-breakers fix | hypotheses.md §5.4/§5.5 |
| **COUNT evaluates at `bufferedCalls`=capacity, not `n_min`; config keeps `n_min`=200** | **PR #59 live per-call trace** |
| **HALF_OPEN admits exactly `permittedNumberOfCalls`, rejects past it mid-episode** | **PR #60 event trace** |
| **COUNT_BASED never bounces, 0/18; TIME bounce count rises with window size** | **D22** |

### Interpretation that is mine, not yours

The draft reads the H3 arms separately rather than through the ratio:
*count-based recovery scales at roughly 0.4–0.5 × $D_w$; time-based carries a
large fixed cost (19.34 s against a 5 s wait duration) and the shrinking ratio
is that cost being diluted.* That reading is arithmetic on your three data
points, but the "fixed cost" framing is an inference from three levels. It is
defensible and more informative than quoting 9.49×, but it is not something
your analysis scripts output. **Check it against the per-run distributions
before it goes in front of a reviewer.**

### Still deliberately unwritten

| Draft section | Why |
|---|---|
| Containment numbers (§V-B) | `analysis/out/` predates the CRASH strip; re-run first |
| Breaker map table | Derivable from `cb_state_pre`; I did not want to guess the mapping |
| Figure 1 (ρ) | Data exists; I cannot plot what I cannot read |
| H3 mechanism | See §4 — analysis only, no new runs |
| Reproducibility (§VII-E) | Needs tag + manifest |
| Future work, acknowledgment | Needs your input |

### Do NOT reintroduce

- τ_leg sensitivity table (hypotheses.md §5.1) — 79/80-row archive.
- `order_leg` means table (§5.4) — same archive, marked "do not re-quote."
- H4's "10 of 10 pairs, min τ_b = 0.238" — STATUS says 36/36, min 0.891.
  **The effect nearly collapsed when FAN_OUT data arrived.** Neither is safe
  until `tau_sweep.py` re-runs on the live 360 rows.
- D15's combined-dataset separation numbers — under explicit embargo.
- "COUNT max 0.2250 < TIME min 0.2686" — believed current, computed pre-top-up.
- Old detection-latency contrast (TIME 9.43 ± 5.41 vs COUNT 5.22 ± 2.19) —
  nominal window size, the comparison the paper argues against.
- **`p=0.0005` and "36/36 uncensored" for the H3 table.** Superseded: n=34,
  p=0.0014 at $D_w$=5/15. Medians and ratios are unchanged. See §13.
- **The H2b/H3 shared-root-cause framing.** Ruled out by Lead 2 (§12.2).
- **My config-time clamp hypothesis.** Wrong on this configuration path (§12.1).
- **The H3 COUNT progression 2.04 -> 9.83 -> 14.99 s**, and the framing that
  count-based recovery scales with $D_w$. Gateway confound (§15.4).
- **p=0.0082 at $D_w$=15.** Below its own exact floor (§16).
- **"The gateway structurally cannot trip."** False for COUNT_BASED (§15.1).
- **The "~9.8 s unexplained residual"** and §12.3's two-component framing.
  Dissolved by the decomposition (§19.2).
- **"τ = 0.50 was calibrated when the distribution was bimodal" / "after a testbed
  rebuild".** Fabricated; nothing of the sort is in D-001 (§20.1).
- **The τ sensitivity curve as a standalone construct-validity finding.** Computed
  through the unfixed blending path; D17 says the band may be an artifact (§20.2).
- **The "information exists but not where the decision is made" thesis.** Fits one
  of six own-defects; the count was padded with Resilience4j findings (§24.1).
- **τ = 0.0189, τ = 0.238, τ = 0.891.** Degenerate, pre-fix, and confounded
  respectively. None are usable (§26.4).
- **"Demote H4 to descriptive."** Superseded by absorption into §VI (§26.1).
- **"H3 confirmed", "H3 supported", "H3 holds", or `LEAK_CONFIRMED` in prose.** H3's
  prediction was falsified; the effect is the recovery leak (§28). **Superseded §30
  (2026-10-01): "the recovery leak" is itself now retracted as a harness
  fault-exposure artifact, not a library finding — H3's recovery-side control passes
  under R2. Do not write "H3 falsified" or "the recovery leak" either; see §30.**
- **"FANOUT's fan-out happens inside order-service" / "only `orderServiceCB` is on
  the FANOUT path".** Wrong — the gateway fans out directly to all three (§29.2).
- **The pre-fix H3 numbers** (9.0×–10.35×, `LEAK_SUGGESTIVE_INCOMPLETE`) and the
  even earlier 8.9×–14.3×. Both came from censored data. Superseded by Table II.

---

## 3. Judgement calls (all reversible)

1. **ρ/D18 leads Results.** Scope growth, which D-004 permits; not a reopening.
2. **No mechanism claims across fault types** — crash/injection-point confound
   becomes a scope statement.
3. **Title scoped to Resilience4j** (objection #8).
4. **Prof. Negi listed third author**, flagged. Never answered.
5. **Metric evolution framed as contribution, not apology.**
6. **Threats-to-validity answers the objections table in-paper.**
7. **New:** H3 written as "significant at every level, with different scaling per
   arm" rather than as a single headline multiplier.
8. **New:** the probe-window ceiling argued as *qualitatively different* from the
   other four defects — it manufactured an effect in the wrong direction rather
   than obscuring one, and replication would not have caught it. That is the
   strongest claim in §VI and also the most load-bearing; if a reviewer attacks
   the section, it will be here.
9. **2026-09-17:** recommending H3's mechanism be written as *two components*
   (arm-exclusive bounce mechanism + unexplained ~9.8 s offset) rather than as
   one partial mechanism. See §12.3. This is my framing, not your analysis's
   output — the numbers are D22's, the two-component split is mine.

---

## 4. H3: resolved, with the mechanism still open

**The direction reversal did not reproduce.** My synthetic self-test suggested
COUNT might be *faster* at $D_w$=30. On real data COUNT's bounds sat under
TIME's actual values, so there was never a basis for that. Both my prediction
and the "confirmed as-is" prediction were wrong.

**What was actually wrong was the instrument**, in two layers:

- My first `extract_observations` measured only the last HALF_OPEN entry,
  discarding failed-probe bounces — collapsing a real ~27 s recovery to ~2 s.
  The censoring fallback used "last event logged" rather than the harness
  deadline, producing 0.00 s censoring times. Both were my bugs; the first was
  *documented as intentional in the code comment*, which made it worse.
- The harness's `_drive_half_open_probes` used a flat ~4.1 s budget. Since
  OPEN→HALF_OPEN consumes `wait_duration` first, the observable window for the
  HALF_OPEN→CLOSED leg did not scale with $D_w$. Censoring rose with $D_w$ by
  construction.

**Fix:** poll-until-transition with a generous ceiling (PR #57), then re-collect
$D_w$=15/30 (PR #58). Result: 36/36 uncensored, all three levels significant.

**RESOLVED 2026-09-17 — see §12.2 and §12.3.** The regression below was run.
`permittedNumberOfCallsInHalfOpenState` governs HALF_OPEN, not
`minimumNumberOfCalls`; the bounce mechanism explains most of the gap; a
~9.8 s residual remains. The text below is kept as the reasoning that led
there.

**Was open — and cheap.** The mechanism is unidentified; the suspected one
(HALF_OPEN re-reading the TIME window) is architecturally ruled out.
`permittedNumberOfCallsInHalfOpenState` (3/5/10) and `slidingWindowSize`
(5/10/20) are both already swept IVs. Regress recovery on both, per arm. If
time-based's fixed cost tracks window size and count-based's does not, that
identifies it — and an identified mechanism turns H3 from an observation into
an explanation. **Analysis only, no new runs. Highest value per hour remaining.**

---

## 5. The bibliography is not trustworthy

Every entry was reconstructed from working notes. **I read none of the PDFs.**
Titles approximate the topic; they are not transcriptions. Authors and years are
roughly right. Check every field. The `\verify{}` markers exist so this cannot
be forgotten.

The related-work *framing* (window-type gap, ResilienceBench as closest
precedent) comes from your notes and is probably right, but "no prior work
treats this at the application library layer" is **your** novelty claim, not one
I independently verified.

---

## 6. Gaps I want to name explicitly

**~~I never opened `decision-log.md`.~~ CLOSED 2026-09-18 — see §20.** The audit
found exactly what this warning predicted: two fabricated claims in §VI and one
serious omission. D-001, D15, D17 and D20 are now read and checked; the rest of
the log remains unread (§20.7).

**The public README describes a different study.** Now that the repo is public
this is a live problem, not a tidiness one — your mentor and any reviewer will
read it before the paper. It currently claims: blast radius is the primary
dependent variable (D15 retired it), a 13-column CSV (you are at 36), 162
configs × 2 faults = 324 runs (live file is 360, LATENCY-only), `data/` is
gitignored (it is committed), and the roadmap ends at "Weeks 8–10: IEEE paper."
`SESSION_HANDOFF.md` is still at repo root despite STATUS.md retiring it.

**Some context came from my memory of earlier sessions**, not from anything
supplied this time: gateway `application.yml` values, exception class names,
Toxiproxy ports and injection points, the D16 λ_achieved host effect. Accurate
before; unverified against current main.

---

## 7. What to give me next, in priority order

1. **`docs/paper/decision-log.md`** — and tell me to read it. Closes §6.
2. **`analysis/out/*.json`** after re-running `tau_sweep.py` and
   `order_leg_containment.py` on the live 360 rows. Fills §V-B.
3. ~~The mechanism regression from §4~~ — **done**, see §12.3. What would help
   now: the raw event traces for the two 0-bounce COUNT W20/D30 runs (§12.3's
   open thread), and the corrected KM readout at n=34.
4. **The 10 PDFs or correct BibTeX.** Fixes §5.
5. **`docs/paper/statistical-treatment.md`** (D19).
6. **`data/DATA_DICTIONARY.md`** + the 36-column header — for the breaker table.
7. **A venue.** Still undecided. Sets template and limit. (9 pages assumed.)
8. **Authorship** — is Prof. Negi a co-author, in what position?

The repo is public now, so I can read source directly. Point me at files rather
than pasting.

---

## 8. Background: Paper A, and why B

**Paper A — "The Window Is an Estimator."** Spine was H1 + H2, labelled "the
novelty" in hypotheses.md, with H3/H5 as "the floor."

- H1: at matched horizon H, COUNT and TIME differ in *variance*, not mean, of t_open.
- H2: a crossover λ* exists below which TIME_BASED cannot trip.

**Killed by the Day-2 canary, twice.** H2 found no effect — trip rate flat at
1.00 across λ ∈ {5, 20, 80, 320}, both window types, n=15/cell; likely because
n_min was pinned at 5, so ρ never fell below 1. H1 was untestable as collected:
matched_horizon generated TIME {5,10,20} and COUNT {25…800}, zero overlap. A
**Paper A′** rescue died to the same flat trip rate. Gateway shadowing (H6),
Paper A's other mechanism, had already been removed by `measurement-plane`.

**D-004 (2026-09-08)** closed the gate on Paper B, not reopenable by later data.

**H2b is Paper A's ghost, and it worked.** Restating H2's crossover in
dimensionless units (ρ = H/n_min rather than λ) produced the clean result Paper
A was reaching for. Good line for your mentor: *the effect Paper A predicted was
found, once the hypothesis was stated in the right units.*

---

## 9. Reviewer-objection status

| # | Objection | Status |
|---|---|---|
| 1 | COUNT-vs-TIME gap is definitional | Matched-horizon framing (§IV-B) + stated band limitation |
| 2 | n=3, MDE ≈ 3.07, nulls underpowered | MDE up front (§IV-F); structural vs underpowered nulls distinguished |
| 3 | Fault type confounded with target/depth | Scope statement (§VII-B); no cross-fault mechanism claims |
| 4 | **Breaker state leak (Critical)** | **Fully closed (§23).** Both modes measured: CLOSED *and* empty window, 3,600 per-breaker observations, zero exceptions |
| 5 | ρ=1 arithmetically obvious | Answered by leading with the asymmetry (§V-A) |
| 6 | Null `time_to_open` censoring | Closed by D19; §IV-E, demonstrated in §V-D. Censoring handling now also caught a live data-integrity error (§13) |
| 7 | Six services, one laptop-class host | §VII-C + D16 |
| 8 | One library, one version | Title and claims scoped to 2.2.0 |
| 9 | No breaker-disabled baseline | **Open.** ~20-run arm not done; φ arm is partial cover |
| 10 | Not reproducible, dataset gitignored | **Partly closed** — repo is public, dataset committed. Still needs a tag, a manifest, and per-claim row counts. README staleness now hurts here too |
| 11 | TPS inflated in fast-fail | Closed — D20 |

---

## 10. Remaining `\pending{}` markers in the draft

1. Breaker map table (§III-A)
2. Figure 1 — ρ against outcome (§V-A)
3. Containment numbers, needs regenerated `analysis/out/` (§V-B)
4. H3 mechanism regression (§V-D)
5. Crash-arm scope confirmation (§VII-B)
6. Reproducibility: tag, manifest, per-claim row counts (§VII-E)
7. Future work (§VIII)
8. Acknowledgment

Everything else is written. Two of these (1 and 5) are minutes of work; two
(2 and 3) need scripts you already have; one (4) is the mechanism hunt.

---

## 11. Build

```bash
pdflatex cascadeshield.tex && pdflatex cascadeshield.tex
```

`IEEEtran.cls` ships alongside — not installed on either machine. Red
`\pending{}` = unsupported by analysed data. Blue `\verify{}` = needs checking
against a source. **Never submit with either still present.**

---

## 12. Mechanism investigations, 2026-09-17 (Leads 1 and 2, plus D22)

Three questions were opened on 2026-09-16 and resolved on 2026-09-17. PRs #59
(Lead 1) and #60 (Lead 2); D22 in the decision log for the bounce analysis.

### 12.1 Lead 1 — why COUNT_BASED never goes inert

**Result: §V-A's mechanism claim is correct. No rewrite needed. The citation
upgrades from an inferred story to direct call-level evidence.**

Method was three-stage, and the staging mattered:

1. Repo-wide grep for any clamp on `minimumNumberOfCalls` — zero matches.
2. Live `CircuitBreakerConfig` dump on order-service, three configs
   (A: window=5/min=200; B: TIME_BASED control; C: window=20/min=5 control).
   **The config object reports `minimumNumberOfCalls=200` unchanged at window=5.**
3. Live per-call trace replaying the D7 ρ=0.025 cell against the real mesh, with
   a `CircuitBreaker` event listener logging `bufferedCalls` and `failureRate`
   on every call. **Evaluation began the instant `bufferedCalls` hit 5** — the
   window capacity — never near 200, and the breaker opened shortly after.
   Reproduced `occupancy_ratio=0.0250`, `inert=False`: the exact dataset row.

**My config-time clamp hypothesis was wrong**, and step 2 alone would have sent
the paper the wrong way. `CircuitBreakerConfig.slidingWindow(size, minCalls,
type)` does contain `this.minimumNumberOfCalls = Math.min(minimumNumberOfCalls,
slidingWindowSize)` for COUNT_BASED — that part of the source reading was right —
but Spring Boot's YAML binding evidently does not route through that composite
builder, so the clamp never fires on this configuration path. The gate is
instead applied at Resilience4j's **runtime metrics layer**, which begins
evaluating once the ring buffer fills.

**Recommended wording for §V-A**, stronger than what is currently in the draft:

> Resilience4j applies the same ceiling on `minimumNumberOfCalls` in two
> independent places for count-based windows — at configuration time via
> `CircuitBreakerConfig.slidingWindow()`'s `Math.min`, and again at runtime in
> the metrics layer, which begins evaluating once the ring buffer fills. Neither
> applies to time-based windows, where the window has no capacity ceiling and
> `minimumNumberOfCalls` is therefore honoured exactly as configured — and can
> be unsatisfiable.

Two independent implementations of the same guardrail, both absent on the other
branch, is harder to dismiss as incidental than a single ring-buffer artifact.
Cite the source for the config-time half and the PR #59 trace for the runtime half.

**Caveat to keep:** the config-time clamp was *not* observed firing on this
path. Do not write it as though both fired in these experiments — write it as
two places the ceiling exists in the implementation, one of which was observed
in operation here.

### 12.2 Lead 2 — what governs HALF_OPEN recovery

**Result: `permittedNumberOfCallsInHalfOpenState` governs, not
`minimumNumberOfCalls`. §IV-A's assumption was right and is now proven rather
than assumed. The H2b/H3 unifying mechanism is ruled out.**

Discriminator: TIME_BASED (unclamped branch), `permittedNumberOfCalls-`
`InHalfOpenState=3` fixed in both arms, `slidingWindowSize=20` in both (chosen
for ~60-call headroom so the discriminator could not fail for capacity reasons),
baseline `n_min=3` vs discriminator `n_min=30`, six replicates each, live mesh.

Pre-registered before running: `n_min`-governs would show either ~10x slower or
full censoring. Both arms recovered in 19.7--20.2 s, 6/6, zero censoring. The
event trace shows why: every HALF\_OPEN episode in both arms admits exactly 3
calls, rejects everything past the 3rd outright even mid-episode, and evaluates
the instant those 3 complete. `minimumNumberOfCalls` never enters the gating
logic in either arm.

**Secondary finding worth a footnote in §IV-A and an upstream issue:** the
javadoc on `maxWaitDurationInHalfOpenState` states that the CircuitBreaker will
by default stay in HALF\_OPEN until `minimumNumberOfCalls` is completed. The
trace shows it does not. That is a documentation defect in a widely-used
library, demonstrated by direct observation. Filing it upstream costs nothing
and reviewers notice when authors do.

**What this closes off:** the hoped-for unifying claim — that window type
reaches recovery through the same clamped `n_min` path as inertness — is dead.
Do not write H2b and H3 as sharing a root cause.

### 12.3 D22 — the bounce mechanism

**Result: real, dominant, and explicitly partial. Do not write it as solved.**

- **COUNT_BASED never bounces: 0 of 18 runs.** This is the load-bearing number.
  It is structural, not a rate difference.
- TIME_BASED bounce count rises with window size: 1.33 -> 1.5 -> 1.75.
- Joint regression (not the naive decomposition, which over-explained):
  R^2 = 0.862, ~6.4 s per bounce.
- **A ~9.8 s TIME-vs-COUNT residual remains at bounce\_count=0.**
- **Two 0-bounce COUNT W20/D30 runs at ~25.3 s do not fit the model at all.**

This confirms the residual-window-contents hypothesis: a time-based window still
holds failure records from the last T seconds when the breaker re-evaluates,
while a count-based ring buffer has been overwritten by fresh successes. Larger
T means longer residual memory of the fault, so more bounces before a clean
close.

> **SUPERSEDED 2026-09-17 by §19 (D26).** The residual below does not exist —
> it is failed-episode time, accounted for by the additive decomposition. Do not
> use the two-component framing. Kept here as the reasoning that led to the
> decomposition test.

**Recommended framing for §V-D — two components, not one partial mechanism:**

1. A bounce mechanism that is *arm-exclusive*: time-based windows re-open during
   recovery; count-based structurally never do. Its dependence on window size is
   a second, independent confirmation of the paper's estimator argument.
2. A ~9.8 s offset at zero bounces, present regardless, openly unexplained.

Reporting two components is stronger than one partial mechanism, because
component 1 is qualitative — a behaviour one arm exhibits and the other cannot —
and component 2 then reads as a bounded open question rather than a shortfall.

**Open thread worth chasing before §V-D is written.** The two 0-bounce COUNT
W20/D30 runs at ~25.3 s are the most informative rows in the set. If COUNT never
bounces and a 3-probe HALF\_OPEN episode should take about a second, 25 s in a
non-bouncing count-based run is unexplained by everything above — and it is
roughly the 9.8 s residual scaled up. Pull the raw event traces for those two
and measure the gap between `OPEN_TO_HALF_OPEN` and the **first admitted probe**.
If the probes land late rather than the episode running long, the residual is
probe *arrival* latency, not recovery semantics: the harness paces at ~0.3 s
against a 3-call permit, so the breaker may simply be waiting for traffic. That
would explain component 2 across both arms and leave component 1 as the sole
real finding. Two rows, one grep.

---

## 13. Correction: the KM table is n=34, not 36

**The draft currently prints numbers that are wrong.** Fix before anyone reads it.

Two further lid-sleep-corrupted records (700.4 s, 1703.4 s) were found inside the
published 36-run H3 table — a different pair from the earlier coarse-metric
artifacts (704.6 s, 2657.1 s).

| | Published in draft | Corrected |
|---|---|---|
| n | 36/36 uncensored | **34**, two excluded |
| Medians and ratios | 2.04/19.34, 9.83/21.27, 14.99/35.90 | **unchanged** — both artifacts were cell maxima, so KM's median never moved |
| $D_w$=5 and 15 log-rank $p$ | 0.0005 | **0.0014** |
| $D_w$=30 log-rank $p$ | 0.0005 | 0.0005 |

Not a reversal, and nowhere near the significance threshold. But "36 of 36
uncensored, zero exclusions" is a claim made in print, and it is no longer true.
**§V-D's Table II caption, the surrounding text, and §IV-D's exclusion sentence
all need updating.**

`half_open_survival.py` now carries a permanent sanity-ceiling filter — flagged,
not silent — so this class of error cannot recur. A claim in D13 that the
precise metric was "immune to this artifact by construction" has been falsified
and corrected in the decision log.

**Four host-sleep artifacts total now**, all caught by an automated
ceiling/quarantine rule rather than by inspection. §IV-E should state this as a
generalisable methods point rather than an apology: laptop-class collection
hosts suspend, wall-clock-derived measurements are vulnerable to it, and the
defence is a machine-checked ceiling. The draft's §IV-E currently describes only
the first two.

---

## 14. Draft edits outstanding — SUPERSEDED by §17

In priority order. Nothing here needs new data.

| # | Section | Change |
|---|---|---|
| 1 | §V-D Table II + text | n=34, p=0.0014 at $D_w$=5/15. **Currently wrong in print.** |
| 2 | §IV-D | Exclusion sentence: two runs excluded from the recovery set |
| 3 | §IV-E | Four host-sleep artifacts, machine-checked ceiling as method |
| 4 | §V-D | Write the closed mechanism chain P1/P2/P3 (§19) — **not** §12.3's two-component framing; cite the confirmed HALF\_OPEN gate |
| 5 | §V-A | Upgrade to the two-places wording (§12.1); cite PR #59's trace |
| 6 | §IV-A | Assumption -> proven; footnote the javadoc defect |
| 7 | §V-B | Still stale — re-run `tau_sweep.py` and `order_leg_containment.py` |
| 8 | §V-A | Figure 1 (ρ vs outcome) still missing |

Plus, outside the paper: the public README still describes a different study
(see §6). That is now the first thing a mentor or reviewer will read.

---

## 15. D23 — the gateway was never isolated for COUNT_BASED

**The largest correction in this project so far.** It invalidates a published
result shape, falsifies a design claim, reopens a retired hypothesis, and leaves
a third of the main dataset in unknown status. Read this before touching §V-D,
§III-D or §VII-A.

### 15.1 What the bug is

The `measurement-plane` block hardcodes `minimum-number-of-calls=1000000` and
`failure-rate-threshold=100`, intending a breaker that cannot trip. It **never
sets `slidingWindowSize` or `slidingWindowType`**, and does not inherit from
`configs.default`. Those two fields therefore silently track whatever the sweep
is currently testing.

Combined with D18's confirmed mechanism — COUNT_BASED evaluates once the ring
buffer fills, not at the configured minimum — the gateway's real gate is:

```
min(1000000, slidingWindowSize)
```

Live replay of W20/D30 showed `bufferedCalls` climbing to 20 on ordinary
traffic, evaluation firing the instant the buffer filled, and a genuine
`CLOSED_TO_OPEN` mid-run.

**Scope:** 20 of 73 sidecar records show a real gateway trip. All COUNT_BASED,
all at `wait_duration` ∈ {15, 30}. Zero among TIME_BASED — isolation genuinely
holds there, exactly as D18's TIME_BASED finding predicts. Spans both sides of
D21, so it traces to the original measurement-plane commit (2026-07-30), not to
any recent change. Confirmed by live `CB_CONFIG_DUMP`, not inferred.

### 15.2 Why this is a finding, not just a bug

Two researchers who had already discovered, verified and written up this
mechanism still wrote a configuration that fell to it, and did not notice for
seven weeks.

**Do not bury that.** It is the most persuasive evidence in the project that the
hazard is reachable in practice — stronger than any config audit, because the
victims were the people who understood the mechanism best. It belongs in §VI as
a sixth instance: the one where the instrument was compromised by the very
effect under study.

It also yields a directly practical claim for the paper and for Lead 3's audit:

> **You cannot disable a Resilience4j COUNT_BASED circuit breaker by raising
> `minimumNumberOfCalls`.** Setting it to 10^6 looks decisive and does nothing;
> the ring buffer's capacity overrides it. This idiom is common in test
> harnesses and staged rollouts.

### 15.3 The two-directions framing for §V-A

D23 completes the asymmetry, running the opposite way from §V-A's version:

| | `minimumNumberOfCalls` is… | Failure mode |
|---|---|---|
| TIME_BASED | honoured exactly | **unsatisfiable** — a breaker meant to protect cannot open (§V-A) |
| COUNT_BASED | capped by window capacity | **unenforceable** — a breaker meant to be disabled opens anyway (D23) |

One parameter, two opposite failure modes, selected by a neighbouring enum. Live
call-level evidence for both halves. This is stronger than the draft's current
one-directional claim and should replace it.

### 15.4 What it does to H3

The within-COUNT trend was **entirely** the leak. $D_w$=30's COUNT sample is 6/6
gateway-tripped (zero clean data); $D_w$=15 is 4/6.

- **Retracted:** the published progression 2.04 → 9.83 → 14.99 s, and with it my
  "count-based scales with $D_w$, time-based carries a fixed cost" framing from
  2026-09-16. That was reading gateway contamination as a property of the
  count-based arm. **Do not re-quote either.**
- **Survives** *(but see §28 — this is the recovery leak, not H3; H3's prediction was falsified;
  **and see §30 — the recovery leak itself is now retracted, D29, H3's control passes**)*:
  the TIME-slower-than-COUNT effect, at $D_w$=5 (n=6,
  unchanged) and directionally at $D_w$=15 (n=2 clean — but see §16 on its
  p-value).
- **$D_w$=30 is now honestly untestable**, not falsely confirmed.

**§V-D must be rewritten, not softened.** On clean data H3 rests on one solid
wait duration plus a directionally consistent, statistically weak second. That
is publishable and much better than a three-level curve tracking a confound —
but it is thinner than the draft claims.

### 15.5 What it does to D22

The ~9.8 s residual mostly dissolves: 9.8 s → 2.75 s, R² 0.862 → 0.934. Most of
what looked like a TIME-intrinsic slowdown independent of bounces was gateway
confound. Bounce count explains *more* once cleaned, not less — the right
direction for the mechanism story.

**Report n and adjusted R² alongside.** The cleaned sample is roughly 8 COUNT +
14–16 TIME against 2–3 predictors. R² rising while n falls is expected and does
not by itself mean a better model. The substantive claim is sound; the raw R²
cannot carry weight it does not have.

### 15.6 Two audit by-products that are findings

**The containment metric structurally cannot see the gateway.** Both
`runner.py` and `BlastRadiusService.java` hard-exclude it from
`leg_failure_rates`, `blast_radius` and `real_blast_radius`. Methodologically
correct for measuring *interior* containment — and it means every containment
measurement was blind to the gateway precisely when the gateway was opening
mid-run. Same shape as every other instance in §VI: the instrument produced
clean-looking numbers because it could not see the problem.

**A new, unexplained host effect.** The indirect proxy shows a ~2×/1× ratio
splitting cleanly by collection batch (soham-local/codespace vs jay-mac), not by
the leak's parameter region — 1.9000 in-region vs 1.9000 out, i.e. no separation
at all. D16 cleared cross-machine splitting for the **timing** DVs specifically;
this is a different DV showing a clean host boundary. Correctly not forced into
a signal, but it should not be filed as noise either. Open observation about a
quantity the paper may rely on.

### 15.7 H6 — reopened, deliberately not re-decided

H6 (gateway shadowing) was retired as untestable because the isolation block
removed the condition. That isolation claim is now false for COUNT_BASED, so the
condition occurred anyway — and in a form the original hypothesis did not
anticipate.

Classic shadowing: the edge breaker opens first, so interior breakers never
engage. **What was observed:** the interior breaker already open and unable to
*close* until the edge breaker reopens traffic — order closed ~1.5 s after
gateway did, twice, not 1.5 s after its own HALF_OPEN began. That is
**recovery-side shadowing**, a composition effect of exactly the kind this paper
argues for.

**Recommended position:** report it as an *observation consistent with*
recovery-side shadowing, cite D23, and mark H6 now-testable rather than tested.
The caveat to state plainly: the condition arose from a bug, not a design. That
is defensible and honest, but weaker than a designed test. Given 9 pages and no
venue, do not promote it to a claim.

### 15.8 On `cb_state_pre` — still valid, narrower than believed

`check_breaker_precondition()` runs before load and fault injection, and does
cover the gateway's breakers. So the 360/360 CLOSED claim remains **correct
evidence against leakage between replicates**, and objection #4 stays closed.

It was never evidence about **mid-run** state. hypotheses.md's "every current row
is isolated" conflated the two and has been corrected. Keep §IV-D's wording
scoped to load-start state; do not let it imply mid-run isolation.

### 15.9 The scoping decision that cannot be deferred

The sidecar does not reach the historical collection, and `leg_failure_rates`
cannot answer it retroactively. So COUNT_BASED × $D_w$ ∈ {15, 30} in the 360-row
dataset — roughly a third of the grid — is of **unknown status**.

1. **Fix and re-collect the stratum.** Pin `slidingWindowType` and
   `slidingWindowSize` explicitly in the measurement-plane block (the real bug
   fix — makes isolation actual rather than accidental), then re-run
   COUNT_BASED × $D_w$ ∈ {15,30}. ~108 rows, ~4 h. Cheaper than the FANOUT CRASH
   sweep already cut, and it buys back a third of the dataset.
2. **Scope every analysis to $D_w$=5 plus all TIME_BASED rows.** Zero runs, but
   two-thirds of the COUNT arm leaves every result, including containment and
   detection latency.

**Do the config fix regardless** — it is a genuine bug, and leaving it in a
public repo undercuts the reproducibility claim (objection #10). Whether to
re-collect depends on how much §V-B and detection latency matter; both are
currently unwritten.

---

## 16. A reported p-value is below its own exact floor

**Fix before this goes anywhere.**

The stratified $D_w$=15 comparison reports p=0.0082 with 2 clean COUNT
observations against 6 TIME. That value is not attainable from this data.

Under the null all 8 observations are exchangeable. There are C(8,2) = 28 ways
to choose which two are COUNT, and exactly one gives complete separation. So:

- smallest attainable one-sided p = 1/28 ≈ **0.036**
- two-sided ≈ **0.071**

p=0.0082 is below the floor — an artifact of the log-rank chi-square asymptotic
approximation used far outside its validity range, not a result.

**Action:** replace with an exact permutation test at all small-n cells. The
honest answer at $D_w$=15 is ≈0.036 one-sided, ≈0.071 two-sided — **not
significant at conventional two-sided thresholds.**

**Why this one matters disproportionately.** Objection #2 is already "your nulls
are underpowered, not negative." A sub-floor p-value at n=2 hands a reviewer the
strongest possible version of that objection, and it is the kind of error that
costs credibility on every other number in the paper. Worth a general guard in
`common.py`: refuse to emit an asymptotic p below the exact permutation floor
for the given group sizes.

---

## 17. Draft edits outstanding as of 2026-09-17 (supersedes §14)

| # | Section | Change |
|---|---|---|
| 1 | §V-D | **Rewrite.** Table II: n=34, exact p-values, gateway-stratified. H3 = solid at $D_w$=5, weak at 15, untestable at 30 (§15.4, §16) |
| 2 | analysis | Exact permutation test at small n; floor guard in `common.py` (§16) — **and compute the floor on cluster n, not raw rows** (§21.1) |
| 3 | §III-D, §VII-A | Gateway "cannot trip" is false for COUNT_BASED — cite D23 (§15.1); note the fix at D25 is forward-only (§18) |
| 4 | §V-A | Two-directions framing: unsatisfiable vs unenforceable (§15.3) |
| 5 | §VI | **Rewrite per §20** — remove the two fabrications, add D17's implication for D-001's band, fix the chronology, add D20's fingerprint table. Then: sixth instance — the instrument compromised by the effect under study (§15.2); plus the containment metric's structural blindness (§15.6) |
| 6 | §IV-D | Use §23's sentence — both leakage modes, 3,600 observations. Still scope to load-start; do not imply mid-run isolation (§15.8) |
| 7 | §IV-E | Use §25.4's two-sentence version — **not** a detection narrative. Plus the new unexplained host effect (§15.6) |
| 8 | §IV-A | HALF_OPEN gate proven, not assumed; footnote the javadoc defect (§12.2) |
| 13 | §V-B, §VI | H4 absorbed into §VI per §26 — drop the Kendall number, add the scope clause, remove H4 from the load-bearing list |
| 14 | §V (new) | Add a Results subsection for the D25 config audit — currently absent from the outline entirely (§26.3) |
| 15 | §III-B | CRASH arm excluded alongside THROTTLE, two stated reasons (§26.5) |
| 9 | §VII | H6 reopened as now-testable, not tested (§15.7) |
| 10 | §V-D | D22 with n and adjusted R² (§15.5) |
| 11 | §V-B | Still stale — re-run `tau_sweep.py`, `order_leg_containment.py` |
| 12 | §V-A | Figure 1 (ρ vs outcome) still missing |

Plus the scoping decision in §15.9, the measurement-plane config fix, and the
public README, which still describes a different study (§6).

---

## 18. D25 — measurement-plane fixed and live-verified (2026-09-17)

The bug identified in §15.1 is now fixed forward. **This does not clean any
already-collected data** — §15.9's scoping decision is unchanged and still open.

### 18.1 What the diagnostic settled

A live `CB_CONFIG_DUMP` on **gateway-service** during a W5 sweep resolved a
competing explanation. Two candidates were on the table:

- **D23 as written:** the unset fields track the swept values, so the gateway's
  window was 5 and `min(1000000, 5)` gated it.
- **The alternative** (mine): an instance naming `base-config` builds from
  Resilience4j's own defaults rather than from `configs.default`, so the window
  would have been the library default of 100.

**D23 is correct.** The gateway reported `slidingWindowSize=5`, tracking the
sweep. The hardcoded `minimum-number-of-calls: 1000000` was silently gated by
`min(1000000, slidingWindowSize)`, exactly as D23 states. No rewrite needed.

Worth recording as method: this is the second time in the session that reading
library source produced the wrong answer and live instrumentation produced the
right one (the first was the config-time clamp hypothesis, §12.1). Both were
settled in minutes by a dump. That is an argument for the paper's own thesis and
belongs in §VI's framing.

### 18.2 The three suspected additional gaps were not gaps

`record-exceptions` / `ignore-exceptions`, `wait-duration-in-open-state`,
`permitted-number-of-calls-in-half-open-state` and
`automatic-transition-from-open-to-half-open-enabled` were **all silently
inherited from `configs.default`** — the same mechanism as the window fields,
not separate defects. So the 4xx firewall *was* present on the gateway, and the
half-open parameters *did* match the sweep.

**This also dissolves the 23.7 s figure**, which had been treated as a quantity
needing explanation. The gateway's wait duration was never a fixed 60 s; it
tracked the swept value. The 23.7 s is the gap between *two different breakers'*
timestamps, not one breaker's wait duration measured from its own OPEN. A number
that looked like a measurement and was not one — worth a line in §VI.

### 18.3 The fix, and how far the defect reached

`configs.measurement-plane` now pins every field explicitly: `TIME_BASED` / 600 s
window / `minimum-number-of-calls: 1000000`, plus wait duration, half-open
permits, auto-transition, and both exception lists. `TIME_BASED` is the
load-bearing choice — it has no capacity ceiling, so the 10^6 gate is honoured
exactly and is genuinely unreachable. Keeping COUNT_BASED would recreate the bug
at whatever capacity the window ended up with.

`grep -rn "base-config" services/` confirms `measurement-plane` was **the only
named, non-default config profile in the codebase without a `base-config` of its
own**. The defect was confined to one block. For §VII that is a stronger
statement than "we fixed it": the same pattern was searched for elsewhere and
does not exist.

### 18.4 Verification standard — worth citing in §VII-E

Not "changed the config and it reads correctly." The chain was:

1. `CB_CONFIG_DUMP` before the fix → confirmed `slidingWindowSize=5`
2. Rebuild gateway-service with the pinned config
3. Second dump → confirmed `failureRateThreshold` reading back 100.0% live,
   against the swept 70%
4. **A real fault-injection replicate through the harness** (canary
   T70-W20-D30, 17 of 60 requests failed) → **zero `CLOSED_TO_OPEN` on any of the
   gateway's three breakers**

Step 4 is what makes this a verification rather than an assertion: the conditions
that previously produced the trip were recreated, and it did not trip.

### 18.5 Status

D25 in the decision log, with both dump outputs and the fault-run verification.
STATUS.md's H6 row notes the fix is **forward-only** — D23 and D24's findings
describe already-collected data and stand unchanged.

Open PRs: **#65** (exact-test p-value correction, §16) and **#66** (this fix).
Both independent, both off main.

**Unchanged by this:** §15.9. COUNT_BASED × $D_w$ ∈ {15, 30} in the 360-row
dataset is still unverified. What the fix buys is that a re-collection would now
be clean; whether to spend the ~4 h is still the open call.

---

## 19. D26 — H3's mechanism, closed (2026-09-17, PR #68)

> **Read §28 first.** This section explains *why* window type affects recovery.
> That effect **falsifies** H3's stated prediction rather than confirming it.
> The mechanism below is the explanation of a failed prediction. Also: Soham
> reports there is no D26 in the decision log — this content sits in D22 as an
> update dated 2026-09-18. Use the log's numbering, not these notes'.

**H3 moves from "confirmed effect, unidentified mechanism" to "confirmed effect
with a specified and quantified mechanism, no residual."** This is the largest
positive change to the paper's content in the session.

### 19.1 The chain

```
larger window_size
  -> more attempts needed before one lands cleanly          (P1)
  -> each failed attempt costs one full wait_duration in OPEN (P3)
  -> the winning attempt costs a constant ~2.3 s             (P2)
```

| Test | Result |
|---|---|
| **P1** bounce count vs window size | scales, TIME_BASED only (reproduces D22) |
| **P2** *final* episode vs window size — **the falsification test** | **flat**: 2.38 → 2.33 → 2.29 s at W=5/10/20, a 4% change, not material |
| **P3** inter-attempt gap vs wait_duration | slope **1.024**, R² **0.987** |

Verdict: `CONSISTENT_WITH_RESIDUAL_WINDOW_CONTENTS`.

The hypothesis survived a test designed to kill it. P2 predicted the window
governs *how many* attempts are needed, not how long the successful one takes —
and that is what the data shows.

### 19.2 The ~9.8 s residual does not exist

D22 and D24 both carried an unexplained TIME-intrinsic component of ~9.8 s
(later ~2.75 s after gateway cleaning). **It was never a separate mechanism** —
it is failed-episode time, which the additive decomposition accounts for
directly.

**Consequence: retract the two-component framing** recommended in §12.3
(arm-exclusive bounce mechanism + unexplained offset). That framing existed to be
honest about a residual that no longer exists. §V-D should now be written as a
single closed mechanism with no remainder.

### 19.3 What to quote

**P3's slope of 1.024 is the line.** Each bounce costing almost exactly one
`wait_duration` is not a fitted parameter — it is the breaker's specified
behaviour recovered from raw timestamps. The decomposition predicts the library's
documented semantics without having been told them. That is what makes the
mechanism credible rather than merely fitted.

### 19.4 Why this matters for the thesis

The mechanism is **the same estimator argument as §V-A, applied to recovery**: a
time-based window retains fault evidence for its full duration T, so recovery
requires outlasting the window. A count-based ring buffer is overwritten by fresh
successes and never bounces at all.

This ties H3 to the paper's central claim **without** the H2b link that Lead 2
ruled out (§12.2). Same thesis, different route.

### 19.5 Two bugs, both instructive

1. **Caught pre-ship by the script's own self-test.** A perfect fit has zero
   residual, hence no standard error and no t statistic. The original verdict
   logic read "no t" as "not significant" — which would have reported the
   strongest possible dependence as evidence of *independence*. Fixed to judge on
   effect size **and** significance jointly, with an exact fit counted as maximal
   evidence and a third `INCONCLUSIVE` state for material-but-unreliable results.
2. **Caught by the live run.** P3 initially read R²=0.000 against `wait_duration`
   — exactly the "extraction is wrong, not the theory" signal the test exists to
   produce. Root cause: the two host-sleep rows (700.4 s, 1703.4 s) that
   `half_open_survival.py` already filters, which this new script had no
   equivalent guard for. Added the same ceiling check
   (`breaker_observer.half_open_probe_deadline_s`); P3 then confirmed cleanly and
   P1/P2 barely moved.

**Worth a line in §IV-E:** the second script re-derived the *identical two bad
rows* through a completely separate extraction path, with no shared filter. That
is an independent cross-check that they are artifacts rather than inconvenient
data. The host-sleep problem has now been caught by three distinct mechanisms,
which strengthens the methods point about machine-checked ceilings over
inspection.

A test whose purpose is to fail when extraction is wrong, failing when extraction
was wrong, is the design working.

### 19.6 Scope caveat — unchanged

The mechanism is established; the **range over which it is demonstrated is still
narrow**. Clean data supports $D_w$=5 solidly and $D_w$=15 weakly (n=2, see §16
on its p-value). $D_w$=30 remains untestable until the re-collection lands.
Do not write the mechanism as demonstrated across the full wait-duration range.

---

## 20. §VI audited against the real decision log (2026-09-18)

**The gap named in §6 is now closed.** `decision-log.md`'s D-001, D15, D17 and D20
were read in full and checked against what §VI of the draft actually says. The
section contains **two fabricated claims and one serious omission**. Fix before
writing.

### 20.1 Fabricated — remove

The draft's paragraph on the thresholded metric reads:

> "This value had been calibrated when the leg distribution was bimodal. After a
> testbed rebuild, the only firing leg topped out just below the threshold..."

**Neither clause appears anywhere in D-001.** No bimodality, no prior
calibration, no testbed rebuild. That is invented causal connective tissue — a
metric that once worked and then degraded — written to make the narrative flow.

**What D-001 actually says** (Day 1, 2026-08-10, 80 runs / 26 configs): the first
time it was measured, order-service's max leg rate was **0.4867**, and the shipped
τ = 0.50 already sat above the entire support, so `real_blast_radius` read
identically 0.0 in all 80 rows — *constant by construction*.

**It never worked.** There was no degradation. That is the better story, and the
draft replaced it with a worse invented one.

### 20.2 The omission — and it undercuts advice given earlier

D17 contains a finding §VI misses completely:

> A leg experiencing 100% true failure on its faulted edge is mathematically
> incapable of reporting above 0.50 blended; D-001's entire informative band
> [0.25, 0.45] sits inside the range this bug can produce regardless of real
> severity.

So **the τ = 0.50 dead-zone finding may itself be an artifact of the blending
bug.** Averaging one fully-failed breaker against one healthy sibling caps every
reading at 0.50 by construction. "The shipped threshold sits above the entire
support" may reduce to "the bug caps the support at 0.50."

**This retracts advice given on 2026-09-18** (demote H4, lead §V-B with the τ
sensitivity curve as the construct-validity finding). That curve was computed
through the unfixed blending path. D-001's own update says to re-derive it once
D17's fix lands **and CRASH is re-collected**. Until then the τ argument cannot
carry §V-B.

D-001's *methodological* point — report a threshold as a curve rather than pick a
value — survives regardless of what caused the ceiling. **The numbers do not.**

### 20.3 Chronology — the draft's structure is weaker than the truth

§VI implies three successive definitions, each replacing a broken predecessor.
The real sequence is D-001 (2026-08-10) → D15 (2026-08-26) → D17 (2026-09-04),
and **D17 is a discovery about the measurement**, not a new definition. It
retroactively implicates both earlier entries.

That is a stronger structure: the third event did not introduce a third metric,
it revealed that the first two were computed through a defect. Rewrite §VI on
that spine.

### 20.4 D20 — the draft's argument is right but omits the evidence

§VI's throughput paragraph states the confound correctly (constant denominator,
numerator's window sized by the IVs). What it omits is D20's **empirical
fingerprint**, which is what makes the argument land:

| `window_type` | mean | by `window_size` 5/10/20 | by `wait_duration` 5/15/30 |
|---|---|---|---|
| COUNT_BASED | 0.728 | 0.734 / 0.723 / 0.726 | 0.728 / 0.727 / 0.728 |
| TIME_BASED | 0.894 | 0.925 / 0.896 / 0.863 | 0.854 / 0.900 / 0.929 |

COUNT plans are sized in calls, so load duration barely moves and the metric is
flat to within 0.011 across both IVs. TIME plans are sized in seconds, so
duration tracks both IVs and the metric slides monotonically with each.
**The between-window-type gap of +0.166 — the number most likely to be reported
— is exactly the contaminated one.** Add this table; it converts an argument into
a demonstration.

Two further details worth carrying:

- **Not repairable post hoc**: neither `throughput` nor `baseline_throughput` is
  in `DATASET_HEADERS` — only the derived ratio is written. A fix means
  re-collection (the 324 rows took 11 h 19 min wall-clock).
- **Carried, not closed**: `ml/preprocessing.py::IF_NUMERIC_FEATURES` fits the
  Isolation Forest on `throughput_loss`, so its anomaly scores inherit the
  confound. **If any ML result enters the paper, drop it and re-fit first.**

D20 also confirms the README correction in §6: the TPS pacing bug README §4.7
calls "queued for the Week 2 hardening pass" was fixed in `508575f`
(2026-06-18), eleven weeks before any live row was collected. §4.7 was simply
never reconciled.

### 20.5 Numbers in §V-B — three generations, do not mix

| Source | Claim |
|---|---|
| D15 original (79-row archive) | COUNT max 0.4167 < TIME min 0.4500, Cliff's δ = −1.0 |
| D15 update 2026-09-06 (LATENCY-only) | COUNT max 0.2250 < TIME min 0.2686 |
| Live re-run 2026-09-17 (360 rows) | **overlap**: COUNT max 0.3667 > TIME min 0.2686; δ = −0.987 |

Only the third is current. Report δ with a bootstrap CI and acknowledge the
overlap — near-total stochastic dominance is more defensible than "zero overlap,"
which is precisely the claim that just dissolved when 36 rows arrived.

### 20.6 Breaker map for §III-A — derived from `cb_state_pre`

| Service | Breakers |
|---|---|
| gateway | `orderServiceCB`, `inventoryServiceCB`, `paymentServiceCB` |
| order | `inventoryServiceCB`, `sharedDbCB` |
| inventory | `paymentServiceCB`, `sharedDbCB` |
| payment | `notificationServiceCB`, `sharedDbCB` |
| notification | `sharedDbCB` |

Ten breakers. This table also **demonstrates D17's mechanism directly**: every
service except notification owns two breakers, and `sharedDbCB` is the healthy
sibling that got averaged in. Place it near §VI's blending paragraph, not only in
§III-A — it makes the defect self-evident rather than something the reader has to
take on trust.

### 20.7 What is now verified vs still unread

**Read in full and checked:** D-001, D15, D17, D20.
**Still unread:** D-002, D-003, D-005, D8, D13, D14, D16, D18, D19, and D-004's
gate table. D13 and D18 back §V-A and §V-D, and their prose in the draft came
from `hypotheses.md` rather than the log — lower risk, since hypotheses.md was
read in full, but not zero.

---

## 21. Remaining decision-log entries audited (2026-09-18)

D18, D19 and D-004 read in full. **No fabrications this time**, but three things
matter — one of which interacts directly with the exact-test patch just shipped.

### 21.1 D19's second open item undercuts the p-floor guard

D19's 2026-09-14 update records an unclosed defect:

> `compare_censored_groups` computes its CIs with the cluster bootstrap (correct)
> but runs its conditional-timing Mann-Whitney **on raw rows**, treating 3
> replicates of one `experiment_id` as 3 independent observations. The effect is
> one-directional — the reported p-value is smaller than the design earns.

**This compounds with §16's fix rather than being fixed by it.** The floor guard
computes `1/C(n₁+n₂, n₁)` from the same row counts. If those counts are inflated
by clustering, the floor is *also* too low — so a p-value can clear a floor that
is itself wrong, and both errors point the same way.

**Action:** the floor must be computed on the **effective (cluster) n** — the
number of configurations — not raw rows. Until D19 §5.2 is closed, the guard
catches the arithmetic-impossibility case but does not make a clustered p-value
honest. Say so in the patch and in §IV-E.

D19 deliberately did not fix this, for the same reason its **Rejected** paragraph
gives: aggregating to per-config means changes the unit of analysis and can flip a
contrast's significance. That is a reviewed decision, not a side effect. **It is
still pending review by Soham and the standard's author** — and it is now a
blocker for any small-n p-value the paper reports.

### 21.2 §IV-E overstates the statistical standard

The draft says Mann-Whitney with Cliff's δ is the default two-group test. True,
with two caveats D19 records and the draft omits:

- **`canary_readout.py::h1_matched_horizon` has not migrated** — it still uses
  Welch's t, Cliff's δ and Brown-Forsythe. Deliberate: its numbers back the closed
  D-004 gate, and changing the test on an already-decided result is its own
  reviewed step. Flagged in `statistical-treatment.md` §5.1.
- **The clustering defect above** (§5.2).

Two known, deliberate deviations. §IV-E should state them rather than describe a
uniformly applied standard — a reviewer who reads the repo will find both.

### 21.3 D-004 names H4 load-bearing — and §20.2 compromises its evidence

The gate table's Paper B row reads: **"B — construct validity. H3 + H5 + H4 +
metric evolution."** The Consequence paragraph names H4 (τ_leg curve, D-001)
explicitly as a load-bearing chapter.

So the demote-H4 decision is **a change to D-004's stated spine**, not a scoping
tweak. Combined with §20.2 — D-001's informative band may be an artifact of D17's
blending — the position is:

- D-004 names H4 load-bearing.
- H4's Kendall evidence is degenerate on current single-leg data (τ = 0.0189).
- H4's τ-curve evidence was computed through the unfixed blending path.
- Re-deriving it properly needs the CRASH re-collection that was cut.

**This needs an explicit decision recorded as a new log entry**, not a quiet
omission during writing. D-004 says the Day-4 gate does not reconsider which
paper — but it says nothing about a chapter whose evidence base was later found
defective. Write it up as such.

### 21.4 D18 — §V-A verified exactly, plus numbers worth adding

Every §V-A figure checks out against D18: 54 configs (36 TIME_BASED, 18
COUNT_BASED control) × 3 replicates, 162/162, zero `precondition_ok=False`, zero
`lambda_deviation_flag`. TIME_BASED inert ≤ 0.4996, tripped ≥ 0.9967, range
0.1249–79.79. COUNT_BASED zero inertness across ρ ∈ {0.025 … 4.0}.

Available and not yet in the draft:

- **30 inert vs 78 tripped rows** in the TIME_BASED arm — worth stating; it makes
  the crossover concrete rather than abstract.
- **D19's independent validation**: `censored_timing_summary` on the same arm gives
  trip rate **0.722 [0.583, 0.861]** over 36 configs, conditional `time_to_open`
  **9.89 s [8.16, 11.79]** — cluster-bootstrapped, and it reproduces D18's numbers
  exactly. Two methods agreeing on the paper's lead result is worth a sentence.
- **Scope detail:** the occupancy sweep ran to λ = 20 req/s, twice the standard
  sweep's default. The λ ∈ {5, 20, 80, 320} range belongs to the *canary*, a
  different arm. §IV-B's worked example uses λ = 80 — fine as an illustration, but
  do not imply the occupancy sweep sampled there.

### 21.5 λ fidelity — a threats-to-validity number the draft lacks

From D-004's preconditions: **38 of 300 canary runs (12.7%) missed target λ by
more than 15%**, worst deviation 35.3%, concentrated entirely at the top end —
0 off at λ = 5 and 20; 23 off at λ = 80; 15 off at λ = 320.

Two consequences:

- H1/H2 are read off `lambda_achieved`, never `lambda_target`. The draft should
  say this; it is the correct handling and currently goes unmentioned.
- It bears on §IV-B's λ = 80 example — that is exactly where fidelity degrades.
  Either pick a lower λ for the illustration or note the harness ceiling.

### 21.6 Reproducibility gap in the canary data

`data/canary_matrix_runs.csv` **never persisted an `arm` column** — it is not in
`runner.DATASET_HEADERS`. D-004 read it by joining onto `data/canary_matrix.csv`
on `(run_index, replicate)`, *not* `experiment_id`, because the design file
predates the `-M{n_min}` suffix.

That join is a read-time reconstruction recorded only in D-004's prose. **Any
future read needs the same join**, and a reader reproducing the gate from the repo
has no way to know that. It belongs in §VII-E alongside the tag and manifest, and
ideally `arm` should be persisted going forward.

### 21.7 Still unread

D-002, D-003, D-005, D8, D13, D14, D16. D13 backs §V-D and D16 backs §VII-C;
both have been read via `hypotheses.md` and STATUS.md, and D13 has since been
superseded twice (§13, §19), so the residual risk is low. D8 (schema freeze) and
D14 (`machine_id`) are schema history. D-002/003/005 are short procedural entries.

---

## 22. Stratified cluster permutation — verified, and the p-floor rule refined

Closes D19's remaining "Revisit if" and settles a floor question that came up twice
with different answers.

### 22.1 The result

`window_type_recovery_leak.py` tested each $D_w$ separately — the same defect
shape corrected for H3. Now stratified. Diagnostic run first, which was worth it:
the assumed flooring problem (1-vs-3 configs) **does not apply to the COARSE
table** (18v18 configs per $D_w$, floor ≈ 1e-10). It lives entirely in the
PRECISE `half_open_to_closed` table.

Diffed field-by-field against the pre-change output: **no verdict flipped.**

**Headline number for §V-D:** PRECISE `half_open_to_closed`, joint stratified
test, **p = 0.025** — identical pooled and gateway-cleaned, and stronger than
either stratum alone ($D_w$=5 → p=0.1; $D_w$=15 → p=0.5).

Worth a sentence: per-$D_w$ tests are individually uninformative at these cluster
counts, and the combined test is not a rescue but **the correct unit of
inference** — the recovery claim was never "at each wait duration separately." That
pooled and cleaned agree exactly is also quietly reassuring: the gateway confound
does not touch this DV.

### 22.2 p = 0.025 is the attainable floor — verified by enumeration

A concern was raised that the two-sided floor might be 1/80 = 0.0125 rather than
2/80, which would mean the test sat one step *above* its floor and the sentence
"returns that floor" was false.

**Enumerated all 80 joint assignments. The concern was wrong.** Exactly 2 reach
|S| ≥ |S_obs|, so 2/80 = 0.025, and the null distribution is symmetric about zero
(min −6.00, max +6.00).

The error in the objection: it assumed the mirror assignment fails to exist at
unequal group sizes (1-vs-3). It does not. For a **rank-based** statistic the map
`r → N+1−r` is a bijection on the assignment set and negates the centred
rank-sum, at any group sizes. With 1-vs-3 the four possible COUNT ranks
{1,2,3,4} centre to {−1.5, −0.5, +0.5, +1.5} — symmetric.

### 22.3 The floor rule, stated correctly

Two earlier statements looked contradictory. They are not — they describe
different statistics:

| Statistic | Two-sided attainable minimum |
|---|---|
| Log-rank on censored durations (§16) | **1/C** — not a rank-sum; its null depends on actual event times and censoring, so it need not be symmetric |
| Stratified rank-sum (this test) | **2/C** — symmetric by construction |

**The hard floor is 1/C for any permutation test** — nothing can go below it, and
that is what `exact_p_floor` must return for the guard to catch impossible values.
The *attainable* minimum for a symmetric statistic is one step up at 2/C.

**Add to `exact_tests.py`'s docstring:** a rank-based test reporting 1/C
two-sided is itself a bug. This distinction caused two errors in one session and
should be written down where the next person will see it.

### 22.4 Sentence for §V-D

> **Superseded three times.** (1) Per §28, do not call this "H3 holds" — it is the
> recovery leak that falsified H3. (2) Soham's pre-registered Phase 4B sweep
> (4 configs per arm per stratum, $D_w$ ∈ {5,15,30}) will replace the 80-assignment
> test and its 0.025 floor. Keep the *structure* of the sentence below — state
> the number of assignments and the resulting floor — but not its numbers.
> (3) Per §30 (D29): the Phase 4B sweep's own recovery comparison is retracted too
> (fault-exposure confound, D28). The sentence this note describes no longer belongs
> in §V at all — see §30 for the R2 confirmatory numbers and where they go instead
> (§VI).

> The stratified permutation admits 80 label assignments, so the smallest
> attainable two-sided p is 0.025. Every count-based configuration recovered
> faster than every time-based configuration in both strata — complete
> separation — and the test returns that floor.

Pair it with the effect size, which does the real work: ~2 s against ~19 s at
$D_w$=5, a ~9.5× separation, and complete separation means **Cliff's δ = −1.0**
on config-level values. Lead with δ; p is confirmatory. State the floor
explicitly — it pre-empts the reviewer asking why there is no smaller number, and
a p that *equals* its floor is a stronger claim than one merely below 0.05: no
arrangement of this data could have been more extreme.

### 22.5 Monte Carlo quoting rule

The COARSE table pools the threshold×window_size grid, so exact enumeration is
impossible. Its old row-level p-values of 1e-13 to 1e-21 are corrected to the
Monte Carlo floor **~5e-5** — an honest **upper bound**, not an estimate (the
true exact floor is ~1.1e-10, unresolvable at 20,000 resamples).

**Always quote as `p < 5e-5 (20,000 resamples)`, never as an equality.**

Those 1e-13 to 1e-21 values are worth one line in §VI: the same error shape as the
0.0082 that started this, eight orders of magnitude more obviously wrong, and
nobody noticed — because a very small number looks like a strong result rather
than an impossible one.

### 22.6 The error shape, now four appearances

A statistic computed on more independent units than the design contains:

1. D19 §5.2 flagged it 2026-09-14 — sat unreviewed
2. PR #65 reproduced it at the floor
3. H3's per-cell tests
4. The COARSE table at 1e-21

One defect, four appearances, caught only when someone computed what the design
could actually produce. That belongs in §VI as a single narrative, not four
separate fixes.

### 22.7 Why the row-preserving permutation is the right fix

Worth stating in `statistical-treatment.md`, because a reader who knows the
literature will otherwise ask why means weren't used.

D19 rejected mean-collapsing because it changes the unit of analysis and can flip
a contrast. `cluster_permutation_rank_test` permutes whole configurations but
**ranks every raw row** — the unit *tested* stays the row; only the unit *randomly
assigned* is the configuration, which is what independence actually requires.
A self-test case has the two approaches disagreeing **in sign**, not just
magnitude, on the same data. That is why the rejected fix stayed rejected.

### 22.8 One real crossing found by running both ways

PRECISE `half_open_to_closed` at $D_w$=5 went **p = 0.00216 (significant) →
p = 0.1 (not significant)** once the true 3-vs-3 configuration count replaced the
inflated 6-vs-6 row count. Never cited anywhere, so nothing in print changes —
but it is the reason the "run both ways and diff" condition was imposed, and it
earned its keep on the first use.

---

## 23. Objection #4 fully closed — both leakage modes measured (2026-09-19)

A concern was raised that `cb_state_pre` alone does not close objection #4.
CLOSED at load start rules out an *open* breaker carrying over, but not a breaker
that is CLOSED while holding a partially-filled ring buffer with stale failures
from the previous run. That second mode would bias `time_to_open` **downward** —
fewer fresh failures needed to cross the threshold.

**Checked. Both modes are clean, with zero exceptions.**

| Column | Rules out | Result |
|---|---|---|
| `cb_state_pre` | an OPEN breaker carrying over | CLOSED on all 10 breakers in all 360 runs |
| `buffered_calls_pre` | a CLOSED breaker holding stale failures | 0 on all 10 breakers in all 360 runs |

**3,600 per-breaker observations (10 × 360), zero exceptions on either column.**
Gateway breakers included, so the D23 concern about measurement-plane
contamination does not apply here either. No dirty subset exists, so there is
nothing to test against `time_to_open`.

**Format note for anyone re-running this:** `buffered_calls_pre` is the same
semicolon-joined per-breaker string as `cb_state_pre`. A naive
`value_counts()` / `describe()` returns counts of long strings, not numbers —
it must be parsed per breaker.

### Sentence for §IV-D

> Every run began from a verified-clean breaker state: all ten circuit breakers
> recorded CLOSED with an empty sliding window immediately prior to load
> generation, across all 360 runs — 3,600 per-breaker observations with no
> exceptions and no runs excluded.

**State the per-breaker count, not just "360 of 360."** The measurement is per
breaker, and "ten breakers × 360 runs" signals a systematic check rather than a
spot inspection.

**Name the two modes separately.** A reviewer who has thought about circuit
breakers knows CLOSED alone does not mean clean; showing that both were measured
is worth a clause. This is now the best-evidenced claim in the paper — it is
measurement, not assumption, and it is exhaustive.

### Scope, unchanged

This remains evidence about **load-start** state only. It says nothing about
mid-run behaviour, which is where D23's gateway trips occurred. §15.8's
distinction still holds: do not let §IV-D's wording imply mid-run isolation.

---

## 24. §VI's unifying framing — corrected (2026-09-19)

An adversarial pass over the notes' own claims. One suggestion is **retracted**,
and the draft's existing framing turns out to be the right one, with an addition.

### 24.1 Retracted: the "hidden information" thesis

Earlier notes floated a possible thesis-level observation: *the information needed
to avoid the error exists, but not where the decision gets made.* It was
deliberately flagged and not developed. That caution was correct — the idea does
not hold up.

Tested against the project's own six instrumentation defects, **it fits one**
(the gateway isolation). The count was padded: two of the three originally
claimed — the `maxWaitDurationInHalfOpenState` javadoc and
ρ / `minimumNumberOfCalls` — are **findings about Resilience4j**, not
CascadeShield's own defects. Different category, counted anyway.

**Do not use this framing.** It does not unify, and building §I or §VI on it
would mean defending a generalisation that breaks on its own examples.

### 24.2 The draft's existing framing holds — seven for seven

§VI already says the problems were *"invisible in aggregate statistics and
visible only when the metric's full distribution or full parameter surface was
examined."* Tested exhaustively:

| Defect | Where it was actually visible |
|---|---|
| Constant blast radius (D-001) | the distribution — zero variance |
| τ = 0.50 dead zone (D-001) | the parameter surface — the τ curve |
| Blended breakers (D17) | per-breaker raw counts, not the service aggregate |
| Throughput confound (D20) | the fingerprint across IVs — COUNT flat, TIME sliding |
| Probe-window ceiling (D21) | the raw event stream — two events then silence |
| Gateway isolation (D23) | the live config object |
| Sub-floor p-values (D19 §5.2, §16, §22) | the permutation space |

Seven for seven. Keep it.

### 24.3 What sharpens it — and ties §VI to §V-A

As stated, that framing is a truism: "look at raw data, not summaries" is advice,
not a finding. The sharpening is the **second half** — in every case a cheap
diagnostic existed and was not run, because *nothing looked wrong*. The output was
clean. There was no trigger.

That is the same failure mode as the systems under study:

> A count-based breaker configured with `minimumNumberOfCalls = 10⁶` reports that
> configuration faithfully while silently ignoring it. A time-based breaker at
> ρ < 1 reports CLOSED throughout while being structurally unable to open. A
> metric with zero variance reports a clean number while carrying no information.
> A p-value of 0.0082 reports significance while being arithmetically impossible.

**Every one fails by reporting normally. The absence of an error signal is the
failure mode.**

That unifies the instrumentation narrative with the paper's subject instead of
leaving §VI as a methods essay sitting beside the results. It also explains the
project's sharpest self-referential fact: the researchers who had already
published the ρ mechanism still wrote a configuration that fell to it, and did
not notice for seven weeks — because nothing reported an error.

### 24.4 How to use it

**One paragraph at the end of §VI. Not a restructure.** §I's estimator framing
stays as the paper's spine; this is the closing move of the metric-evolution
section, offered as an observation rather than a thesis. If a reviewer or the
mentor picks it up, promote it in revision.

Costs a paragraph, claims nothing the seven rows above do not support, and needs
no new analysis.

---

## 25. Disclosure budget — how much self-criticism the paper can carry

A correction to advice these notes have been accumulating, considered at the level
of the whole paper rather than sentence by sentence.

### 25.1 The risk

Count what the draft currently plans to disclose about itself: §VI narrates five
or six instrumentation defects; §VII-B adds the gateway confound; §IV-F states an
MDE of 3.07 up front; §IV-E was about to add a detection-coverage gap.

Each is individually honest. **Cumulatively, a reviewer stops reading "rigorous"
around the fourth admission and starts reading "this dataset is a minefield."**
That is a real acceptance risk, and these notes have been walking toward it one
sentence at a time.

### 25.2 The distinction to apply

**§VI's defects are a contribution.** They are findings about metric construct
validity, which is the paper's subject. Length there is earned.

**Host suspension corrupting four wall-clock readings is hygiene.** Every
empirical paper excludes outliers; almost none narrate how they noticed. Putting
a discovery narrative in §IV-E dilutes §VI, because the reader starts reading the
construct-validity findings as a list of mistakes rather than as analysis.

**The rule: spend disclosure where disclosure is the contribution.** Hygiene
should read as competence, not confession.

### 25.3 What a reviewer actually needs on an exclusion

Four things — and the detection chronology is not among them:

1. exclusions declared
2. criterion stated
3. **criterion principled rather than fitted to the data**
4. effect on results reported

Only (3) is a genuine vulnerability here. The ceiling filter *was* added after
seeing bad values, which is textbook post-hoc exclusion, and a sharp reviewer
will ask.

**The defence is strong — lead with it.** The ceiling derives from
`breaker_observer.half_open_probe_deadline_s`, the harness's own observation
deadline: a pre-existing constant, not a number chosen by inspecting the
distribution. It was validated against all 26 completed recovery episodes with
zero violations. That makes the criterion principled and defuses the objection.

### 25.4 §IV-E wording — two sentences, not four

> Four runs were excluded as wall-clock artifacts from host suspension, flagged
> by automated ceiling rules rather than inspection. The ceilings derive from the
> harness's own observation deadline rather than from the observed distribution,
> and were validated against all 26 completed recovery episodes with no
> violations; an independent extraction path subsequently re-derived the same
> excluded records.

Covers all four requirements, states the anti-post-hoc defence, keeps the
independent cross-check, and spends no space on how the gap was found.

### 25.5 The accurate chronology — for the decision log, not the paper

Recorded here because an earlier note in these files overstates it. The claim
that four artifacts were "all caught by an automated ceiling/quarantine rule
rather than inspection" is **not accurate as written**:

- **Artifacts 1–2** (704.6 s, 2657.1 s, coarse `time_to_recover`) — caught by
  `quarantine.py`'s pre-existing `RECOVERY_TIMEOUT_HANG` rule. A genuine
  automated catch.
- **Artifacts 3–4** (700.4 s, 1703.4 s, precise `half_open_to_closed`) — **not
  caught by any rule.** Surfaced when downstream results failed sanity checks
  (the KM p-values would not reconcile; then P3's regression returned R²=0.000).
  The `half_open_survival.py` ceiling was added in response. A D13 claim that the
  precise metric was "immune to this artifact by construction" was falsified.

The coverage gap is a real methods observation — automation covered one metric
and not another, and the gap was invisible until something downstream broke,
which is exactly §24.3's framing (**the uncovered metric reported normally**).
It belongs in the decision log and in §VI's closing paragraph if anywhere, **not
as its own confession in §IV-E**.

The genuinely strong part survives either way: `recovery_decomposition.py`
re-derived the identical two records through a completely separate extraction
path with no shared filter. That is independent confirmation they are artifacts
rather than inconvenient data, and it is worth more than the detection story.

### 25.6 Action before submission

Do a pass over the full draft with this lens: **count the admissions, and for
each ask whether it is a finding or a chore.** Findings earn narrative; chores
get a clause.

---

## 26. H4 — absorbed into §VI, not demoted (decision, 2026-09-19)

**Decision: H4 stops being a standalone chapter. Its content moves into §VI;
the Kendall ranking number is dropped. The freed subsection goes to the config
audit (D25).**

This changes D-004's stated spine and needs its own decision-log entry.

### 26.1 What was rejected, and why

Two options were on the table before this one.

**Keep H4 as load-bearing.** Not viable. Its Kendall evidence on current data is
τ = 0.0189 — degenerate, because LATENCY-only data has exactly one firing leg and
a ranking comparison needs configurations that differ in how many legs fire.
Rescuing it needs CRASH data, which was cut (§26.5). Separately, whether the
*pre-fix* rankings were ever trustworthy is unresolvable until the soham-local run
separates the D17 fix from an uncalibrated machine effect (see `task.md`).

**Demote to descriptive.** This was the earlier recommendation in these notes and
it is **worse than both alternatives**. A "descriptive" subsection is an orphan:
reviewers read it as *here is a hypothesis we named, tested, and could not
resolve, presented anyway*. It costs page space, carries no claim, and invites
"why is this here?" It also forces an awkward sentence — *we designated this
load-bearing and it turned out unmeasurable* — drawing attention to a weakness
that need not be raised at all.

### 26.2 Why absorption is right

**H4's content was never really a separate hypothesis.** Its claim is that
competing containment definitions rank configurations differently. That *is*
§VI's argument — construct validity of the containment metric — not a parallel
finding.

**Most of it is already in §VI.** The τ-sensitivity sweep, the dead zone, the
shipped τ = 0.50 ranking nothing: all of that sits in the D-001 → D15 → D17 chain
the section already narrates. What is genuinely separate is *only* the Kendall
ranking statistic. Drop that one number and H4 does not need demoting, because it
stops being a standalone chapter.

**The degeneracy becomes evidence instead of embarrassment.** A ranking metric
that cannot discriminate on data where only one leg fires is itself a
construct-validity finding: **the metric's resolution depends on a property of
the fault topology, not only on the configurations being compared.** That is a
sentence in §VI's favour, not an apology in §V-B.

### 26.3 Why this improves acceptance odds

- **Reviewers do not count hypotheses.** They ask what was learned. Four weak
  claims read worse than three strong ones.
- **The paper's real vulnerability is underpowering** (n=3, MDE 3.07, reviewer
  objection #2), not scope. Keeping a degenerate τ = 0.0189 adds another
  thinly-supported number to a paper already exposed on exactly that line.
  Removing it tightens the argument against its own weakest point of attack.
- **The freed space is already spoken for.** The D25 config audit — 447
  configurations across 192 repos, the λ* distribution, the three-repo λ*=20 case
  — is a genuine empirical contribution and **is not in the draft outline at
  all**. It needs a Results subsection. That more than replaces H4, and it is
  stronger material: evidence about deployed software rather than a lab statistic.

**Net: one weak subsection out, one strong subsection in, §VI slightly stronger.**

### 26.4 What to actually write

**In §VI**, at the point where the τ chain already appears, add a scope clause —
not a retreat:

> The ranking comparison between competing containment definitions requires
> configurations that differ in how many legs fire. The latency-only dataset
> provides one firing leg throughout, so the rank correlation is degenerate by
> construction rather than by measurement — a property of the fault topology, not
> of the configurations compared.

**Do not** include the τ = 0.0189 figure, τ = 0.238, or τ = 0.891. All three are
either degenerate, pre-fix, or confounded (§20.5, §21.3, `task.md`).

**Keep** the τ-sensitivity curve as a methodological point — report a threshold as
a curve rather than picking a value — while remembering §20.2: the *numbers* on
that curve came through the unfixed blending path and the dead-zone result is a
blending artifact (x/2 ≤ 0.5 always). The methodological point survives; the
figures do not.

**In the hypothesis scoreboard**, H4 is no longer listed as a load-bearing
chapter. State it as absorbed, with the scope reason.

**In the decision log**, a new entry: D-004 named H4 load-bearing; the chapter's
evidence base turned out to require data the study does not have; the content is
absorbed into the metric-evolution narrative rather than reported as an
unresolved hypothesis.

### 26.5 Companion decision — CRASH arm excluded

Recommended and not yet confirmed by Soham/Jay. Recorded here so §26 is
self-contained.

**Exclude the CRASH arm, stated in §III-B alongside THROTTLE.** Two reasons,
both already established:

1. **No resolution.** Post-D17 CRASH saturates at exactly 1.0000 regardless of
   window type, so it cannot discriminate COUNT from TIME on any DV the paper
   reports.
2. **Injection point confounded with fault type.** Latency injects at the
   inventory proxy, crash at the payment proxy — different services, different
   chain depths. README §2.5 documents this as deliberate ("mid-chain and
   deep-chain respectively"), so it is citable as a design choice rather than a
   defect found later. PR #47's LINEAR re-collection carries no `-I` suffix,
   confirming it fell through to the per-fault default.

Precedented by the project's own THROTTLE exclusion. Costs one paragraph.

**Check before finalising:** Soham reportedly ran FANOUT CRASH. If that data
exists and post-dates D25, say so — *"collected and excluded on stated grounds"*
is materially stronger than *"not collected."*

### 26.6 One thing this analysis cannot decide

Whether H4 matters to the **capstone assessment** independently of the paper. If
a rubric expects four hypotheses tested, absorbing one may cost marks even where
it is right for publication. That is Soham and Jay's call, and it is the only
reason to override the above.

If the rubric does require it: keep H4 in the *capstone report* as a tested
hypothesis with the degeneracy explained, and absorb it in the *paper*. The two
documents have different audiences and need not match.

---

## 27. Acceptance audit — gaps in these notes as a writing brief

Sections 1–26 are an audit trail: what is true, what was retracted, what not to
write. As preparation for *producing* a paper they have a systematic weakness —
they are almost entirely backward-looking. Eight gaps, ordered by acceptance risk.

### 27.1 🔴 The novelty claim has never been verified

**The single largest acceptance risk in the project, and nothing in these notes
addresses it.**

The draft asserts: *"To our knowledge, no prior work treats the count-based versus
time-based window distinction as the object of study at the application library
layer, nor reports the conditions under which a breaker is structurally unable to
open."*

That sentence carries the paper. It has never been checked. The related-work
corpus is ten PDFs assembled for a capstone proposal, the bibliography entries in
the draft are reconstructed from working notes with **invented titles** (§5), and
nobody has run a systematic search against this specific claim.

If a reviewer knows of prior work on window-type semantics, the contribution
collapses — and unlike every other risk in this file, no amount of internal rigour
defends against it.

**Required before submission:**
- Search terms that actually match the claim: "sliding window" + circuit breaker;
  failure rate estimation + microservice resilience; Resilience4j empirical;
  circuit breaker configuration + misconfiguration; "minimumNumberOfCalls".
- Venues to sweep: ICPE, ICSA, ISSRE, EuroSys, Middleware, SoCC, ASE, ICSE SEIP,
  IEEE Access, SPE, EMSE. Plus arXiv and the Resilience4j issue tracker itself —
  a maintainer thread describing the same behaviour would not invalidate the
  empirical work but **must** be cited.
- If prior work exists, the honest reframe is available and still strong:
  *first systematic empirical characterisation with live instrumented evidence*,
  rather than first observation.

**Do not write the novelty sentence until this is done.**

### 27.2 🔴 No fallback wording if the D23 region stays unverified

§15.9 records the decision (re-collect or scope down) but no text for the branch
where the re-collection does not happen. Roughly a third of the 360-row dataset
— COUNT_BASED × $D_w$ ∈ {15, 30} — has unverified gateway isolation, and the
sidecar does not reach back far enough to audit it.

Draft both branches now, while the reasoning is fresh:

**If re-collected:** *"A configuration defect in the measurement-plane isolation
was identified during analysis (§VII-B) and the affected stratum re-collected
under verified isolation; all reported rows are drawn from verified-clean runs."*

**If not:** *"Isolation of the measurement plane was verified by configuration
dump and live fault injection for all runs collected after [date]. For earlier
runs in the count-based arm at wait durations of 15 s and 30 s, per-run
verification is unavailable, since the transition sidecar does not extend to that
collection. Results in that stratum are reported with that limitation stated;
the time-based arm is unaffected, as the defect is structurally confined to
count-based windows."*

The second is defensible. It is much weaker written under deadline pressure than
written now.

### 27.3 🟠 No figure plan

At nine pages with four results plus §VI, the paper needs three to four figures.
Only one has ever been specified. Figures drive reviewer comprehension more than
any paragraph, and an under-illustrated empirical paper reads as thin regardless
of content.

| # | Figure | Status | Data |
|---|---|---|---|
| 1 | Trip outcome vs ρ, log x, coloured by window type | specified, not made | `occupancy_dataset.csv` (register in `DATASETS` first) |
| 2 | λ* distribution from the config audit — histogram or ECDF, quartiles marked, the λ*=20 case annotated | **not specified** | D25 audit output |
| 3 | Recovery decomposition — stacked bars per arm: failed episodes, OPEN gaps, final episode | **not specified** | `recovery_decomposition.py` output |
| 4 | Breaker state machine annotated with where each finding sits (ρ gates CLOSED→OPEN; the leak sits on HALF_OPEN→CLOSED) | **not specified** | none — a diagram |

Figure 3 is the one that makes H3's mechanism legible in a glance; the prose
version takes a paragraph. Figure 4 is cheap and orients the reader early.

### 27.4 🟠 Title, abstract and contribution list are stale

All three predate D23, D25, D26 and the H4 absorption. The abstract still claims
four results in the old configuration and says nothing about the config audit —
which is now the paper's only evidence about software outside the lab.

Rewrite after the Results sections are drafted, not before. Note in particular
that the two-directions asymmetry (§15.3 — `minimumNumberOfCalls` *unsatisfiable*
under time-based, *unenforceable* under count-based) is a stronger abstract
sentence than anything currently there.

### 27.5 🟠 Multiple comparisons never considered

The paper reports tests across several hypotheses and several DVs. No
family-wise error discussion exists anywhere in the project, and a
statistically-minded reviewer will ask — especially of a paper that devotes a
section to statistical rigour.

The answer is probably fine and should be stated explicitly rather than left to
inference: effect sizes are the primary reported quantity with p-values
confirmatory; hypotheses were pre-registered in `hypotheses.md` rather than
selected post hoc; and the headline claims rest on structural results (exact zero
variance, complete separation, zero inertness) that no correction would touch.
One paragraph in §IV-E.

### 27.6 🟠 The MDE quoted does not apply to the headline test

§IV-F states Cohen's *d* ≈ 3.07 at three replicates. That is the **main sweep's**
design. H3's result comes from a stratified cluster permutation with **three
configurations per arm** — a different design with a different detectable effect,
which has never been computed.

Quoting 3.07 next to a result it does not describe is the same error class as
§16's row-vs-cluster confusion. Either compute the MDE for the cluster design or
scope the 3.07 sentence explicitly to the main sweep.

### 27.7 🟡 Reproducibility package is named but not specified

Objection #10 is only partly closed (repo public, data committed). What a
manifest must contain has never been written down:

- tagged release commit, cited in the paper by tag
- per-claim row counts: which dataset generation and which row subset backs each
  reported number
- the archive map (v1–v6) with the reason each exists
- **the canary `arm`-column join recipe** (§21.6) — currently recoverable only
  from D-004's prose
- environment: Resilience4j 2.2.0, Spring Boot 3, JVM version, Docker image digests
- a data-availability statement, which several IEEE venues require

### 27.8 🟡 Config-audit ethics and reporting unit

Two unresolved points on D25:

**Naming repositories.** The audit identifies public configurations as hazardous.
Naming them reads as shaming and invites complaint; anonymising weakens
verifiability. The defensible middle: report aggregate statistics and describe
the λ*=20 case by its configuration shape rather than by repository, while making
the query reproducible so anyone can regenerate the sample.

**Instance-level vs config-level.** 23% of the sample is one repeated
`(n_min=5, T=10s)` block. Earlier analysis concluded instance-level weighting is
right for a hazard-reachability claim — a config copied 100 times is 100
deployments — and that deduplication would perversely upweight rare odd configs.
**Decide and state the estimand explicitly in one sentence**, and report the
deduplicated distribution as a robustness line. Do not leave it implicit.

Also: "propagates by copying" is a **hypothesis, not a finding**. It needs
provenance evidence (fork graphs, identical surrounding context) before it
appears in the paper. And the three-repo λ*=20 independence claim needs the same
check — if one is forked from another, the example weakens.

### 27.9 Re-score

Sections 1–26 covered provenance, corrections and decisions well and forward
construction poorly. With §27 the brief now covers what to write, what to check
before writing it, and where the paper is exposed.

**Score: 8.5/10.** The remaining deduction is that two of these gaps — the
novelty verification and the D23 fallback — require work outside this document
before writing can safely begin. They are named but not closed.

**Priority order before drafting:** §27.1 (novelty search), then §27.2 (fallback
wording), then §27.3 (figures). Everything else can happen during writing.

---

## 28. H3 is a falsified prediction, not a confirmed one (2026-09-22)

> **AGREED 2026-09-22 by Soham and Jay.** This is now the project's position, not
> a proposal. H3 is reported as a falsified prediction; the recovery leak is the
> finding. Write the recovery sections on this basis.

**The most important framing decision for the recovery result.**

### 28.1 What H3 predicted

`hypotheses.md` states H3 as a **double dissociation** — two cause-and-effect
lines that should not cross:

- **window settings** (type, size, threshold) → affect **detection** (`time_to_open`)
- **wait duration** → affects **recovery** (`time_to_recover`)

The part that makes it testable is what each should *not* do. **Window settings
should have no effect on recovery.** That is H3's negative control — the result
that would prove it wrong.

### 28.2 What the data showed

Window settings **do** affect recovery. Time-based windows recover roughly an
order of magnitude more slowly than count-based. D22's 2026-09-18 update (called
D26 in these notes) goes further: larger time-based windows cause more failed
recovery attempts, so **window size** affects recovery as well.

**The negative control fails. By its own definition, H3 is falsified.**

### 28.3 Where the contradiction came from

At some point the result was labelled `LEAK_CONFIRMED` — window type *leaks* into
recovery, a stage it should not reach. That is a genuine and interesting finding.
`STATUS.md` (line 56) then recorded it as **H3 confirmed**.

Meanwhile `hypotheses.md` §4.1 still states the original prediction: no window
effect on recovery. So the repo currently says both *H3 predicted no effect* and
*H3 is confirmed by an effect*. Both cannot be true. Soham's Phase 4B audit
surfaced this on 2026-09-22.

### 28.4 Redefining "window parameters" does not rescue it

`hypotheses.md` never defines "window parameters" (row 67, the §2 notation
table). The tempting fix is to define them as size and threshold only, excluding
type — then the type effect would not count against H3.

**That fails.** D22's update shows window **size** affects recovery too, through
the bounce mechanism. However "window parameters" is defined, at least one of them
affects recovery, and the dissociation fails regardless.

Defining the term is still worth doing for clarity. It just does not change the
verdict.

### 28.5 Why this matters for acceptance

`hypotheses.md` is public and marked frozen. A reviewer who reads it sees that H3
predicted **no** window effect on recovery. If the paper says "H3 confirmed," it
reads as a failed prediction relabelled as a success after the data came in.
Reviewers treat that as a serious credibility problem — and it would sit badly in
a paper whose §VI argues for exactly this kind of rigour.

### 28.6 The honest framing is also the stronger one

**Report H3 as a falsified prediction, and the recovery leak as what the data
showed instead.** Suggested wording:

> We predicted that window configuration would affect detection but not recovery.
> It does not hold: window type affects recovery substantially, with time-based
> windows recovering roughly an order of magnitude more slowly than count-based
> ones. We trace this to the recovery process itself — a time-based window
> retains fault evidence for its full duration, so the breaker fails repeated
> recovery attempts until that evidence ages out of the window.

A falsified prediction with an identified cause is more convincing than a
confirmed one. It shows the test was capable of failing, that it did, and that
the reason was then found. It also removes any appearance of post-hoc relabelling.

**Terminology for the paper:** call the finding "the recovery leak" or "window
type's effect on recovery." Do not call it "H3 confirmed," "H3 supported," or
"LEAK_CONFIRMED" in prose. Reserve "H3" for the prediction.

### 28.7 Agree with Soham

1. H3 is reported as a **falsified prediction**; the recovery leak is the finding.
2. Fix `STATUS.md` line 56 so it stops calling H3 confirmed.
3. Define "window parameters" in `hypotheses.md` — for clarity, not rescue.
4. **Check the framing in Soham's pre-registered Phase 4B plan** (SHA `3e4ad1e`).
   If it is written as "confirm H3," the plan and the hypothesis disagree. That
   needs a written note **before** his results are analysed, not after — otherwise
   it looks like the framing changed once the numbers were seen.

Because `hypotheses.md` is frozen by repo convention, record the clarification as
an appended note rather than an in-place edit.

### 28.8 What stays the same

The data, the statistics and the mechanism are unchanged. The stratified test,
the effect sizes, and the bounce decomposition all stand. Only the label on the
result changes — from "H3 holds" to "H3's prediction failed, and here is the
effect and its cause."

---

## 29. Infrastructure facts established 2026-09-22 (Jay)

Verified directly against the running system, not inferred. Several correct
earlier assumptions in these notes, and one that was wrong.

### 29.1 The gateway image genuinely carries the D25 fix

Extracted from `BOOT-INF/classes/application.yml` inside
`infra-gateway-service:latest`'s jar (packaged 2026-09-18 07:49):

```yaml
sliding-window-type: TIME_BASED
sliding-window-size: 600              # seconds; longer than any run
minimum-number-of-calls: 1000000      # unreachable under TIME_BASED
```

Confirmed by reading the config out of the built artefact rather than by
comparing a build timestamp against a commit date. That distinction matters —
Soham's own image was two weeks stale and same-day builds can still predate a
same-day commit.

### 29.2 🔴 All three gateway breakers are on the FANOUT path

**This corrects an assumption these notes carried.** Earlier reasoning supposed
FANOUT's branching happened inside order-service, so that the gateway would only
ever call order and only `orderServiceCB` would be exercised. **Wrong.**

`GatewayController.fanout()` calls all three downstream services **directly and in
parallel from the gateway**, via `CompletableFuture.supplyAsync` on a
three-thread pool: `callOrder`, `callInventory`, `callPayment`, each annotated
with its own breaker in `GatewayDownstreamService` (lines 30, 35, 40). It joins
all three and returns 503 if any failed.

**Consequences:**

- FANOUT exercises `orderServiceCB`, `inventoryServiceCB` **and**
  `paymentServiceCB`. LINEAR exercises only `orderServiceCB`.
- Soham's 4-run LINEAR canary proved D25 holds for `orderServiceCB` only. It says
  nothing about the other two, which were never in the request path.
- **Any FANOUT sweep needs all three gateway breakers canaried first.** The D25
  fix is config-level and applies to all three by construction, but "by
  construction" is exactly the reasoning D23 falsified once already.
- For §III: FANOUT's fan-out is a **gateway-level** property, not a downstream
  one. If the draft describes inventory and payment as "parallel children of
  order," that is wrong — they are parallel children of the *gateway*. Check and
  correct §III-A.

### 29.3 `/mesh` is an alias for `/fanout`

`GatewayController.mesh()` is literally `return fanout();`. Same code path, same
three breakers, same request pattern.

The docstring states the *intent* — order, inventory and payment each calling
shared-db internally, so a shared-db fault degrades all three — but at the
gateway level it is not a distinct topology.

**For the paper:** if MESH appears anywhere in the dataset as a separate
condition, it is the same code path logged under two names, not a third topology.
The README records MESH as "considered and excluded"; worth confirming whether
that decision was made *because* of this aliasing, and stating it plainly. A
reviewer diffing FANOUT and MESH rows would otherwise expect a difference and
find none.

### 29.4 Codespace data is unrecoverable, and does not matter

Two Codespaces survive in Shutdown state but are quota-locked (Student Developer
Pack allowance, not a renewing monthly quota — there may be no reset to wait for):

- `expert-goldfish`, last used 2026-09-10, on the CRASH re-collection branch
- `legendary-space-goldfish`, last used 2026-08-27, on a debugging branch —
  likely already past GitHub's 30-day retention

**Not being chased.** Whatever sidecar data they hold covers the CRASH arm, which
§26.5 excludes from the paper.

**For §VII-E / T20:** Codespace-collected runs have no retrievable transition
sidecar. State it as a provenance fact rather than letting a reviewer find the
gap.

### 29.5 Jay's local sidecar adds nothing

Everything Jay holds is already the repo copy — the sidecar was committed with
`git add -f` at D13 (`c59ef95`), which is where Soham's 72 jay-mac records came
from. No additional historical coverage exists on his machine.

This does **not** shrink the unverified historical stratum (§15.9). Phase 4B's
fresh collection remains the only route to verified-clean rows.

## 30. D28/D29 — the recovery leak is retracted; H3's control passes under equal exposure (2026-10-01)

**Supersedes §28 in full.** §28's "H3 is a falsified prediction, not a confirmed one"
(agreed 2026-09-22 by Soham and Jay) is not left standing. Keep §28 — it is the
correctly-dated record of what the project believed and why, and the paper's own
chronology argument (below) depends on it having been a real, reasoned position, not a
straw man. But the position itself reversed twice more since.

### 30.1 What D28 found (2026-09-29)

Soham's Phase 4B re-collection (D26, which §28 is about) held fault exposure
*unequal* across arms without anyone noticing. `run_experiment_run()` clears the
injected fault only after `generate_load()` returns, and `compute_load_plan()` sizes
that load call by window type: `max(3W, 3·n_min, 40)` calls at 10 req/s for
COUNT_BASED (~4-6s) vs `W + D_w + 10s` for TIME_BASED. So in every Phase 4B run the
fault stayed on far longer, after OPEN, for TIME_BASED than for COUNT_BASED (median
3.0-3.2s vs 20.3-47.9s). Every HALF_OPEN episode that began while the fault was still
on bounced; every one that began after it cleared closed — no exceptions, 123/123 and
134/134 (`recovery_fault_timing_check.py`). A window-type-*blind* simulation (HALF_OPEN
fires `wait_duration` after each (re)open; bounces iff the fault is still on; fixed
episode durations shared by both arms; never reads `window_type` or `window_size`)
reproduces the observed bounce count in 72/72 Phase 4B runs and recovery time within
0.6s (`recovery_exposure_model.py`). `CircuitBreakerMetrics.forHalfOpen()` builds a
fresh COUNT_BASED buffer for HALF_OPEN regardless of the configured window type
(verified with `javap` on the pinned jar) — there is no mechanism left by which window
type could reach recovery.

**This is the same defect class as D20** (§20.4): the measurement window — here, how
long the fault stays on after OPEN — is sized by the independent variable.

Conclusion at this point: **H3's recovery-side negative control was not tested.** Not
"confirmed," not "falsified, as §28 says" — untested, because the comparison §28 is
about was comparing two different experiments (different fault-exposure duration) and
calling the difference a window-type effect. §28's own epistemic standard — "a falsified
prediction with an identified cause is more convincing than a confirmed one" — cuts the
other way once the cause of the *difference* is the exposure confound, not window type.

### 30.2 What R2 found (2026-10-01)

D28 commissioned a confirmatory run rather than resting on the inspection alone — the
same standard §27's acceptance audit and §25's disclosure-budget rule hold the paper to
everywhere else: a diagnosed mechanism is not a tested one. R2
(`docs/paper/r2-equal-exposure-plan.md`, pre-registered at commit `9964211`, before any
R2 row existed) cleared the fault at `OPEN + D_w + 5s` identically in both arms,
continuous 10 req/s load until recovery, the same 24 Phase 4B configurations × 3
replicates, one host (`jay-mac`, arm64), seed `20260929`.

72/72 runs completed, 0 excluded under any of the plan's five pre-registered exclusion
rules, 72/72 independently VERIFIED_CLEAN against the gateway poller.

- **P1.** Both arms bounced exactly once in every run, every stratum (72/72). Phase
  4B's "COUNT_BASED never bounces" (0/18) does not replicate under equal exposure — it
  was the exposure confound, not a ring-buffer limitation.
- **P2, primary.** Per-stratum median diff vs the pre-registered 1s threshold: $D_w$=5
  0.040s, $D_w$=15 0.029s, $D_w$=30 0.101s — all pass, all the same order of magnitude as
  each arm's own between-config SD (0.021-0.102s, added 2026-10-01 to the committed
  analysis as a dispersion check). Direction signs are mixed across strata (not
  reported as a clean monotone COUNT-faster or TIME-faster pattern) — stated as
  observed, because hiding the mixed sign would overstate how clean the equivalence
  call is.
- **P2, secondary.** `stratified_cluster_permutation_test` p=0.366 (floor 0.000006) —
  non-significant, and per the plan's own §5, **not** treated as proof of equivalence on
  its own. The primary evidence is the median-difference check above.
- **Falsification check.** Neither of D28's two revisit conditions fired.

**H3's recovery-side negative control passes.** Window type does not reach recovery.

### 30.3 What this means for the draft

- **Do not write** "H3 falsified," "the recovery leak," "COUNT_BASED never bounces,
  structurally," or "a time-based window retains fault evidence into recovery" as
  current findings anywhere in the draft. §4 (claim-by-claim provenance) and §9
  (reviewer-objection status) both reference the old framing and should be read through
  this correction.
- **§V-D is retired**, not softened a third time. The recovery comparison does not go
  in Results, because under the confound-free run it is not a window-type effect to
  report.
- **§VI gains an eighth defect entry**, distinct in kind from the other seven: it is the
  only one of the eight that inspection and modeling alone could not close — it needed
  a dedicated pre-registered confirmatory experiment. That is worth stating explicitly
  in §VI's own text, not just in these notes: it is a stronger demonstration of the
  paper's construct-validity thesis than a code-read defect is, because it shows the
  self-referential failure mode (§VI's closing argument) surviving even a first
  correction (D26) before a second, deeper one (D28) and a confirmatory test (R2) were
  needed to actually close it.
- **The chronology is the content, not an embarrassment to minimize.** Three dated
  positions, each the honest best read of the evidence available at the time: Phase 4B
  appeared to falsify H3 (2026-09-22, §28) → shown to be a fault-exposure confound, not
  tested either way (D28, 2026-09-29) → confirmed artifact, control passes (R2/D29,
  2026-10-01). §VI's thesis is that defects like this are invisible in aggregate
  statistics; this one stayed invisible through one full re-collection (D26) and one
  statistical correction pass, and needed a live experiment designed specifically to
  rule it out.
- **PAPER_BRIEF.md is updated** (§1, §2, §3, §4, §V plan, §VI plan) to the post-D29
  narrative — it is what to write; these notes are why.
