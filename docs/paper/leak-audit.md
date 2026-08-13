# Breaker-State Leak Audit

**Owner:** Soham More · **Day 1 deliverable** · Regenerate with `python analysis/leak_audit.py`
**Machine-readable output:** `analysis/out/leak_audit.json`, `analysis/out/leak_audit_rows.csv`

---

## The question this had to answer

`runner.py` does not reset circuit breakers between replicates. A breaker left OPEN by the
previous run starts the next one already tripped, which fabricates an impossibly fast
`time_to_open` and a `blast_radius` above zero on subjects whose own legs recorded no failures.

The canonical instance is `LIN-LAT-CNT-T30-W20-D5` replicate 1: $t_{\text{open}}$ = 0.303 s
against 6.256 / 6.377 for its identical siblings, and $B$ = 0.75 with three of four legs at
exactly 0.0000. That single row invented precisely the multi-service cascade this project exists
to look for.

The Day-1 risk was that this is endemic in the archive, in which case the July 30 detection
latency numbers move and **H3 has to be recomputed on clean data only**.

**It is not endemic. 2 contaminated rows in 334 timed rows — 0.6%. H3 stands.**

Two other findings displaced it, and both are more consequential.

---

## Results

| Dataset | Rows | Early-open hits | After global screen | Impossible-blast | Verdict |
|---|---:|---:|---:|---:|---|
| `master_dataset_v1_prefix.csv` | 486 | — | — | — | **Un-auditable and unusable** |
| `master_dataset_v2_latency_5svc.csv` | 162 | 3 | **1** | n/a | 1 leak + 1 hang, quarantined |
| `master_dataset_v3_gateway_not_rebuilt.csv` | 92 | 1 | **0** | 88 (95.7%) | Timing usable, `blast_radius` **dead** |
| `master_dataset.csv` (current) | 80 | 1 | **1** | 1 | 1 leak, quarantined; 79 analysable |

### Finding 1 — the 486-row archive cannot support H3, or anything else

`time_to_open` and `time_to_recover` are **null in all 486 rows**. The collector was a stub when
that sweep ran. There is no `leg_failure_rates` column either, so neither leak signature can even
be evaluated, and `blast_radius` is on the raw 0–100 percent scale with a 5-service denominator.

This file cannot be audited, cannot be analysed, and cannot be pooled with anything. It is
provenance, not data. Any claim sourced to "the 486-run sweep" needs re-sourcing.

### Finding 2 — the leak is real but rare

After screening (below), two rows survive as genuine contamination, both in the SEVERE tier:

| Dataset | Config | Rep | $t_{\text{open}}$ | Cell median | Also fails blast check |
|---|---|---:|---:|---:|---|
| current | `LIN-LAT-CNT-T30-W20-D5` | 1 | **0.303** | 6.256 | yes — $B$ = 0.75, 1 leg firing |
| v2 | `LIN-LAT-TIM-T50-W5-D15` | 1 | **0.291** | 3.779 | n/a (disjoint node sets) |

Both are now marked `excluded_reason = STATE_LEAK_EARLY_OPEN` by `analysis/quarantine.py`.
Neither is deleted.

### Finding 3 — $t_{\text{open}}$ is bimodal under TIME_BASED, and it is a mechanism

The naive rule flagged five more rows in the current dataset. They are not contamination. In
TIME_BASED / $W = 5$ cells, $t_{\text{open}}$ takes two values and nothing between them:

```
3.38  3.44  3.45  3.55  3.58  3.59  3.63  3.68  3.69        <- 9 runs, "fast" mode
6.26  6.27  6.27  6.32  6.32  6.35  6.36  6.39  6.47  6.51  6.52   <- 11 runs, "slow" mode
```

The displacement is −2.70 s, reproduced across four distinct configurations in the current
dataset, and a −2.59 s displacement recurs across three more configurations spanning the v2 and
v3 archives. Contamination is sporadic; this is a property of the instrument.

**This bears directly on H1.** H1 claims COUNT and TIME differ in the *variance* of
$t_{\text{open}}$ at matched horizon. If TIME_BASED $t_{\text{open}}$ is mode-switching rather
than continuous, an observed variance gap may be a mixing proportion between two discrete modes
rather than a sampling property of the estimator — a different and much weaker claim. The Day-2
read-out has to separate those before H1 can be asserted.

The mode gap is unexplained as of Day 1. It is carried into Section VII.

