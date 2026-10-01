#!/usr/bin/env python3
"""Config-audit V2 reconciliation, STEP 1: the canonical parser, ported.

Parsing logic ported from `audits/resilience4j_timebased_audit.py` (branch
`audits/resilience4j-timebased-config-audit`, PR #63, retired/never merged). That script's
parser is correct where `analysis/lambda_star_ecdf.py` (merged, PR #73, powers paper Figure 2)
is not: it accepts both camelCase and kebab-case keys, resolves `base-config`/`baseConfig`
inheritance, handles multi-document YAML (`---`-separated Spring profile files) via
`yaml.safe_load_all`, and is restricted to the `resilience4j.circuitbreaker.instances.*` path
-- so a `configs:` template or an off-schema node never gets counted as a deployed instance.
`lambda_star_ecdf.py` has the better REPORTING (four groupings, estimand sensitivity, tutorial
split) but a weaker parser (camelCase only, no inheritance, single-document only, unrestricted
walk). This module ports only the parser; the retired branch's own report/fetch/search code,
and everything carrying repo identifiers (repo_full_name, path, sha, html_url, stargazers),
is deliberately left behind -- STEP 3's canonical run reuses the merged script's reporting
discipline instead, on top of this parser's output.

Config-inheritance model (unchanged from the retired script, see its own account in
decision-log.md's D23 update): an instance's explicit `base-config`/`baseConfig` is followed;
an instance naming a `configs:` entry identical to its own name resolves against that entry
directly; an instance with neither implicitly inherits `configs.default`. A *named config*
with no `base-config` of its own does NOT get implicit `default` inheritance here, even though
Resilience4j 2.2.0 itself does via an internal fallback branch not guaranteed across versions
-- the conservative, version-agnostic reading: unset fields on a base-config-less named config
fall straight to the library's raw defaults (slidingWindowSize=100, minimumNumberOfCalls=100).
This is a stated simplification, not a silent one, carried over unchanged from the source.

Resilience4j's own CircuitBreakerConfig.java constants (verified against the pinned jar,
resilience4j-circuitbreaker 2.2.0 -- library-wide, not version-drifted):
    DEFAULT_SLIDING_WINDOW_SIZE = 100
    DEFAULT_MINIMUM_NUMBER_OF_CALLS = 100
    DEFAULT_SLIDING_WINDOW_TYPE = COUNT_BASED

Usage:
    python3 analysis/config_audit_parser.py --self-test
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SLIDING_WINDOW_SIZE = 100
DEFAULT_MINIMUM_NUMBER_OF_CALLS = 100
DEFAULT_SLIDING_WINDOW_TYPE = "COUNT_BASED"


def _field(d: dict, *names: str) -> Any:
    """Reads the first present key from `names` -- the camelCase/kebab-case acceptor. Every
    caller passes both spellings; this is the single place that distinction is resolved."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def resolve_named_config(name: str, configs: dict, visited: set) -> dict:
    """Resolves a `configs:` entry by following ONLY its own explicit base-config chain.
    No implicit `default` fallback here -- a named config that doesn't itself point at
    `default` is not assumed to mean it."""
    if not isinstance(name, str) or name in visited or name not in configs:
        return {}
    entry = configs[name]
    if not isinstance(entry, dict):
        # Real-world YAML is messy: a `configs:` key can resolve to a non-mapping (an
        # env-var placeholder string, a YAML anchor gone sideways, etc). Not a real
        # profile -- treat as empty rather than crash the whole file's analysis.
        return {}
    visited = visited | {name}
    base_name = _field(entry, "base-config", "baseConfig")
    resolved = resolve_named_config(base_name, configs, visited) if base_name else {}
    resolved = dict(resolved)
    resolved.update({k: v for k, v in entry.items() if k not in ("base-config", "baseConfig")})
    return resolved


