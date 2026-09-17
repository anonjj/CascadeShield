#!/usr/bin/env python3
"""Lead 3 -- audits real-world Resilience4j TIME_BASED circuit breaker configs found via
GitHub code search, and computes each one's inertness threshold.

Framing (depends on D18, decision-log.md): a COUNT_BASED sliding window structurally
self-repairs an unsafe minimumNumberOfCalls -- it evaluates once its ring buffer fills,
regardless of the configured minimum (live-verified). A TIME_BASED window does NOT --
minimumNumberOfCalls genuinely gates evaluation there, no ring-buffer bypass. So a
TIME_BASED breaker with minimumNumberOfCalls too high relative to its actual traffic and
window size can never evaluate at all -- permanently inert, and Resilience4j accepts this
silently at startup. For a TIME_BASED window of size T seconds and threshold n_min, the
breaker needs a sustained arrival rate of at least

    lambda* = n_min / T   (calls/sec)

to EVER accumulate enough calls in the trailing window to evaluate. This is arithmetic on
the file's own stated parameters -- defensible. "X% of deployed breakers are inert" would
require knowing real traffic and isn't claimed here; only the distribution of lambda* across
the sample is reported (see decision-log.md D18/D22/D23 for the mechanism this audit is
downstream of).

Auth: reuses the already-authenticated `gh` CLI token (`gh auth token`) -- no separate PAT
needed; code search only requires any authenticated token (confirmed live before building
this), and the existing `repo` scope is a superset of `public_repo`.

Config-inheritance model (see decision-log.md's D23 update for the full account): an
instance's explicit `base-config`/`baseConfig` is followed; an instance naming a
`configs:` entry identical to its own name resolves against that entry directly; an
instance with neither implicitly inherits `configs.default` (standard, version-stable
Resilience4j behavior). A *named config* that has no `base-config` of its own does NOT
get implicit `default` inheritance here, even though resilience4j-framework-common 2.2.0
(CascadeShield's own pinned version) actually does this via an internal fallback branch --
that specific behavior isn't guaranteed across Resilience4j versions, and scanned repos in
the wild pin unknown versions, so this tool uses the conservative, version-agnostic
reading: unset fields on a `base-config`-less named config fall straight to Resilience4j's
raw library defaults (slidingWindowSize=100, minimumNumberOfCalls=100). This may slightly
OVERSTATE lambda* (report configs as more inert-looking than they truly are, on older
Resilience4j versions using a CascadeShield-`measurement-plane`-style pattern) -- stated
here once, and again in every report this tool produces.

Usage:
    python3 audits/resilience4j_timebased_audit.py search --max-pages 1   # smoke test
    python3 audits/resilience4j_timebased_audit.py fetch --limit 20       # smoke test
    python3 audits/resilience4j_timebased_audit.py report
    python3 audits/resilience4j_timebased_audit.py --self-test
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".cache"
CONTENT_DIR = CACHE_DIR / "content"
HITS_PATH = CACHE_DIR / "hits.jsonl"
REPOS_PATH = CACHE_DIR / "repos.jsonl"
OUT_DIR = BASE_DIR / "out"

API_ROOT = "https://api.github.com"
SEARCH_PACE_S = 6.5  # 10 req/min budget, with margin
CONTENT_PACE_S = 0.1  # fast bucket (5000/hr) -- just avoid hammering

# Resilience4j's own CircuitBreakerConfig.java constants (verified from the pinned jar this
# session, resilience4j-circuitbreaker 2.2.0 -- these are library-wide, not version-drifted).
DEFAULT_SLIDING_WINDOW_SIZE = 100
DEFAULT_MINIMUM_NUMBER_OF_CALLS = 100
DEFAULT_SLIDING_WINDOW_TYPE = "COUNT_BASED"

QUERIES = [
    "slidingWindowType TIME_BASED extension:yml",
    "slidingWindowType TIME_BASED extension:yaml",
    "sliding-window-type TIME_BASED extension:yml",
    "sliding-window-type TIME_BASED extension:yaml",
]

TUTORIAL_MARKERS = ("demo", "tutorial", "example", "sample", "learning", "test")


# --------------------------------------------------------------------------
# GitHub API
# --------------------------------------------------------------------------

def get_token() -> str:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _sanitize_url(url: str) -> str:
    """GitHub's Contents API URLs embed the raw file path unencoded -- real repos have
    spaces, unicode, and other characters in paths that urllib refuses to send as-is
    ("URL can't contain control characters", or a UnicodeEncodeError building the request
    line). Re-quote just the path component; scheme/host/query are already well-formed."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/:@")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(_sanitize_url(url), headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cascadeshield-resilience4j-audit",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# Cache helpers (resumable)
# --------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def hit_key(hit: dict) -> str:
    return f"{hit['repo_full_name']}:{hit['path']}:{hit['sha']}"


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def search_code(query: str, token: str, max_pages: int) -> list[dict]:
    hits = []
    page = 1
    total_count = None
    while page <= max_pages:
        url = f"{API_ROOT}/search/code?q={urllib.parse.quote(query)}&per_page=100&page={page}"
        try:
            data = api_get(url, token)
        except urllib.error.HTTPError as e:
            print(f"  ERROR page {page}: {e}", file=sys.stderr)
            break
        total_count = data.get("total_count", 0)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            hits.append({
                "repo_full_name": item["repository"]["full_name"],
                "path": item["path"],
                "sha": item["sha"],
                "html_url": item["html_url"],
                "contents_url": item["url"],
                "query": query,
            })
        if page * 100 >= total_count:
            break
        if page * 100 >= 1000:
            print(f"  WARN: query {query!r} has total_count={total_count} > 1000 -- "
                  f"GitHub's search cap means only the first 1000 are retrievable, "
                  f"the rest are silently unreachable via this API. Reporting this, "
                  f"not hiding it.", file=sys.stderr)
            break
        page += 1
        if page <= max_pages:
            time.sleep(SEARCH_PACE_S)
    print(f"  query {query!r}: total_count={total_count}, fetched {len(hits)} hits")
    return hits


def cmd_search(args: argparse.Namespace) -> int:
    token = get_token()
    existing = {hit_key(h) for h in load_jsonl(HITS_PATH)}
    queries = QUERIES if args.query is None else [QUERIES[args.query - 1]]
    new_count = 0
    for i, q in enumerate(queries):
        print(f"[{i+1}/{len(queries)}] searching: {q}")
        hits = search_code(q, token, args.max_pages)
        for h in hits:
            if hit_key(h) not in existing:
                append_jsonl(HITS_PATH, h)
                existing.add(hit_key(h))
                new_count += 1
        if i < len(queries) - 1:
            time.sleep(SEARCH_PACE_S)
    print(f"\n{new_count} new hits cached to {HITS_PATH} "
          f"({len(existing)} total across all cached queries)")
    return 0


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def content_cache_path(sha: str) -> Path:
    return CONTENT_DIR / f"{sha}.yml"


def cmd_fetch(args: argparse.Namespace) -> int:
    token = get_token()
    hits = load_jsonl(HITS_PATH)
    if args.limit:
        hits = hits[: args.limit]

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    fetched, skipped = 0, 0
    for h in hits:
        dest = content_cache_path(h["sha"])
        if dest.exists():
            skipped += 1
            continue
        try:
            data = api_get(h["contents_url"], token)
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            dest.write_text(content)
            fetched += 1
        except Exception as e:
            print(f"  ERROR fetching {h['repo_full_name']}/{h['path']}: {e}", file=sys.stderr)
        time.sleep(CONTENT_PACE_S)
    print(f"content: {fetched} fetched, {skipped} already cached")

    repos_seen = {r["full_name"] for r in load_jsonl(REPOS_PATH)}
    unique_repos = sorted({h["repo_full_name"] for h in hits})
    repo_fetched = 0
    for full_name in unique_repos:
        if full_name in repos_seen:
            continue
        try:
            data = api_get(f"{API_ROOT}/repos/{full_name}", token)
            append_jsonl(REPOS_PATH, {
                "full_name": full_name,
                "stargazers_count": data.get("stargazers_count", 0),
                "pushed_at": data.get("pushed_at"),
            })
            repo_fetched += 1
        except Exception as e:
            print(f"  ERROR fetching repo {full_name}: {e}", file=sys.stderr)
        time.sleep(CONTENT_PACE_S)
    print(f"repo metadata: {repo_fetched} fetched, "
          f"{len(unique_repos) - repo_fetched} already cached/skipped")
    return 0


# --------------------------------------------------------------------------
# parse + resolve + lambda*
# --------------------------------------------------------------------------

def _field(d: dict, *names: str) -> Any:
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def resolve_named_config(name: str, configs: dict, visited: set) -> dict:
    """Resolves a `configs:` entry by following ONLY its own explicit base-config chain.
    No implicit `default` fallback here -- see module docstring for why."""
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
        # case documented in the module docstring).
        resolved = resolve_named_config("default", configs, set())
    else:
        resolved = {}
    resolved = dict(resolved)
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
    silent one)."""
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return []
    sections = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        node = doc
        for key in ("resilience4j", "circuitbreaker"):
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            sections.append(node)
    return sections


def analyze_file(text: str) -> list[dict]:
    """Returns one result dict per TIME_BASED breaker instance found, or [] if the file
    doesn't parse as a Resilience4j config at all (skipped, not an error)."""
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


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def is_tutorial_like(full_name: str, path: str) -> bool:
    s = f"{full_name}/{path}".lower()
    return any(m in s for m in TUTORIAL_MARKERS)


