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

| stratum | n | median | IQR | min | max |
|---|---|---|---|---|---|
| all | 447 | 0.500 | [0.150, 0.500] | 2e-05 | 20 |
| tutorial-like | 49 | 0.500 | [0.167, 1.000] | 0.05 | 20 |
| non-tutorial-like | 398 | 0.500 | [0.100, 0.500] | 2e-05 | 20 |
| stars = 0 | 350 | 0.500 | [0.100, 0.500] | 5.787e-05 | 20 |
| stars = 1–9 | 88 | 0.500 | [0.300, 1.000] | 2e-05 | 10 |
| stars = 10–99 | 8 | 0.700 | [0.400, 1.000] | 0.06667 | 1 |
| stars = 100+ | 1 | 0.050 | — | 0.05 | 0.05 |

**Median TIME_BASED config in this sample needs a sustained ≥0.5 calls/sec to ever evaluate**,
consistent across the tutorial/non-tutorial split and across star buckets — not obviously a
"toy config" artifact, since the tutorial-like subset isn't systematically lower than the
non-tutorial one.

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
  independent authors is the honest count, not 9).

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
