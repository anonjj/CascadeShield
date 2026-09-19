"""Dry-list what `experiments/runner.py` WOULD schedule -- without a mesh.

Why this exists: runner.py's main() calls `toxiproxy.setup_default_proxies()` and
`sys.exit(1)`s before it prints anything if Toxiproxy is unreachable, so there is no
way to ask the real runner "what would you run?" without bringing the mesh up. This
reproduces main()'s scheduling sequence exactly, in the same order, calling the same
runner.py functions -- it imports runner.py rather than reimplementing it, so it
cannot drift from the code it is predicting.

Importing runner.py is safe with Docker down: the module-scope `ToxiproxyClient()`
constructor does not connect.

Sequence mirrored from runner.py main() (runner.py:1669-1745):

  1. generate_combinations(mode)
  2. --only-ids filter, keyed on make_experiment_id(topology, fault, config)
     -- note: runner.py's FILTER call passes no toxicity/inject_point/mode, while
     the RESUME check below passes all three. Mirrored verbatim, including that.
  3. build_shuffled_run_list(configs, replicates, seed)
  4. resumability filter (is_done against the dataset), BEFORE --limit
  5. apply_run_limit(run_list, limit)

Read-only: touches no dataset, no container, no network.

    python analysis/phase4b_dry_list.py --only-ids docs/paper/phase4b_smoke_ids.txt \
        --replicates 1 --limit 1 --seed 20260920
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experiments"))

import runner  # noqa: E402  (path must be set first)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default="full")
    ap.add_argument("--fault", default="latency")
    ap.add_argument("--topology", default="linear")
    ap.add_argument("--toxicity", type=float, default=1.0)
    ap.add_argument("--inject-point", default=None)
    ap.add_argument("--only-ids", default=None)
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dataset", default=None,
                    help="simulate resumability against this existing CSV "
                         "(default: none -- treat the file as absent/empty)")
    a = ap.parse_args()

    # 1. grid
    configs = runner.generate_combinations(a.mode)
    print(f"generate_combinations({a.mode!r}) -> {len(configs)} configs")

    # 2. --only-ids filter, mirroring runner.py:1670-1684 exactly
    if a.only_ids:
        if os.path.isfile(a.only_ids):
            with open(a.only_ids) as f:
                wanted = {line.split("#", 1)[0].strip() for line in f}
        else:
            wanted = {tok.strip() for tok in a.only_ids.split(",")}
        wanted.discard("")
        before = len(configs)
        configs = [c for c in configs
                   if runner.make_experiment_id(a.topology, a.fault, c) in wanted]
        print(f"--only-ids filter: {before} configs -> {len(configs)} matching "
              f"'{a.topology}'/'{a.fault}' (of {len(wanted)} IDs listed).")

    total_runs = len(configs) * a.replicates
    print(f"Generated {len(configs)} configs x {a.replicates} replicates = "
          f"{total_runs} total runs.")

    # 4a. resumability set
    if a.dataset and os.path.exists(a.dataset):
        from resumable_runner import load_completed, is_done
        completed = load_completed(a.dataset, runner.DATASET_HEADERS)
        print(f"Resuming {a.dataset}: {len(completed)} cell(s) already recorded.")
    else:
        completed = set()
        from resumable_runner import is_done
        print("Resume source: none (treating the output file as absent/empty).")

    # 3. shuffle
    seed, run_list = runner.build_shuffled_run_list(configs, a.replicates, a.seed)
    print(f"Run order shuffled with seed {seed} ({len(run_list)} runs).")

    # 4b. resume filter, BEFORE --limit (runner.py:1727-1740)
    eff_inject = runner.resolve_inject_point(a.inject_point, a.mode)
    pending, skipped = [], 0
    for i, config, rep in run_list:
        eid = runner.make_experiment_id(a.topology, a.fault, config,
                                        a.toxicity, eff_inject, a.mode)
        if is_done(eid, rep, completed):
            skipped += 1
        else:
            pending.append((i, config, rep, eid))
    print(f"resume filter: {skipped} skipped, {len(pending)} pending.")

    # 5. --limit
    if a.limit is not None:
        trimmed = runner.apply_run_limit([(i, c, r) for i, c, r, _ in pending], a.limit)
        keep = {(i, r) for i, _, r in trimmed}
        pending = [p for p in pending if (p[0], p[2]) in keep]
        print(f"--limit {a.limit}: truncated to {len(pending)} new run(s).")

    print(f"\nWOULD SCHEDULE {len(pending)} run(s), in this order:")
    for n, (i, _c, rep, eid) in enumerate(pending, start=1):
        print(f"  {n:>3}. {eid}  replicate={rep}")
    print(f"\ndistinct experiment_ids: {len(sorted({p[3] for p in pending}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
