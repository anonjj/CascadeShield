"""T8 / paper Figure 2: the distribution of lambda* = minimumNumberOfCalls / slidingWindowSize
across real-world TIME_BASED Resilience4j configurations, mined from GitHub (the "D25 audit" --
not this repo's own decision-log D25, a separate external audit numbering; the raw scrape lives
in audits/.cache/, collected via GitHub code search for `slidingWindowType TIME_BASED`).

lambda* is the minimum average request rate (req/s) a TIME_BASED circuit breaker needs to see
before it can ever evaluate a failure rate at all: minimumNumberOfCalls calls have to land
inside a slidingWindowSize-second window. Below lambda*, the breaker is structurally inert --
this project's own H2b/D18 finding, now asked of real-world configurations rather than the
harness's own sweep.

Every TIME_BASED block found anywhere in the parsed YAML (under `resilience4j.circuitbreaker.
instances.*`, `.configs.*`, or any other nesting -- the walk is structural, not path-specific)
counts as one row. A single scraped file can contain more than one such block; the same file
content (by git blob sha) can be scraped from more than one repo (a fork or a copied tutorial)
and each occurrence counts separately -- that duplication is exactly what the config-level
(deduplicated) curve is for. minimumNumberOfCalls/slidingWindowSize are read as stated in the
YAML; Resilience4j's library defaults (100 and 100 respectively -- CircuitBreakerConfig's
DEFAULT_MINIMUM_NUMBER_OF_CALLS / DEFAULT_SLIDING_WINDOW_SIZE) are substituted where a field is
absent. No baseConfig/extends inheritance is resolved -- a block that doesn't state
slidingWindowType itself is not counted, even if it inherits TIME_BASED from a shared config.

The entire audits/.cache/ tree (raw YAML content AND the hits.jsonl/repos.jsonl scrape index)
is gitignored, local-only, never committed. Raw configuration content was not retained or
published because the corpus contained credentials -- GitHub's push protection caught real
leaked secrets on the first attempt to commit it (an API key, OAuth credentials) -- so only
structured parameter extractions were kept. That extraction (analysis/out/lambda_star_instances.
csv, the one artifact this pipeline commits) never carries repo_full_name, path, sha,
html_url, or stargazers_count: naming or linking a specific repository -- especially one whose
scraped file happened to contain a live secret -- is never done anywhere in this project's
committed output, the figure, or the paper. It carries only the extracted parameters
(minimumNumberOfCalls, slidingWindowSize, lambda*, the tutorial-heuristic flag) needed to
reproduce the aggregate statistics and the figure. Re-running extract() from scratch requires
the local (uncommitted, gitignored) cache; without it, main() falls back to the already-
extracted, anonymized CSV, so the figure and JSON stay reproducible from a fresh checkout.

Usage:  python analysis/lambda_star_ecdf.py
Output: analysis/out/lambda_star_ecdf.json, analysis/out/lambda_star_instances.csv,
        figures/fig9_lambda_star_ecdf.{png,pdf}  (T8 calls this "Figure 2"; renumbered to avoid
        colliding with this repo's own existing fig2_trip_rate_heatmap)
"""

import json
import re
import sys

import numpy as np
import pandas as pd

from common import BASE_DIR, FIG_DIR, OUT_DIR, write_json

AUDIT_DIR = BASE_DIR / "audits" / ".cache"
DEFAULT_MINIMUM_NUMBER_OF_CALLS = 100  # Resilience4j CircuitBreakerConfig library default
DEFAULT_SLIDING_WINDOW_SIZE = 100      # ditto

TUTORIAL_KEYWORDS = (
    "tutorial", "demo", "example", "sample", "learn", "study", "course",
    "training", "workshop", "bootcamp", "practice", "playground", "guide",
    "starter", "101", "test-project", "toy",
)


