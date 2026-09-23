# DEVIATION 02 — drop the outcome-dependent term from the verification horizon

**Supersedes DEVIATION 01 as the horizon used in the primary H3 analysis.** It produces
verdicts identical to DEVIATION 01's on every one of the 72 Phase 4B runs, and it does so
without reading any measurement column, so it needs no argument about circularity.

The pre-registration (`docs/paper/h3-postd25-analysis-plan.md`, frozen at
`3e4ad1e5d0596883bbd35604828d0d2db39a9eb2`) is **not edited**. §5 of this note proves it.

---

## 1. The finding — DEVIATION 01's `min()` clips to `run_timestamp` on all 72 runs

DEVIATION 01's rule is

```
end = min( fault_cleared_at + (time_to_recover, or the §5.1 fallback) + 5 s ,
           run_timestamp )
```

Define the slack between the two terms:

```
slack = run_timestamp - (fault_cleared_at + time_to_recover + 5 s)
```

`slack < 0` means `run_timestamp` is the smaller term, so the `min()` takes it and the first
term has no effect. Measured over all 72 runs:

| arm | $D_w$ | n | min slack | median | max | `min()` binds |
|---|---|---|---|---|---|---|
| COUNT | 5 | 12 | −4.833 | −4.673 | −3.758 | **12 / 12** |
| COUNT | 15 | 12 | −5.569 | −4.828 | −4.197 | **12 / 12** |
| COUNT | 30 | 12 | −5.435 | −4.559 | −4.209 | **12 / 12** |
| TIME | 5 | 12 | −28.768 | −22.331 | −19.091 | **12 / 12** |
| TIME | 15 | 12 | −39.773 | −32.827 | −30.151 | **12 / 12** |
| TIME | 30 | 12 | −56.252 | −49.894 | −47.292 | **12 / 12** |
| **all** | | **72** | **−56.252** | **−12.330** | **−3.758** | **72 / 72** |

Slack is negative on every run, and the largest value (−3.758 s) is not close to zero. **The
first term of the `min()` never has any effect on this dataset**, so it can be removed without
changing anything.

The clip removes a median of **4.59 s** from a COUNT horizon and **32.83 s** from a TIME one —
which is exactly the arm-correlated over-coverage DEVIATION 01 identified.

## 2. The simplification

```
start = fault_injected_at        (sidecar record)
end   = run_timestamp           (CSV column)
```

Coverage tolerance **1.6 s, unchanged**. The horizon is undefined — and the run therefore
`NOT_VERIFIED` — if either stamp is unusable, or if the run's end precedes fault injection.

**This rule reads no measurement column at all.** Not `time_to_recover`, not `wait_duration`,
not `half_open_probe_deadline_s`. `fault_injected_at` and `run_timestamp` are pure scheduling
timestamps: the harness writes them at fixed points in `run_experiment_run` regardless of what
the run measured or whether it measured anything.

Two consequences worth stating:

* **§5.1's null-`time_to_recover` fallback becomes irrelevant here**, because the rule never
  reads `time_to_recover`. A run whose recovery was never observed gets exactly the same
  horizon as one whose recovery was observed instantly.
* **DEVIATION 02 is not a relabelling of DEVIATION 01.** The two coincide only while the
  `min()` clips. Where the §5 term is the smaller one — which does not occur in this dataset
  but is perfectly possible in another — they give different windows, and the self-test
  constructs that case explicitly so the distinction cannot rot into an assumed identity.

## 3. Equivalence, proved on the actual data as a verdict-set diff

Not a comparison of totals. The verdict maps are compared key by key over
`(experiment_id, replicate)`:

```
literal  {'NOT_VERIFIED': 35, 'VERIFIED_CLEAN': 37}
dev01    {'VERIFIED_CLEAN': 72}
dev02    {'VERIFIED_CLEAN': 72}

DIFF dev01 vs dev02 : 0 disagreement(s)
  {}   <- empty: the two verdict sets are IDENTICAL, key by key, all 72

identical as dicts   : True
all 72 VERIFIED_CLEAN under dev02 : True (72 keys)

DIFF literal vs dev02 : 35 disagreement(s)   (the 35 TIME runs, as expected)
```