def resolve_instance(instance_name: str, instance: dict, configs: dict) -> dict:
    base_name = _field(instance, "base-config", "baseConfig")
    if base_name:
        resolved = resolve_named_config(base_name, configs, set())
    elif instance_name in configs:
        # Instance name matches a configs: entry directly (Resilience4j's createDirectConfig
        # branch) -- resolves against it without going through `default`.
        resolved = resolve_named_config(instance_name, configs, set())
    elif "default" in configs:
        # Instance with no base-config of its own implicitly inherits `default` --
        # standard, version-stable Resilience4j behavior (distinct from the named-config
        # case above).
        resolved = resolve_named_config("default", configs, set())
    else:
        resolved = {}
    resolved = dict(resolved)
    # The instance's OWN fields always win last -- this is what makes "overrides
    # base-config" work: an instance can inherit from a base-config and then restate any
    # one field itself, and that restated value is what's used.
    resolved.update({k: v for k, v in instance.items() if k not in ("base-config", "baseConfig")})
    return resolved


def apply_library_defaults(resolved: dict) -> dict:
    out = dict(resolved)
    out["_sliding_window_type"] = str(_field(resolved, "slidingWindowType", "sliding-window-type")
                                       or DEFAULT_SLIDING_WINDOW_TYPE).upper()
    out["_sliding_window_size"] = _field(resolved, "slidingWindowSize", "sliding-window-size")
    if out["_sliding_window_size"] is None:
        out["_sliding_window_size"] = DEFAULT_SLIDING_WINDOW_SIZE
    out["_minimum_number_of_calls"] = _field(resolved, "minimumNumberOfCalls",
                                              "minimum-number-of-calls")
    if out["_minimum_number_of_calls"] is None:
        out["_minimum_number_of_calls"] = DEFAULT_MINIMUM_NUMBER_OF_CALLS
    return out


def extract_cb_sections(text: str) -> list[dict]:
    """Multi-document YAML (Spring profile sections, `---`-separated) is common in real
    application.yml files. Each document is resolved independently -- this does NOT model
    Spring profile-merge semantics across documents (a known, stated simplification, not a
    silent one, carried over unchanged from the source script)."""
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return []
    sections = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        # Nested form: resilience4j: \n  circuitbreaker: ...
        node = doc
        for key in ("resilience4j", "circuitbreaker"):
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            sections.append(node)
        # Flat-dotted-key form: resilience4j.circuitbreaker: ... as ONE literal string key
        # at the document root. PyYAML never expands dots in keys, so these two forms are
        # genuinely different document shapes, not a stylistic variant the nested walk
        # already covers -- Spring Boot's relaxed binding accepts both. Found empirically:
        # 245 of 991 re-fetched config-audit files (98.4% of this specific gap) use this
        # form exclusively, verified by direct instance-name walk against the committed
        # 821-row comparison run (not a residual catch-all -- see decision-log.md / the V2
        # reconciliation notes once filed).
        flat = doc.get("resilience4j.circuitbreaker")
        if isinstance(flat, dict):
            sections.append(flat)
    return sections


def analyze_file(text: str) -> list[dict]:
    """Returns one result dict per TIME_BASED breaker INSTANCE found -- restricted to
    `resilience4j.circuitbreaker.instances.*`, resolved through its base-config chain. A
    `configs:` template is never itself a result, only an inheritance source. Returns []
    if the file doesn't parse as a Resilience4j config at all (skipped, not an error; the
    caller is responsible for flagging rather than silently dropping at the corpus level
    -- see STEP 3)."""
    results = []
    for section in extract_cb_sections(text):
        configs = section.get("configs") or {}
        instances = section.get("instances") or {}
        if not isinstance(configs, dict):
            configs = {}
        if not isinstance(instances, dict):
            continue
        for inst_name, inst in instances.items():
            if not isinstance(inst, dict):
                continue
            resolved = resolve_instance(inst_name, inst, configs)
            resolved = apply_library_defaults(resolved)
            if resolved["_sliding_window_type"] != "TIME_BASED":
                continue
            T = resolved["_sliding_window_size"]
            n_min = resolved["_minimum_number_of_calls"]
            try:
                T = float(T)
                n_min = float(n_min)
            except (TypeError, ValueError):
                continue
            if T <= 0:
                continue
            results.append({
                "instance": inst_name,
                "sliding_window_size_s": T,
                "minimum_number_of_calls": n_min,
                "lambda_star": n_min / T,
            })
    return results


