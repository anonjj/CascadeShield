# Related work — novelty verification (T1)

**Status:** search closed 2026-09-20. See [decision-log D27](decision-log.md) for the verdict
and how it changes the novelty sentence. This file is the evidence base; the decision log is
the record of what was decided from it.

**Why this file exists.** The project's novelty claim — most explicitly at `README.md:13`,
"a dimension largely absent from existing Resilience4j empirical literature" — had never been
checked against the literature; it was written from project notes. This is that check: every
near-miss found, with a one-line note on how CascadeShield differs, so the eventual paper's
Related Work section has a real base instead of an assertion.

**Search coverage.** Query terms (from the task): `"sliding window" + circuit breaker`,
`failure-rate estimation + microservice resilience`, `Resilience4j empirical`,
`circuit breaker misconfiguration`, `"minimumNumberOfCalls"`. Run across Consensus (Semantic
Scholar/PubMed/Scopus/arXiv), Firecrawl's arXiv-affiliated paper search, general web search
targeted at the named venues (ICPE, ICSA, ISSRE, Middleware, SoCC, ASE, ICSE SEIP, IEEE Access,
SPE, EMSE) plus arXiv directly, and the Resilience4j GitHub issue/discussion tracker. No paper
search API used here can filter by venue directly, so venue coverage was checked by querying
each venue name alongside the search terms rather than by an exhaustive per-venue crawl —
noted as a limitation below.

## Verdict

**No prior work found treats `COUNT_BASED` vs `TIME_BASED` sliding-window type as an
independent variable in a live-instrumented empirical study at the application
resilience-library layer.** The closest work studies adjacent parameters (retry budgets,
open-state duration, adaptive control) of the same libraries, or studies the same *kind* of
question (window-based failure aggregation) at a different layer (streaming systems, service
mesh/proxy). The Resilience4j maintainer/issue tracker shows the count/time distinction's
*behavioral* consequences are known operationally to library users — but not characterized as
a research question with controlled, replicated, live-fault evidence.

