# Decision Log

Decisions that determine the shape of the paper, with the numbers that produced them. Entries
are append-only. **A decision recorded here is not reopened** — re-litigating scope mid-sprint is
the failure mode that costs the week, and it is the one risk the plan rates as certain.

Format: what was decided, the numbers, what was rejected, and what would have to be true to
revisit it.

---

## D-001 · $\tau_{\text{leg}}$ is reported as a curve, not chosen as a value

**Date:** Day 1 (Mon 10 Aug 2026) · **Decided by:** Soham · **Status:** final

**Decision.** The paper reports $B_{\text{real}}$ as a function of $\tau_{\text{leg}}$ over
$[0.05, 0.95]$ (Figure 7). No single threshold is adopted as *the* containment metric.

**Numbers** (`analysis/out/tau_sweep.json`, 80 runs / 26 configs):

- Only one service ever fires across all 320 leg observations: order-service, max rate
  **0.4867**.
- The shipped $\tau = 0.50$ sits above the entire support, so `real_blast_radius` is
  identically 0.0 in all 80 rows — constant by construction.
- The metric has resolution only on $\tau \in [0.25, 0.45]$: saturated at 0.25 below it,
  identically zero above it.
- **10 of 10 live threshold pairs rank the 26 configurations differently**, minimum Kendall's
  $\tau_b = 0.238$. Comparisons against $\tau = 0.50$ are undefined — it ranks everything at
  zero.

**Rejected:** re-pinning $\tau$ to a value inside the informative band. It would work, and it
would be a researcher degree of freedom exercised after seeing the data. The curve is both more
honest and more useful.

**Consequence:** H4 is supported on Day 1 with zero new experiments, against a plan that
scheduled it for Day 5 and expected it to be degenerate on LINEAR.

**Revisit if:** the FAN_OUT sweep produces legs on more than one service, which changes the
support and may move the informative band.

---

## D-002 · Contaminated rows are marked, never dropped

**Date:** Day 1 · **Decided by:** Soham · **Status:** final

**Decision.** `excluded_reason` is added to the dataset schema (column 20). Rows failing an
audit signature are marked with a machine-readable code and retained. `analysis/quarantine.py`
is the only writer; `runner.py` always writes it empty.

**Numbers** (`analysis/out/quarantine.json`): 1 of 80 current rows, 2 of 162 v2 rows, 0 of 92 v3
rows. Codes: `STATE_LEAK_EARLY_OPEN`, `STATE_LEAK_BLAST`, `RECOVERY_TIMEOUT_HANG`.

**Rejected:** deleting the rows. A silently dropped row is indistinguishable from one never
collected, and the difference is exactly what a reviewer cloning the artifact will check.

**Also rejected:** quarantining v3 row-by-row on its 95.7% impossible-blast rate. That is one
subject reading degraded in every run — a dead *column*, not 88 bad rows. Marking the column and
keeping 92 usable $t_{\text{open}}$ values is the correct trade.

---

## D-003 · The matched-horizon comparison is tested on a diagonal band, and the paper says so

**Date:** Day 2 (Tue 11 Aug 2026) · **Decided by:** Soham · **Status:** final

**Decision.** The matched-horizon arm derives the partner window in **both** directions —
$T = W/\lambda$ and $W = \lambda T$ — and infeasible cells are emitted with `feasible = 0` and a
stated reason rather than dropped.

**Numbers** (`data/canary_matrix.csv`): matching in the plan's single direction
($T = W/\lambda$) yields **3 usable configurations out of 12**. $T$ falls below Resilience4j's
one-second resolution for every $\lambda > 5$ with $W \in \{5, 10, 20\}$. Adding the reverse
direction recovers 12 usable configurations spanning $H = 5$ to $H = 800$, bounded above by the
1000-call `slidingWindowSize` ceiling ($\lambda = 320$, $T = 20$ would need $W = 6400$).

**Consequence:** H1 is testable on a diagonal band of the $(\lambda, H)$ plane, not on the full
plane. Section VII states this as a design limit rather than letting a reviewer find the gap.

---

## D-004 · Day-2 Gate — which paper gets written

**Date:** Day 2 (Tue 11 Aug 2026) · **Decided by:** Soham + Jay, jointly · **Status:** ⏳ PENDING CANARY