# --------------------------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(name, cond, got=None):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}" + (f" -- got {got}" if not cond else ""))

    # 1. camelCase only
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        slidingWindowType: TIME_BASED
        slidingWindowSize: 10
        minimumNumberOfCalls: 50
    instances:
      plainBreaker: {}
"""
    r = analyze_file(doc)
    check("camelCase only: implicit default inheritance resolves",
          len(r) == 1 and r[0]["lambda_star"] == 5.0, r)

    # 2. kebab-case only
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        sliding-window-type: TIME_BASED
        sliding-window-size: 20
        minimum-number-of-calls: 5
      myProfile:
        base-config: default
        failure-rate-threshold: 70
    instances:
      myBreaker:
        base-config: myProfile
"""
    r = analyze_file(doc)
    check("kebab-case only: explicit base-config chain resolves",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 20
          and r[0]["minimum_number_of_calls"] == 5
          and abs(r[0]["lambda_star"] - 0.25) < 1e-9, r)

    # 3. mixed -- base-config in kebab-case, window fields in camelCase, on the SAME config
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        slidingWindowType: TIME_BASED
        slidingWindowSize: 40
        minimumNumberOfCalls: 8
    instances:
      myBreaker:
        base-config: default
"""
    r = analyze_file(doc)
    check("mixed casing: kebab-case base-config pointer + camelCase window fields both read",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 40
          and r[0]["minimum_number_of_calls"] == 8, r)

    # 4. inherits from base-config (distinct from case 2/3: the instance adds nothing of
    #    its own beyond the pointer)
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      slow:
        sliding-window-type: TIME_BASED
        sliding-window-size: 300
        minimum-number-of-calls: 15
    instances:
      inherited:
        base-config: slow
"""
    r = analyze_file(doc)
    check("inherits from base-config, no override",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 300
          and r[0]["minimum_number_of_calls"] == 15, r)

    # 5. overrides base-config -- instance inherits from a base-config AND restates one
    #    field itself; the restated value must win
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      slow:
        sliding-window-type: TIME_BASED
        sliding-window-size: 300
        minimum-number-of-calls: 15
    instances:
      overridden:
        base-config: slow
        minimum-number-of-calls: 3
"""
    r = analyze_file(doc)
    check("overrides base-config: instance's own minimum-number-of-calls (3) wins over "
          "the inherited 15, sliding-window-size (300) still inherited",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 300
          and r[0]["minimum_number_of_calls"] == 3, r)

    # 5b. flat-dotted-key form: `resilience4j.circuitbreaker:` as ONE literal string key
    #     at document root, not nested `resilience4j: \n circuitbreaker:`. PyYAML never
    #     expands dots in keys -- this is a genuinely different document shape, found in
    #     245/991 re-fetched config-audit files (V2 reconciliation).
    doc = """
resilience4j.circuitbreaker:
  configs:
    default:
      slidingWindowType: TIME_BASED
      slidingWindowSize: 12
      minimumNumberOfCalls: 6
  instances:
    flatKeyBreaker:
      base-config: default
"""
    r = analyze_file(doc)
    check("flat-dotted-key document root ('resilience4j.circuitbreaker' as one literal "
          "string key) is resolved, not just the nested form",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 12
          and r[0]["minimum_number_of_calls"] == 6, r)

    # 6. multi-document YAML, the live instance is in the THIRD document (after the
    #    second `---`) -- proves safe_load_all is actually walking every document, not
    #    just the first
    doc = """
spring:
  profiles: dev
---
spring:
  profiles: staging
---
resilience4j:
  circuitbreaker:
    configs:
      default:
        sliding-window-type: TIME_BASED
        sliding-window-size: 25
        minimum-number-of-calls: 4
    instances:
      prodBreaker:
        base-config: default
