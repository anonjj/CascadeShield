# Statistical Treatment — The Paper's Default Test, CI, and Censoring Protocol

**Backlog item:** B5 (roadmap board) — "Define the statistical treatment, including censoring"
**Decision-log entry:** D19 (`docs/paper/decision-log.md`)
**Enforcement:** `analysis/common.py` — `mann_whitney`, `compare_groups`,
`censored_timing_summary`, `compare_censored_groups`
**Status:** defined and implemented; one existing script (`analysis/canary_readout.py`'s
`h1_matched_horizon`) predates this and has not been migrated — see §5.

---

## Why this needed writing down

`hypotheses.md` §6 ("Metrics contract") already states the *principles* — every mean carries a
bootstrap CI, every contrast carries an effect size, nulls in `time_to_open`/`time_to_recover`
are outcomes and are never mean-imputed. What it never pinned down is the *mechanics*: which
test, which CI procedure, and — most concretely — what a single reported number is allowed to
be when the underlying column is right-censored. Two people writing analysis scripts a week
apart without that pinned down will not independently arrive at the same answer, and the MDE
power-check (`analysis/mde_power_check.py`) already went ahead using Cohen's *d* — a fine
design-time rule of thumb, wrong as the paper's reported test (§2). This document is that
missing mechanics layer, and the four functions in `analysis/common.py` are its enforcement —
"write it once" means these functions are the only place any of this logic should live.

---

## 1. The default significance test: Mann-Whitney U, not a t-test

Every two-group comparison in this paper (COUNT vs. TIME at a given horizon, base vs.
matched-horizon arm, any config-vs-config contrast) uses the **Mann-Whitney U test**
(`analysis/common.py::mann_whitney`), not Welch's t-test or a pooled-variance t-test.

**Why non-parametric, not parametric.** Three independent reasons, any one of which would be
enough on its own:

1. **Small n per cell.** Most comparisons are between 3 and ~55 replicates/configs per side
   (`N_REPLICATES` is 3 for the main sweep; canary-matrix cells run 5). A t-test's validity
   at this n leans on the Central Limit Theorem rescuing it from non-normal data, which needs
   more observations than this project collects per cell to be a safe bet.
2. **The timing DVs are not shaped like a t-test wants.** `time_to_open`/`time_to_recover` are
   bounded below at 0, right-skewed (a breaker can take arbitrarily long to trip but not less
   than 0s), and `hypotheses.md` §4 documents an unexplained **TIME_BASED bimodality** in
   `time_to_open` — a bimodal distribution is about as far from the Gaussian a t-test assumes
   as this project's data gets.
3. **Consistency with the effect size already in use.** `cliffs_delta` (`analysis/common.py`)
   was already the project's standard effect size (D-001, D15, D18 all report it). Cliff's
   delta is the natural effect size *for* a rank-based test — pairing it with a parametric
   significance test (as `canary_readout.py`'s H1 currently does, see §5) reports two numbers
   answering two different questions about the same comparison.

**The rule.** Call `compare_groups(a, b)` — it runs `mann_whitney` and `cliffs_delta` together
and returns both, so a script cannot report one without the other. Every p-value in the paper
is Holm-Bonferroni corrected across its hypothesis family (`analysis/common.py::holm_bonferroni`,
unchanged by this document) before it is called significant.

**What this does not replace.** `stats.chi2_contingency` (trip-rate-by-window-type
contingency tables, `canary_readout.py`) and `stats.kendalltau` (`tau_sweep.py`, ranking
robustness under a moving threshold) are answering categorical-association and monotonicity
questions respectively, not "do these two continuous distributions differ" — they are outside
this document's scope and are not changed by it. `stats.levene`/Brown-Forsythe (variance
homogeneity) is a diagnostic, not the paper's significance test, and may still be reported
alongside Mann-Whitney where variance itself is the thing being described (e.g. the
TIME_BASED-5s-window variance finding from the MDE top-up).

## 2. Confidence intervals: bootstrap, clustered by configuration

Unchanged from the existing metrics contract, restated here because it's part of the same
protocol: every mean is a **percentile bootstrap CI**, 10,000 resamples
(`analysis/common.py::bootstrap_ci`). Whenever the quantity pools multiple replicate rows of
the same configuration, the **cluster bootstrap** (`bootstrap_ci_grouped`) is used instead of
plain row-level resampling — the effective sample size is the number of *configurations*, not
rows, because replicates of one `experiment_id` are not independent draws. Every function added
by this document (`censored_timing_summary`, `compare_censored_groups`) builds its CIs on
`bootstrap_ci_grouped`, never on the ungrouped version, for exactly this reason.

