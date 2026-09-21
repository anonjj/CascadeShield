# Phase 4B — launch manifest

The frozen launch record: what will be run, with which inputs, and what must be true first.

**Status: the smoke run (Part B) was executed on 2026-09-20 under GO SMOKE and PASSED every
gate — see §10.** The 72-run sweep has **not** been launched and is a separate approval.

§1-§9 were written before any run and are left as written; §10 records what actually happened,
including where the pre-launch figures in §1 were superseded by the values measured at GO SMOKE.

---

## 0. Frozen artifacts

| artifact | value |
|---|---|
| Pre-registration, **superseded** | `8f1623b`, then `34bfda7` — both superseded on 2026-09-20, **before any run** |
| Pre-registration, **FINAL** | **`3e4ad1e5d0596883bbd35604828d0d2db39a9eb2`** |
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

The analytic rules are frozen as of `3e4ad1e`. Any later change is reported as a deviation,
never edited in.

Two amendments were made on 2026-09-20, both before any run. `8f1623b` → `34bfda7` added the
lambda gate (§9), quarantine/re-collection (§10) and the poller duty cycle (§11).
`34bfda7` → `3e4ad1e` added:

| new | what it fixes |
|---|---|
| **§3.2** censoring sensitivity | the primary rule (drop censored replicates) biases config means **downward**; the sensitivity imputes each at `3*wait+60` and both are reported |
| **§5.1** horizon fallback | a null `time_to_recover` used to collapse the horizon to `cleared + 5 s`; it now falls back to `3*wait+60` |
| **§9.1** lambda instrument | `lambda_achieved` is **2.3x-3.9x noisier in the COUNT arm** — 39-59 intervals over 4-6 s vs 199-599 over 20-60 s |
| **§9.2** exclusion reporting + margin | per-arm exclusion counts before any p-value; a no-lambda-exclusion sensitivity fires at **>10 pp** between arms, or **>20%** in either |
| **§10.1** re-collection cap | at most **2 re-attempts** per key; every attempt counted; a key past the cap stays excluded |

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
| `git rev-parse HEAD` | `3e4ad1e` at the time of writing | re-read at launch; it moves |
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
> a full image rebuild mid-sweep is not. `docker builder prune` would reclaim ~15 G but was
> **declined** (§2.0), so the sweep launches with this margin. Re-check `df -h .` at launch.

> **RAM.** 2.96 G free is measured with the mesh **down**. Bring the mesh up and re-check
> before GO SMOKE; if the JVMs swap, `time_to_recover` is measuring the host, not the breaker.
> **Superseded by §10:** at GO SMOKE this read 4.38 G free with the mesh down and **1.28 G free
> (90.8 % used) with the mesh up**. Disk read 30 G free, not 27 G.

---

## 2. Smoke run (Part B — requires "GO SMOKE")

### 2.0 Decisions carried in from the Part A review (2026-09-20)

| decision | status |
|---|---|
| Smoke writes to `data/phase4b_smoke.csv`, not the sweep file | **approved** |
| `docker builder prune` | **skipped** — launching with ~27 G free; re-check `df -h .` at launch |
| Dummy-job survival test | **PASSED** (closed-window test only; no logout/lock/suspend variant was run, so job survival is established against *closing the terminal* and nothing stronger) |

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

## 3. The 72-run sweep — launch commands (NOT LAUNCHED)

**Nothing below has been run.**

**The launch path is `docs/paper/phase4b_launch.sh` (tracked), not these commands by hand.**
It runs assertions **a-k** (§3.7) and starts nothing unless every one passes. From your own
Git Bash window, at the repo root:

```bash
bash docs/paper/phase4b_launch.sh --check-only   # assertions only; starts nothing
bash docs/paper/phase4b_launch.sh                # assertions, then launch
```

`--check-only` writes nothing at all — no manifest, no timestamp, no log — and starts and
stops no service. The full run writes the manifest, then starts the poller, then the memory
logger, then the sweep, in that order, and records the real Windows `python.exe` PIDs in
`data/audit/phase4b_pids.txt`.

§3.0-§3.4 below describe the same actions the script performs, kept for review so the script
can be read against an independent statement of what it is supposed to do. §3.5 is the
first-run check, which is **not** part of the script — it is done by hand after launch.

### 3.0 Re-confirm the start state (read-only, 10 seconds)

```bash
cd /c/Users/Lenovo/OneDrive/Desktop/CascadeShield

git rev-parse HEAD; git status --porcelain
sha256sum data/cb_transitions.jsonl          # must be ffad69d6...bee0e
wc -l     data/cb_transitions.jsonl          # must be 73
ls data/phase4b_postd25.csv data/audit/phase4b_poll.jsonl 2>&1   # both must be absent
df -h .                                                          # free space
docker ps --format '{{.Names}}\t{{.Status}}' | wc -l             # expect 11
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/v1/linear   # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8474/proxies         # expect 200
docker image inspect infra-gateway-service --format '{{.Id}}'
docker inspect gateway-service --format '{{.Image}}'   # must equal the line above
```

### 3.1 Copy the ID list in and verify it

```bash
cp docs/paper/phase4b_only_ids.txt data/phase4b_only_ids.txt
sha256sum docs/paper/phase4b_only_ids.txt data/phase4b_only_ids.txt
#   both must be 6d6e57452ba56e814cb525d1a0f48c7b6c198830f7d8296a6bf856f2e36a0f12
cmp docs/paper/phase4b_only_ids.txt data/phase4b_only_ids.txt && echo "byte-identical"
```

