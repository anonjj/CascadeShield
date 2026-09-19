# Phase 4B — launch manifest

**Nothing in this document has been run.** No experiment, no mesh, no smoke run. This is the
frozen launch record: what will be run, with which inputs, and what must be true first.

Part B (the smoke run) starts only on an explicit "GO SMOKE". The 72-run sweep is a separate,
later approval.

---

## 0. Frozen artifacts

| artifact | value |
|---|---|
| Pre-registration, **superseded** | `8f1623b` — superseded on 2026-09-20, **before any run** |
| Pre-registration, **FINAL** | **`34bfda7c7fe5cda70725508b654a162ef28161c9`** |
| Branch | `h3-evidence-audit` (not pushed) |
| Design | Option C — 24 configs x 3 replicates = **72 runs** |
| Arms | LINEAR topology, LATENCY fault, COUNT_BASED vs TIME_BASED |
| Strata | $D_w \in \{5, 15, 30\}$ |
| Machine | `soham-local` (passed explicitly as `--machine-id`, never auto-detected) |
| Seed | `20260920` |
| Sweep dataset | `DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv` |
| Smoke config | `LIN-LAT-CNT-T30-W5-D5` |
| Sidecar baseline | `data/cb_transitions.jsonl`, **73** records, sha256 `ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e` (verified 2026-09-20) |
| Host | Windows 11 Pro 26200, inside OneDrive; **OneDrive sync paused for the run** |

The analytic rules are frozen as of `34bfda7`. Any later change is reported as a deviation,
never edited in.

### Tracked input lists

`data/` is gitignored, so the authoritative copies of both `--only-ids` files live in
`docs/paper/` and are **copied into `data/` at launch**. The copies must be byte-identical.

| tracked file | sha256 | contents |
|---|---|---|
| `docs/paper/phase4b_only_ids.txt` | `6d6e57452ba56e814cb525d1a0f48c7b6c198830f7d8296a6bf856f2e36a0f12` | the 24 Option C configs |
| `docs/paper/phase4b_smoke_ids.txt` | `35aa1a330cc17c7cbbdb760b0aa851c7862ae693a7e49979f879bb64ce9e518d` | `LIN-LAT-CNT-T30-W5-D5` only |

The smoke ID is deliberately **not** one of the 24: `T30` is absent from Option C, which uses
`T50` and `T70` only. Verified by dry-list (§2): the two sets are disjoint.

---

## 1. Host preflight (read-only) — record these in the run log

Every command is read-only. Run them all and paste the output into the run log; the manifest
JSON in §7 carries the ones the post-sweep check needs.

```bash
# --- repo state -------------------------------------------------------------
git rev-parse HEAD
git status --porcelain            # must be empty at launch
git log -1 --format='%H %cI %s'
sha256sum docs/paper/phase4b_only_ids.txt docs/paper/phase4b_smoke_ids.txt

# --- sidecar baseline -------------------------------------------------------
sha256sum data/cb_transitions.jsonl     # must be ffad69d6...bee0e
wc -l     data/cb_transitions.jsonl     # must be 73

# --- disk -------------------------------------------------------------------
df -h .
docker system df

# --- docker inventory -------------------------------------------------------
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
docker ps -aq  | wc -l
docker images -q | wc -l
docker image inspect infra-gateway-service --format '{{.Id}} {{.Created}}'
docker inspect gateway-service --format '{{.Image}}'
```

```powershell
# --- RAM --------------------------------------------------------------------
Get-CimInstance Win32_OperatingSystem |
  Select-Object TotalVisibleMemorySize, FreePhysicalMemory

# --- sleep / power ----------------------------------------------------------
powercfg /a
powercfg /getactivescheme
powercfg /q SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
powercfg /q SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE
powercfg /q SCHEME_CURRENT SUB_BUTTONS LIDACTION

# --- OneDrive sync ----------------------------------------------------------
Get-Process OneDrive -ErrorAction SilentlyContinue |
  Select-Object Id, ProcessName, StartTime
```

### Values observed 2026-09-20 (pre-launch, informational)