"""
    r = analyze_file(doc)
    check("multi-document YAML: instance after the second '---' is found",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 25
          and r[0]["minimum_number_of_calls"] == 4, r)

    # 7. a configs: template with no instance referencing it -- must produce ZERO rows.
    #    This is the exact defect that inflated analysis/lambda_star_ecdf.py's count: its
    #    unrestricted walk counts this kind of block as if it were a deployed instance.
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        sliding-window-type: TIME_BASED
        sliding-window-size: 20
        minimum-number-of-calls: 5
      unused:
        sliding-window-type: TIME_BASED
        sliding-window-size: 999
        minimum-number-of-calls: 999
"""
    r = analyze_file(doc)
    check("configs: template with no referencing instance yields zero rows (not a "
          "pseudo-instance)", r == [], r)

    # 8a. off-schema node: `backends:` instead of `instances:` (pre-2.x / different schema)
    doc = """
resilience4j:
  circuitbreaker:
    backends:
      legacyBreaker:
        slidingWindowType: TIME_BASED
        slidingWindowSize: 10
        minimumNumberOfCalls: 5
"""
    r = analyze_file(doc)
    check("off-schema node (backends.*) yields zero rows", r == [], r)

    # 8b. off-schema node: circuitBreakers as a LIST, not instances: as a mapping
    doc = """
resilience4j:
  circuitBreakers:
    - name: listedBreaker
      slidingWindowType: TIME_BASED
      slidingWindowSize: 10
      minimumNumberOfCalls: 5
"""
    r = analyze_file(doc)
    check("off-schema node (circuitBreakers.0, list-shaped) yields zero rows", r == [], r)

    # 8c. off-schema node: typo'd path ("intances" instead of "instances")
    doc = """
resilience4j:
  circuitbreaker:
    intances:
      typoBreaker:
        slidingWindowType: TIME_BASED
        slidingWindowSize: 10
        minimumNumberOfCalls: 5
"""
    r = analyze_file(doc)
    check("off-schema node (typo'd 'intances' path) yields zero rows", r == [], r)

    # 9. a TIME_BASED string entirely outside Resilience4j -- e.g. a different library or
    #    framework section that happens to reuse the same key name
    doc = """
spring:
  cloud:
    gateway:
      routes:
        - id: route1
          filters:
            - name: RequestRateLimiter
              args:
                slidingWindowType: TIME_BASED
                slidingWindowSize: 10
"""
    r = analyze_file(doc)
    check("TIME_BASED string outside Resilience4j entirely yields zero rows", r == [], r)

    # 10. COUNT_BASED instance must never appear in results
    doc = """
resilience4j:
  circuitbreaker:
    instances:
      countBreaker:
        sliding-window-type: COUNT_BASED
        sliding-window-size: 10
        minimum-number-of-calls: 200
"""
    r = analyze_file(doc)
    check("COUNT_BASED instance excluded", r == [], r)

    # 11. malformed / non-Resilience4j YAML skipped cleanly, no crash
    r = analyze_file("apiVersion: v1\nkind: ConfigMap\ndata:\n  foo: bar\n")
    check("non-Resilience4j YAML yields [] without crashing", r == [], r)
    r = analyze_file("not: valid: yaml: [[[\n")
    check("malformed YAML yields [] without crashing (not a raise)", r == [], r)

    # 12. instance name matches a configs: entry directly (createDirectConfig branch)
    doc = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        sliding-window-type: TIME_BASED
        sliding-window-size: 20
        minimum-number-of-calls: 5
      myBreaker:
        sliding-window-type: TIME_BASED
        sliding-window-size: 30
        minimum-number-of-calls: 90
    instances:
      myBreaker: {}
"""
    r = analyze_file(doc)
    check("instance name matching a configs: entry resolves directly against it "
          "(not via default)",
          len(r) == 1 and r[0]["sliding_window_size_s"] == 30
          and r[0]["minimum_number_of_calls"] == 90, r)

    print("\nself-test:", "PASS" if ok else "FAIL")
    return ok


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return 0 if self_test() else 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