This is asserted programmatically, not narratively.
`analysis/phase4b_postsweep_check.py --self-test` loads the real dataset when it is present
and asserts:

* all 72 runs present,
* **`verdict_diff(dev01, dev02) == {}`** — the empty-diff claim itself,
* the two verdict maps are equal as dicts,
* every DEVIATION 02 verdict is `VERIFIED_CLEAN`,
* the literal rule genuinely differs, on exactly 35 runs — so the diff being empty is not an
  artifact of a comparison that cannot detect anything.

The synthetic half of the self-test proves the property that motivates the change: the
DEVIATION 02 horizon is **unchanged** when `time_to_recover` is varied across
`0.001 / 3 / 30 / 600 / "" / "not-a-number"` and when `wait_duration` is blanked, while
DEVIATION 01's end **does** move with `time_to_recover`.

## 4. Why this matters — it is outcome-independent by construction

DEVIATION 01 §5 had to argue that its residual circularity was harmless. The argument was
sound but it was an argument: the horizon still contained `time_to_recover`, the primary
outcome, so the defence rested on (i) the `min()` capping it, (ii) the residual dependence
biasing *against* the observed result rather than toward it, and (iii) no run being excluded
in the end. A reader had to check three things and accept a direction-of-bias claim.

**DEVIATION 02 needs none of that.** The rule is a function of two scheduling timestamps. There
is no outcome inside it, so there is no circularity to point in any direction, and no reader
has to take a direction-of-bias argument on trust. The property is mechanical and is asserted
by a test rather than asserted in prose.