| item | value | note |
|---|---|---|
| `git rev-parse HEAD` | `34bfda7` at the time of writing | re-read at launch; it moves |
| `git status --porcelain` | clean before this session's commits | must be clean at launch |
| Sidecar | 73 records, `ffad69d6…bee0e` | matches the decided baseline |
| Disk `C:` | 232 G total, **27 G free (89% used)** | see the warning below |
| `docker system df` | images 4.625 G (1.848 G reclaimable), **build cache 17.83 G (15.35 G reclaimable)** | see the warning below |
| Containers / images | 11 containers (all `Exited (255)`), 17 images | mesh is **down**, as required |
| RAM | 14.5 G total, **2.96 G free** | 6 JVMs + Prometheus + Grafana on 14.5 G is tight |
| Sleep | `Standby (S0 Low Power Idle)` + `Hibernate` available; `STANDBYIDLE` = **0 (never)** on both AC and DC | S0 idle means the machine can still enter a low-power state with the lid shut |
| OneDrive | process **not running** | sync is stopped, consistent with "paused for the run" |

> **Disk.** 27 G free with a 17.8 G Docker build cache is the thinnest resource here. A 72-run
> sweep force-recreates six containers 72 times and writes a ~300 KB/run poll log — small — but
> a full image rebuild mid-sweep is not. `docker builder prune` would reclaim ~15 G. That is a
> write operation, so it is **not** done here; decide before GO SMOKE.

> **RAM.** 2.96 G free is measured with the mesh **down**. Bring the mesh up and re-check
> before GO SMOKE; if the JVMs swap, `time_to_recover` is measuring the host, not the breaker.

---

## 2. Smoke run (Part B — requires "GO SMOKE")

### 2.1 The output-path problem, and the decision taken

The decided sweep override is `DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv`. Pointing the
**smoke** run at that same file would write a `LIN-LAT-CNT-T30-W5-D5` row into the sweep's
dataset, which breaks two invariants the post-sweep check enforces: "exactly 72 rows" and
"every `experiment_id` is in the `--only-ids` list". Removing it afterwards would mean
hand-editing a dataset, which §10 of the pre-registration forbids.

**Decision: the smoke run writes to `data/phase4b_smoke.csv`.** The sweep's
`DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv` is unchanged and is used only by the sweep.
The two runs still share one sidecar (`--mode full` always appends to
`data/cb_transitions.jsonl`), which is exactly what §3's baseline-and-restore procedure is for.

### 2.2 Sidecar baseline — before the smoke run

```bash
cp data/cb_transitions.jsonl data/audit/sidecar_baseline_73.jsonl
sha256sum data/audit/sidecar_baseline_73.jsonl
#   expect ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e
wc -l data/audit/sidecar_baseline_73.jsonl
#   expect 73
```

**Do not proceed if either differs.** No hand-editing, at any point.

### 2.3 Start the poller first

Its own terminal, started **before** the run and left running (pre-registration §11):

```bash
python analysis/gateway_poll_verify.py poll \
  --base http://localhost:8080 \
  --out  data/audit/phase4b_smoke_poll.jsonl \
  --interval 1.0 --label phase4b-smoke
```

### 2.4 The smoke command

```bash
cp docs/paper/phase4b_smoke_ids.txt data/phase4b_smoke_ids.txt
sha256sum docs/paper/phase4b_smoke_ids.txt data/phase4b_smoke_ids.txt   # must match

export DATASET_PATH_OVERRIDE=data/phase4b_smoke.csv

python experiments/runner.py \
  --mode full \
  --fault latency \
  --topology linear \
  --only-ids data/phase4b_smoke_ids.txt \
  --replicates 1 \
  --limit 1 \
  --seed 20260920 \
  --machine-id soham-local
```

Then confirm `data/phase4b_smoke.csv` appears within ~2 minutes of launch (CLAUDE.md footgun
1 — `get_dataset_path()` falls through to `master_dataset.csv` for modes it has no case for;
`full` does honour the override, but verify the file rather than trusting it).

### 2.5 Dry-list evidence (run 2026-09-20, no mesh)

`analysis/phase4b_dry_list.py` imports `runner.py` and replays `main()`'s scheduling sequence
— `generate_combinations` → `--only-ids` filter → `build_shuffled_run_list` → resume filter →
`apply_run_limit` — calling the same functions in the same order. It exists because
`runner.py` `sys.exit(1)`s on an unreachable Toxiproxy before it prints anything, so the real
runner cannot be asked "what would you run?" without a mesh.

