"""Smoke test for the recommender pipeline.

Exists because the committed model bundle silently went stale: it had been pickled
against an older topology vocabulary (`LINEAR_CHAIN`), the vocabulary was later changed
to `LINEAR`, and every `recommend()` call raised ValueError from then on. Nothing caught
it -- the .pkl still looked current in review, and no test loaded it. The model artifacts
are now gitignored, and this test rebuilds the pipeline from the dataset and exercises
`recommend()` across the full vocabulary, so any drift between the feature schema and a
persisted bundle fails a test run instead of sitting broken.

Runs under pytest, or standalone (pytest is not in requirements.txt):

    python ml/test_smoke.py
    python -m pytest ml/test_smoke.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from decision_tree import MODELS_DIR, recommend, train  # noqa: E402
from preprocessing import (  # noqa: E402
    DEFAULT_TAU, ENCODED_FEATURE_NAMES, FAULT_TYPES, TOPOLOGIES,
)

DATASET = SCRIPT_DIR.parent / "data" / "master_dataset.csv"

_CACHED: dict | None = None


def _bundle() -> dict:
    """Train once from the real dataset and reuse across tests."""
    global _CACHED
    if _CACHED is None:
        _, _, clf, reg, metrics = train(DATASET, DEFAULT_TAU)
        _CACHED = {"classifier": clf, "regressor": reg, "metrics": metrics}
    return _CACHED


def test_pipeline_trains():
    """train() completes on the committed dataset and reports a sane row count."""
    m = _bundle()["metrics"]
    assert m["n_rows"] > 0, "trained on an empty dataset"
    assert m["tau"] == DEFAULT_TAU


def test_regressor_scores_are_config_level():
    """Regressor validation must stay grouped by experiment_id.

    Replicates of one config are near-duplicate rows; ungrouping them silently turns the
    holdout into a memorisation test. Pin the grouping and the effective-n reporting so a
    future edit cannot quietly revert to a random split.
    """
    m = _bundle()["metrics"]
    r = m["regressor"]
    assert r["grouped_by"] == "experiment_id"
    assert r["n_configs"] == m["n_configs"]
    assert r["n_configs"] <= m["n_rows"], "effective n must be configs, not rows"
    for key in ("cv_r2_grouped", "test_r2_grouped", "test_mae_grouped"):
        assert key in r, f"missing grouped metric {key}"
    for stale in ("cv_r2", "test_r2", "test_mae"):
        assert stale not in r, (
            f"ungrouped key {stale!r} reappeared -- regressor scores must be config-level")


def test_recommend_across_full_vocabulary():
    """recommend() works for every topology x fault_type.

    This is the check that would have caught the LINEAR_CHAIN drift: a stale estimator
    raises ValueError ("feature names should match those passed during fit") the moment
    it is asked to predict on a config encoded with the current vocabulary.
    """
    bundle = _bundle()
    for topology in TOPOLOGIES:
        for fault_type in FAULT_TYPES:
            rec = recommend(bundle, topology, fault_type)
            assert rec["context"] == {"topology": topology, "fault_type": fault_type}
            assert set(rec["recommended_config"]) == {
                "window_type", "threshold", "window_size", "wait_duration"}
            assert rec["predicted_label"] in ("safe", "unsafe")
            assert 0.0 <= rec["predicted_blast_radius"] <= 1.0
            assert 0.0 <= rec["p_safe"] <= 1.0
            assert isinstance(rec["any_safe_config_exists"], bool)


def test_top_k_is_total_configs_surfaced():
    """Pins the documented contract: top_k counts the best config, not just alternatives."""
    bundle = _bundle()
    for k in (1, 2, 3, 5):
        rec = recommend(bundle, TOPOLOGIES[0], FAULT_TYPES[0], top_k=k)
        assert 1 + len(rec["alternatives"]) == k, (
            f"top_k={k} surfaced {1 + len(rec['alternatives'])} configs; "
            "top_k is documented as the TOTAL number returned")


def test_persisted_bundle_matches_current_schema():
    """A bundle left on disk must agree with the live feature schema.

    Skipped when no bundle is present (the artifacts are gitignored, so a clean
    checkout has none until train_all.py runs).
    """
    path = MODELS_DIR / "decision_tree.pkl"
    if not path.exists():
        return
    import joblib
    saved = joblib.load(path)
    assert list(saved["feature_names"]) == list(ENCODED_FEATURE_NAMES), (
        "persisted bundle's feature_names drifted from ENCODED_FEATURE_NAMES -- "
        "stale artifact, re-run: python ml/train_all.py --no-generate")
    for role in ("classifier", "regressor"):
        fitted = list(getattr(saved[role], "feature_names_in_", ENCODED_FEATURE_NAMES))
        assert fitted == list(ENCODED_FEATURE_NAMES), (
            f"persisted {role} was fit on a different vocabulary than the code now "
            f"encodes -- stale artifact, re-run: python ml/train_all.py --no-generate")
    # the real end-to-end proof: the stale bundle raised ValueError right here
    recommend(saved, TOPOLOGIES[0], FAULT_TYPES[0])


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001 - standalone runner reports, not raises
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
