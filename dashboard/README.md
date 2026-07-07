# CascadeShield — Results Dashboard

A local Flask app that turns `data/master_dataset.csv` into a browsable results view,
so you don't have to watch `runner.py`'s terminal output or re-run a lost ad-hoc plotting
script to see what a sweep produced. Reproduces the fault_type × window_type heatmaps and
summary stats that used to live only in an uncommitted `figures/` directory.

## Run it

```bash
cd dashboard
pip install -r requirements.txt
python app.py
```

Serves on `http://127.0.0.1:5050`. Port 5050 (not 5000) avoids the macOS AirPlay Receiver
conflict. This is the Flask **development** server only — no auth, no WSGI, not meant for
deployment.

## Routes

| Route | Purpose |
|---|---|
| `/` | Overview: total run count, distinct swept values (fault_type, window_type, topology, environment, mode), data-health panel (e.g. % of rows with null `time_to_open`/`time_to_recover`). |
| `/results` | Filterable via query params (`?fault_type=CRASH&window_type=COUNT_BASED&...`). Renders the blast-radius heatmaps (median + mean), the breaker trip-rate heatmap, the COUNT_BASED blast-radius distribution, and the underlying summary table — all recomputed fresh on every request. |

## Design notes / caveats

- **No hardcoded schema.** `data_loader.py` reads whatever columns are actually in
  `data/master_dataset.csv` via pandas — it never imports a fixed column list or enum.
  `data/master_dataset_schema.csv` has drifted from the real data before (missing the
  `mode` column at one point); the dashboard is intentionally immune to that class of bug.
- **Filter options are derived dynamically** from the loaded CSV's distinct values, not from
  `ml/preprocessing.py`'s hardcoded `TOPOLOGIES`/`WINDOW_SIZES` constants — those are
  already stale relative to the real sweep (real data only has `topology=LINEAR` so far,
  not the 3-way `LINEAR_CHAIN`/`FAN_OUT`/`SHARED_DEP_MESH` enum).
- **`blast_radius` is 0–100** (percent of mesh), not a 0.0–1.0 fraction — displayed as-is.
- **`time_to_open`/`time_to_recover` are always null today** — `runner.py` doesn't wire
  these up yet (separate, tracked TODO). No chart here touches those columns.
- Charts are rendered server-side with matplotlib's `Agg` backend + the object-oriented
  `Figure` API (not global `pyplot`, which isn't thread-safe under Flask's dev server),
  streamed as base64 PNGs embedded directly in the HTML. Nothing is written to disk, so
  there's no stale-image cache to worry about and filters always recompute from scratch.

## Out of scope (for now)

- **Live run progress** — this only shows completed runs. Watching a sweep in progress
  still means the terminal, or Grafana (`infra/grafana/`) for live Prometheus metrics
  during an active run. A live-progress view is a planned future phase; it would need
  `runner.py` to write a status file as it runs, which it doesn't today.
- Fixing the `master_dataset_schema.csv` / `ml/preprocessing.py` enum drift — adjacent,
  pre-existing issue, not this dashboard's responsibility.
- AWS/cloud deployment.