### 3.2 Write the launch manifest JSON

Fill §7's template into `data/audit/phase4b_manifest.json`. The values established by the
smoke run:

```json
  "git_head":           "<git rev-parse HEAD, re-read now>",
  "preregistration_sha": "3e4ad1e5d0596883bbd35604828d0d2db39a9eb2",
  "gateway_image_id":   "sha256:ce110c0a0bfbc290e735fe810f4bb5a60b2ef84ad5e63c0b627a0b90cecbabfc",
  "poll_path":          "data/audit/phase4b_poll.jsonl",
  "audit_dir":          "data/audit",
  "sweep_window": { "start": "<UTC ISO, just before launch>", "end": "<UTC ISO, after it finishes>" }
```

Re-read `gateway_image_id` from `docker image inspect` rather than pasting it, in case the
image has been rebuilt since.

### 3.3 Start the poller — FIRST, and leave it running for the whole sweep

*(The script does this, with the liveness check of §3.3 built in: it starts the poller, waits
5 s, confirms a real `python.exe` PID exists, confirms the log is non-empty, waits 3 s more
and confirms the line count is still increasing — alive **and** logging, not merely alive.)*

Pre-registration §11 requires **one continuous session** across all 72 runs. Start it before
the sweep, stop it after the last run, and do not restart it in between.

```bash
mkdir -p data/audit logs

nohup python -u analysis/gateway_poll_verify.py poll \
  --base http://localhost:8080 \
  --out  data/audit/phase4b_poll.jsonl \
  --interval 1.0 --label phase4b \
  > logs/phase4b_poller.log 2>&1 &
echo $! > data/audit/phase4b_poller.shellpid
disown
```

Confirm it is ticking before going further:

```bash
sleep 5; wc -l data/audit/phase4b_poll.jsonl     # expect >= 5 and growing
tail -1 data/audit/phase4b_poll.jsonl            # states should all read CLOSED
```

> **Stopping it afterwards — established empirically during the smoke (§10).** On this host
> `kill -INT` against the shell job PID does **not** reach the Python process, and
> `taskkill /PID <pid>` is refused (*"can only be terminated forcefully"*). What works:
>
> ```bash
> PID=$(powershell -NoProfile -Command "Get-CimInstance Win32_Process | \
>   Where-Object { \$_.CommandLine -like '*gateway_poll_verify*poll*' -and \$_.Name -like 'python*' } | \
>   Select-Object -ExpandProperty ProcessId")
> echo "poller PID: $PID"
> powershell -NoProfile -Command "Stop-Process -Id $PID -Force"
> ```
>
> A forced stop skips the poller's `finally` block, so **no `poller_stop` marker is written**.
> `check_run()` handles this — it falls back to the last tick — and the smoke run still
> verified clean. If you would rather have the clean marker, run the poller **in the
> foreground in a second Git Bash window** instead of the `nohup` form above, and press
> Ctrl-C when the sweep finishes. Either is acceptable; the foreground form is tidier.

### 3.4 Launch the sweep, detached

```bash
export DATASET_PATH_OVERRIDE=data/phase4b_postd25.csv

nohup python -u experiments/runner.py \
  --mode full \
  --fault latency \
  --topology linear \
  --only-ids data/phase4b_only_ids.txt \
  --replicates 3 \
  --seed 20260920 \
  --machine-id soham-local \
  > logs/phase4b_sweep.log 2>&1 &
echo $! > data/audit/phase4b_sweep.shellpid
disown
```

`export` must be in the **same shell** as the `nohup` line — `DATASET_PATH_OVERRIDE` is read
at `runner.py` import time (`runner.py:33`), and CLAUDE.md records that a missed override has
misfiled data twice.

### 3.5 First-run check — do this ~5 minutes after launch, before walking away

```bash
# 1. the output file exists and the header is the runner's own 38 columns
ls -la data/phase4b_postd25.csv
head -1 data/phase4b_postd25.csv | tr ',' '\n' | wc -l          # expect 38

# 2. exactly one data row so far, and it is one of the 24 IDs
wc -l data/phase4b_postd25.csv                                  # expect 2 after run 1
cut -d, -f1 data/phase4b_postd25.csv | tail -n +2 | sort -u
grep -f - -c docs/paper/phase4b_only_ids.txt <<< "$(cut -d, -f1 data/phase4b_postd25.csv | tail -n +2 | sort -u)"

# 3. the sidecar grew by exactly the number of completed runs
wc -l data/cb_transitions.jsonl                                 # expect 73 + completed runs
tail -1 data/cb_transitions.jsonl | python -m json.tool | head -12
#    machine_id must be soham-local, mode must be full

# 4. the poller is still alive and clean
wc -l data/audit/phase4b_poll.jsonl
grep -c '"ok": false' data/audit/phase4b_poll.jsonl             # errors are expected ONLY in
                                                                # container-recreate windows
python - <<'EOF'
import json
ticks=[json.loads(l) for l in open("data/audit/phase4b_poll.jsonl",encoding="utf-8") if l.strip()]
bad=[(t.get("iso"),b,s) for t in ticks if "_meta" not in t
     for b,s in (t.get("states") or {}).items() if s and s!="CLOSED"]
print("non-CLOSED gateway observations:", len(bad), bad[:5])
EOF
#    this must print 0. Anything else is a gateway trip -> stop and report.

# 5. progress and no silent stall
python -c "import json;d=json.load(open('data/run_status.json'));print(d['phase'],d['success_runs'],'/',d['total_runs'],d['updated_at'])"
tail -5 logs/phase4b_sweep.log

# 6. reconcile, dry run -- every row written so far has a matching record
python analysis/phase4b_reconcile.py \
  --dataset data/phase4b_postd25.csv \
  --transitions data/cb_transitions.jsonl \
  --machine-id soham-local --mode full
#    expect MATCHED == rows so far, ORPHAN_ROW 0, DUPLICATE_KEY 0, AT_REATTEMPT_CAP 0.
#    ORPHAN_RECORD will read 73 -- that is the untouched baseline, not a problem; the
#    post-sweep check skips the baseline prefix and only scores records after it.
```