```
$ python analysis/phase4b_dry_list.py --mode full --fault latency --topology linear \
      --only-ids docs/paper/phase4b_smoke_ids.txt --replicates 1 --limit 1 --seed 20260920

generate_combinations('full') -> 54 configs
--only-ids filter: 54 configs -> 1 matching 'linear'/'latency' (of 1 IDs listed).
Generated 1 configs x 1 replicates = 1 total runs.
Resume source: none (treating the output file as absent/empty).
Run order shuffled with seed 20260920 (1 runs).
resume filter: 0 skipped, 1 pending.
--limit 1: truncated to 1 new run(s).

WOULD SCHEDULE 1 run(s), in this order:
    1. LIN-LAT-CNT-T30-W5-D5  replicate=1

distinct experiment_ids: 1
```

And the disjointness check against the sweep list:

```
smoke runs        : 1 [('LIN-LAT-CNT-T30-W5-D5', '1')]
sweep runs        : 72
sweep distinct ids: 24
intersection      : set()
smoke id in the 24: set()
```

**Exactly one run is scheduled, and it is none of the 24.**

### 2.6 Sidecar restore — after the smoke run

Preserve the smoke's own record first, then restore. Copying only; nothing is edited.

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)

# 1. preserve the post-smoke sidecar (74 records) as evidence
cp data/cb_transitions.jsonl data/audit/phase4b_smoke_sidecar_$TS.jsonl
wc -l     data/audit/phase4b_smoke_sidecar_$TS.jsonl      # expect 74
sha256sum data/audit/phase4b_smoke_sidecar_$TS.jsonl      # record it

# 2. restore the baseline by copying it back
cp data/audit/sidecar_baseline_73.jsonl data/cb_transitions.jsonl

# 3. re-verify -- both must match the baseline exactly
sha256sum data/cb_transitions.jsonl
#   must be ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e
wc -l data/cb_transitions.jsonl
#   must be 73
```

If the restored hash is not `ffad69d6…bee0e`, **stop**: something other than an append
happened to the sidecar, and the baseline for the sweep is no longer established.

---

## 3. The 72-run sweep (NOT APPROVED — recorded for completeness)

```bash
cp docs/paper/phase4b_only_ids.txt data/phase4b_only_ids.txt
sha256sum docs/paper/phase4b_only_ids.txt data/phase4b_only_ids.txt   # must match

export DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv

python experiments/runner.py \
  --mode full --fault latency --topology linear \
  --only-ids data/phase4b_only_ids.txt \
  --replicates 3 \
  --seed 20260920 \
  --machine-id soham-local
```

with the poller running in its own window for the whole sweep (pre-registration §11):

```bash
python analysis/gateway_poll_verify.py poll --base http://localhost:8080 \
  --out data/audit/phase4b_poll.jsonl --interval 1.0 --label phase4b