> **This entry is not yet a decision.** It is filled in from
> `analysis/out/canary_readout.json` the evening the canary finishes, and closed before
> midnight on Day 2.

### Gate table

| Canary outcome | Paper | Days 3–7 pivot |
|---|---|---|
| Crossover $\lambda^*$ visible **and** variance gap significant at matched $H$ | **A — "The Window Is an Estimator."** H1/H2 core, H3/H5 supporting | Full sweep includes $\lambda$. Target ICPE / IEEE Access |
| Crossover visible, variance gap not significant | **A′** — H2 alone: static window configuration is correct at exactly one traffic level | Same sweep, narrower claim |
| No $\lambda$ effect at all | **B — construct validity.** H3 + H5 + H4 + metric evolution | Drop $\lambda$. Days 3–4 go to FAN_OUT + TREE breadth |

`analysis/canary_readout.py` prints the recommendation directly. Its three branches are verified
against synthetic data (`--self-test`); the gate logic is not decided by hand at 23:00.

### Preconditions — check these before reading the gate

- [ ] **$\lambda$ fidelity.** `lambda_achieved` recorded, and within 15% of target. If it was
      never recorded, **H1 and H2 cannot be claimed at all** — the independent variable is
      unmeasured. This is a hard blocker, not a caveat, and it is Jay's Day-2 instrumentation.
- [ ] **Monotone trip rate.** If trip rate *falls* as $\lambda$ rises for either window type,
      no mechanism explains that. Stop and diagnose the harness before reading anything else.
- [ ] **`precondition_ok`** true on every row (breakers asserted CLOSED before each run).
- [ ] **Mode-mixing check.** Per the leak audit, TIME_BASED $t_{\text{open}}$ is bimodal
      (−2.70 s displacement, 4 configs). Before claiming H1, establish whether any variance gap
      is a **sampling property** or a **mixing proportion between two discrete modes**. If it is
      mixing, H1 as stated is not supported and the finding is different — and more interesting.

### To be filled in

```
Decision:              Paper ___
H2 crossover:          TIME_BASED ___ (bracket: lambda in [___, ___] req/s)
                       COUNT_BASED ___ (must be absent for H2 as stated)
H1 at matched H:       Welch p = ___ (Holm ___), difference ___ s, 95% CI [___, ___]
                       Brown-Forsythe W = ___, p = ___ (Holm ___)
                       sd COUNT ___ vs TIME ___, Cliff's delta ___ (___)
Mode-mixing verdict:   ___
phi (false-trip rate): ___ [___, ___] over ___ null-fault runs
lambda fidelity:       ___ of ___ runs off target; worst deviation ___
Signed:                Soham ___  Jay ___
```

**Not reopened on Day 4.** The Day-4 gate decides whether the *data* supports the chosen paper.
It does not reconsider which paper.

---

## D-005 · Run-order seed

**Date:** Day 2 · **Status:** final

`RUN_ORDER_SEED = 20260811`, persisted to every dataset row as `run_order_seed` with position as
`run_index`. Sequential execution of a long sweep on one host confounds treatment with thermal
and memory drift; the seeded shuffle is what lets anyone re-derive the exact order from the
artifact alone.

---

## D-006 · H3's recovery-side negative control is downgraded to untested, pending the
transition sidecar

**Date:** 2026-08-25 (ad hoc D12 investigation, outside the Day 1–5 cadence) · **Decided
by:** Jay · **Status:** final (downgrade), revisit conditional on new data

**Decision.** H3's §4 leak-audit clearance never actually tested `window_type` as a factor
on $t_{\text{rec}}$ — it tested for breaker state carrying over between replicates, a
different contamination mode. `analysis/window_type_recovery_leak.py` runs the direct test.
H3's negative control on $t_{\text{rec}}$ is downgraded from "cleared" to "untested against
this specific mechanism, pending a re-run that retains `data/cb_transitions.jsonl`."

