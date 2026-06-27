#!/usr/bin/env python3
"""
decision_tree.py -- CascadeShield Configuration Recommender (Soham)

Trains the interpretable Decision Tree recommender described in the README ML
layer. Two small trees (both max_depth <= 6, the interpretability cap that ruled
out deep learning):

  * classifier  -- predicts safe / unsafe (blast_radius <= tau). Gives the
                   recommend() label and a confidence.
  * regressor   -- predicts blast_radius itself. Used to RANK configs within a
                   context so we can recommend the lowest predicted blast radius.

Reports 5-fold cross-validated scores and the train-vs-test gap (the
overfitting check the spec asks to log), exports a human-readable rule dump and
per-config decision paths, writes data/feature_importance.csv, and saves a
joblib bundle the Lambda loads.

Run:  python decision_tree.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, mean_absolute_error, r2_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from preprocessing import (  # noqa: E402
    DEFAULT_TAU, ENCODED_FEATURE_NAMES, build_outcome_frame, config_grid,
    encode_features, featurize_config, load_dataset, make_labels,
)

DATA_DIR = SCRIPT_DIR.parent / "data"
MODELS_DIR = SCRIPT_DIR / "models"
MAX_DEPTH_CAP = 6           # hard interpretability constraint
CANDIDATE_DEPTHS = [3, 4, 5, 6]
RANDOM_STATE = 42


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #
def _best_depth(estimator_factory, X, y, scoring: str) -> tuple[int, float]:
    """Pick the max_depth in CANDIDATE_DEPTHS with the best 5-fold CV score."""
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    best_d, best_s = CANDIDATE_DEPTHS[0], -np.inf
    for d in CANDIDATE_DEPTHS:
        scores = cross_val_score(estimator_factory(d), X, y, cv=cv, scoring=scoring)
        if scores.mean() > best_s:
            best_d, best_s = d, scores.mean()
    return best_d, best_s


def train(dataset_path: Path, tau: float):
    df = load_dataset(dataset_path)
    X = encode_features(df)
    y_label = make_labels(df, tau)
    y_blast = df["blast_radius"].astype(float)

    # ---- classifier: safe / unsafe -----------------------------------------
    depth_c, cv_c = _best_depth(
        lambda d: DecisionTreeClassifier(max_depth=d, class_weight="balanced",
                                         random_state=RANDOM_STATE),
        X, y_label, scoring="f1_macro")
    Xtr, Xte, ytr, yte = train_test_split(
        X, y_label, test_size=0.25, random_state=RANDOM_STATE, stratify=y_label)
    clf = DecisionTreeClassifier(max_depth=depth_c, class_weight="balanced",
                                 random_state=RANDOM_STATE).fit(Xtr, ytr)
    train_acc = clf.score(Xtr, ytr)
    test_acc = clf.score(Xte, yte)
    report = classification_report(yte, clf.predict(Xte), output_dict=True, zero_division=0)
    cm = confusion_matrix(yte, clf.predict(Xte), labels=list(clf.classes_)).tolist()
    # ship the model fit on ALL data
    clf_full = DecisionTreeClassifier(max_depth=depth_c, class_weight="balanced",
                                      random_state=RANDOM_STATE).fit(X, y_label)

    # ---- regressor: blast_radius -------------------------------------------
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    # stratify the regressor's CV by the safe/unsafe label to keep folds comparable
    best_dr, best_r2 = CANDIDATE_DEPTHS[0], -np.inf
    for d in CANDIDATE_DEPTHS:
        scores = cross_val_score(
            DecisionTreeRegressor(max_depth=d, random_state=RANDOM_STATE),
            X, y_blast, cv=cv.split(X, y_label), scoring="r2")
        if scores.mean() > best_r2:
            best_dr, best_r2 = d, scores.mean()
    Xtr2, Xte2, btr, bte = train_test_split(
        X, y_blast, test_size=0.25, random_state=RANDOM_STATE, stratify=y_label)
    reg = DecisionTreeRegressor(max_depth=best_dr, random_state=RANDOM_STATE).fit(Xtr2, btr)
    reg_mae = mean_absolute_error(bte, reg.predict(Xte2))
    reg_r2 = r2_score(bte, reg.predict(Xte2))
    reg_full = DecisionTreeRegressor(max_depth=best_dr, random_state=RANDOM_STATE).fit(X, y_blast)

    metrics = {
        "tau": tau,
        "classifier": {
            "max_depth": depth_c, "cv_f1_macro": round(float(cv_c), 4),
            "train_accuracy": round(float(train_acc), 4),
            "test_accuracy": round(float(test_acc), 4),
            "overfit_gap": round(float(train_acc - test_acc), 4),
            "test_report": report, "confusion_matrix": cm,
            "classes": list(clf.classes_),
        },
        "regressor": {
            "max_depth": best_dr, "cv_r2": round(float(best_r2), 4),
            "test_r2": round(float(reg_r2), 4), "test_mae": round(float(reg_mae), 4),
        },
        "n_rows": int(len(df)),
        "class_balance": {k: int(v) for k, v in pd.Series(y_label).value_counts().items()},
    }
    return df, X, clf_full, reg_full, metrics


# --------------------------------------------------------------------------- #
# Recommendation (also imported by lambda_handler / closed_loop_demo)
# --------------------------------------------------------------------------- #
def decision_path_text(tree_model, x_row: pd.DataFrame, feature_names) -> list[str]:
    """Human-readable list of the split decisions taken for a single config."""
    t = tree_model.tree_
    node, steps = 0, []
    xv = x_row.iloc[0]
    while t.children_left[node] != t.children_right[node]:  # not a leaf
        feat = feature_names[t.feature[node]]
        thr = t.threshold[node]
        if xv[feat] <= thr:
            steps.append(f"{feat} <= {thr:.2f}")
            node = t.children_left[node]
        else:
            steps.append(f"{feat} > {thr:.2f}")
            node = t.children_right[node]
    return steps


def recommend(bundle: dict, topology: str, fault_type: str, top_k: int = 3) -> dict:
    """Search the 54-config CB grid for the safest config in the given context."""
    clf, reg = bundle["classifier"], bundle["regressor"]
    safe_label = "safe"
    candidates = []
    for cfg in config_grid():
        x = featurize_config(topology=topology, fault_type=fault_type, **cfg)
        proba = clf.predict_proba(x)[0]
        p_safe = float(proba[list(clf.classes_).index(safe_label)]) if safe_label in clf.classes_ else 0.0
        pred_blast = float(reg.predict(x)[0])
        label = str(clf.predict(x)[0])
        candidates.append({**cfg, "predicted_label": label,
                           "p_safe": round(p_safe, 4),
                           "predicted_blast_radius": round(pred_blast, 4)})
    # rank: safe first, then lowest predicted blast, then highest confidence
    candidates.sort(key=lambda c: (c["predicted_label"] != safe_label,
                                   c["predicted_blast_radius"], -c["p_safe"]))
    best = candidates[0]
    x_best = featurize_config(topology=topology, fault_type=fault_type,
                              window_type=best["window_type"], threshold=best["threshold"],
                              window_size=best["window_size"], wait_duration=best["wait_duration"])
    return {
        "context": {"topology": topology, "fault_type": fault_type},
        "recommended_config": {k: best[k] for k in
                               ("window_type", "threshold", "window_size", "wait_duration")},
        "predicted_label": best["predicted_label"],
        "predicted_blast_radius": best["predicted_blast_radius"],
        "p_safe": best["p_safe"],
        "any_safe_config_exists": any(c["predicted_label"] == safe_label for c in candidates),
        "decision_path": decision_path_text(clf, x_best, ENCODED_FEATURE_NAMES),
        "alternatives": candidates[1:top_k],
    }


# --------------------------------------------------------------------------- #
# Persistence / CLI
# --------------------------------------------------------------------------- #
def save_bundle(clf, reg, metrics, dataset_path: Path) -> Path:
    import sklearn
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "classifier": clf, "regressor": reg,
        "feature_names": ENCODED_FEATURE_NAMES,
        "tau": metrics["tau"], "metrics": metrics,
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": str(dataset_path),
        "is_synthetic": dataset_path.name == "master_dataset.csv"
        and (DATA_DIR / "_synthetic_truth.csv").exists(),
    }
    path = MODELS_DIR / "decision_tree.pkl"
    joblib.dump(bundle, path)
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Train the CascadeShield Decision Tree recommender.")
    p.add_argument("--data", type=Path, default=DATA_DIR / "master_dataset.csv")
    p.add_argument("--tau", type=float, default=DEFAULT_TAU)
    p.add_argument("--demo-context", default="SHARED_DEP_MESH,LATENCY",
                   help="topology,fault_type to demo recommend() on")
    args = p.parse_args(argv)

    df, X, clf, reg, metrics = train(args.data, args.tau)

    # readable global rules + feature importances
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    rules = export_text(clf, feature_names=list(ENCODED_FEATURE_NAMES))
    (MODELS_DIR / "decision_tree_rules.txt").write_text(rules, encoding="utf-8")
    fi = (pd.DataFrame({"feature": ENCODED_FEATURE_NAMES,
                        "importance": clf.feature_importances_})
          .sort_values("importance", ascending=False))
    fi.to_csv(DATA_DIR / "feature_importance.csv", index=False)

    bundle_path = save_bundle(clf, reg, metrics, args.data)
    bundle = joblib.load(bundle_path)

    c = metrics["classifier"]
    r = metrics["regressor"]
    print("[decision_tree] trained on", metrics["n_rows"], "rows  (tau =", metrics["tau"], ")")
    print(f"  classifier  depth={c['max_depth']}  cv_f1_macro={c['cv_f1_macro']}"
          f"  train_acc={c['train_accuracy']}  test_acc={c['test_accuracy']}"
          f"  (overfit gap {c['overfit_gap']})")
    print(f"  regressor   depth={r['max_depth']}  cv_r2={r['cv_r2']}"
          f"  test_r2={r['test_r2']}  test_mae={r['test_mae']}")
    print("  class balance:", metrics["class_balance"])
    print("  top features:", ", ".join(f"{row.feature}({row.importance:.2f})"
                                        for row in fi.head(4).itertuples()))
    print("  saved:", bundle_path.name, "| rules: decision_tree_rules.txt",
          "| data/feature_importance.csv")

    topo, fault = [s.strip() for s in args.demo_context.split(",")]
    rec = recommend(bundle, topo, fault)
    print(f"\n  recommend({topo}, {fault}) ->")
    print("   ", json.dumps(rec["recommended_config"]),
          f"=> {rec['predicted_label']} (pred blast {rec['predicted_blast_radius']},"
          f" any_safe={rec['any_safe_config_exists']})")
    print("    why:", " AND ".join(rec["decision_path"]) or "(root)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
