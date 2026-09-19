# Lead 3 — Resilience4j TIME_BASED config audit

**Framing (depends on Lead 1, D18).** A COUNT_BASED sliding window structurally self-repairs
an unsafe `minimumNumberOfCalls` — it evaluates once its ring buffer fills, regardless of the
configured minimum (live-verified, decision-log.md D18). A TIME_BASED window does **not** —
`minimumNumberOfCalls` genuinely gates evaluation there. So a TIME_BASED breaker with
`minimumNumberOfCalls` too high relative to its actual traffic and window size can never
evaluate at all — permanently inert — and Resilience4j accepts this silently at startup, no
warning, no error. **The library silently repairs unsafe count-based configs and silently
accepts unsafe time-based ones.**

## Method

GitHub code search, 4 queries (`slidingWindowType`/`sliding-window-type` × `TIME_BASED` ×
`extension:yml`/`extension:yaml`), authenticated via the existing `gh` CLI login (no separate
PAT needed). 1,141 distinct file hits fetched and parsed
(`audits/resilience4j_timebased_audit.py`, self-tested). Config inheritance resolved
conservatively (see the script's module docstring and decision-log.md's D23 update for the
full reasoning): explicit `base-config` chains, the standard instance-without-`base-config` →
implicit `default` rule, and Resilience4j's own raw library defaults
(`slidingWindowSize=100`, `minimumNumberOfCalls=100`, confirmed from the library's own
`CircuitBreakerConfig.java` constants) for anything left unset beyond that — not the deeper,
version-specific implicit-`default`-inheritance-for-named-configs behavior CascadeShield's own
pinned Resilience4j 2.2.0 happens to have, since scanned repos pin unknown, heterogeneous
versions. This is a stated simplification, not a silent one: it means this audit's λ* values
may slightly *overstate* inertness for repos on older Resilience4j versions using a
`base-config`-less named-profile pattern.

For each resolved TIME_BASED breaker instance, we compute

    λ* = minimumNumberOfCalls / slidingWindowSize   (calls/sec)

— the sustained arrival rate a breaker needs just to ever accumulate enough calls in its
trailing window to evaluate at all. This is arithmetic on the file's own stated parameters,
not a claim about real traffic. **No prevalence claim is made or implied** ("X% of deployed
breakers are inert" would require knowing real traffic to each one, which this audit does not
and cannot know); only the distribution of λ* across the sample is reported.

## Results

**Reported first, before any other number:** 280 files across 192 distinct repositories
contained at least one resolved TIME_BASED breaker instance (447 instances total, some files/
repos define several). **49 of 447 (11%) look like demo/tutorial/example/sample/learning/test
repos or paths** by a case-insensitive substring heuristic on repo name or path — a heuristic,
not ground truth, and probably an undercount (many real tutorials don't say "demo" anywhere in
their name or path).

### λ* distribution by stratum (calls/sec needed to ever evaluate)

| stratum | n | min | Q1 | median | Q3 | max | >1/s | >10/s |
|---|---|---|---|---|---|---|---|---|
| all | 447 | 2e-05 | 0.150 | 0.500 | 0.500 | 20 | 47 (11%) | 9 (2%) |
| tutorial-like | 49 | 0.05 | 0.167 | 0.500 | 1.000 | 20 | 10 (20%) | 7 (14%) |
| non-tutorial-like | 398 | 2e-05 | 0.100 | 0.500 | 0.500 | 20 | 37 (9%) | 2 (1%) |
| stars = 0 | 350 | 5.787e-05 | 0.100 | 0.500 | 0.500 | 20 | 34 (10%) | 9 (3%) |
| stars = 1–9 | 88 | 2e-05 | 0.300 | 0.500 | 1.000 | 10 | 13 (15%) | 0 (0%) |
| stars = 10–99 | 8 | 0.06667 | 0.400 | 0.700 | 1.000 | 1 | 0 (0%) | 0 (0%) |
| stars = 100+ | 1 | 0.05 | 0.050 | 0.050 | 0.050 | 0.05 | 0 (0%) | 0 (0%) |

