"""
analysis/machine_calibration.py  (D6 -- the user's own working label; backs decision
docs/paper/decision-log.md D-008.)

Cross-machine confounding, currently unnoticed: the plan is to run LINEAR on one box and
FAN_OUT on another. That's the shared-VM-style confound this project already refused once
for splitting one sweep across two hosts -- except now machine is perfectly aligned with
topology, so a LINEAR-vs-FAN_OUT contrast on any timing DV can't tell topology and machine
apart. `experiments/runner.py` now stamps every row with `machine_id`
(socket.gethostname(), auto-captured -- see MACHINE_ID) so this is at least measurable.

This script is the other half: given an identical ~10-run LINEAR calibration block
executed on each machine (reuse `--mode canary --topology linear --limit 10` -- no new CLI
mode needed), check whether the machine itself moves time_to_open / time_to_recover. Two
outcomes decide between decision D-008's options:

  - MACHINE_EFFECT_NEGLIGIBLE -> (c) succeeded. Cross-topology timing claims may proceed,
    citing this file's JSON.
  - MACHINE_EFFECT_DETECTED   -> fall back to (b): no cross-topology time_to_open /
    time_to_recover claim without a stated per-machine correction. order_leg /
    blast-radius-style ratios (D-007) are NOT gated by this -- they are assumed
    low machine-sensitivity per the decision.

No real calibration run exists yet (this environment has neither machine) -- run with
--self-test against a synthetic fixture, or point it at a real two-machine CSV once one
exists. It reports SKIPPED_NO_CALIBRATION_DATA rather than fabricate a verdict.

Usage:  python analysis/machine_calibration.py --self-test  (fixture only, no I/O)
        python analysis/machine_calibration.py <csv_path> [csv_path_2]
            one CSV with >=2 distinct machine_id values, or two CSVs (one per machine) --
            either way both machines' rows are pooled and grouped by machine_id.
Output: analysis/out/machine_calibration.json
"""

import sys

import pandas as pd

from common import bootstrap_ci_grouped, cliffs_delta, write_json

TIMING_DVS = ["time_to_open", "time_to_recover"]


def load_calibration(paths):
    """Load one or two CSVs, coerce timing columns numeric (blank = null, never 0.0 --
    same convention as every other DV in this repo), and require >=2 machine_id values."""
    frames = [pd.read_csv(p) for p in paths]
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    for col in TIMING_DVS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def machine_effect(df):
    """Per timing DV: bootstrap CI per machine (clustered by experiment_id, same
    convention as every other analysis script here) plus Cliff's delta between the two
    machines with the most rows. Returns SKIPPED_* status if the data can't support it."""
    if "machine_id" not in df.columns or df["machine_id"].nunique() < 2:
        return {"status": "SKIPPED_NO_CALIBRATION_DATA",
                "reason": "fewer than 2 distinct machine_id values in the data provided"}

    machines = df["machine_id"].value_counts().index[:2].tolist()
    by_dv = {}
    max_magnitude_rank = {"negligible": 0, "small": 1, "medium": 2, "large": 3}
    worst = "negligible"
    for dv in TIMING_DVS:
        if dv not in df.columns:
            by_dv[dv] = {"status": "SKIPPED_NO_COLUMN"}
            continue
        sub = df[df["machine_id"].isin(machines)]
        ci_by_machine = {
            m: bootstrap_ci_grouped(sub[sub["machine_id"] == m], dv, group_col="experiment_id")
            for m in machines
        }
        a = sub.loc[sub["machine_id"] == machines[0], dv]
        b = sub.loc[sub["machine_id"] == machines[1], dv]
        delta = cliffs_delta(a, b)
        by_dv[dv] = {"machines": machines, "ci_by_machine": ci_by_machine, "cliffs_delta": delta}
        mag = delta["magnitude"]
        if mag in max_magnitude_rank and max_magnitude_rank[mag] > max_magnitude_rank[worst]:
            worst = mag

    verdict = "MACHINE_EFFECT_NEGLIGIBLE" if worst in ("negligible", "small") \
        else "MACHINE_EFFECT_DETECTED"
    return {"status": "COMPUTED", "verdict": verdict, "worst_magnitude": worst, "by_dv": by_dv}