## 3. Censoring: nulls are outcomes, and they get their own number

A null in `time_to_open` means the breaker never opened during the observation window. A null
in `time_to_recover` means it opened but never returned to `CLOSED` within the window. Both are
**right-censored observations, not missing data** — this was already stated in
`data/DATA_DICTIONARY.md` and `hypotheses.md` §6 rule 4. What was missing is the reporting
shape that actually honors it.

**The failure mode this closes off.** `df[value_col].dropna().mean()` — averaging only the
non-null rows — silently *conditions on the event having happened*. If cell A trips in 40% of
its runs and cell B trips in 90% of its runs, a plain mean-of-non-null comparison between them
is not comparing "how fast do they trip," it's comparing "how fast do they trip, among a
40%-selected sample vs. a 90%-selected sample" — a different, uncontrolled population in each
arm. The comparison silently drifts up or down depending on each cell's own censoring rate,
which is exactly the shape of bug this document exists to make structurally impossible to
write by accident.

**The rule.** A right-censored timing DV is never reported as one number. It is reported as
**two, always together**:

1. **The rate** — the fraction of runs (or configs, cluster-bootstrapped the same as
   everything else) for which the event was observed at all. For `time_to_open` this is the
   **trip rate**; for `time_to_recover`, computed only among rows that did open, it is the
   **recovery rate**. This is `censored_timing_summary(df, value_col)["rate"]`.
2. **The conditional-timing distribution** — the bootstrap CI (and, in a two-group comparison,
   the Mann-Whitney/Cliff's-delta contrast) of `value_col`, computed *only* over the rows where
   the event was observed, explicitly labeled "conditional on tripping" / "conditional on
   recovering" wherever it's written up in prose. This is
   `censored_timing_summary(df, value_col)["conditional_timing"]`.

For a two-group comparison, `compare_censored_groups(df_a, df_b, value_col)` returns both
groups' rate + conditional-timing summaries *and* the Mann-Whitney/Cliff's-delta contrast on
the conditional-timing subset in one call — the single entry point every H1-H5 comparison on
`time_to_open`/`time_to_recover` should go through.

**φ is a related but distinct quantity.** The false-trip rate φ (mandatory control DV, §6 of
`hypotheses.md`) is the trip rate computed specifically over `fault_type = NONE` (null-fault)
runs. The "rate" half of `censored_timing_summary` is the general mechanism; φ is one specific,
already-named use of it and keeps its own name in every place it's reported.

**Validated against live project data** (not synthetic): running
`censored_timing_summary` on `data/occupancy_dataset.csv`'s TIME_BASED arm (the D18 occupancy
sweep) reproduces the already-published D18 numbers exactly — 108 rows, 30 censored
(`inert=True`), 78 observed, trip rate 0.722 [0.583, 0.861] (36 configs), conditional
`time_to_open` 9.89s [8.16, 11.79]. Anyone doubting the function can regenerate this from the
tracked dataset.

## 4. What every number in the paper must carry

Restating the existing metrics-contract rules alongside the two new ones, as one checklist:

1. Every mean/rate is a bootstrap CI (§2) — cluster-bootstrapped whenever it pools replicates.
2. Every two-group contrast on an uncensored quantity is Mann-Whitney U + Cliff's delta (§1),
   via `compare_groups`, Holm-Bonferroni corrected across its hypothesis family.
3. Every right-censored timing DV is reported as a rate + a conditional-timing distribution
   (§3), via `censored_timing_summary`/`compare_censored_groups` — never mean-imputed, never
   silently reduced to the non-null mean.
4. `excluded_reason`-marked rows are dropped from all of the above (unchanged, D-002) and their
   count is reported alongside, not silently absorbed into a smaller denominator.

## 5. Known deviation, not yet migrated

`analysis/canary_readout.py::h1_matched_horizon` currently uses `stats.ttest_ind` (Welch's t)
as its significance test, alongside `cliffs_delta` and a Brown-Forsythe variance check — it
predates this document and does not conform to §1. Its numbers already back a **closed**
decision (D-004, the Day-2 gate, 2026-09-08: "Paper B confirmed"), so this document does not
silently rewrite it: re-running H1 under Mann-Whitney could change the reported p-values on an
already-signed-off finding, and that re-run should happen as its own reviewed step, not as a
side effect of writing this file. Flagged here so it isn't rediscovered from scratch later.
Cliff's delta itself (already computed there) does not need to change — it was already the
project's rank-based effect size and is unaffected by which significance test runs alongside
it.