def stars_bucket(stars: int) -> str:
    if stars >= 100:
        return "100+"
    if stars >= 10:
        return "10-99"
    if stars >= 1:
        return "1-9"
    return "0"


def cmd_report(args: argparse.Namespace) -> int:
    hits = load_jsonl(HITS_PATH)
    repos = {r["full_name"]: r for r in load_jsonl(REPOS_PATH)}

    rows = []
    parsed, skipped_no_content, skipped_no_match, skipped_error = 0, 0, 0, 0
    for h in hits:
        path = content_cache_path(h["sha"])
        if not path.exists():
            skipped_no_content += 1
            continue
        text = path.read_text()
        try:
            results = analyze_file(text)
        except Exception as e:
            # Real-world YAML is messy across ~1000+ files; one file's unexpected shape
            # shouldn't take down the whole report. Counted and reported, not hidden.
            print(f"  ERROR analyzing {h['repo_full_name']}/{h['path']}: {e}", file=sys.stderr)
            skipped_error += 1
            continue
        if not results:
            skipped_no_match += 1
            continue
        parsed += 1
        repo_meta = repos.get(h["repo_full_name"], {})
        for r in results:
            rows.append({
                **r,
                "repo_full_name": h["repo_full_name"],
                "path": h["path"],
                "html_url": h["html_url"],
                "stars": repo_meta.get("stargazers_count", 0),
                "pushed_at": repo_meta.get("pushed_at"),
                "tutorial_like": is_tutorial_like(h["repo_full_name"], h["path"]),
                "stars_bucket": stars_bucket(repo_meta.get("stargazers_count", 0)),
            })

    print(f"files with cached content: {parsed + skipped_no_match + skipped_error}")
    print(f"files with no cached content (run `fetch` first): {skipped_no_content}")
    print(f"files with cached content but no TIME_BASED instance found: {skipped_no_match}")
    print(f"files that errored during analysis (not a crash, counted and skipped): {skipped_error}")
    print(f"TIME_BASED breaker instances found: {len(rows)}\n")

    if not rows:
        print("Nothing to report yet.")
        return 0

    n_tutorial = sum(1 for r in rows if r["tutorial_like"])
    print(f"*** {n_tutorial}/{len(rows)} ({100*n_tutorial/len(rows):.0f}%) look like "
          f"demo/tutorial/example/sample/learning/test repos or paths (substring heuristic, "
          f"not ground truth) -- reported first, before any other number. ***\n")

    print("Limitation, repeated from the module docstring: a base-config-less named config's "
          "unset fields resolve to Resilience4j's raw library defaults here, not implicit "
          "`default`-block inheritance -- CascadeShield's own pinned resilience4j 2.2.0 does "
          "the latter internally (decision-log.md D23), but that's version-specific and can't "
          "be assumed for these repos' unknown pinned versions. lambda* may be slightly "
          "OVERSTATED for configs using that pattern.\n")

    def report_stratum(label: str, subset: list[dict]) -> None:
        if not subset:
            print(f"{label}: n=0")
            return
        vals = sorted(r["lambda_star"] for r in subset)
        n = len(vals)
        median = statistics.median(vals)
        q1 = vals[n // 4]
        q3 = vals[(3 * n) // 4]
        print(f"{label}: n={n}  median={median:.3f}/s  "
              f"IQR=[{q1:.3f}, {q3:.3f}]  min={vals[0]:.4g}  max={vals[-1]:.4g}")

    print("lambda* (calls/sec needed to ever evaluate) by stratum:")
    report_stratum("  ALL", rows)
    report_stratum("  tutorial-like", [r for r in rows if r["tutorial_like"]])
    report_stratum("  non-tutorial-like", [r for r in rows if not r["tutorial_like"]])
    for bucket in ("0", "1-9", "10-99", "100+"):
        report_stratum(f"  stars={bucket}",
                        [r for r in rows if r["stars_bucket"] == bucket])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "report.json"
    out_path.write_text(json.dumps({
        "n_files_with_content": parsed + skipped_no_match,
        "n_time_based_instances": len(rows),
        "n_tutorial_like": n_tutorial,
        "rows": [{k: v for k, v in r.items() if k != "html_url"} | {"html_url": r["html_url"]}
                 for r in rows],
    }, indent=2))
    print(f"\nwrote {out_path} (aggregate + per-hit derived numbers only, "
          f"no raw third-party file content)")
    return 0


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test() -> bool:
    ok = True

    # Case 1: explicit base-config chain (config -> config -> instance)
    doc1 = """
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
    results = analyze_file(doc1)
    if len(results) != 1 or results[0]["sliding_window_size_s"] != 20 \
            or results[0]["minimum_number_of_calls"] != 5 \
            or abs(results[0]["lambda_star"] - 0.25) > 1e-9:
        print(f"FAIL: explicit base-config chain -- got {results}")
        ok = False

    # Case 2: instance with no base-config, implicit default inheritance
    doc2 = """
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
    results = analyze_file(doc2)
    if len(results) != 1 or results[0]["lambda_star"] != 5.0:
        print(f"FAIL: implicit instance->default -- got {results}")
        ok = False

    # Case 3: named config with NO base-config of its own -- slidingWindowSize/minimumNumberOfCalls
    # unset on it fall to raw library defaults (100/100), NOT to `default`'s values (the
    # conservative reading) -- even though it explicitly sets TIME_BASED itself (realistic:
    # the file was found via a text search for "TIME_BASED", so it's normally set directly).
    doc3 = """
resilience4j:
  circuitbreaker:
    configs:
      default:
        sliding-window-type: TIME_BASED
        sliding-window-size: 20
        minimum-number-of-calls: 5
      isolated:
        sliding-window-type: TIME_BASED
        failure-rate-threshold: 100
    instances:
      myBreaker:
        base-config: isolated
"""
    results = analyze_file(doc3)
    if len(results) != 1 or results[0]["sliding_window_size_s"] != 100 \
            or results[0]["minimum_number_of_calls"] != 100 \
            or abs(results[0]["lambda_star"] - 1.0) > 1e-9:
        print(f"FAIL: base-config-less named config should use raw defaults (100/100) -- "
              f"got {results}")
        ok = False

    # Case 4: COUNT_BASED instance should never appear in results
    doc4 = """
resilience4j:
  circuitbreaker:
    instances:
      countBreaker:
        sliding-window-type: COUNT_BASED
        sliding-window-size: 10
        minimum-number-of-calls: 200
"""
    results = analyze_file(doc4)
    if results:
        print(f"FAIL: COUNT_BASED instance leaked into results -- got {results}")
        ok = False

    # Case 5: malformed / non-Resilience4j YAML skipped cleanly, no crash
    doc5 = "apiVersion: v1\nkind: ConfigMap\ndata:\n  foo: bar\n"
    results = analyze_file(doc5)
    if results != []:
        print(f"FAIL: non-Resilience4j YAML should yield [] -- got {results}")
        ok = False
    doc6 = "not: valid: yaml: [[[\n"
    results = analyze_file(doc6)
    if results != []:
        print(f"FAIL: malformed YAML should yield [] not crash -- got {results}")
        ok = False

    # Case 6: instance name matches a configs: entry directly (createDirectConfig branch)
    doc7 = """
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
    results = analyze_file(doc7)
    if len(results) != 1 or results[0]["sliding_window_size_s"] != 30 \
            or results[0]["minimum_number_of_calls"] != 90:
        print(f"FAIL: instance-name-matches-configs-entry branch -- got {results}")
        ok = False

    # Helpers
    if stars_bucket(0) != "0" or stars_bucket(5) != "1-9" or stars_bucket(50) != "10-99" \
            or stars_bucket(500) != "100+":
        print("FAIL: stars_bucket")
        ok = False
    if not is_tutorial_like("someone/spring-demo", "src/main/resources/application.yml"):
        print("FAIL: is_tutorial_like should match 'demo' in repo name")
        ok = False
    if is_tutorial_like("someone/production-service", "src/main/resources/application.yml"):
        print("FAIL: is_tutorial_like false positive")
        ok = False

    print("self-test PASSED" if ok else "self-test FAILED")
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="command")

    sp_search = sub.add_parser("search", help="Query GitHub code search, cache hits (resumable)")
    sp_search.add_argument("--query", type=int, default=None,
                            help=f"Run only query N (1-{len(QUERIES)}), for smoke testing")
    sp_search.add_argument("--max-pages", type=int, default=10)

    sp_fetch = sub.add_parser("fetch", help="Fetch raw content + repo metadata (resumable)")
    sp_fetch.add_argument("--limit", type=int, default=None,
                           help="Only process the first N cached hits, for smoke testing")

    sub.add_parser("report", help="Parse cached content, compute lambda*, report")

    args = ap.parse_args()

    if args.self_test:
        return 0 if self_test() else 1

    if args.command == "search":
        return cmd_search(args)
    if args.command == "fetch":
        return cmd_fetch(args)
    if args.command == "report":
        return cmd_report(args)

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