### Finding 4 — `blast_radius` in the v3 archive is a constant, not a measurement

In 88 of 92 rows the metric reports a subject OPEN whose own leg recorded zero failed or
rejected calls. At 95.7% this cannot be per-run contamination — one subject reads degraded in
every single run, so the column carries a fixed offset.

This is the actual explanation for the July 30 gate result. `validate_gate.py` passed at
Cramér's V = 0.196 not because the label was independent of window type, but because the label
was **near-constant**. The ≥15%-per-class guard the sprint plan calls for on Day 3 is the right
fix, and this is the evidence for it.

The rows are **not** quarantined — their timing measurements are unaffected and quarantining
would throw away 92 usable $t_{\text{open}}$ values to fix a column that timing analyses never
touch. The *column* is marked unusable instead.

---

## Method, and why the stated rule could not be used as stated

### S1 — early open

The sprint plan words this as "$t_{\text{open}}$ more than 3 SD below its sibling replicates".
That rule is unusable at $n = 3$: the sibling SD is estimated from two points, so a cell whose
replicates agree to three decimals yields SD ≈ 0.002 s and a row 0.05 s faster scores $z = -41$.
**Run as written it flags 33 of the 80 current rows**, almost all on sub-0.1 s gaps that are
plainly timer noise.

Three changes make it work:

1. **Borrow the scale across cells.** Per-cell residuals (row − cell median) are pooled *within
   window type* — COUNT and TIME differ in spread by an order of magnitude — and their MAD gives
   a robust $\sigma$ that a minority of contaminated points cannot inflate. Measured $\sigma$:
   0.048 s (COUNT) and 0.062 s (TIME) on the current dataset.
2. **Reference the full-cell median, not leave-one-out.** At $n = 3$ the leave-one-out median of
   two siblings is just their midpoint, so on a cell like (9.73, 9.61, 15.90) both members of
   the majority pair get measured against ≈12.75 and both are flagged, while the genuine odd row
   is not. Including the row keeps the reference on an actual observation.
3. **Require a material absolute gap** (≥ 1 s) alongside the $z$ gate, which is what keeps timer
   noise out regardless of how tight a cell happens to be.

Hits are tiered — SEVERE (opened in under half the cell median) and MODERATE — then screened for
recurrence: hits whose residuals agree within 15% across ≥ 3 distinct configurations are
reclassified `RECURRENT_MODE` and dropped from the leak count. That screen is what separates
Finding 2 from Finding 3, and without it the audit would have reported a 7.5% leak rate that is
mostly Finding 3 in disguise.

### S2 — impossible containment

$\text{round}(B \times \text{denominator}) > \text{count}(\text{leg failure rate} > 0)$. A
breaker cannot sit OPEN across the fault window while its own leg records zero failed-or-rejected
calls, unless it entered the run already open.

This check is **exact only where `blast_radius` and the leg vector range over the same nodes**,
which is true only for the current dataset. On v2 the legs include the gateway and the blast
subjects exclude it, so the gateway leg alone satisfies the inequality on every row and the
check returns zero hits that mean nothing — reported as `INDETERMINATE`, never as `CLEAN`.

Above a 50% hit share the signature is reclassified `CONSTANT_OFFSET`, because a per-run leak is
sporadic by nature. That is what produced Finding 4.

### Not counted as leaks

- **Late-open outliers.** Rows far *above* their cell median (e.g. 32.8 s where the cell opens
  at 9.5 s). The leak makes breakers trip early, never late. Recorded as a diagnostic because
  they are the mild form of the hang that produced the 7540.5 s recovery row, and they feed the
  120 s protocol cap.
- **Recurrent modes** (Finding 3).

---

## Consequences for the sprint

1. **H3 does not need recomputing on a reduced dataset.** Prevalence is 0.6%; the two affected
   rows are excluded and the numbers hold. The Day-1 risk closes.
2. **Never source a claim to the 486-run archive.** It has no timing data at all.
3. **`blast_radius` from v3 must not be used as an outcome.** Timing from v3 is fine.
4. **H1 has a new prerequisite:** distinguish a mode-mixing explanation from a sampling-variance
   explanation of any COUNT-vs-TIME variance gap. This is a Day-2 read-out obligation.
5. **Jay's reset-and-assert protocol remains the highest-leverage fix**, even at 0.6%. The two
   contaminated rows are not random noise — they are the rows that fabricate cascades, which is
   the one failure mode this project cannot afford to publish.