**Stop and report if any of these is true:** the file did not appear within ~2 minutes; the
header is not 38 columns; an `experiment_id` appears that is not in the 24; the sidecar did not
grow; the poller died; any non-CLOSED gateway observation; `run_status.json` stops advancing
for more than ~10 minutes.

### 3.6 While it runs

Do not touch `data/phase4b_postd25.csv`, `data/cb_transitions.jsonl` or the poll log. Do not
start a second runner. Do not run `phase4b_reconcile.py --apply` — it will refuse anyway while
`run_status.json` reads `phase=running`.

### 3.7 What the launch script asserts (a-k)

All ten run **before anything is started**. The first failure aborts with a message naming
what was expected and what was found, and the script states that nothing was started, no
manifest was written and no file was changed.

| | assertion | abort condition |
|---|---|---|
| **a** | HEAD full SHA printed; `git status --porcelain` empty | any dirty path |
| **b** | `3e4ad1e5d0596883bbd35604828d0d2db39a9eb2` exists, **is an ancestor of HEAD** (`git merge-base --is-ancestor`), **and** `git diff --quiet 3e4ad1e… HEAD -- docs/paper/h3-postd25-analysis-plan.md` | the commit is missing, not an ancestor, or the plan file has changed since it |
| **c** | sidecar sha256 `ffad69d6…bee0e`, exactly 73 lines | either differs |
| **d** | `data/phase4b_postd25.csv` and `data/audit/phase4b_poll.jsonl` **absent** | either exists — the poller appends, so an old log would be silently merged |
| **e** | sha256 of `docs/paper/phase4b_only_ids.txt` == `6d6e5745…a0f12` (hard-coded), 24 unique IDs, replicates 3, expected_runs 72, and `data/phase4b_only_ids.txt` byte-identical | any mismatch, or the `data/` copy missing |
| **f** | `docker image inspect infra-gateway-service .Id` == `docker inspect gateway-service .Image`; image `.Created` **later than** the newest commit touching its source paths | IDs differ, or `.Created` is **older** than that commit. A missing commit label is **not** an abort |
| **g** | gateway `GET /api/v1/linear` == 200; Toxiproxy admin `/proxies` lists exactly the 5 expected, all `enabled`, `toxics` empty | non-200, wrong proxy set, any disabled proxy, any attached toxic |
| **h** | `prometheus` and `grafana` **not running**; the six application services plus `postgres` and `dynamodb-local` running and `healthy` | either observability container running, or any required container not running/healthy |
| **i** | free physical RAM ≥ 1500 MB (**median of 5 samples**), free disk ≥ 15 GB, power not positively "on battery" | median below the floor, disk below the floor, or `Win32_Battery.BatteryStatus == 1` |
| **j** | no `gateway_poll_verify`, `phase4b_mem_log` or `experiments/runner.py` **`python.exe`** process already running | any match |
| **k** | the three scripts the full run starts all exist; `data/audit` and `logs` exist and are **writable** (proved with a probe file); every output path (`$MANIFEST`, `$PIDFILE`, `$POLL_LOG`, `$MEM_LOG`, `$SWEEP_LOG`, `$POLLER_LOG`) is in a writable directory; `python -c "import json"` works | any missing script, any unwritable path |

**k was added on 2026-09-21** to satisfy the order rule — *anything that can fail must fail
before the poller starts*. Without it, a launch could reach "sweep running" and then die
because `data/audit` was not writable, stranding three live processes.

Four of these need their scope stated precisely rather than assumed:

* **f — provenance is evidence, not proof.** Docker images carry no commit label here:
  `services/gateway-service/Dockerfile` sets no `LABEL org.opencontainers.image.revision` and
  the runner emits no `git_commit` column, and Dockerfile/compose edits are not permitted. So
  the script checks the only thing available — that the image was built *after* the newest
  commit touching everything it is built from. The `COPY` lines of that Dockerfile are
  `cascadeshield-parent/pom.xml`, `services/gateway-service/pom.xml` and
  `services/gateway-service/src`, so the paths checked are **`services/gateway-service`** (which
  also covers the Dockerfile itself) and **`cascadeshield-parent/pom.xml`**. Both timestamps are
  printed and the result is labelled *best available evidence, not proof*. A missing label never
  aborts; an image older than its source does.
* **g — what each check actually tests.** `GET /api/v1/linear` == 200 tests that *the gateway
  process answers its LINEAR route*. It does not test any downstream breaker state and does not
  test Toxiproxy. The `/proxies` check tests *the Toxiproxy admin API's view of proxy
  configuration* — the five expected names, each enabled, each with an empty `toxics` array. It
  does not send traffic through a proxy and does not prove a downstream service is reachable. No
  other URL is invented.
* **i — why the RAM gate is a median.** A single instantaneous reading is not usable on this
  host: six readings 10 s apart during preparation ranged **1334.3 – 1944.6 MB**, so one sample
  could pass or fail at random. The gate is the **median of five** samples taken 2 s apart; the
  **min and max are always printed** so the volatility stays visible, and a minimum below the
  floor is reported as a note rather than silently swallowed. If you would rather gate on the
  minimum, that is a one-word change in `analysis/phase4b_mem_log.py` — say so and it becomes a
  recorded deviation.

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

