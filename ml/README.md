# CascadeShield — ML Pipeline

Owner: **Soham**. Consumes the 486-config chaos-sweep dataset and produces the two
interpretable models in the project's ML layer, plus the recommendation Lambda and an
adaptive closed-loop demo.

```
data/experiment_matrix.csv ──┐
                             │  (1) generate_synthetic_data.py   [until real sweep lands]
                             ▼
data/master_dataset.csv  ──┬──► (2) decision_tree.py     ──► models/decision_tree.pkl ──► lambda_handler.py  (POST /recommend)
   (15-col schema)         │                                  models/decision_tree_rules.txt        │
                          │                                  data/feature_importance.csv          └─► closed_loop_demo.py
                          └──► (3) isolation_forest.py   ──► models/isolation_forest.pkl
                                                            data/anomalies.csv
```

---

## ⚠️ The dataset is synthetic *for now*

The real numbers come from `experiments/runner.py` sweeping the 486 circuit-breaker
configs across the mesh. Until that sweep has run, `generate_synthetic_data.py` produces a
**schema-identical** stand-in so the entire pipeline can be built, tested, and demoed.

**To switch to real data:** drop the real `data/master_dataset.csv` in place and run
`python train_all.py --no-generate`. Nothing else changes — the 15-column contract is the
only coupling point. Synthetic-only files (`_synthetic_truth.csv`) are simply ignored when
absent.

The synthetic response model encodes the study's working hypotheses (so the models have
real structure to learn and the demo is meaningful), all documented in
`generate_synthetic_data.py`:

| Driver | Encoded effect |
|--------|----------------|
| Fault contagion | `CRASH > LATENCY > THROTTLE` |
| Topology blast | `SHARED_DEP_MESH > FAN_OUT > LINEAR_CHAIN` |
| Breaker tightness | looser (higher threshold / larger window) → bigger blast |
| **Novelty interaction** | best `window_type` **depends on fault**: `TIME_BASED` wins under LATENCY, `COUNT_BASED` under CRASH/THROTTLE |
| Environment | AWS ~ a few % worse than LOCAL (feeds the divergence analysis) |

These are *assumptions to be validated against the real sweep* — not findings. The real run
will confirm, refute, or refine them.

---

## Run

```bash
pip install -r requirements.txt
python train_all.py            # generate synthetic data + train both models
```

Individual stages:

```bash
python generate_synthetic_data.py            # data/master_dataset.csv (+ _synthetic_truth.csv)
python decision_tree.py                      # recommender (+ rules, feature_importance.csv)
python isolation_forest.py                   # anomaly detector (+ anomalies.csv)
python lambda_handler.py --topology FAN_OUT --fault-type CRASH   # /recommend locally
python closed_loop_demo.py --topology SHARED_DEP_MESH --fault LATENCY   # adaptive demo -> recommended.env
```

> **Windows / PowerShell:** use the `--topology / --fault-type` flags shown above.
> (Windows PowerShell strips the quotes off a `'{"...":"..."}'` JSON argument, so the
> raw-event form must be passed via `--event '<json>'`, which is only needed to exercise
> the actual Lambda event path.)

---

## The two models

### Decision Tree — configuration recommender (`decision_tree.py`)
- **Features:** the 6 swept independent variables (`topology`, `fault_type`, `window_type`,
  `threshold`, `window_size`, `wait_duration`). Provenance columns are never features, so the
  model can't learn LOCAL-vs-AWS shortcuts.
- **Two trees, both `max_depth ≤ 6`** (the interpretability cap that ruled out deep learning):
  a **classifier** (`safe`/`unsafe` at `blast_radius ≤ τ`, default `τ=0.5`) and a **regressor**
  (predicts `blast_radius`, used to rank configs).
- **Validation:** depth chosen by **5-fold cross-validation**; train-vs-test accuracy logged
  as the overfitting check.
- **Interpretability:** full rule dump in `models/decision_tree_rules.txt`; every
  recommendation ships the **decision path** that produced it; `data/feature_importance.csv`
  ranks the drivers.
- **`recommend(topology, fault_type)`** searches the 54-config CB grid and returns the config
  with the lowest predicted blast radius (and whether *any* config is predicted safe — for
  brutal contexts it honestly returns the least-bad).

### Isolation Forest — anomaly detector (`isolation_forest.py`)
- Fit on the **measured outcomes** (`blast_radius`, `error_rate`, `throughput_loss` scaled,
  plus `cb_opened` / `recovered` flags). It flags runs whose outcomes are internally
  contradictory (e.g. blast high while errors don't surge).
- **Meaningful nulls** (`time_to_open` / `time_to_recover` null = breaker never opened / never
  recovered) are **not mean-imputed** — per the data dictionary we encode the *event* via the
  companion booleans rather than inventing a magnitude.
- On synthetic data, detection is **scored against injected ground truth**
  (`_synthetic_truth.csv`) — precision/recall/F1, broken down by anomaly kind.

---

## AWS Lambda (`lambda_handler.py`)
Backs `POST /recommend`. Package this module with `preprocessing.py`, `decision_tree.py`,
`models/decision_tree.pkl`, and a scikit-learn/joblib layer; set the handler to
`lambda_handler.handler`. The model bundle is cached at module scope, so only cold starts pay
the unpickle cost. Request `{"topology": ..., "fault_type": ...}` → JSON with the recommended
CB config, predicted blast radius, and decision path.

## Closed loop (`closed_loop_demo.py`)
Observe → recommend → emit the new config as the exact `CB_*` env vars the compose stack and
`runner.py` already read (`recommended.env`), printing the projected blast-radius reduction.
Demonstrates the adaptive-reconfiguration control loop end-to-end.

---

## Files
| Path | What |
|------|------|
| `generate_synthetic_data.py` | schema-conformant synthetic dataset (placeholder for the real sweep) |
| `preprocessing.py` | shared encoding/labeling/outcome-matrix — single source of train/serve truth |
| `decision_tree.py` | recommender (classifier + regressor) + `recommend()` |
| `isolation_forest.py` | anomaly detector + ground-truth scoring |
| `lambda_handler.py` | `POST /recommend` entrypoint (AWS + local) |
| `closed_loop_demo.py` | adaptive reconfiguration demo |
| `train_all.py` | one-command orchestrator |
| `feature_engineering.md` | encoding/scaling decision log (Week-1 locked, Week-2 open items) |
| `models/` | saved `.pkl` bundles + rule dump (created by training) |

> **Repo placement:** in the GitHub layout `ml/` and `data/` sit at the repository root
> (siblings of `services/`). They live here for now because this working copy is rooted at
> `services/`; moving them up one level at integration time is a pure path move — no code
> changes (paths resolve relative to each script).