**Median TIME_BASED config in this sample needs a sustained ≥0.5 calls/sec to ever evaluate**,
consistent across the tutorial/non-tutorial split and across star buckets — not obviously a
"toy config" artifact, since the tutorial-like subset isn't systematically lower than the
non-tutorial one. Kept split by tutorial-vs-not and by star bucket throughout — never pooled
into one number, since a single copy-pasted starter config (see next paragraph) could otherwise
masquerade as independent convergence.

**The median is substantially driven by one duplicated config, not independent diversity.**
140/447 (31%) of all instances sit at exactly the sample median (0.500/s); of those, 101
(72% of the at-median group, 23% of the *entire* 447-instance sample) share one single
`(minimumNumberOfCalls=5, slidingWindowSize=10s)` pair — almost certainly one widely-copied
tutorial/starter snippet, not 101 independent authors converging on the same rate by chance.
A second pair, `(minimumNumberOfCalls=15, slidingWindowSize=30s)` — also λ*=0.5 — accounts for
another 36 (26% of at-median). Together these two pairs alone are 137 of the 140 at-median
instances. **The 0.5/s figure is a real central tendency, not an artifact of the search picking
up duplicate/forked files** (the underlying finding — TIME_BASED breakers commonly need
sub-1/s sustained traffic just to ever evaluate — still holds, since even the non-duplicated
majority of the sample sits in the same Q1–Q3 band), but the *median specifically* should be
read as "what one popular starter config plus everything near it looks like," not as evidence
of 447 independently-reasoned deployments landing on 0.5/s by coincidence.

### The extremes, checked by hand (not parser artifacts — both spot-verified against source)

- **Lowest:** `leellun/cloud-manager`, `T=100000s` (~27.8 hours), `n_min=2` → λ*≈0.00002/s —
  a real, legitimate long-window breaker (evaluates almost as soon as any 2 calls land within
  more than a day). `U-235-92/payment-system`, `T=86400s` (24h exactly), `n_min=5` — a
  plausible daily-cadence "currency rate update" service.
- **Highest, and the concrete illustration of the audit's framing:** `T=5s` with
  `minimumNumberOfCalls` **unset** (falling to the library default of 100) → λ*=20 calls/sec.
  Whoever wrote `sliding-window-size: 5` almost certainly wanted a fast-reacting breaker;
  instead, without also setting `minimum-number-of-calls`, they got one that can never
  evaluate unless the protected call site sustains ≥20 req/s. Found in **3 distinct
  repositories** (`sag128/MSDemo`, `Seonooo/kp-tickets`, `victorrentea/resilience` — 9 file
  hits total, but 6 of those are repeated config-server profile files within one repo, so 3
  independent authors is the honest count, not 9). **Tail placement, checked rather than
  assumed:** λ*=20 sits at the **98th percentile** of the full 447-instance distribution — 40×
  the ALL stratum's own Q3 (0.5/s) — clearly the tail, not the body. It is not a perfectly
  isolated point, though: 16/447 instances (3.6%) sit at λ*≥10/s, of which the 9 file hits
  above account for 9 and **7 other instances**, from different (n_min, T) pairs, also clear
  ≥10/s — a small cluster of similarly under-provisioned fast-window configs, not one freak
  outlier.

## Limitations, stated plainly

- **Not a prevalence claim.** This is a GitHub code-search sample, not a census of production
  Resilience4j deployments — repos that happen to be public, indexed, and textually matched
  are all that's here.
- **Tutorial heuristic is a substring match**, likely an undercount of actual toy/learning
  repos that don't name themselves as such.
- **Inheritance model is conservative** (see Method) — may overstate λ* for some
  older-Resilience4j-version configs using a specific inheritance pattern.
- **No cross-file/profile merge semantics** — each YAML document is resolved independently;
  Spring profile-layering across multiple `application-{profile}.yml` files sharing one
  logical service is not modeled.
- **1,000-result cap per GitHub search query** — none of the 4 queries here hit it
  (highest `total_count` was 650), so this sample isn't truncated by the cap, but a broader
  future query easily could be.

Raw third-party file content and hit metadata are not committed to this repository
(`audits/.cache/`, gitignored) — only this report and its underlying per-hit derived numbers
(`audits/out/report.json`) are.