**The re-attempt cap (§10.1) is enforced here.** `phase4b_reconcile.py` derives each key's
attempt number from the `data/audit/phase4b_orphans_*.csv` files — one quarantine event per
file — and prints it next to every row it would quarantine. A key that has already used its
**2 re-attempts** is classified `AT_REATTEMPT_CAP`, is **not** quarantined, and its row is left
in the CSV so `load_completed()` keeps skipping it.

> **Watch the one case that is not self-enforcing.** If a capped key's row has
> `precondition_ok != True`, leaving it in place does **not** stop a resume retrying it —
> `load_completed()` only skips `True` rows. The reconciler prints an explicit OPERATOR ACTION
> warning for exactly these rows. Stop resuming that sweep, or report the extra attempts as a
> deviation. Do not edit the dataset to work around it.

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
| 4 | all 72 rows reconcile **one-to-one** with an in-scope record; zero orphan rows, zero orphan records, zero keys at the re-attempt cap |
| 4b | **no key exceeded 2 re-attempts** (§10.1), and the full attempt ledger is printed *whether or not* the gate fires — the re-collection count is required output, not just a tripwire |
| 5 | all 72 rows have `precondition_ok == True` |
| 6 | **no gateway `CLOSED_TO_OPEN`** in any in-scope record |
| 7 | **poller coverage per run**: every run `VERIFIED_CLEAN` under the pre-registered §5 horizon and §6 verdict rule, with `POLL_ERROR` / `MISSING_TICK` / `GATEWAY_NOT_CLOSED` / `POLLER_STOPPED` reported separately. A missing poll log is reported as UNVERIFIED, which the plan treats as `NOT_VERIFIED`, not as clean. Runs with a **null `time_to_recover`** use the §5.1 `3*wait+60` fallback horizon and are counted and flagged |
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
5. **Free disk.** Currently **27 G**. `docker builder prune` was **declined** (§2.0), so the
   17.8 G build cache stays. Re-check `df -h .` at launch, and re-check free RAM with the mesh
   **up**, not down — 2.96 G free was measured with it down.
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

   **Status: PASSED** (2026-09-20) — the job survived the window closing. Scope of that
   result, stated precisely: it establishes survival against **closing the terminal only**.
   It says nothing about a logout, a lock-screen suspend, or the S0 low-power idle state this
   machine supports, none of which were tested. Item 2 is still the binding risk.

---

## 7. Manifest JSON (consumed by the post-sweep check)

Write this to `data/audit/phase4b_manifest.json` **at launch**, with the run-time fields
filled in. `sidecar_baseline_struct_sha256` is optional; omit it to skip gate 3b.

```json
{
  "git_head": "<git rev-parse HEAD at launch>",
  "preregistration_sha": "3e4ad1e5d0596883bbd35604828d0d2db39a9eb2",
  "preregistration_superseded": ["8f1623b", "34bfda7"],
  "machine_id": "soham-local",
  "mode": "full",
  "fault": "latency",
  "topology": "linear",
  "replicates": 3,
  "seed": 20260920,
  "dataset_path": "data/phase4b_postd25.csv",
  "transitions_path": "data/cb_transitions.jsonl",
  "poll_path": "data/audit/phase4b_poll.jsonl",
  "audit_dir": "data/audit",
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

---

## 10. Smoke run record — 2026-09-20 (PASSED)

Run under GO SMOKE. Every gate passed; nothing was stopped early. Evidence quarantined under
`data/audit/smoke_20260919T235235Z/` (gitignored), hashes below.

### Gate results

| # | gate | result |
|---|---|---|
| 1 | preflight recorded | PASS — see below |
| 2 | sidecar baseline `ffad69d6…bee0e`, 73 lines | **PASS** |
| 3a | `up -d --build`, Toxiproxy 5 proxies, `GET /api/v1/linear` == 200 | **PASS** (200 in 2 s; all 6 services UP) |
| 3b | `docker image inspect .Id` == `docker inspect gateway-service .Image` | **PASS** — both `sha256:ce110c0a0bfb…cbabfc`; short ID `ce110c0a0bfb` is a prefix of it |
| 4 | 3 gateway breakers CLOSED at 100.0 / 100.0 while the container env carries swept `CB_*` | **PASS** — see the readback below |
| 5 | poller detached, smoke run once, poller stopped | **PASS** — 194 ticks over 210.1 s |
| 6a | header 38 cols == `runner.DATASET_HEADERS`; `wc -l` == 2 | **PASS** |
| 6b | sidecar exactly 74 records | **PASS** |
| 6c | new record matches the CSV row (`phase4b_reconcile.py`, dry run) | **PASS** — `MATCHED 1`, 0 orphan rows, 0 duplicates, 0 capped |
| 6d | poller coverage clean over the pre-registered §5 horizon | **PASS** — `VERIFIED_CLEAN`, 19 ticks, 0 uncovered s, no issues |
| 6e | no gateway `CLOSED_TO_OPEN` | **PASS** — 0 gateway transitions of any kind; 0 non-CLOSED gateway states across all 194 ticks |
| 6f | lambda reported against the frozen two-sided rule | **PASS** — reported, threshold not touched |
| 7 | quarantine, restore, start state | **PASS** |

### Gate 4 readback — the D25 pin, verified live on `ce110c0a`

Gateway container env (swept, from `infra/.env`) vs what the gateway breakers actually report:

```
CB_FAILURE_RATE_THRESHOLD=70      CB_SLIDING_WINDOW_TYPE=TIME_BASED
CB_SLIDING_WINDOW_SIZE=20         CB_WAIT_DURATION_OPEN=30s
CB_MINIMUM_CALLS=5                CB_PERMITTED_CALLS_HALF_OPEN=5
CB_EVENT_BUFFER_SIZE=5000