This supports the ticket's fallback framing: reframe as **first systematic empirical
characterization of the count/time window distinction, with live instrumented evidence** —
not "first observation" (the distinction itself is not unobserved; the *systematic controlled
characterization* is what's missing) and not an unqualified "no prior work" claim.

## Near-miss log

| Source | Venue/year | What it does | How CascadeShield differs |
|---|---|---|---|
| [Aderaldo et al., "A declarative approach and benchmark tool for controlled evaluation of microservice resiliency patterns"](https://onlinelibrary.wiley.com/doi/10.1002/spe.3368) + [ResilienceBench-Operator](https://consensus.app/papers/details/e8bd9ed541195faa8f4a13cabb7d979a/) | *Software: Practice and Experience* 2024/2025; JSERD 2026 | Declarative benchmark harness for Retry/Circuit Breaker across Resilience4j (Java) and Polly (C#); controlled, live, varies workload/failure-rate/retry config; Kubernetes operator extension varies retry params across Pareto-frontier analysis | Closest methodological sibling (controlled, live-instrumented, real resilience libraries). Never varies `slidingWindowType`/window size as an IV — sweeps retry and workload parameters, not the count/time window distinction |
| [Sedghpour et al., "Breaking the Vicious Circle: Self-Adaptive Microservice Circuit Breaking and Retry"](https://ieeexplore.ieee.org/document/10305819/) | IEEE IC2E 2023 | Sensitivity analysis of circuit breaker + retry parameters under transient overload/noisy-neighbor scenarios; proposes an adaptive retry controller | Sensitivity analysis targets retry/open-state behavior and proposes a *new adaptive mechanism*; doesn't isolate window-type as the studied dimension, and the contribution is a controller, not a characterization |
| [Mendonça et al., "Model-Based Analysis of Microservice Resiliency Patterns"](https://consensus.app/papers/details/f8696f0b1a8b5c1ca3cf7029e495bba1/) | IEEE ICSA 2020 | PRISM/CTMC model-checking of Retry + Circuit Breaker parameter tuning | Analytical/model-based, not live-instrumented — explicitly the gap CascadeShield's live-mesh evidence fills |
| [Zdun et al., "Impact of API Rate Limit on Reliability of Microservices-Based Architectures"](https://consensus.app/papers/details/21a87b5aaece53a6b09396777d69fd26/) | IEEE SOSE 2022 | Analytical + empirically-validated model of Rate Limit pattern impact on reliability; explicitly notes "very few works empirically studied the impact of Rate Limit or similar API-related patterns" | Different resilience pattern (rate limiting, not circuit breaking); supports the general "empirical resilience-pattern research is sparse" framing but isn't itself a near-miss on window type |
| [Bansal et al., "Testing Resilience of Envoy Service Proxy with Microservices: A Fault-Oriented, Evidence-Driven Methodology"](https://consensus.app/papers/details/c46cc6deda975184b4ae88db11150a90/) | Innovative Journal of Applied Science, 2025 | Live, fault-injection-driven evaluation of circuit-breaking/retry/timeout policies, including circuit thresholds | **Different layer** — Envoy sidecar/service-mesh (infrastructure layer), not an application resilience library. Directly supports the "at the application library layer" scoping in the novelty claim: comparable rigor exists, but one layer down |
| [Pashko et al., "Improvements to the circuit breaker prediction model..."](https://consensus.app/papers/details/ef1ea031ac27513bb08eba51a778792b/) | Bulletin of Taras Shevchenko National University of Kyiv, 2026 | Proposes an adaptive sliding-window mechanism (dynamic context size) as part of a custom Circuit Breaker Prediction Model | Custom, non-standard windowing mechanism; evaluated via **simulated** experiments, not a live mesh; not a COUNT_BASED/TIME_BASED comparison of an existing library |
| [Falahah et al., "Circuit Breaker in Microservices: State of the Art and Future Prospects"](https://www.semanticscholar.org/paper/af14214165010f4a2a29c97555f1cb8f1b0c4815) | IOP Conf. Series, 2021 | Systematic mapping study of circuit-breaker research | Confirms the general gap ("research on circuit breaker is relatively less than... other microservices resiliency [topics]") — a citable grounding for the sparsity claim, not itself an empirical near-miss |
| [Sivakumar et al., "Self-Adaptive Circuit Breaker Open-State Interval for Enhancing Resiliency of Microservices"](https://consensus.app/papers/details/4a7980a986595d30901d7bd565c72a22/) | OCIT 2024 | Dynamic adjustment of the open-state interval parameter, empirically evaluated | Different parameter (open-state duration, not window type/aggregation) |
| [Yu et al., "A Systematic Literature Review on Fault Injection Testing of Microservice Systems"](https://consensus.app/papers/details/d03c2ecf3cc95901a659001bc6367cef/) | IEEE Trans. Services Computing, 2025 | First comprehensive SLR of fault-injection testing techniques for microservices | Surveys FIT methodology broadly; doesn't cover circuit-breaker window-type configuration specifically — useful as a general FIT-methodology citation, not a window-type near-miss |
| **Resilience4j GitHub Issue [#1731](https://github.com/resilience4j/resilience4j/issues/1731)** — "Proposition regarding the COUNT_BASED sliding window algorithm" | Maintainer/issue tracker | Practitioner-reported behavioral quirk: `COUNT_BASED` windows require the circular buffer to fill before `failureRateThreshold` is evaluated, causing early-life failure rates to read as 100% instead of the configured threshold | Confirms the count/time distinction has *known, discussed* operational consequences among Resilience4j's own maintainers/users — but as a bug report/proposal, not a controlled empirical study. Must be cited per the task's own instruction (a maintainer thread doesn't invalidate the work, but needs acknowledging) |
| **Resilience4j GitHub Discussion [#1815](https://github.com/resilience4j/resilience4j/discussions/1815)** — "Circuit breaker TIME_BASED use case scenario" | Maintainer/discussion tracker | Practitioner Q&A clarifying `TIME_BASED` window interaction with `minimumNumberOfCalls` and `failureRateThreshold` | Same category as #1731 — confirms practitioner-level awareness of window-type semantics, not a research characterization |
| **Resilience4j GitHub Issue [#1349](https://github.com/resilience4j/resilience4j/issues/1349)** — "Issue with minimum number of calls" | Maintainer/issue tracker | Practitioner-reported misconfiguration around `minimumNumberOfCalls` vs `slidingWindowSize` | Same category — a reported misconfiguration, not an empirical characterization of its consequences |

## Limitations of this search

- No academic search tool available in this session supports direct per-venue filtering
  (ICPE/ISSRE/Middleware/SoCC/ASE/ICSE SEIP proceedings specifically) — coverage of those
  venues was via query terms combined with venue names in web search, not a proceedings crawl.
  If a stronger claim than "systematic characterization" is ever needed, a manual pass through
  ICPE/ISSRE proceedings indices would strengthen this further.
- Consensus and Firecrawl's research search skew toward biomedical/general-science indexing;
  results were manually filtered for relevance to circuit breakers/microservices.
- This is a snapshot as of 2026-09-20. Re-run before the manuscript's Related Work section is
  finalized if significant time has passed.
