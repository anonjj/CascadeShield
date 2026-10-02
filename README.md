# CascadeShield

A construct-validity study of circuit-breaker sliding-window configuration in Resilience4j
2.2.0: a controlled, six-service Spring Boot mesh with Toxiproxy fault injection, instrumented
to test what the library's own `COUNT_BASED`/`TIME_BASED` window-type distinction actually
measures, and where that measurement breaks.

[![Java](https://img.shields.io/badge/Java-17-orange.svg)](https://adoptium.net/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.2.5-brightgreen.svg)](https://spring.io/projects/spring-boot)
[![Resilience4j](https://img.shields.io/badge/Resilience4j-2.2.0-blue.svg)](https://resilience4j.readme.io/)
[![Toxiproxy](https://img.shields.io/badge/Toxiproxy-2.9.0-red.svg)](https://github.com/Shopify/toxiproxy)
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Data: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](LICENSE-DATA)

## Three results

- **Occupancy asymmetry (D18).** The occupancy ratio ρ = λ·T/n_min cleanly predicts when a
  `TIME_BASED` breaker is structurally unable to open (every inert run at ρ ≤ 0.4996, every
  tripping run at ρ ≥ 0.9967, zero overlap across 162 runs) — but `COUNT_BASED` shows no such
  boundary at all (0/54 rows ever inert): its ring buffer self-repairs an unsafe
  `minimumNumberOfCalls` by filling regardless of the configured value, while `TIME_BASED`
  genuinely gates evaluation on it. One config surface, two opposite, library-hidden failure
  modes.
- **The recovery null (D28/D29).** A re-collection initially appeared to show window type
  affecting recovery speed — but that comparison held fault exposure *unequal* between arms
  by construction (the harness's load call was sized by the independent variable). A
  pre-registered, equal-exposure confirmatory run (R2, 72/72 clean) found no such effect:
  both arms bounce exactly once in every run, and recovery medians agree within the
  pre-registered 1-second threshold at every stratum. Window type does not reach recovery.
  The original reading is retracted as a harness construct-validity defect, not a library
  finding.
- **The config audit (D30).** 1,057 real-world `TIME_BASED` Resilience4j instances mined from
  public GitHub repositories, after reconciling two disagreeing parser runs (447 vs. 821) to
  zero remainder. The finding is the corpus's *composition*, not its median: those 1,057
  instances collapse to 66 distinct parameter pairs, and the single largest pair alone is 433
  instances across only ~3–5 structural template lineages — the data measures how far a
  configuration propagates, not how many engineers independently chose it.

Each result's full statement, the defect it survived, and what's and isn't reproducible from
this repo is in **[`docs/MANIFEST.md`](docs/MANIFEST.md)** — start there, not here, before
quoting any number.

## Reproducing a result

```
pip install -r requirements.txt
python3 analysis/occupancy_asymmetry_figure.py        # D18
python3 analysis/r2_equal_exposure_analysis.py         # D28/D29
python3 analysis/config_audit_v2_report.py             # D30 (needs the local, gitignored
                                                        #  audits/.cache/ -- see MANIFEST)
```

Every `analysis/*.py` script has a `--self-test` (or `self-test` subcommand) that validates
its own logic against synthetic fixtures before you trust it against real data.
`docs/MANIFEST.md` states, per result, whether committed data alone is enough, or whether a
re-fetch or a live mesh run is required.

## License

Code: [MIT](LICENSE). Data, documentation, and figures: [CC BY 4.0](LICENSE-DATA).

## Citing this work

See [`CITATION.cff`](CITATION.cff).

## Full documentation

The complete system architecture, topology diagrams, dataset schema, and experiment design
this brief summarizes is preserved unchanged at **[`docs/README-full.md`](docs/README-full.md)**.
`docs/paper/decision-log.md` is the append-only record of every measurement decision, in
order; `docs/paper/hypotheses.md` states each hypothesis as pre-registered.