gateway   orderServiceCB      state=CLOSED  failureRateThreshold=100.0%  slowCallRateThreshold=100.0%
gateway   inventoryServiceCB  state=CLOSED  failureRateThreshold=100.0%  slowCallRateThreshold=100.0%
gateway   paymentServiceCB    state=CLOSED  failureRateThreshold=100.0%  slowCallRateThreshold=100.0%

order     inventoryServiceCB  state=CLOSED  failureRateThreshold= 70.0%  slowCallRateThreshold= 70.0%
order     sharedDbCB          state=CLOSED  failureRateThreshold= 70.0%  slowCallRateThreshold= 70.0%
```

The downstream readback is the control: the swept `70` **is** live in `order-service`, so the
gateway's `100.0` is the `measurement-plane` pin winning over a present env var — not an env
var that failed to arrive.

### Gate 6f — lambda, reported, threshold untouched

| | |
|---|---|
| `lambda_target` | 10.0000 |
| `lambda_achieved` | **9.1639** |
| ratio achieved/target | **0.9164** |
| `|achieved − target| / target` | **0.0836** (8.36 %) |
| `lambda_cv` | 0.0142 |
| frozen rule (§9, `3e4ad1e`) | 0.15 two-sided → retain iff `0.85 ≤ ratio ≤ 1.15` |
| `lambda_deviation_flag` | `False` — **not** excluded |

The threshold was **not** adjusted, per §9. One observation is not a variance estimate and
sets no expectation for the sweep.

### Gate 6d/6e detail, and a live check of §11

The §5 horizon for this run was `2026-09-19T23:49:37Z` + **18.8 s**
(`fault_cleared_at` + `time_to_recover` 6.774 s + 5 s). `time_to_recover` was measured, so the
§5.1 fallback was not exercised.

The poller logged **39 error ticks** and two gaps over 2 s (8.169 s, 8.182 s), all between
`23:48:15Z` and `23:49:08Z` — the `update_containers()` recreate window, when the gateway JVM
is down. **Zero of them fall inside the run horizon**, where coverage was 19 ticks and
0 uncovered seconds. That is the §11 prediction confirmed on real data rather than argued.

The sidecar record for the run contains a complete interior lifecycle and no gateway events:

```
order / inventoryServiceCB   CLOSED_TO_OPEN        23:49:41.092Z
order / inventoryServiceCB   OPEN_TO_HALF_OPEN     23:49:46.093Z
order / inventoryServiceCB   HALF_OPEN_TO_CLOSED   23:49:49.426Z
```

### Preflight values recorded at GO SMOKE

| item | mesh down | mesh up |
|---|---|---|
| `git rev-parse HEAD` | `534d3700b57e44696654287e308a40ee671a04b6`, tree clean | — |
| Free RAM | 4.38 G of 13.84 G | **1.28 G of 13.84 G (90.8 % used)** |
| Disk `C:` | 30 G free (88 % used) | — |
| Docker | 17 images, 11 containers, build cache 18 G | 11 containers healthy |
| `STANDBYIDLE` | 0 (never) on AC and DC | — |
| `HIBERNATEIDLE` | 0 (never) on AC; `0x7fffffff` (never) on DC | — |
| `LIDACTION` | **no setting index returned** — this setting is hidden on this machine and was not verifiable | — |
| OneDrive | process not running (sync stopped) | — |

> **Free RAM with the mesh up is 1.28 G (90.8 % used).** This is the thinnest resource at
> launch and it was not measurable before the mesh came up. Six JVMs plus Prometheus and
> Grafana on 13.84 G leaves little headroom for a 4.3 h sweep; if the host starts paging,
> `time_to_recover` measures the host rather than the breaker. Stopping Grafana and Prometheus
> would free headroom and costs nothing measurable — CLAUDE.md records that the dataset comes
> from `runner.py` polling `/actuator/metrics` directly and never touches Prometheus. That is
> a change to the running mesh, so it is **not** done here.

### Quarantine — `data/audit/smoke_20260919T235235Z/`

| file | sha256 |
|---|---|
| `phase4b_smoke.csv` | `3ce2acb1d36158df9786d4adcc7aa4786fae35e0abad37fab370bdde2ae45682` |
| `cb_transitions_post_smoke_74.jsonl` | `caa068c08ed32f75050e1d39510985a86339720741fadbe57e4fb3dfd2bfabbc` |
| `smoke_sidecar_record.jsonl` | `fd971b4b7709898a33a1ac92859fcf4b9095fe547534a6432b6a0ee82d22dbb6` |
| `phase4b_smoke_poll.jsonl` | `282a4f65024116dcaed7a6c5ee0437d5bd1a2484b6dcbac664a08e7d92ac72d2` |
| `phase4b_smoke_ids.txt` | `35aa1a330cc17c7cbbdb760b0aa851c7862ae693a7e49979f879bb64ce9e518d` |
| `infra_env_at_smoke.env` | `c1e24dfad2ff165f6ade1b515db3b0998b13978bcc10f0ed8e9eacd120c4d547` |

### Restore and sweep start state

`data/cb_transitions.jsonl` restored by copying `data/audit/sidecar_baseline_73.jsonl` back:
**`ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e`, 73 lines** — byte-identical
to the baseline. Nothing was hand-edited at any point.

| start-state assertion | |
|---|---|
| `data/phase4b_postd25.csv` absent | YES |
| `data/phase4b_smoke.csv` absent (preserved in quarantine) | YES |
| `data/audit/phase4b_poll.jsonl` absent | YES |
| sidecar at baseline, 73 lines | YES |
| no `data/audit/phase4b_orphans_*.csv` | YES |
| no poller process | YES (`runner_active()` → `False`) |
| no runner process | YES |
| `data/run_status.json` phase | `completed` |
| mesh | up, 11 containers healthy |
| gateway image | `sha256:ce110c0a0bfb…cbabfc`, container on the same image after the runner's own recreate |
| `infra/.env` | left at the smoke config (`T30/W5/D5/COUNT_BASED`); the runner rewrites it per run, so this is not a launch precondition |

**Record `"gateway_image_id": "sha256:ce110c0a0bfbc290e735fe810f4bb5a60b2ef84ad5e63c0b627a0b90cecbabfc"`
in the §7 manifest JSON at launch.** The image ID changed from the Part A value (`406bc235`)
when `up -d --build` re-exported it; the container now runs the same ID as the tag, which is
what gate 3b requires. The image's `.Created` is `2026-09-19T22:14:43Z`, later than the last
commit touching `services/gateway-service` (`d1c6a481`, `2026-09-18T07:50:50Z`) on a clean
tree — still the best available evidence, still not proof, for the reason §8 gives.

### Operational finding: stopping the poller on this host

`kill -INT` against the Git Bash job PID did **not** reach the Python process, and
`taskkill /PID <pid>` was refused (*"can only be terminated forcefully"*). Only
`Stop-Process -Force` worked, which skips the poller's `finally` block, so **no `poller_stop`
marker was written**. `check_run()` handles that — it falls back to the last tick when
`poll_stop` is `None` — and the run still verified clean. For the sweep, prefer the
foreground-in-its-own-window form in §11 so Ctrl-C produces a clean marker.

---

---

## 11. Stop commands

The launch script writes the real Windows `python.exe` PIDs to `data/audit/phase4b_pids.txt`:

```
# Phase 4B real Windows python.exe PIDs, launched 2026-...
poller=<pid>
mem_logger=<pid>
sweep=<pid>
```

Stop **by PID read from that file**. No `pkill`, no killing by name — this repo has three
python processes running at once and a name match would take the wrong one.

```bash
cd /c/Users/Lenovo/OneDrive/Desktop/CascadeShield
cat data/audit/phase4b_pids.txt