```

CLAUDE.md's "long sweeps run detached" rule assumes a POSIX host. On this Windows host the
equivalent property — *does a job survive its terminal closing?* — is not assumed; it is
tested as a precondition (§6, dummy-job survival test).

---

## 4. Resume procedure

The runner is resumable by `(experiment_id, replicate)` for rows with
`precondition_ok=True`. Resuming a sweep that has aborted, orphaned or gate-failing rows in it
will **silently skip** those cells, because `load_completed()` counts any
`precondition_ok=True` row as done. So reconciliation comes between stopping and resuming:

1. **Stop the runner.** Confirm it is dead — `data/run_status.json` stops advancing, and no
   `runner.py` process remains. Leave the poller running if it is healthy; restarting it
   breaks the one-continuous-session property (pre-registration §11).
2. **Reconcile, dry run first:**
   ```bash
   python analysis/phase4b_reconcile.py \
     --dataset data/phase4b_postd25.csv \
     --transitions data/cb_transitions.jsonl \
     --machine-id soham-local --mode full
   ```
   Read the orphan list before changing anything.
3. **Quarantine:** add `--apply`. It refuses to run while a runner process is alive or while
   `run_status.json` says `phase=running`. It writes a hashed backup, moves every unmatched
   row into `data/audit/phase4b_orphans_<timestamp>.csv`, and atomically rewrites the CSV with
   the runner's exact header. The sidecar is never modified.
4. **Resume with the same seed and the same `--only-ids`:**
   ```bash
   export DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv
   python experiments/runner.py --mode full --fault latency --topology linear \
     --only-ids data/phase4b_only_ids.txt --replicates 3 \
     --seed 20260920 --machine-id soham-local
   ```
   The same `--seed` keeps the remaining cells in the order the original shuffle assigned.
5. **Record** how many keys were re-collected, by class. Pre-registration §10 requires that
   number in the results, alongside the exclusion counts and before any p-value.

---

## 5. Post-sweep integrity check

`analysis/phase4b_postsweep_check.py --manifest data/audit/phase4b_manifest.json`.
Every item is a gate: if one fails, the dataset is not cleared for the H3 analysis.

| # | gate |
|---|---|
| 1a | CSV has exactly **72** rows |
| 1b | every `(experiment_id, replicate)` is **unique** |
| 2a | every `experiment_id` is in the manifest's `--only-ids` list — anything else is a contaminant, reported and excluded |
| 2b | all **24** configs carry exactly replicates `1,2,3` |
| 3a | the sidecar was **appended to**, not truncated or rewritten |
| 3b | its first 73 records are still the recorded baseline (structural hash) |
| 3c | exactly **72 in-scope** post-baseline records. Every post-baseline record is validated on `experiment_id` + `replicate` + `machine_id` + `mode` + the sweep's time window **and** the manifest's `--only-ids` list. Anything unexpected, on the wrong machine, in the wrong mode, with an out-of-range replicate, outside the sweep's time range, **or the smoke run's own record**, is reported with its reason and **excluded — never silently counted** |
| 4 | all 72 rows reconcile **one-to-one** with an in-scope record; zero orphan rows, zero orphan records |
| 5 | all 72 rows have `precondition_ok == True` |
| 6 | **no gateway `CLOSED_TO_OPEN`** in any in-scope record |
| 7 | **poller coverage per run**: every run `VERIFIED_CLEAN` under the pre-registered §5 horizon and §6 verdict rule, with `POLL_ERROR` / `MISSING_TICK` / `GATEWAY_NOT_CLOSED` / `POLLER_STOPPED` reported separately. A missing poll log is reported as UNVERIFIED, which the plan treats as `NOT_VERIFIED`, not as clean |
| 8 | gateway **image ID unchanged** vs the manifest, and the running container is still on that image |

Self-tested with synthetic data (`--self-test`): the exclusion path is exercised for a smoke
record, an unlisted ID, the wrong machine, the wrong mode, an out-of-range replicate, and a
record before and after the sweep window; plus a gateway-trip record, a non-gateway trip, a
duplicate key and a wrong row count.

---

## 6. What must be confirmed before "GO SMOKE"

These are the operator's to confirm, not the harness's. Each one has cost this project data
before, or is the Windows analogue of something that has.

1. **AC power.** The laptop is on mains and will stay on mains for the run. Battery is not a
   factor.
2. **Sleep and hibernate.** `STANDBYIDLE` already reads 0 (never) on AC and DC, but this
   machine has `Standby (S0 Low Power Idle)` and `Hibernate` available. Confirm
   `HIBERNATEIDLE` and the lid-close action too. Host sleep is the known cause of the 704.6 s
   and 1703.4 s artifacts; the pre-registration's §4.4 rule catches them after the fact, but
   a caught artifact is still a lost run.
3. **Pending Windows updates / restart.** `Get-WindowsUpdateLog` is heavy; the practical check
   is Settings → Windows Update showing nothing pending and no "restart required" banner. A
   forced restart mid-sweep kills the runner **and** Docker.
4. **Docker up and the mesh reachable.**
   ```bash
   docker compose -f infra/docker-compose.yml up -d --build
   curl -s http://localhost:8474/proxies              # must return JSON
   python experiments/fault_injector.py               # expect 5 proxies created and reset
   sleep 60
   curl -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/v1/linear   # expect 200
   ```
   `up -d --build` is also what makes the §7 image check pass — see the note there.
5. **Free disk.** Currently **27 G**. Decide whether to `docker builder prune` (~15 G
   reclaimable) first. Also re-check free RAM with the mesh **up**, not down.
6. **OneDrive stays paused** for longer than the run will take. OneDrive's pause is a fixed
   duration (2 / 8 / 24 h); confirm the window covers it. The repo lives inside OneDrive, so a
   resumed sync mid-run can touch files under `data/` while the runner is appending to them.
7. **Dummy-job survival test, run from your own Git Bash window.** This replaces CLAUDE.md's
   SSH-drop assumption, which does not apply here:
   ```bash
   nohup bash -c 'for i in $(seq 1 900); do echo "$(date -u +%FT%TZ) tick $i"; sleep 1; done' \
     > /tmp/dummy_survival.log 2>&1 & disown
   ```
   Note the PID, **close the Git Bash window**, wait ~60 s, open a new one, and check that
   `/tmp/dummy_survival.log` kept growing across the close. If it stopped, the 72-run sweep
   must not be launched from an interactive window — use a detached launcher or a scheduled
   task instead, and record which.

---

## 7. Manifest JSON (consumed by the post-sweep check)

Write this to `data/audit/phase4b_manifest.json` **at launch**, with the run-time fields
filled in. `sidecar_baseline_struct_sha256` is optional; omit it to skip gate 3b.

```json
{
  "git_head": "<git rev-parse HEAD at launch>",
  "preregistration_sha": "34bfda7c7fe5cda70725508b654a162ef28161c9",
  "preregistration_superseded": "8f1623b",
  "machine_id": "soham-local",
  "mode": "full",
  "fault": "latency",
  "topology": "linear",
  "replicates": 3,
  "seed": 20260920,
  "dataset_path": "data/phase4b_postd25.csv",
  "transitions_path": "data/cb_transitions.jsonl",
  "poll_path": "data/audit/phase4b_poll.jsonl",
  "only_ids_file": "docs/paper/phase4b_only_ids.txt",
  "only_ids_sha256": "6d6e57452ba56e814cb525d1a0f48c7b6c198830f7d8296a6bf856f2e36a0f12",
  "smoke_ids_sha256": "35aa1a330cc17c7cbbdb760b0aa851c7862ae693a7e49979f879bb64ce9e518d",
  "only_ids": [
    "LIN-LAT-CNT-T50-W5-D5",  "LIN-LAT-TIM-T50-W5-D5",
    "LIN-LAT-CNT-T50-W10-D5", "LIN-LAT-TIM-T50-W10-D5",
    "LIN-LAT-CNT-T50-W20-D5", "LIN-LAT-TIM-T50-W20-D5",
    "LIN-LAT-CNT-T70-W10-D5", "LIN-LAT-TIM-T70-W10-D5",
    "LIN-LAT-CNT-T50-W5-D15",  "LIN-LAT-TIM-T50-W5-D15",
    "LIN-LAT-CNT-T50-W10-D15", "LIN-LAT-TIM-T50-W10-D15",
    "LIN-LAT-CNT-T50-W20-D15", "LIN-LAT-TIM-T50-W20-D15",
    "LIN-LAT-CNT-T70-W10-D15", "LIN-LAT-TIM-T70-W10-D15",
    "LIN-LAT-CNT-T50-W5-D30",  "LIN-LAT-TIM-T50-W5-D30",
    "LIN-LAT-CNT-T50-W10-D30", "LIN-LAT-TIM-T50-W10-D30",
    "LIN-LAT-CNT-T50-W20-D30", "LIN-LAT-TIM-T50-W20-D30",
    "LIN-LAT-CNT-T70-W10-D30", "LIN-LAT-TIM-T70-W10-D30"
  ],
  "sidecar_baseline": {
    "path": "data/audit/sidecar_baseline_73.jsonl",
    "lines": 73,
    "sha256": "ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e"
  },
  "smoke": {
    "experiment_id": "LIN-LAT-CNT-T30-W5-D5",
    "replicate": 1,
    "dataset_path": "data/phase4b_smoke.csv",
    "poll_path": "data/audit/phase4b_smoke_poll.jsonl"
  },
  "sweep_window": {
    "start": "<UTC ISO of the first run's fault_injected_at, or launch time>",
    "end":   "<UTC ISO when the sweep finished>"
  },
  "gateway_image_repo": "infra-gateway-service",
  "gateway_container": "gateway-service",
  "gateway_image_id": "<docker image inspect infra-gateway-service --format '{{.Id}}' at launch>",
  "gateway_image_created": "<its .Created>",
  "onedrive_sync": "paused for the duration of the run"
}
```

---

## 8. Gateway image check (performed 2026-09-20)

Procedure from `phase4a-recollection-plan.md` §5, with the force-rebuild done and the
comparison by full image ID (prefix-compatible: the recorded IDs are full `sha256:…` digests,
and `docker images`' short ID is a prefix of them).

| step | result |
|---|---|
| Force-rebuild | `docker compose -f infra/docker-compose.yml build --no-cache gateway-service` → exit 0 |
| Image before | `sha256:bdc2fff79e7538f4c783ba61767edab5e63d3513806e0cd22ceab75603e1c2e3`, created `2026-09-19T18:48:16Z` |
| Image after | **`sha256:406bc2359f119874a8e347e6741fa37198cbc946961d59d34e89c2f2d780a35c`**, created **`2026-09-19T22:14:43Z`** |
| `docker inspect gateway-service --format '{{.Image}}'` | `sha256:bdc2fff7…` — the **old** image |
| Match? | **NO — and this is expected, not a failure.** |

**What the mismatch means.** `build` produces a new image; it does not touch containers. The
`gateway-service` container is currently `Exited (255)` and still references the pre-rebuild
image. This is precisely the state `phase4a §5` step 4 exists to catch — the
`master_dataset_v3_gateway_not_rebuilt.csv` failure mode, which has already cost this project
one dataset.

**It is resolved by GO-SMOKE step 4**, `docker compose -f infra/docker-compose.yml up -d
--build`, which recreates the container onto the current image. Re-run the two commands
immediately after that and confirm they are equal **before** the smoke run:

```bash
docker image inspect infra-gateway-service --format '{{.Id}}'
docker inspect gateway-service --format '{{.Image}}'
```

Record the agreed ID as `gateway_image_id` in the §7 manifest. Note that the rebuild was
`--no-cache`, so the new image ID differs from the old one even though the source tree is
unchanged — an image ID is not a content hash of the source.

**Image age vs source commit.**

| | |
|---|---|
| Last commit touching `services/gateway-service` | `d1c6a4817e87db14ed2d358ec0c5a1bcc5b334eb`, `2026-09-18T13:20:50+05:30` (= `2026-09-18T07:50:50Z`) — *"fix(D25): pin gateway's measurement-plane config explicitly"* |
| New image `.Created` | `2026-09-19T22:14:43Z` |
| Verdict | image is **~1.6 days newer** than the last source commit, and the working tree is clean at that commit, so the image is consistent with having been built from `d1c6a481` (the D25 pin) |

**Docker images carry no commit label** — `services/gateway-service/Dockerfile` sets no
`LABEL org.opencontainers.image.revision` and the runner emits no `git_commit` column — so
"image `.Created` is later than the last commit touching the service, on a clean tree" is the
**best available evidence** that the image contains the D25 pin. It is not proof. Making it
proof would mean adding a build-arg commit label, which is a harness change and out of scope
for this launch.

---

## 9. Correction to the Phase 1 canary README (recorded here because `data/` is gitignored)

`data/audit/canary_2026-09-20/README.md` claimed that TIME at W=5 could not be run because
`--mode full`'s output path is hardcoded to `data/master_dataset.csv`. **That was wrong.**

1. `runner.py:33` reads `DATASET_PATH_OVERRIDE`, and `get_dataset_path("full")` returns the
   overridden `DATASET_PATH` (`runner.py:1040-1049`). A `--mode full` run with the override
   set would have reached any config in the 54-cell grid while leaving `master_dataset.csv`
   untouched. The override is documented in CLAUDE.md's own footgun list.
2. A TIME_BASED **W=5** config was not absent from canary mode either: `LIN-LAT-TIM-T30-W5-D5`
   is the second of canary mode's five configs (`runner.py:1505`). What is absent is the
   specific ID `LIN-LAT-TIM-T70-W5-D30`, not the window size.

**The claim that stands: TIME_BASED at W=5 was not gateway-checked in Phase 1.** The deviation's
*rationale* is unaffected — the gateway is pinned `TIME_BASED`/600 s regardless of the swept
window — but the stated *blocker* was false.

The README was corrected in place, appended-not-rewritten style, and its hash recomputed:

| | sha256 |
|---|---|
| `data/audit/canary_2026-09-20/README.md`, before | `aa8a4bb768fd8165b706c4c0983b67a571aa97df824b42faf813c574ce713bde` |
| `data/audit/canary_2026-09-20/README.md`, **after** | **`1a8be6e7ed648d5b29cd0aafac5f6f3a45c73172f17c48046cdec114778880e3`** |

`data/audit/canary_2026-09-20/SHA256SUMS.txt` was updated with the new hash; the other six
entries are unchanged and all still verify. (That file mixes two path conventions — the README
line is repo-root-relative while the rest are bare filenames — so `sha256sum -c` must be run
twice, once from the repo root and once from inside the directory. That predates this change
and was left as-is.)