**DEVIATION 01 remains historically accurate and is not withdrawn.** It is what was reasoned
through on 2026-09-21, during collection, before any verification count under a corrected
horizon existed — and that ordering is the guarantee that matters for it. Its diagnosis of the
defect (§2 and §3 of that note: the §5 horizon over-covers by an amount proportional to the
dependent variable, and reaches into the next run's `update_containers()` window) is unchanged
and is the reason this note exists at all.

**DEVIATION 02 supersedes it as the horizon used in the primary analysis**, on the narrow
ground that it is simpler and requires no defence of circularity — not because DEVIATION 01
was wrong. Both remain implemented, both remain selectable, and both are printed on every run
of the post-sweep check.

What DEVIATION 02 does **not** buy: it is still a data-contingent analytic choice, made after
seeing that the literal rule emptied the TIME arm. It inherits that from DEVIATION 01 and does
not repair it. The reporting plan below is unchanged from DEVIATION 01 §6 for exactly that
reason.

### Reporting plan — unchanged

Every result carries all of:

* **(a)** the **literal pre-registered rule** and its consequence: TIME arm empty, all strata
  excluded, **the stratified test is not run**, reported as *"insufficient clean data"*, never
  as a null result;
* **(b)** the **DEVIATION 02** analysis, labelled as such in every table, caption and p-value;
* **(c)** the sensitivity with the coverage requirement removed entirely.

DEVIATION 01's numbers need not be reported separately, since they are identical to (b) on this
dataset — but the note stays in the repository as the record of how (b) was arrived at, and any
report of (b) should cite both.

## 5. The pre-registration is not edited

```
$ git diff --quiet 3e4ad1e5d0596883bbd35604828d0d2db39a9eb2 HEAD -- docs/paper/h3-postd25-analysis-plan.md
$ echo $?
0
```

Blob at HEAD: `199770f9819ae7e52b23edde903bd92d076a9f8f` — the same blob the launch script's
assertion **b** checked when this sweep launched. Nothing in the plan file was changed for
DEVIATION 01 and nothing is changed for DEVIATION 02.

## 6. Implementation

`analysis/phase4b_postsweep_check.py`:

* `simplified_horizon(rec, row)` — the DEVIATION 02 rule.
* `HORIZONS` — `{"literal", "dev01", "dev02"}`, so all three are addressable by name.
* `verdicts_by_horizon(...)` / `verdict_diff(...)` — the key-by-key comparison §3 reports.
* **`--horizon-v2`** selects DEVIATION 02 for gate 7. A **separate flag** from
  `--corrected-horizon` rather than a redefinition of it, so DEVIATION 01's result stays
  reproducible from the same script and the historical record does not silently change meaning.
  The two flags are mutually exclusive and the parser rejects both together.
* Gate 7 **always prints all four views** — literal, DEV 01, DEV 02, sensitivity — plus the
  DEV01-vs-DEV02 diff count, whichever flag is passed. The pre-registered rule remains the
  default when no flag is given.

`analysis/gateway_poll_verify.py` is still **not** modified: it is the implementation of the
pre-registered rule and remains byte-identical to the version the live poller ran during
collection.

---

## Correction (2026-09-22) — the DEVIATION 02 horizon is not outcome-independent

*Appended; the text above is unedited. Recorded in decision-log.md D26.*

§2 above says `fault_injected_at` and `run_timestamp` "are pure scheduling timestamps: the
harness writes them at fixed points in `run_experiment_run` regardless of what the run measured
or whether it measured anything", and §4 calls the rule "outcome-independent by construction".
**Both statements are wrong about `run_timestamp`.** The *code point* is fixed; the *wall-clock
instant* at which it is reached is not.

`run_timestamp` is stamped by `time.gmtime()` inside `log_results()`
(`experiments/runner.py:1125`), when the CSV row is written. That happens after recovery
polling, and the recovery poll exits the moment recovery is detected. So a run that recovers
later writes its row later, and its DEVIATION 02 horizon `fault_injected_at .. run_timestamp`
is longer. Measured on all 72 Phase 4B runs:

| | value |
|---|---|
| correlation, horizon length vs `time_to_recover` | **r = 0.994** |
| OLS slope | +1.073 s of horizon per 1 s of `time_to_recover` |
| COUNT horizon length | median 25.0 s, range 15.0–41.0 s |
| TIME horizon length | median 48.0 s, range 31.0–82.0 s |

The rule reads no outcome **column**. It is still outcome-**dependent**, through the timing of
the row write.

**Why this does not undermine the fix.**

1. **It removes the defect DEVIATION 01 identified.** The horizon ends at the row write, and
   `update_containers()` for the next run is called only after the current run has returned,
   so the verification window structurally cannot fall inside the next run's recreate window.
   The differential exclusion of the TIME arm cannot recur.
2. **The dependence runs toward strictness, not leniency.** A longer horizon demands complete
   poller coverage and an all-`CLOSED` gateway over more seconds. Slow recoveries therefore
   face a *harder* verification test than fast ones. Had that excluded anything, it would have
   removed slow — predominantly TIME — runs, which shrinks a TIME-slower gap. That is the
   opposite of a bias that could manufacture the observed effect. In this dataset it excluded
   nothing: 72/72 are VERIFIED_CLEAN.
3. **The zero-trip evidence does not depend on any horizon.** The sidecar records zero gateway
   transitions across the 72 runs, and the poller observed no non-CLOSED gateway state among
   all 59,292 state observations in the session.

What changes is only the justification: DEVIATION 02 should be defended on points 1–3, not on a
claim that it is independent of the outcome.

**Where r = 0.994 was computed.** In the 2026-09-22 verification of the D26 draft, by an ad hoc
script that is not committed. It reproduces from committed files alone:

```bash
python - <<'PY'
import csv, json, datetime as dt, statistics as st
ts = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
rows = list(csv.DictReader(open('data/phase4b_postd25.csv', encoding='utf-8-sig')))
sc = {(r['experiment_id'], str(r['replicate'])): r
      for r in (json.loads(l) for l in open('data/cb_transitions.jsonl', encoding='utf-8') if l.strip())
      if r.get('machine_id') == 'soham-local' and r.get('fault_injected_at', '') >= '2026-09-21T17'}
H = [ts(r['run_timestamp']) - ts(sc[(r['experiment_id'], r['replicate'])]['fault_injected_at']) for r in rows]
T = [float(r['time_to_recover']) for r in rows]
mh, mt = st.mean(H), st.mean(T)
r = sum((h - mh) * (t - mt) for h, t in zip(H, T)) / ((len(H) - 1) * st.stdev(H) * st.stdev(T))
print(len(H), round(r, 4))   # -> 72 0.9937
PY
```

The sidecar filter selects the 72 Phase 4B records (the file also holds the 73 historical
records). Pearson is computed by hand so the snippet runs on the repo's Python 3.9.