# stop the SWEEP
PID=$(grep '^sweep='      data/audit/phase4b_pids.txt | cut -d= -f2)
powershell -NoProfile -Command "Stop-Process -Id $PID -Force"

# stop the POLLER
PID=$(grep '^poller='     data/audit/phase4b_pids.txt | cut -d= -f2)
powershell -NoProfile -Command "Stop-Process -Id $PID -Force"

# stop the MEMORY LOGGER
PID=$(grep '^mem_logger=' data/audit/phase4b_pids.txt | cut -d= -f2)
powershell -NoProfile -Command "Stop-Process -Id $PID -Force"

# confirm each one is gone
powershell -NoProfile -Command "Get-Process -Id $PID -ErrorAction SilentlyContinue"
#   prints nothing when the process is gone
```

**Mechanism verified 2026-09-21** on a throwaway `python.exe` started and killed for the
purpose — never on a real job. The process reported `os.getpid()` = 6824, the
`Get-CimInstance Win32_Process` lookup returned the same 6824 (so the discovered PID is the
Python process, not a Git Bash wrapper), `Stop-Process -Id 6824 -Force` succeeded, and
`Get-Process -Id 6824` then returned nothing.

`Stop-Process -Force` is the only thing that works here: during the smoke run `kill -INT`
against the shell job PID did not reach the Python process, and `taskkill /PID <pid>` without
`/F` was refused with *"can only be terminated forcefully"* (§10).

### What a killed runner leaves behind

| artifact | state after a forced kill |
|---|---|
| `data/phase4b_postd25.csv` | every **completed** run's row is present and intact — `append_row()` does `flush()` + `fsync()` per row, so at most the row being written is lost |
| `data/cb_transitions.jsonl` | one record per completed run. A run killed mid-flight leaves **no** record, because `observer.log()` is reached only at the end of a completed run |
| the in-flight run | may leave a CSV row with **no** sidecar record (an `ORPHAN_ROW`), or no row at all |
| `data/run_status.json` | frozen at `phase=running` — it is never updated to "stopped". `phase4b_reconcile.py --apply` refuses while it reads `running` and is less than 15 minutes old; after that it says so and offers `--ignore-stale-status` |
| Toxiproxy | a toxic may still be attached if the kill landed inside the fault window. Assertion **g** catches this on the next launch (zero toxics required) |
| `infra/.env` | left at the killed run's config. The runner rewrites it per run, so this is not a launch precondition |
| containers | left running as they were; the runner recreates the six application services at the start of each run anyway |

**A killed poller or memory logger leaves no experimental artifact at all.** The poller's log
simply ends without a `poller_stop` marker, which `check_run()` handles by falling back to the
last tick.

### Resuming after a stop

Unchanged, per §4 and pre-registration §10: **stop the runner and confirm it is dead → run
`phase4b_reconcile.py` dry-run and read the orphan list → `--apply` to quarantine → resume
with the same `--seed 20260920` and the same `--only-ids`**. The same seed keeps the remaining
cells in the order the original shuffle assigned. Report how many keys were re-collected, by
class; the §10.1 cap of 2 re-attempts per key applies.

---

## 12. Observability plane: prometheus and grafana are STOPPED for this sweep

### Dependency check (read-only, 2026-09-21) — clean

Performed **before** stopping anything, because the smoke run passing is not evidence that
nothing depends on them.

| what was searched | result |
|---|---|
| `experiments/` and `analysis/gateway_poll_verify.py` for `prometheus`/`grafana`/`:9090`/`:3000` | only `analysis/gateway_poll_verify.py:80` and `:92` |
| `infra/docker-compose.yml` — every `depends_on` | only `grafana` → `prometheus` (line 88). **No application service depends on either.** `gateway-service`, `order-service`, `inventory-service`, `payment-service`, `notification-service` and `shared-db-service` depend only on `toxiproxy`, `postgres`, `dynamodb-local` and `shared-db-service` |
| healthchecks referencing them | none — neither `prometheus` nor `grafana` even defines a healthcheck |
| environment variables referencing them | none |
| repo-wide for port `9090` / `3000` | `infra/docker-compose.yml:71` (the port mapping) and `infra/grafana/provisioning/datasources/datasource.yml:7` (`http://prometheus:9090`, Grafana pointing at Prometheus — both stopped together) |