def _coerce_int(value):
    """YAML values for these two fields are almost always bare ints, but scraped real-world
    files occasionally quote them or leave stray whitespace/units. Returns None (never a
    fabricated number) when nothing digit-shaped is found."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        m = re.match(r"\s*(\d+)", value)
        return int(m.group(1)) if m else None
    return None


def _walk(node, path=()):
    """Yield (path, dict) for every mapping anywhere in the parsed YAML that states
    slidingWindowType: TIME_BASED as its own key -- inheritance is deliberately not resolved,
    see module docstring."""
    if isinstance(node, dict):
        if node.get("slidingWindowType") == "TIME_BASED":
            yield path, node
        for k, v in node.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, path + (i,))


def _is_tutorial(repo_full_name, path):
    hay = "{}/{}".format(repo_full_name, path).lower()
    return any(kw in hay for kw in TUTORIAL_KEYWORDS)


def extract():
    """Walk every hits.jsonl row, load its content file by sha, and pull out every genuine
    TIME_BASED block. Returns (instances_df, skip_counts)."""
    import yaml

    repos = {}
    with open(AUDIT_DIR / "repos.jsonl") as f:
        for line in f:
            r = json.loads(line)
            repos[r["full_name"]] = r

    skips = {"content_file_missing": 0, "read_error": 0, "yaml_parse_error": 0,
             "not_a_mapping": 0, "no_live_time_based_block": 0,
             "uncoercible_field": 0}
    rows = []

    with open(AUDIT_DIR / "hits.jsonl") as f:
        hit_rows = [json.loads(line) for line in f]

    for hit in hit_rows:
        content_path = AUDIT_DIR / "content" / "{}.yml".format(hit["sha"])
        if not content_path.exists():
            skips["content_file_missing"] += 1
            continue
        try:
            text = content_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skips["read_error"] += 1
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            skips["yaml_parse_error"] += 1
            continue
        if not isinstance(doc, (dict, list)):
            skips["not_a_mapping"] += 1
            continue

        blocks = list(_walk(doc))
        if not blocks:
            # A search hit whose match was in a comment, a string, or otherwise not a live
            # YAML key -- text search over-matches, the structural walk is the real filter.
            skips["no_live_time_based_block"] += 1
            continue

        for key_path, block in blocks:
            min_calls_raw = block.get("minimumNumberOfCalls")
            window_raw = block.get("slidingWindowSize")
            min_calls = (_coerce_int(min_calls_raw) if min_calls_raw is not None
                        else DEFAULT_MINIMUM_NUMBER_OF_CALLS)
            window = (_coerce_int(window_raw) if window_raw is not None
                     else DEFAULT_SLIDING_WINDOW_SIZE)
            if min_calls is None or window is None or window == 0:
                skips["uncoercible_field"] += 1
                continue
            repo_meta = repos.get(hit["repo_full_name"], {})
            rows.append({
                "repo_full_name": hit["repo_full_name"],
                "path": hit["path"],
                "sha": hit["sha"],
                "key_path": ".".join(str(p) for p in key_path),
                "stargazers_count": repo_meta.get("stargazers_count"),
                "minimum_number_of_calls": min_calls,
                "minimum_number_of_calls_is_default": min_calls_raw is None,
                "sliding_window_size": window,
                "sliding_window_size_is_default": window_raw is None,
                "lambda_star": min_calls / window,
                "likely_tutorial": _is_tutorial(hit["repo_full_name"], hit["path"]),
            })

    return pd.DataFrame(rows), skips


def _quartiles(values):
    v = np.asarray(sorted(values), dtype=float)
    return {
        "n": int(len(v)),
        "q1": float(np.percentile(v, 25)),
        "median": float(np.percentile(v, 50)),
        "q3": float(np.percentile(v, 75)),
        "min": float(v.min()),
        "max": float(v.max()),
        "share_below_1": float((v < 1.0).mean()),
        "share_below_10": float((v < 10.0).mean()),
    }


def _ecdf_xy(values):
    v = np.sort(np.asarray(values, dtype=float))
    y = np.arange(1, len(v) + 1) / len(v)
    return v, y


def make_figure(instance_vals, config_vals, top_case, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.4, 5.0))

    x_i, y_i = _ecdf_xy(instance_vals)
    ax.step(x_i, y_i, where="post", color="#1f3b73", lw=1.8, zorder=4,
            label="instance-level, primary (n={})".format(len(x_i)))

    x_c, y_c = _ecdf_xy(config_vals)
    ax.step(x_c, y_c, where="post", color="#1f3b73", lw=1.3, ls="--", alpha=0.55, zorder=3,
            label="config-level, deduplicated (n={})".format(len(x_c)))

    # Reference-rate lines: label sits INSIDE the axes (not above it), so it never competes
    # with the title for vertical space.
    for rate in (1.0, 10.0):
        ax.axvline(rate, color="#999999", ls=":", lw=1.0, zorder=0)
        ax.text(rate, 0.965, "{:.0f} req/s".format(rate), transform=ax.get_xaxis_transform(),
                color="#666666", fontsize=8, ha="center", va="top",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))

    # Quartile markers: Q1 and median coincide here (both 0.4) -- merge coincident labels
    # instead of stacking two annotations on the same point. The near-vertical step this
    # produces is real, not a rendering artefact (see module docstring / D25 audit): flag the
    # share of instances sitting at that exact value rather than leaving the jump unexplained.
    q = _quartiles(instance_vals)
    instance_arr = np.asarray(instance_vals)
    points = [("Q1", q["q1"]), ("median", q["median"]), ("Q3", q["q3"])]
    merged = []
    for label, val in points:
        if merged and np.isclose(merged[-1][1], val):
            merged[-1] = (merged[-1][0] + " = " + label, val)
        else:
            merged.append((label, val))
    y_offsets = [10, -14, 10]
    for (label, val), dy in zip(merged, y_offsets):
        frac = float((instance_arr <= val).mean())
        ax.plot([val], [frac], marker="o", ms=5, color="#b3261e", zorder=5)
        ax.annotate("{} = {:.3g}".format(label, val), (val, frac),
                    textcoords="offset points", xytext=(8, dy),
                    fontsize=8, color="#b3261e")

    # The near-vertical step a shared value produces is real, not a rendering artefact (see
    # module docstring) -- annotate the share separately, in the empty space the jump itself
    # opens up, rather than crowding it into the quartile labels above.
    for label, val in merged:
        if " = " not in label:
            continue
        share_at_val = float(np.isclose(instance_arr, val).mean())
        if share_at_val <= 0.1:
            continue
        lo = float((instance_arr < val).mean())
        hi = float((instance_arr <= val).mean())
        ax.annotate(r"{:.0%} of instances share $\lambda^{{*}}$={:.3g}".format(share_at_val, val),
                    (val, (lo + hi) / 2), textcoords="offset points", xytext=(-10, 0),
                    ha="right", va="center", fontsize=7.5, color="#7a1f17")

    if top_case is not None:
        # The point itself is the rightmost step of the primary curve (obvious without a
        # pointer); a long diagonal leader line across the plot is noisier than it's worth.
        # Marked instead, with the label as a caption box in the empty top-left corner.
        ax.plot([top_case["lambda_star"]], [1.0], marker="o", ms=6, mfc="none",
                mec="#333333", mew=1.2, zorder=5)
        ax.text(0.02, 0.88, r"top case, $\lambda^{{*}}$={:.0f}: {}".format(
                    top_case["lambda_star"], top_case["shape_label"]),
                transform=ax.transAxes, fontsize=7.5, color="#333333",
                ha="left", va="top", wrap=True,
                bbox=dict(boxstyle="round,pad=0.35", fc="#f5f5f5", ec="#cccccc", lw=0.6))

    ax.set_xscale("log")
    ax.set_xlabel(r"$\lambda^{*}$ = minimumNumberOfCalls / slidingWindowSize (req/s, log scale)")
    ax.set_ylabel("cumulative fraction of configurations")
    ax.set_ylim(0, 1.04)
    ax.set_title("Real-world TIME_BASED configurations: distribution of "
                 r"$\lambda^{*}$", fontsize=10, pad=10)
    ax.legend(frameon=False, fontsize=8, loc="lower right")

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    fig.savefig(str(path).replace(".png", ".pdf"))
    plt.close(fig)


# Columns that identify a specific repository or file. Never written to the committed CSV --
# naming or linking a repo, especially one whose scraped file happened to contain a live
# secret, is never done anywhere in this project's committed output, the figure, or the paper.
IDENTIFYING_COLUMNS = ["repo_full_name", "path", "sha", "stargazers_count"]


def main():
    instances_csv = OUT_DIR / "lambda_star_instances.csv"
    have_local_cache = (AUDIT_DIR / "content").is_dir() and (AUDIT_DIR / "hits.jsonl").exists()

    if have_local_cache:
        df, skips = extract()
        if df.empty:
            raise RuntimeError("lambda* extraction found zero live TIME_BASED blocks -- check "
                                "audits/.cache/content/ actually has files in it.")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        anonymized = df.drop(columns=[c for c in IDENTIFYING_COLUMNS if c in df.columns])
        anonymized.to_csv(instances_csv, index=False)
    elif instances_csv.exists():
        # The local audit cache (raw YAML + its repo/path index) is entirely gitignored, see
        # module docstring -- a fresh checkout re-derives the figure/JSON from the already-
        # extracted, already-anonymized CSV instead of failing outright.
        print("local audit cache not present -- reusing the already-extracted "
              "{}".format(instances_csv), file=sys.stderr)
        df = pd.read_csv(instances_csv)
        skips = {"note": "extraction not re-run -- loaded from committed CSV, see stderr"}
    else:
        raise RuntimeError(
            "Neither the local audit cache (gitignored, see module docstring) nor {} "
            "(committed extraction) is present. Nothing to build the figure from."
            .format(instances_csv))

    instance_vals = df["lambda_star"].tolist()
    config_df = df.drop_duplicates(subset=["minimum_number_of_calls", "sliding_window_size"])
    config_vals = config_df["lambda_star"].tolist()

    # The estimand choice is NOT cosmetic -- see estimand_sensitivity_warning below, computed
    # from these, for how much the median actually moves. Every plausible grouping is
    # reported, not just the two plotted curves, so a reader can see the sensitivity rather
    # than take one number on faith. File-level/repo-level require the (gitignored) identifying
    # columns, so they're only available on a run against the local cache -- the committed CSV
    # never carries them, and a fallback-mode rerun reports instance/config-level only.
    grouping_sensitivity = {
        "instance_level": _quartiles(instance_vals),
        "config_level_deduplicated_by_parameter_pair": _quartiles(config_vals),
    }
    if "sha" in df.columns:
        grouping_sensitivity["file_level_one_row_per_scraped_file"] = _quartiles(
            df.groupby("sha").first()["lambda_star"].tolist())
    if "repo_full_name" in df.columns:
        grouping_sensitivity["repo_level_one_row_per_repo"] = _quartiles(
            df.groupby("repo_full_name").first()["lambda_star"].tolist())

    top_row = df.loc[df["lambda_star"].idxmax()]
    top_case = {
        "lambda_star": float(top_row["lambda_star"]),
        "minimum_number_of_calls": int(top_row["minimum_number_of_calls"]),
        "sliding_window_size": int(top_row["sliding_window_size"]),
        "shape_label": "{:g} s window, minimumNumberOfCalls {}".format(
            top_row["sliding_window_size"],
            "unset -> library default of {}".format(DEFAULT_MINIMUM_NUMBER_OF_CALLS)
            if top_row["minimum_number_of_calls_is_default"]
            else "= {}".format(top_row["minimum_number_of_calls"]),
        ),
    }

    fig_path = FIG_DIR / "fig9_lambda_star_ecdf.png"
    make_figure(instance_vals, config_vals, top_case, fig_path)

    tutorial_df = df[df["likely_tutorial"]]
    non_tutorial_df = df[~df["likely_tutorial"]]

    if have_local_cache:
        with open(AUDIT_DIR / "repos.jsonl") as f:
            n_repos = sum(1 for _ in f)
        with open(AUDIT_DIR / "hits.jsonl") as f:
            n_hits = sum(1 for _ in f)
        n_content_files = len(list((AUDIT_DIR / "content").glob("*.yml")))
    else:
        # Fallback mode: these are aggregate counts, not identifying data, but they still
        # require the (gitignored) local cache to recount. Reuse whatever the last real run
        # against the local cache already committed, rather than fabricate or omit them.
        n_repos = n_hits = n_content_files = None
        prior_json_path = OUT_DIR / "lambda_star_ecdf.json"
        if prior_json_path.exists():
            with open(prior_json_path) as f:
                prior = json.load(f).get("corpus", {})
            n_repos = prior.get("n_repos_in_repos_jsonl")
            n_hits = prior.get("n_hits_jsonl_rows")
            n_content_files = prior.get("n_unique_content_files_cached")

    payload = {
        "primary_grouping": "instance_level",
        "primary_grouping_rationale": ("The claim is about hazard reachability -- 'X% of "
                     "configs can't open below Y req/s' -- so a configuration deployed in N "
                     "places is N real exposures, not one. Instance-level is therefore the "
                     "primary curve; config-level dedup is reported alongside as the "
                     "robustness check, not averaged into or replacing it."),
        "estimand": ("Distribution over configuration INSTANCES: every scraped occurrence of "
                     "a live slidingWindowType: TIME_BASED block, one row per occurrence -- "
                     "including repos that copy the same file or the same repo declaring "
                     "several near-identical instances. NOT distinct configurations (see "
                     "config_level_deduplicated_by_parameter_pair for that alternative). "
                     "lambda* = minimumNumberOfCalls / slidingWindowSize on stated parameters, "
                     "with Resilience4j library defaults (minimumNumberOfCalls=100, "
                     "slidingWindowSize=100) applied where a field is absent. "
                     "baseConfig/extends inheritance is not resolved -- a block must state "
                     "slidingWindowType: TIME_BASED itself to be counted."),
        "estimand_sensitivity_warning": (
            "The grouping choice is not cosmetic: median ranges {lo_med:.3g}-{hi_med:.3g} "
            "across the {n} groupings computed here (instance-level: {inst_med:.3g}, "
            "config-level dedup: {cfg_med:.3g}). State the grouping explicitly wherever this "
            "number is quoted in the paper.".format(
                lo_med=min(g["median"] for g in grouping_sensitivity.values()),
                hi_med=max(g["median"] for g in grouping_sensitivity.values()),
                n=len(grouping_sensitivity),
                inst_med=grouping_sensitivity["instance_level"]["median"],
                cfg_med=grouping_sensitivity["config_level_deduplicated_by_parameter_pair"]["median"],
            )
        ),
        "corpus": {
            "description": ("Described by what this scrape actually contains, not by any "
                    "earlier/unverified count. GitHub code search for `slidingWindowType "
                    "TIME_BASED` and `sliding-window-type TIME_BASED`, extension:yaml|yml. "
                    "Raw configuration content was not retained or published because the "
                    "corpus contained credentials; only structured parameter extractions "
                    "were kept -- no repository is named or linked anywhere in this "
                    "project's committed output, the figure, or the paper."),
            "n_repos_in_repos_jsonl": n_repos,
            "n_hits_jsonl_rows": n_hits,
            "n_unique_content_files_cached": n_content_files,
            "n_files_with_at_least_one_live_time_based_block": (
                int(df["sha"].nunique()) if "sha" in df.columns else None),
            "n_instance_level_rows": int(len(df)),
            "n_distinct_config_level_rows": int(len(config_df)),
        },
        "extraction_skips": skips,
        "grouping_sensitivity": grouping_sensitivity,
        "instance_level": _quartiles(instance_vals),
        "config_level_deduplicated": _quartiles(config_vals),
        "top_case": top_case,
        "tutorial_stratification_variant": {
            "note": "Heuristic classification only (repo/path keyword match on "
                    "tutorial/demo/example/etc.) -- not the main figure, kept available for a "
                    "reviewer question per the task brief.",
            "tutorial": _quartiles(tutorial_df["lambda_star"].tolist()) if len(tutorial_df) else None,
            "non_tutorial": _quartiles(non_tutorial_df["lambda_star"].tolist()) if len(non_tutorial_df) else None,
        },
        "figure": str(fig_path.relative_to(fig_path.parents[1])),
    }
    write_json("lambda_star_ecdf.json", payload)

    print("grouping sensitivity (median is not stable across these -- see JSON warning):")
    for name, g in grouping_sensitivity.items():
        print("  {:42s} n={:<5d} Q1={:<6.3g} median={:<6.3g} Q3={:<6.3g} max={:.3g}".format(
            name, g["n"], g["q1"], g["median"], g["q3"], g["max"]))
    print("\nprimary (instance-level): %<1={:.1%}  %<10={:.1%}".format(
        payload["instance_level"]["share_below_1"], payload["instance_level"]["share_below_10"]))
    print("top case: lambda*={:.3g} ({})".format(top_case["lambda_star"], top_case["shape_label"]))
    print("extraction skips: {}".format(skips))
    return payload


if __name__ == "__main__":
    main()