**Numbers** (`analysis/out/window_type_recovery_leak.json`, 79 rows / current archive; same
shape on `v2_latency_5svc` and `v3_gateway_not_rebuilt`): TIME's median $t_{\text{rec}}$ is
2.06–3.68x COUNT's at every matched $D_w \in \{5,15,30\}$. Decomposed: TIME's $t_{\text{open}}$
anchor runs a flat ~3s later than COUNT's at every $D_w$ (non-buggy — TIME_BASED windows
accumulate over wall-clock seconds), but TIME's excess over $D_w$ **grows** (19.1s → 20.2s →
35.1s) while COUNT's stays flat (~1.5–1.7s) — not explainable by a constant anchor shift
alone. The precise HALF_OPEN→CLOSED metric that would isolate the leak from the anchor shift
could not be computed: `data/cb_transitions.jsonl` does not exist in any archive on disk.

**Rejected:** treating the existing §4 leak-audit clearance as also covering a window_type
main-effect check on $t_{\text{rec}}$ — it doesn't; it never varied window_type as a factor.
**Also rejected:** reporting a leak/no-leak verdict from the coarse ratio alone — the anchor
shift is a real, legitimate, non-buggy confound that the coarse metric cannot separate from
a genuine recovery-side effect.

**Revisit if:** a future `experiments/runner.py` invocation retains `data/cb_transitions.jsonl`
for a sweep spanning both window types at matched $D_w$ — re-run
`analysis/window_type_recovery_leak.py` against it and read the `precise` block's verdict.

---

## D-007 · $B$ (blast_radius, quartized) is retired; `order_leg` is the reported containment signal

**Date:** 2026-08-26 (ad hoc D3 investigation, outside the Day 1–5 cadence) · **Decided
by:** Jay · **Status:** final

**Decision.** The quartized containment metric — legacy `blast_radius` (CB-state) and
`real_blast_radius` at any pinned $\tau_{\text{leg}}$ — is retired as a reported outcome. It
is not fixed (no threshold is re-pinned) and not replaced by a new binarized definition; it
is dropped to §7 threats-to-validity with an honest paragraph on why. `order_leg` — the raw,
continuous `leg_failure_rates["order-service"]` value, the one leg that ever fires on the
data collected so far — becomes the reported containment DV (hypotheses.md §5.4, §6). The
legacy CB-state `blast_radius` column itself needs no further code fix: it has been
structurally correct since the gateway-isolation change (§7); it stays in the schema for
reference but is cited nowhere as evidence.

**Numbers** (`analysis/out/order_leg_containment.json`, `current` archive, 79 rows): 32
distinct `order_leg` values (vs. 2 for the quartized metric on the same rows); COUNT_BASED
means monotonic in `window_size` (0.2798 / 0.3330 / 0.4160 at $W$ = 5/10/20, pooled 95% CI
[0.293, 0.355]); TIME_BASED tightly banded (0.4688 / 0.4665 / 0.4708, pooled 95% CI [0.461,
0.476]); clean separation with no overlap — COUNT_BASED max 0.4167 < TIME_BASED min 0.4500,
Cliff's $\delta = -1.0$ (large, $n_a$=41, $n_b$=38).

**Rejected:** re-pinning $\tau_{\text{leg}}$ inside D-001's informative band ($\tau \in
[0.25, 0.45]$). It would restore some resolution and rank configurations non-degenerately,
but keeps a researcher-chosen threshold that `order_leg` does not need at all — the
continuous value already separates window_type with zero overlap and moves monotonically
with a swept parameter.

**Consequence — the tension this decision surfaces.** Isolating the gateway (necessary to
kill the gateway-CB confound) also removed the only propagation path a chain topology can
expose: §5.3 shows exactly one leg (order-service) ever fires on LINEAR, structurally, not
by calibration accident. Cascade (more than one leg degraded at once) is therefore
unobservable on LINEAR by construction. Confirmed via topology counts: every row in
`current`, `v2_latency_5svc`, and `v3_gateway_not_rebuilt` is LINEAR — zero FAN_OUT rows
exist in any archive. `--topology fanout` is implemented in `experiments/runner.py`
(argparse choice) but has never been swept. Every cascade-shaped claim (H5 beyond its
LINEAR half, H6) depends on that sweep.

**Revisit if:** a FAN_OUT sweep is run. Re-derive the same table — check whether a second
leg firing changes `order_leg`'s clean separation or monotonicity, and whether the
quartized metric becomes informative again now that more than two node-sets are reachable
(in which case this decision's "retire" call should be revisited, not assumed to still
hold).