def main(paths):
    df = load_calibration(paths)
    result = machine_effect(df)
    payload = {"n_rows": int(len(df)), "sources": [str(p) for p in paths], **result}
    write_json("machine_calibration.json", payload)

    if result["status"] != "COMPUTED":
        print("[machine_calibration] {}: {}".format(result["status"], result.get("reason", "")))
        return payload

    print("machines compared: {}".format(result["by_dv"][TIMING_DVS[0]]["machines"]))
    for dv in TIMING_DVS:
        entry = result["by_dv"].get(dv, {})
        if entry.get("status") == "SKIPPED_NO_COLUMN":
            print("{}: column not present, skipped".format(dv))
            continue
        d = entry["cliffs_delta"]
        print("{}: Cliff's delta = {:.3f} ({}), n_a={}, n_b={}".format(
            dv, d["delta"], d["magnitude"], d["n_a"], d["n_b"]))
    print("\nVERDICT: {} (worst magnitude: {})".format(result["verdict"], result["worst_magnitude"]))
    return payload


# --------------------------------------------------------------------------- self-test

def self_test():
    """Two fixtures: one machine pair with a real timing offset (should detect it), one
    with matched distributions (should read negligible). No file I/O."""
    import numpy as np

    def make_df(machine_a_vals, machine_b_vals):
        rows = []
        for i, v in enumerate(machine_a_vals):
            rows.append({"experiment_id": "CFG-{}".format(i % 3), "machine_id": "host-a",
                         "time_to_open": v, "time_to_recover": v * 3})
        for i, v in enumerate(machine_b_vals):
            rows.append({"experiment_id": "CFG-{}".format(i % 3), "machine_id": "host-b",
                         "time_to_open": v, "time_to_recover": v * 3})
        return pd.DataFrame(rows)

    # 1. Matched distributions -> negligible.
    same = make_df([5.0, 5.2, 4.9, 5.1, 5.0], [5.1, 4.9, 5.0, 5.2, 4.8])
    r1 = machine_effect(same)
    assert r1["status"] == "COMPUTED"
    assert r1["verdict"] == "MACHINE_EFFECT_NEGLIGIBLE", r1["worst_magnitude"]

    # 2. host-b consistently ~3s slower -> detected.
    offset = make_df([5.0, 5.2, 4.9, 5.1, 5.0], [8.1, 7.9, 8.0, 8.2, 7.8])
    r2 = machine_effect(offset)
    assert r2["status"] == "COMPUTED"
    assert r2["verdict"] == "MACHINE_EFFECT_DETECTED", r2["worst_magnitude"]

    # 3. Only one machine present -> honest skip, no fabricated verdict.
    one_machine = pd.DataFrame({"experiment_id": ["CFG-0"], "machine_id": ["host-a"],
                                 "time_to_open": [5.0], "time_to_recover": [15.0]})
    r3 = machine_effect(one_machine)
    assert r3["status"] == "SKIPPED_NO_CALIBRATION_DATA"

    print("self-test: 3/3 checks OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        args = [a for a in sys.argv[1:] if a != "--self-test"]
        if not args:
            print("[machine_calibration] no calibration CSV provided -- reporting "
                  "SKIPPED_NO_CALIBRATION_DATA (expected: no real dual-machine run exists yet)")
            write_json("machine_calibration.json", {
                "status": "SKIPPED_NO_CALIBRATION_DATA",
                "reason": "no calibration data path given; run --self-test for the fixture "
                          "check, or pass one CSV (>=2 machine_id values) or two CSVs "
                          "(one per machine) once a real calibration block has been run.",
            })
        else:
            main(args)
