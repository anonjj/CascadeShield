#!/usr/bin/env python3
"""train_latency_models.py -- CascadeShield detection/recovery latency models."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.tree import DecisionTreeRegressor, export_text

BASE = Path(__file__).resolve().parent
CANDIDATES = [
    "data/master_dataset.csv",
    "data/master_dataset_v2_latency_5svc.csv",
]
FEATURES = ["window_type_is_time", "threshold", "window_size", "wait_duration"]
RECOVER_OUTLIER_S = 1000.0
OUTDIR = BASE / "ml" / "models"


def find_dataset(argv):
    if len(argv) > 1:
        p = Path(argv[1])
        if not p.exists():
            sys.exit(f"Dataset not found: {p}")
        return p
    for c in CANDIDATES:
        p = BASE / c
        if p.exists():
            return p
    sys.exit(f"No dataset found. Tried: {CANDIDATES}. Pass a path explicitly.")


def load(path):
    df = pd.read_csv(path)
    df["window_type_is_time"] = (df["window_type"] == "TIME_BASED").astype(int)
    for c in ["threshold", "window_size", "wait_duration"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"Dataset: {path}  ({len(df)} rows)")
    for c in ["topology", "fault_type"]:
        vals = df[c].unique()
        if len(vals) == 1:
            print(f"  NOTE: {c} is constant ({vals[0]}) -- excluded from features (dead one-hot)")
    return df


def prepare(df, target):
    d = df[df[target].notna()].copy()
    dropped = 0
    if target == "time_to_recover":
        big = d[d[target] > RECOVER_OUTLIER_S]
        for _, r in big.iterrows():
            print(f"  EXCLUDED outlier: {r['experiment_id']} rep {r['replicate']} "
                  f"{target}={r[target]:.1f}s (harness hang)")
        dropped = len(big)
        d = d[d[target] <= RECOVER_OUTLIER_S]
    print(f"  n={len(d)} rows, {d['experiment_id'].nunique()} configs"
          + (f" ({dropped} excluded)" if dropped else ""))
    return d[FEATURES], d[target].astype(float), d["experiment_id"]


def evaluate(name, model, X, y, groups, n_splits=5):
    cv = GroupKFold(n_splits=n_splits)
    pred = cross_val_predict(model, X, y, groups=groups, cv=cv)
    base = cross_val_predict(DummyRegressor(strategy="mean"), X, y, groups=groups, cv=cv)
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1 - ss_res / ss_tot
    mae = float(np.mean(np.abs(y - pred)))
    mae_base = float(np.mean(np.abs(y - base)))
    print(f"  {name:22s} R2={r2:6.3f}  MAE={mae:6.3f}s   (mean-baseline MAE={mae_base:6.3f}s)")
    return r2, mae


def run_target(df, target, label):
    print(f"\n{'=' * 68}\n{label}  (target: {target})\n{'=' * 68}")
    X, y, groups = prepare(df, target)
    print(f"  observed range: {y.min():.3f}s .. {y.max():.3f}s   median {y.median():.3f}s\n")
    print("  Grouped 5-fold CV (grouped by experiment_id -- no replicate leakage):")
    evaluate("DecisionTree(depth=4)", DecisionTreeRegressor(max_depth=4, random_state=0), X, y, groups)
    evaluate("RandomForest(300)", RandomForestRegressor(n_estimators=300, random_state=0), X, y, groups)

    tree = DecisionTreeRegressor(max_depth=4, random_state=0).fit(X, y)
    rf = RandomForestRegressor(n_estimators=300, random_state=0).fit(X, y)
    print("\n  Feature importance (RandomForest, full fit):")
    for f, imp in sorted(zip(FEATURES, rf.feature_importances_), key=lambda t: -t[1]):
        print(f"    {f:22s} {imp:.3f}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{target}_tree_rules.txt"
    out.write_text(export_text(tree, feature_names=FEATURES, decimals=3))
    print(f"\n  Tree rules written to {out.relative_to(BASE)}")
    return tree


def recommend(tree, target_seconds, top_k=5):
    grid = [
        {"window_type_is_time": w, "threshold": t, "window_size": s, "wait_duration": d}
        for w in (0, 1) for t in (30, 50, 70) for s in (5, 10, 20) for d in (5, 15, 30)
    ]
    G = pd.DataFrame(grid)
    G["predicted_s"] = tree.predict(G[FEATURES])
    G["window_type"] = np.where(G["window_type_is_time"] == 1, "TIME_BASED", "COUNT_BASED")
    G["abs_err"] = (G["predicted_s"] - target_seconds).abs()
    cols = ["window_type", "threshold", "window_size", "wait_duration", "predicted_s"]
    return G.sort_values("abs_err").head(top_k)[cols].reset_index(drop=True)


def descriptives(df):
    print(f"\n{'=' * 68}\nDESCRIPTIVES\n{'=' * 68}")
    d = df[df["time_to_open"].notna()]
    for by in ["window_type", "window_size", "threshold", "wait_duration"]:
        g = d.groupby(by)["time_to_open"].agg(["count", "mean", "std"]).round(3)
        print(f"\n-- time_to_open by {by} --\n{g.to_string()}")
    r = df[(df["time_to_recover"].notna()) & (df["time_to_recover"] <= RECOVER_OUTLIER_S)]
    g = r.groupby("wait_duration")["time_to_recover"].agg(["count", "mean", "std"]).round(3)
    print(f"\n-- time_to_recover by wait_duration (outlier excluded) --\n{g.to_string()}")


def main():
    df = load(find_dataset(sys.argv))
    descriptives(df)
    detect_tree = run_target(df, "time_to_open", "DETECTION LATENCY")
    run_target(df, "time_to_recover", "RECOVERY LATENCY")
    print(f"\n{'=' * 68}\nRECOMMENDER DEMO -- configs closest to a 5s detection target\n{'=' * 68}")
    print(recommend(detect_tree, 5.0).to_string(index=False))


if __name__ == "__main__":
    main()
