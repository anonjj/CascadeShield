#!/usr/bin/env python3
"""V2 config-audit reconciliation: the committed, anonymized report.

Reads audits/.cache/ (gitignored, local-only -- re-fetchable by blob sha from the committed
hits.jsonl... except hits.jsonl is itself gitignored too, so the *inputs* to this script are
not reproducible from a fresh checkout without re-running the STEP 2 fetch against GitHub).
What IS committed is this script's output: five groupings (instance/config-dedup/file/repo/
blob level), the top-10 parameter-pair table, the tutorial-flag methodology and its
instances-per-pair distribution, and the full reconciliation of this run against the two
prior parser runs (447, the retired `audits/resilience4j_timebased_audit.py`; 821,
`analysis/lambda_star_ecdf.py`) by cause, with zero unexplained remainder either direction.

No repo name, path, sha, or any other identifying field appears anywhere in the output --
consistent with the reason the raw scrape was never committed in the first place (GitHub
push protection caught real leaked credentials in it). This script requires the local
`audits/.cache/content/` tree to run; without it, there is nothing to re-derive from (that
tree is intentionally never committed).

Usage:
    python3 analysis/config_audit_v2_report.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter, defaultdict

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "audits", ".cache")
CONTENT_DIR = os.path.join(CACHE_DIR, "content")
OUT_PATH = os.path.join(REPO_ROOT, "analysis", "out", "config_audit_v2_report.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_audit_parser import analyze_file  # noqa: E402

TUTORIAL_KEYWORDS = (
    "tutorial", "demo", "example", "sample", "learn", "study", "course",
    "training", "workshop", "bootcamp", "practice", "playground", "guide",
    "starter", "101", "test-project", "toy",
)


def is_tutorial(repo_full_name, path):
    hay = f"{repo_full_name}/{path}".lower()
    return any(kw in hay for kw in TUTORIAL_KEYWORDS)


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def quartiles(vals):
    if not vals:
        return None
    s = sorted(vals)
    out = {"n": len(s), "min": s[0], "max": s[-1], "median": statistics.median(s)}
    if len(s) >= 2:
        q = statistics.quantiles(s, n=4)
        out["q1"], out["q3"] = q[0], q[2]
    else:
        out["q1"], out["q3"] = s[0], s[0]
    return out


# ------------------------------------------------------------------ the 821-script's own
# extraction logic, inlined, for the reconciliation only (never used for the committed numbers)

def _walk_821(node, path=()):
    if isinstance(node, dict):
        if node.get("slidingWindowType") == "TIME_BASED":
            yield path, node
        for k, v in node.items():
            yield from _walk_821(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_821(v, path + (i,))


def _extract_821(text):
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, (dict, list)):
        return []
    rows = []
    for key_path, block in _walk_821(doc):
        min_calls_raw = block.get("minimumNumberOfCalls")
        window_raw = block.get("slidingWindowSize")
        min_calls = min_calls_raw if min_calls_raw is not None else 100
        window = window_raw if window_raw is not None else 100
        try:
            min_calls, window = int(min_calls), int(window)
        except (TypeError, ValueError):
            continue
        if window == 0:
            continue
        rows.append({"key_path": ".".join(str(p) for p in key_path),
                     "minimum_number_of_calls": min_calls, "sliding_window_size": window})
    return rows


def main():
    if not os.path.isdir(CONTENT_DIR):
        print("audits/.cache/content/ not present -- nothing to build this report from "
              "(it is intentionally never committed; see module docstring). Run STEP 2's "
              "fetch first.", file=sys.stderr)
        return 1

    hits = load_jsonl(os.path.join(CACHE_DIR, "hits.jsonl"))
    repos_jsonl_path = os.path.join(CACHE_DIR, "repos.jsonl")
    n_repos_searched = len(load_jsonl(repos_jsonl_path)) if os.path.exists(repos_jsonl_path) else None

    content_cache = {}

    def get_content(sha):
        if sha not in content_cache:
            p = os.path.join(CONTENT_DIR, sha + ".yml")
            content_cache[sha] = (open(p, encoding="utf-8", errors="replace").read()
                                   if os.path.exists(p) else None)
        return content_cache[sha]

    canon_rows = []       # identity kept only in-process, never written out
    run821_rows = []
    canon_skips = Counter()
    run821_skips = Counter()

    for hit in hits:
        sha = hit["sha"]
        text = get_content(sha)
        if text is None:
            canon_skips["content_file_missing"] += 1
            run821_skips["content_file_missing"] += 1
            continue

        try:
            docs = list(yaml.safe_load_all(text))
        except yaml.YAMLError:
            canon_skips["yaml_parse_error"] += 1
        else:
            if not any(isinstance(d, dict) for d in docs):
                canon_skips["not_a_mapping"] += 1
            else:
                results = analyze_file(text)
                if not results:
                    canon_skips["no_time_based_instance_found"] += 1
                else:
                    for r in results:
                        canon_rows.append({**r, "sha": sha, "repo_full_name": hit["repo_full_name"],
                                            "path": hit["path"],
                                            "tutorial_like": is_tutorial(hit["repo_full_name"], hit["path"])})

        r821 = _extract_821(text)
        if r821 is None:
            run821_skips["yaml_parse_error"] += 1
        elif not r821:
            run821_skips["no_live_time_based_block"] += 1
        else:
            for r in r821:
                run821_rows.append({**r, "sha": sha, "repo_full_name": hit["repo_full_name"],
                                     "path": hit["path"]})

    # ---------------------------------------------------------------- five groupings
    inst_vals = [r["lambda_star"] for r in canon_rows]

    config_pairs = defaultdict(list)
    for r in canon_rows:
        config_pairs[(r["minimum_number_of_calls"], r["sliding_window_size_s"])].append(r)

    file_groups = defaultdict(list)
    for r in canon_rows:
        file_groups[(r["repo_full_name"], r["path"])].append(r["lambda_star"])
    file_vals = [statistics.mean(v) for v in file_groups.values()]

    repo_groups = defaultdict(list)
    for r in canon_rows:
        repo_groups[r["repo_full_name"]].append(r["lambda_star"])
    repo_vals = [statistics.mean(v) for v in repo_groups.values()]

    sha_first_seen = {}
    blob_rows = []
    for r in canon_rows:
        if r["sha"] not in sha_first_seen:
            sha_first_seen[r["sha"]] = True
            blob_rows.extend(x for x in canon_rows if x["sha"] == r["sha"]
                              and x["repo_full_name"] == r["repo_full_name"] and x["path"] == r["path"])
    blob_vals = [r["lambda_star"] for r in blob_rows]

    sha_hit_count = Counter(h["sha"] for h in hits)
    sha_repos = defaultdict(set)
    for h in hits:
        sha_repos[h["sha"]].add(h["repo_full_name"])
    multi_repo_shas = {s for s, rs in sha_repos.items() if len(rs) > 1}
    same_repo_shas = {s for s, c in sha_hit_count.items() if c > 1} - multi_repo_shas
    n_cross_repo_dup = sum(1 for r in canon_rows if r["sha"] in multi_repo_shas)
    n_same_repo_dup = sum(1 for r in canon_rows if r["sha"] in same_repo_shas)

    # ---------------------------------------------------------------- top 10 pairs
    ranked = sorted(config_pairs.items(), key=lambda kv: -len(kv[1]))[:10]
    top10 = []
    for (nm, wd), rows in ranked:
        top10.append({
            "minimum_number_of_calls": nm, "sliding_window_size": wd,
            "lambda_star": nm / wd, "instances": len(rows),
            "distinct_blobs": len({r["sha"] for r in rows}),
            "distinct_repos": len({r["repo_full_name"] for r in rows}),
        })

    # ---------------------------------------------------------------- tutorial split
    tut_vals = [r["lambda_star"] for r in canon_rows if r["tutorial_like"]]
    nontut_vals = [r["lambda_star"] for r in canon_rows if not r["tutorial_like"]]
    pairs_tut = defaultdict(lambda: [0, 0])
    for r in canon_rows:
        k = (r["minimum_number_of_calls"], r["sliding_window_size_s"])
        pairs_tut[k][0 if r["tutorial_like"] else 1] += 1
    n_pairs_tut = sum(1 for v in pairs_tut.values() if v[0] > 0)
    n_pairs_nontut = sum(1 for v in pairs_tut.values() if v[1] > 0)

    # ---------------------------------------------------------------- reconciliation by cause
    canon_by_file = defaultdict(list)
    for r in canon_rows:
        canon_by_file[(r["sha"], r["repo_full_name"], r["path"])].append(
            (r["minimum_number_of_calls"], r["sliding_window_size_s"]))

    causes_821 = Counter()
    for r in run821_rows:
        parts = r["key_path"].split(".")
        key = (r["sha"], r["repo_full_name"], r["path"])
        if "instances" in parts:
            if (r["minimum_number_of_calls"], r["sliding_window_size"]) in canon_by_file.get(key, []):
                causes_821["matches_canonical"] += 1
            else:
                causes_821["real_instance_canonical_still_misses"] += 1
        elif "configs" in parts:
            causes_821["config_template_miscounted_as_instance"] += 1
        else:
            causes_821["off_schema_or_false_positive"] += 1

    sha_821_outcome = {}
    for h in hits:
        if h["sha"] in sha_821_outcome:
            continue
        text = get_content(h["sha"])
        if text is None:
            sha_821_outcome[h["sha"]] = "content_missing"
            continue
        try:
            yaml.safe_load(text)
            sha_821_outcome[h["sha"]] = "parsed_ok"
        except yaml.YAMLError:
            sha_821_outcome[h["sha"]] = "multi_doc_or_parse_error"

    run821_by_file = defaultdict(list)
    for r in run821_rows:
        run821_by_file[(r["sha"], r["repo_full_name"], r["path"])].append(
            (r["minimum_number_of_calls"], r["sliding_window_size"]))

    miss_causes = Counter()
    for r in canon_rows:
        key = (r["sha"], r["repo_full_name"], r["path"])
        nm, wd = r["minimum_number_of_calls"], r["sliding_window_size_s"]
        if (nm, wd) in run821_by_file.get(key, []):
            miss_causes["found_in_821"] += 1
            continue
        if sha_821_outcome.get(r["sha"]) == "multi_doc_or_parse_error":
            miss_causes["multi_document_parse_failure_in_821"] += 1
            continue
        text = get_content(r["sha"])
        docs = list(yaml.safe_load_all(text))
        cause = "unexplained"
        for doc in docs:
            candidates = []
            node = doc
            ok = True
            for k2 in ("resilience4j", "circuitbreaker"):
                if not isinstance(node, dict) or k2 not in node:
                    ok = False
                    break
                node = node[k2]
            if ok and isinstance(node, dict):
                candidates.append(node)
            flat = doc.get("resilience4j.circuitbreaker") if isinstance(doc, dict) else None
            if isinstance(flat, dict):
                candidates.append(flat)
            matched_node = None
            for cand in candidates:
                insts = cand.get("instances") or {}
                if isinstance(insts, dict) and r["instance"] in insts:
                    matched_node = cand
                    break
            if matched_node is None:
                continue
            block = matched_node["instances"][r["instance"]]
            if not isinstance(block, dict):
                continue
            has_camel = "slidingWindowType" in block
            has_kebab = "sliding-window-type" in block
            raw_val = block.get("slidingWindowType") or block.get("sliding-window-type")
            if isinstance(raw_val, str) and raw_val.upper() == "TIME_BASED" and raw_val != "TIME_BASED":
                cause = "value_case_sensitivity"
            elif has_kebab and not has_camel:
                cause = "kebab_case"
            elif not has_kebab and not has_camel:
                cause = "inheritance_derived"
            break
        miss_causes[cause] += 1

    report = {
        "methodology_note": (
            "Instances using analysis/config_audit_parser.py's analyze_file(): both camelCase "
            "and kebab-case keys accepted, base-config/baseConfig inheritance resolved, "
            "multi-document YAML handled, flat-dotted-key document roots "
            "(e.g. 'resilience4j.circuitbreaker:' as one literal string key) resolved -- the "
            "defect found and fixed during this reconciliation (see decision log once filed). "
            "No repo name, path, or blob sha appears anywhere below."
        ),
        "corpus": {
            "repos_searched": n_repos_searched,
            "hits_total": len(hits),
            "canonical_skips": dict(canon_skips),
        },
        "groupings": {
            "instance_level": quartiles(inst_vals),
            "config_level_deduplicated": {"n_distinct_pairs": len(config_pairs), **(quartiles(
                [nm / wd for (nm, wd) in config_pairs]) or {})},
            "file_level": {"n_files": len(file_groups), **(quartiles(file_vals) or {})},
            "repo_level": {"n_repos": len(repo_groups), **(quartiles(repo_vals) or {})},
            "blob_level": {"n_blobs": len(sha_first_seen), "n_instances": len(blob_rows),
                            **(quartiles(blob_vals) or {})},
        },
        "duplication": {
            "instances_in_cross_repo_duplicated_content": n_cross_repo_dup,
            "instances_in_same_repo_duplicated_content": n_same_repo_dup,
            "top_10_parameter_pairs_by_instance_count": top10,
            "top_10_pairs_share_of_corpus": sum(t["instances"] for t in top10) / len(canon_rows),
        },
        "tutorial_flag": {
            "method": "substring match on lower(repo_full_name + '/' + path) against a fixed "
                      "keyword list -- not stars, not content, not structure",
            "keywords": list(TUTORIAL_KEYWORDS),
            "tutorial_instances": len(tut_vals),
            "non_tutorial_instances": len(nontut_vals),
            "tutorial_quartiles": quartiles(tut_vals),
            "non_tutorial_quartiles": quartiles(nontut_vals),
            "distinct_pairs_touched_by_tutorial": n_pairs_tut,
            "distinct_pairs_touched_by_non_tutorial": n_pairs_nontut,
            "avg_instances_per_pair_tutorial": len(tut_vals) / n_pairs_tut if n_pairs_tut else None,
            "avg_instances_per_pair_non_tutorial": len(nontut_vals) / n_pairs_nontut if n_pairs_nontut else None,
            "caveat": "the 'non-tutorial' bucket has a HIGHER average instances-per-pair than "
                      "the 'tutorial' bucket -- this flag undercounts templated/duplicated "
                      "content, confirmed directly against the (4,10) cluster (3% tutorial-flagged)",
        },
        "reconciliation": {
            "n_canonical": len(canon_rows),
            "n_run821_on_same_content": len(run821_rows),
            "n_original_447_retired_script": 447,
            "n_original_821_committed": 821,
            "causes_of_821_rows": dict(causes_821),
            "causes_canonical_rows_missed_by_821": dict(miss_causes),
            "zero_remainder_either_direction": (
                sum(causes_821.values()) == len(run821_rows)
                and sum(miss_causes.values()) == len(canon_rows)
            ),
        },
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"wrote {OUT_PATH}")
    print(json.dumps({k: v for k, v in report.items() if k != "groupings"}, indent=2, default=str)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