**`analysis/gateway_poll_verify.py:80` is not a dependency on the Prometheus server.** It does
`_get(base + "/actuator/prometheus")` where `base` defaults to `http://localhost:8080`
(`gateway_poll_verify.py:355`) — that is the **gateway JVM's own** Spring Boot actuator
endpoint, exposed by `services/gateway-service/.../application.yml:94`
(`include: health,prometheus,circuitbreakers,...`). Verified live with both containers stopped:
`GET http://localhost:8080/actuator/prometheus` returns `HTTP/1.1 200` and resilience4j
metrics. Port 8080 is `gateway-service`; the Prometheus server is 9090 and nothing in the
harness touches it. CLAUDE.md states the same: the dataset comes from `runner.py` polling each
service's `/actuator/metrics` directly and never touches Prometheus.

Every actuator URL in the harness targets `http://localhost:{8080..8085}` — the six Spring
Boot services (`runner.py:412`, `:760`, `:775`, `:873`; `breaker_observer.py:45`).

### The stop

```
docker compose -f infra/docker-compose.yml stop prometheus grafana
```

Stop only — no `rm`, no recreate. Executed **2026-09-21T04:54:16Z** (`2026-09-21T10:24:16+05:30`).
Both containers went to `Exited (0)`; the other nine were untouched and stayed `Up ... (healthy)`.

### What it actually changed — measured, not assumed

| | |
|---|---|
| Windows free physical RAM, before | **1967.1 MB** at `2026-09-21T10:24:06+05:30` |
| Windows free physical RAM, after | **1610.7 MB** at `2026-09-21T10:24:43+05:30` |
| naive delta | **−356.4 MB** |

**The Windows-visible figure went down, and that delta is not attributable to the stop.** Six
readings taken 10 s apart immediately afterwards ranged **1334.3 – 1944.6 MB** — a ~610 MB
swing with nothing changing — so a single before/after pair on this counter measures noise.
The reason is structural: Docker Desktop runs the containers inside a WSL2 VM
(`vmmemWSL`, 2472 MB working set), and WSL2 does not promptly return freed guest pages to
Windows.

Where the stop **did** help is inside that VM, which is where the six JVMs live:

```
docker info MemTotal            6848 MB visible to the Docker engine
remaining 9 containers          ~3411 MB total  (gateway 531, inventory 534,
                                 notification 526, order 514, payment 511,
                                 shared-db 519, dynamodb 232, postgres 31, toxiproxy 14)
headroom inside the VM          ~3.4 GB
```

So: **the honest claim is that ~2 containers' worth of VM memory was returned to the Docker
engine's budget, not that Windows gained free RAM.** The Windows-side gate (assertion **i**)
is satisfied on its own terms and is measured as a median of five samples for the reason above.

### The difference this creates between artifacts — recorded, not hidden

> **The Phase 1 canary (2026-09-20) and the smoke run (2026-09-20) were collected WITH
> prometheus and grafana running. This sweep is collected WITHOUT them.**
>
> Within this sweep the condition is **identical for all 72 runs** — both containers are
> stopped before the first run and stay stopped through the last — so it is a constant of the
> experiment and **cannot differ between the COUNT and TIME arms**. It is not a confound for
> the H3 comparison.
>
> It *is* a difference between this sweep and the earlier artifacts, and any comparison across
> them must state it. Assertion **h** re-checks it at launch, and the post-sweep check's
> manifest carries it in the `observability` field.

---

## 13. Memory logger (diagnostic only)

`analysis/phase4b_mem_log.py log --out logs/phase4b_mem.log --interval 30`, started by the
launch script after the poller and before the sweep. One line every 30 s:

```
2026-09-21T10:28:06+05:30 free_mb=1969.5
```

`logs/` is gitignored (`git check-ignore -v logs/phase4b_mem.log` → `.gitignore:64:logs/`), so
it cannot make the tree dirty. The sampler reads `GlobalMemoryStatusEx` via `ctypes` — the same
counter `Win32_OperatingSystem.FreePhysicalMemory` reports — with no dependency and no
subprocess per sample. It writes one header comment line beginning `#` recording the interval,
total RAM and its own PID; every other line is a sample in the format above.

> **It is not an exclusion rule and it changes no pre-registered rule.** Nothing it records may
> remove a run from the analysis, reweight one, or move any threshold in
> `docs/paper/h3-postd25-analysis-plan.md` (frozen at `3e4ad1e`). If it shows memory pressure
> during the sweep, that is **reported as a limitation** alongside the results, in the same way
> §8 already reports the database-state and single-machine limitations. It is evidence about
> the host, not about the breakers.

The launch script's RAM assertion (**i**) calls the same module's `sample` subcommand, so the
gate reading and the logged reading come from one implementation and cannot drift apart.

---

## 14. Defect found and fixed in `phase4b_launch.sh` — 2026-09-21

The first `--check-only` run printed `READY` and then:

```
docs/paper/phase4b_launch.sh: line 320: printf: --: invalid option
```

### Cause

`printf '----------------------------------------------------------------\n'` — bash's
`printf` **builtin** parses a leading `-` in its first argument as an option flag. The
separator was read as the option `--` followed by garbage, so `printf` returned 2.

**It was not cosmetic.** Under `set -e` a builtin returning non-zero aborts the script, so
the two lines after it — including `exit 0` — never ran:

```
$ bash repro.sh
 READY
repro.sh: line 3: printf: --: invalid option
printf: usage: printf [-v var] format [arguments]
EXIT=2
```

`--check-only` therefore **exited 2 while printing READY**. Anything checking the exit
status would have read a passing check as a failure, and the "nothing was started, nothing
was written" line never printed.

### All three occurrences, not just the reported one

| line | where | consequence if left |
|---|---|---|
| 320 | `--check-only` block, right after `READY` | the reported one: exit 2 instead of 0 |
| 329 | full run, immediately after the launch timestamp | **the full run would have aborted here every time** — before the manifest, before the poller. The launch path had never actually worked |
| 434 | full run, after the PID file is written | **the dangerous one**: poller, memory logger and sweep all running, PID file written, then abort with a printf error and exit 2. The operator sees a failure and cannot tell that the sweep is in fact running |

### Fix

One helper, used for every separator:

```bash
RULE="----------------------------------------------------------------"
rule() { printf '%s\n' "$RULE"; }
```

`printf '%s\n' "$RULE"` passes the dashes as an *argument*, which is never option-parsed.
The same treatment was applied to the two other places a `-`-leading string reached a
`printf`/`echo` first argument, and to `echo`-style usages generally: the script now has no
`printf`/`echo` whose first argument begins with `-`. A comment at the top of the file
records why, so it does not come back.

Verified: `grep -nE "^[[:space:]]*(printf|echo)[[:space:]]+('|\")-"` returns nothing.

### Full-run path review — other ways it could fail *after* something had started

Found and fixed in the same pass:

| risk | fix |
|---|---|
| `POLLER_PID="$(pypids X \| head -1)"` — `head` closes the pipe early; under `set -o pipefail` a SIGPIPE upstream makes the assignment non-zero and `set -e` aborts. Would have fired *after* a process was started | `pypids` no longer feeds a pipeline. New `capture_pid` reads the whole output into a variable and takes the first line with parameter expansion |
| `head -1` silently picked one PID if two matched, so the PID file could record a process this script did not start | `capture_pid` **dies on 0 or 2+ matches** and names them, rather than guessing |
| `$PIDFILE` write failing after all three processes were live | new assertion **k** proves every output directory writable before anything starts; the write also has an explicit `\|\| die` |
| `die` printed *"Nothing was started. No manifest written. No file changed."* even when the poller and memory logger were already running — a false statement at the worst moment | `die` now tracks what this invocation started (`STARTED`), **rolls it back in reverse order**, and prints what it stopped. It only claims "nothing was started" when that is true. Rollback touches only PIDs this script recorded — never a pre-existing process, never a container |
| the manifest heredoc was **unquoted**, so every captured value was shell-expanded into Python source. A quote or backslash in `$BATT` or `$IMG_CREATED` would have produced a syntax error — or worse, valid but wrong Python | values now pass through the **environment** into a **quoted** (`<<'PYEOF'`) heredoc; no shell expansion occurs inside the program at all |
| `FREE_MB_NOW` empty would have made the manifest `"free_mb_at_launch": ,` — a syntax error | validated against `^[0-9]+\.[0-9]+$` before use, with `\|\| die` |
| `iso_epoch` returning empty on an unparseable date silently became `0` in `[[ -lt ]]`, so a bad timestamp looked like "image older than source" — right answer, wrong reason | `iso_epoch` now returns non-zero on failure and assertion **f** dies with the unparseable value quoted |
| `$MANIFEST` already existing would have been silently overwritten, losing the previous launch's record | added to assertion **d** alongside the dataset and poll log |

Residual, and deliberately so: whether a process comes up at all, and whether the poller is
*logging* and not merely alive, can only be known after starting it. Those two cases are why
`die` rolls back instead of pretending nothing happened.

### Hashes

| | sha256 |
|---|---|
| `docs/paper/phase4b_launch.sh`, **defective** (commit `d6bd6f5`) | `c897d4f5701904bbc0780d68d85253c258e45c01cd38c622883ce25f7f5d4a8e` |
| `docs/paper/phase4b_launch.sh`, **fixed** | **`af6b9155e13c6f7c2bdccb368bd69455deb2a8cd814eab15fcb83abefdbc9ded`** |

`bash -n` clean; `--check-only` re-run ends with `READY` and exits 0.
