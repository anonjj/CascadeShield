#!/usr/bin/env bash
#
# Phase 4B sweep launcher.  Run from the repo root in Git Bash.
#
#   bash docs/paper/phase4b_launch.sh --check-only   # assertions a-j, then stop
#   bash docs/paper/phase4b_launch.sh                # assertions a-j, then launch
#
# --check-only runs the assertions and NOTHING else: it starts and stops no service,
# no poller, no memory logger and no runner; it writes no manifest, no sweep output,
# no sidecar change and no timestamp of any kind.  The only thing it writes is its own
# stdout.
#
# The poller, the memory logger and the sweep are started only after EVERY assertion
# has passed, in that order.  The first failing assertion aborts with a message naming
# what was expected and what was found.
#
# This script never starts, stops or restarts a container.  Bringing the mesh up, and
# stopping prometheus/grafana, are separate operator actions asserted here (h), not
# performed here.
#
set -euo pipefail

# ---------------------------------------------------------------- expected values
# Hard-coded on purpose.  These are the frozen launch inputs; if one of them has to be
# edited to make the script pass, that is a deviation and belongs in the report, not in
# this file.
PREREG_SHA="3e4ad1e5d0596883bbd35604828d0d2db39a9eb2"
PREREG_SUPERSEDED="8f1623b -> 34bfda7 -> 3e4ad1e"
PLAN_FILE="docs/paper/h3-postd25-analysis-plan.md"

SIDECAR="data/cb_transitions.jsonl"
SIDECAR_SHA="ffad69d6755c8a33e5d2b064a56354981a4fda82c742d642c0097abbf0dbee0e"
SIDECAR_LINES=73

IDS_SRC="docs/paper/phase4b_only_ids.txt"
IDS_DST="data/phase4b_only_ids.txt"
IDS_SHA="6d6e57452ba56e814cb525d1a0f48c7b6c198830f7d8296a6bf856f2e36a0f12"
EXPECTED_IDS=24
REPLICATES=3
EXPECTED_RUNS=72

SEED=20260920
MACHINE_ID="soham-local"
DATASET="data/phase4b_postd25.csv"
POLL_LOG="data/audit/phase4b_poll.jsonl"
MEM_LOG="logs/phase4b_mem.log"
MANIFEST="data/audit/phase4b_manifest.json"
PIDFILE="data/audit/phase4b_pids.txt"
SWEEP_LOG="logs/phase4b_sweep.log"
POLLER_LOG="logs/phase4b_poller.log"

GW_IMAGE="infra-gateway-service"
GW_CONTAINER="gateway-service"
# Every path the gateway image is built from, per services/gateway-service/Dockerfile:
# it COPYs cascadeshield-parent/pom.xml, services/gateway-service/pom.xml and
# services/gateway-service/src.  The Dockerfile itself lives under the first path.
GW_SOURCE_PATHS=("services/gateway-service" "cascadeshield-parent/pom.xml")

PROXIES=(inventory-service-proxy notification-service-proxy order-service-proxy
         payment-service-proxy shared-db-service-proxy)
APP_SERVICES=(gateway-service order-service inventory-service payment-service
              notification-service shared-db-service postgres dynamodb-local)
STOPPED_SERVICES=(prometheus grafana)

MIN_FREE_MB=1500
MIN_FREE_GB=15

CHECK_ONLY=0
[[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
if [[ -n "${1:-}" && "$1" != "--check-only" ]]; then
  echo "usage: bash docs/paper/phase4b_launch.sh [--check-only]" >&2; exit 2
fi

# ------------------------------------------------------------------------ helpers
PASS=0
ok()   { PASS=$((PASS+1)); printf '  [PASS] %s\n' "$*"; }
info() { printf '         %s\n' "$*"; }
die()  { printf '\n  [ABORT] %s\n' "$*" >&2
         printf '  Nothing was started. No manifest written. No file changed.\n' >&2
         exit 1; }
hdr()  { printf '\n%s\n' "$*"; }

# ISO-8601 (with or without fractional seconds, Z or +hh:mm) -> epoch seconds.
iso_epoch() {
  local s="$1"
  if [[ "$s" == *.* ]]; then s="${s%%.*}Z"; fi          # drop fractional seconds
  date -u -d "$s" +%s 2>/dev/null || date -d "$s" +%s
}

# Windows PIDs of python.exe processes whose command line matches $1.  Never matches
# the Git Bash wrapper: the Name filter restricts it to python.exe.
pypids() {
  powershell -NoProfile -NonInteractive -Command \
    "Get-CimInstance Win32_Process | Where-Object { \$_.Name -like 'python*' -and \$_.CommandLine -like '*$1*' } | Select-Object -ExpandProperty ProcessId" \
    2>/dev/null | tr -d '\r' | grep -E '^[0-9]+$' || true
}

printf '================================================================\n'
printf ' Phase 4B launch  --  %s\n' "$([[ $CHECK_ONLY -eq 1 ]] && echo 'CHECK ONLY (nothing will be started)' || echo 'FULL RUN')"
printf '================================================================\n'

# ------------------------------------------------------------------- a. repo state
hdr "a. Repo state"
HEAD_SHA="$(git rev-parse HEAD)"
info "HEAD                : $HEAD_SHA"
info "HEAD subject        : $(git log -1 --format='%s')"
DIRTY="$(git status --porcelain)"
[[ -z "$DIRTY" ]] || die "a: working tree is not clean. git status --porcelain returned:
$DIRTY"
ok "working tree clean (git status --porcelain empty)"

# -------------------------------------------------------------- b. pre-registration
hdr "b. Pre-registration $PREREG_SHA"
git cat-file -e "${PREREG_SHA}^{commit}" 2>/dev/null \
  || die "b: commit $PREREG_SHA does not exist in this repository"
git merge-base --is-ancestor "$PREREG_SHA" HEAD \
  || die "b: $PREREG_SHA is NOT an ancestor of HEAD ($HEAD_SHA). The pre-registration
     is not in this branch's history."
ok "$PREREG_SHA is an ancestor of HEAD"
git diff --quiet "$PREREG_SHA" HEAD -- "$PLAN_FILE" \
  || die "b: $PLAN_FILE has changed since $PREREG_SHA. The analytic rules are frozen.
     Run: git diff $PREREG_SHA HEAD -- $PLAN_FILE"
ok "$PLAN_FILE byte-identical to its state at $PREREG_SHA"
info "superseded chain    : $PREREG_SUPERSEDED"
info "plan blob at HEAD   : $(git rev-parse "HEAD:$PLAN_FILE")"

# ---------------------------------------------------------------------- c. sidecar
hdr "c. Sidecar baseline"
[[ -f "$SIDECAR" ]] || die "c: $SIDECAR is missing"
GOT_SHA="$(sha256sum "$SIDECAR" | cut -d' ' -f1)"
GOT_LINES="$(wc -l < "$SIDECAR" | tr -d ' ')"
info "sha256              : $GOT_SHA"
info "lines               : $GOT_LINES"
[[ "$GOT_SHA" == "$SIDECAR_SHA" ]] \
  || die "c: sidecar sha256 mismatch.
     expected $SIDECAR_SHA
     found    $GOT_SHA"
[[ "$GOT_LINES" == "$SIDECAR_LINES" ]] \
  || die "c: sidecar has $GOT_LINES lines, expected $SIDECAR_LINES"
ok "sidecar at the recorded baseline ($SIDECAR_LINES records)"

# ------------------------------------------------------------- d. outputs absent
hdr "d. Sweep outputs absent"
[[ ! -e "$DATASET" ]]  || die "d: $DATASET already exists. A previous sweep's output is
     in place. Reconcile and move it aside before launching (manifest section 4)."
[[ ! -e "$POLL_LOG" ]] || die "d: $POLL_LOG already exists. The poller appends, so an old
     log would be silently merged with this sweep's. Move it aside."
ok "$DATASET absent"
ok "$POLL_LOG absent"

# ---------------------------------------------------------------------- e. ID list
hdr "e. --only-ids list"
[[ -f "$IDS_SRC" ]] || die "e: $IDS_SRC is missing"
SRC_SHA="$(sha256sum "$IDS_SRC" | cut -d' ' -f1)"
info "sha256 $IDS_SRC : $SRC_SHA"
[[ "$SRC_SHA" == "$IDS_SHA" ]] \
  || die "e: $IDS_SRC sha256 mismatch.
     expected $IDS_SHA
     found    $SRC_SHA"
ok "tracked ID list matches the hard-coded expected sha256"
N_IDS="$(grep -c '^LIN' "$IDS_SRC" || true)"
N_UNIQ="$(grep '^LIN' "$IDS_SRC" | sort -u | wc -l | tr -d ' ')"
info "IDs                 : $N_IDS ($N_UNIQ unique)"
[[ "$N_IDS" == "$EXPECTED_IDS" && "$N_UNIQ" == "$EXPECTED_IDS" ]] \
  || die "e: expected $EXPECTED_IDS unique IDs, found $N_IDS ($N_UNIQ unique)"
ok "$EXPECTED_IDS unique experiment_ids"
[[ -f "$IDS_DST" ]] || die "e: $IDS_DST is missing. Copy it in first:
     cp $IDS_SRC $IDS_DST"
cmp -s "$IDS_SRC" "$IDS_DST" \
  || die "e: $IDS_DST is NOT byte-identical to $IDS_SRC"
ok "$IDS_DST byte-identical to the tracked copy"
info "replicates          : $REPLICATES"
info "expected_runs       : $EXPECTED_IDS x $REPLICATES = $EXPECTED_RUNS"
[[ $(( EXPECTED_IDS * REPLICATES )) -eq $EXPECTED_RUNS ]] \
  || die "e: $EXPECTED_IDS x $REPLICATES != $EXPECTED_RUNS"
ok "expected_runs = $EXPECTED_RUNS"

# ----------------------------------------------------------------- f. gateway image
hdr "f. Gateway image identity and provenance"
IMG_ID="$(docker image inspect "$GW_IMAGE" --format '{{.Id}}' 2>/dev/null)" \
  || die "f: no image named $GW_IMAGE. Build the mesh first."
CNT_ID="$(docker inspect "$GW_CONTAINER" --format '{{.Image}}' 2>/dev/null)" \
  || die "f: no container named $GW_CONTAINER. Bring the mesh up first."
info "docker image inspect .Id  : $IMG_ID"
info "docker inspect .Image     : $CNT_ID"
[[ "$IMG_ID" == "$CNT_ID" ]] \
  || die "f: the running container is NOT on the current $GW_IMAGE image.
     image     $IMG_ID
     container $CNT_ID
     This is the master_dataset_v3_gateway_not_rebuilt failure mode. Recreate the
     container onto the current image before launching."
ok "image .Id == container .Image"

IMG_CREATED="$(docker image inspect "$GW_IMAGE" --format '{{.Created}}')"
IMG_EPOCH="$(iso_epoch "$IMG_CREATED")"
info "image .Created            : $IMG_CREATED"
info "source paths checked (from services/gateway-service/Dockerfile COPY lines):"
NEWEST_EPOCH=0; NEWEST_DESC=""
for p in "${GW_SOURCE_PATHS[@]}"; do
  C_ISO="$(git log -1 --format='%cI' -- "$p")"
  C_SHA="$(git log -1 --format='%h' -- "$p")"
  info "  $p"
  info "      last commit $C_SHA  $C_ISO"
  if [[ -n "$C_ISO" ]]; then
    E="$(iso_epoch "$C_ISO")"
    if [[ "$E" -gt "$NEWEST_EPOCH" ]]; then NEWEST_EPOCH="$E"; NEWEST_DESC="$C_SHA ($p) $C_ISO"; fi
  fi
done
info "newest source commit      : $NEWEST_DESC"
if [[ "$IMG_EPOCH" -lt "$NEWEST_EPOCH" ]]; then
  die "f: the gateway image was built BEFORE its newest source commit.
     image .Created  $IMG_CREATED
     source commit   $NEWEST_DESC
     The image cannot contain that change. Rebuild and recreate the container."
fi
ok "image .Created is later than the newest commit touching its source paths"
info "Docker images carry no commit label -- services/gateway-service/Dockerfile sets no"
info "LABEL org.opencontainers.image.revision, and the runner emits no git_commit column."
info "A missing label is NOT an abort condition. This ordering check is therefore the"
info "BEST AVAILABLE EVIDENCE, NOT PROOF, that the image contains the D25 pin."

# -------------------------------------------------------------------- g. endpoints
hdr "g. Endpoints"
# Tests: the gateway process answers its LINEAR route with 200. It does not test any
# downstream breaker state, and it does not test Toxiproxy.
HTTP="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://localhost:8080/api/v1/linear || echo 000)"
info "GET http://localhost:8080/api/v1/linear -> $HTTP"
[[ "$HTTP" == "200" ]] || die "g: the gateway's LINEAR route returned $HTTP, expected 200"
ok "gateway LINEAR route returns 200 (tests: the gateway answers; nothing else)"

# Tests: the Toxiproxy ADMIN API lists exactly the 5 expected proxies, each enabled,
# each with an empty toxics array. It does not send traffic through them.
PROXY_JSON="$(curl -s --max-time 10 http://localhost:8474/proxies || echo '')"
[[ -n "$PROXY_JSON" ]] || die "g: Toxiproxy admin API at :8474 returned nothing"
PROXY_REPORT="$(printf '%s' "$PROXY_JSON" | python -c '
import json,sys
want=sorted(sys.argv[1:])
try: d=json.load(sys.stdin)
except Exception as e: print("PARSE_ERROR", e); raise SystemExit
got=sorted(d)
if got!=want:
    print("MISMATCH expected=%s got=%s"%(want,got)); raise SystemExit
bad=[]
for n in got:
    p=d[n]
    if not p.get("enabled"): bad.append(n+":disabled")
    t=p.get("toxics") or []
    if t: bad.append(n+":%d toxic(s)"%len(t))
print("OK %d proxies, all enabled, zero toxics"%len(got) if not bad else "BAD "+", ".join(bad))
' "${PROXIES[@]}")"
info "Toxiproxy /proxies  : $PROXY_REPORT"
[[ "$PROXY_REPORT" == OK* ]] \
  || die "g: Toxiproxy proxy set is not in the expected pre-run state -> $PROXY_REPORT"
ok "exactly ${#PROXIES[@]} proxies, all enabled, zero toxics attached"
info "(tests: the admin API's view of proxy configuration. It does not send traffic"
info " through a proxy and does not prove a downstream service is reachable.)"

# --------------------------------------------------------------- h. container state
hdr "h. Container state"
for s in "${STOPPED_SERVICES[@]}"; do
  ST="$(docker inspect "$s" --format '{{.State.Status}}' 2>/dev/null || echo 'absent')"
  info "$s : $ST"
  [[ "$ST" != "running" ]] \
    || die "h: $s is running. The manifest records that the sweep runs WITHOUT
     prometheus/grafana. Stop it: docker compose -f infra/docker-compose.yml stop $s"
done
ok "prometheus and grafana are not running (matches the manifest)"
for s in "${APP_SERVICES[@]}"; do
  ST="$(docker inspect "$s" --format '{{.State.Status}}' 2>/dev/null || echo 'absent')"
  HL="$(docker inspect "$s" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || echo 'none')"
  info "$(printf '%-22s %-9s health=%s' "$s" "$ST" "$HL")"
  [[ "$ST" == "running" ]] || die "h: $s is '$ST', expected running"
  [[ "$HL" == "healthy" || "$HL" == "none" ]] || die "h: $s health is '$HL', expected healthy"
done
ok "all ${#APP_SERVICES[@]} required containers running and healthy"

# ------------------------------------------------------------------- i. host budget
hdr "i. Host budget"
# A single instantaneous free-memory reading is not usable as a gate on this host: six
# readings 10 s apart during preparation ranged 1334.3-1944.6 MB. The gate is the MEDIAN
# of five samples; min and max are printed so the volatility stays visible.
python analysis/phase4b_mem_log.py sample -n 5 --gap 2 --min-free-mb "$MIN_FREE_MB" \
  || die "i: free physical memory below ${MIN_FREE_MB} MB (median of 5 samples)"
ok "free physical memory >= ${MIN_FREE_MB} MB (median of 5)"

FREE_KB="$(df -k . | awk 'NR==2{print $4}')"
FREE_GB=$(( FREE_KB / 1024 / 1024 ))
info "free disk on .      : ${FREE_GB} GB"
[[ "$FREE_GB" -ge "$MIN_FREE_GB" ]] \
  || die "i: free disk ${FREE_GB} GB is below the required ${MIN_FREE_GB} GB"
ok "free disk >= ${MIN_FREE_GB} GB"

# BatteryStatus 1 == discharging (on battery). 2 == AC. Anything else, or no battery
# device at all, is printed and accepted -- only a positive "on battery" aborts.
BATT="$(powershell -NoProfile -NonInteractive -Command \
  "\$b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1; if (\$b) { 'status=' + \$b.BatteryStatus + ' charge=' + \$b.EstimatedChargeRemaining + '%' } else { 'no Win32_Battery instance reported' }" \
  2>/dev/null | tr -d '\r')"
info "power               : $BATT"
if [[ "$BATT" == status=1\ * ]]; then
  die "i: the machine reads ON BATTERY (BatteryStatus=1). Connect AC before launching."
fi
ok "not positively on battery (read: $BATT)"

# ---------------------------------------------------------------- j. nothing running
hdr "j. No conflicting process already running"
for pat in gateway_poll_verify phase4b_mem_log experiments/runner.py; do
  FOUND="$(pypids "$pat" | tr '\n' ' ' | sed 's/ $//')"
  info "$(printf '%-24s %s' "$pat" "${FOUND:-none}")"
  [[ -z "$FOUND" ]] \
    || die "j: a python process matching '$pat' is already running (PID $FOUND).
     Stop it before launching -- see manifest section 5."
done
ok "no poller, memory logger or runner process is running"

printf '\n----------------------------------------------------------------\n'
printf ' %d assertion groups passed.\n' "$PASS"

if [[ $CHECK_ONLY -eq 1 ]]; then
  printf ' READY\n'
  printf '----------------------------------------------------------------\n'
  printf ' --check-only: nothing was started, nothing was written.\n'
  exit 0
fi

# ================================================================= FULL RUN ORDER
LAUNCH_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf ' LAUNCH TIMESTAMP (sweep_window.start) : %s\n' "$LAUNCH_TS"
printf ' MANIFEST                              : %s\n' "$MANIFEST"
printf '----------------------------------------------------------------\n'

mkdir -p data/audit logs

# 1. manifest -------------------------------------------------------------------
FREE_MB_NOW="$(python -c "import sys;sys.path.insert(0,'analysis');from phase4b_mem_log import free_mb;print('%.1f'%free_mb())")"
python - "$MANIFEST" <<PYEOF
import json, sys
m = {
  "git_head": "$HEAD_SHA",
  "preregistration_sha": "$PREREG_SHA",
  "preregistration_superseded": ["8f1623b", "34bfda7"],
  "preregistration_chain": "$PREREG_SUPERSEDED",
  "plan_file": "$PLAN_FILE",
  "machine_id": "$MACHINE_ID",
  "mode": "full", "fault": "latency", "topology": "linear",
  "replicates": $REPLICATES, "seed": $SEED, "expected_runs": $EXPECTED_RUNS,
  "dataset_path": "$DATASET",
  "transitions_path": "$SIDECAR",
  "poll_path": "$POLL_LOG",
  "audit_dir": "data/audit",
  "mem_log": "$MEM_LOG",
  "only_ids_file": "$IDS_SRC",
  "only_ids_sha256": "$IDS_SHA",
  "only_ids_count": $EXPECTED_IDS,
  "only_ids": [l.split("#",1)[0].strip()
               for l in open("$IDS_SRC", encoding="utf-8")
               if l.split("#",1)[0].strip()],
  "sidecar_baseline": {"path": "data/audit/sidecar_baseline_73.jsonl",
                       "lines": $SIDECAR_LINES, "sha256": "$SIDECAR_SHA"},
  "gateway_image_repo": "$GW_IMAGE",
  "gateway_container": "$GW_CONTAINER",
  "gateway_image_id": "$IMG_ID",
  "gateway_image_created": "$IMG_CREATED",
  "gateway_source_paths": ["services/gateway-service", "cascadeshield-parent/pom.xml"],
  "sweep_window": {"start": "$LAUNCH_TS", "end": None},
  "host": {"free_mb_at_launch": $FREE_MB_NOW, "free_disk_gb_at_launch": $FREE_GB,
           "power": "$BATT"},
  "observability": ("prometheus and grafana were STOPPED for this sweep and stay stopped "
                    "for all $EXPECTED_RUNS runs. The Phase 1 canary and the 2026-09-20 "
                    "smoke run were collected WITH them running. This differs between "
                    "those artifacts and this sweep, and is identical across all "
                    "$EXPECTED_RUNS runs here, so it cannot differ between arms."),
  "onedrive_sync": "off for the duration of the run",
}
assert len(m["only_ids"]) == $EXPECTED_IDS, m["only_ids"]
json.dump(m, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
print(f"  manifest written: {sys.argv[1]}  ({len(m['only_ids'])} ids)")
PYEOF

# 2. poller ---------------------------------------------------------------------
printf '\n  starting poller...\n'
nohup python -u analysis/gateway_poll_verify.py poll \
  --base http://localhost:8080 --out "$POLL_LOG" --interval 1.0 --label phase4b \
  > "$POLLER_LOG" 2>&1 &
disown || true
sleep 5
POLLER_PID="$(pypids gateway_poll_verify | head -1)"
[[ -n "$POLLER_PID" ]] || die "poller did not start -- see $POLLER_LOG"
[[ -s "$POLL_LOG" ]]   || die "poller is running (PID $POLLER_PID) but $POLL_LOG is empty"
N1="$(wc -l < "$POLL_LOG" | tr -d ' ')"
sleep 3
N2="$(wc -l < "$POLL_LOG" | tr -d ' ')"
[[ "$N2" -gt "$N1" ]] || die "poller PID $POLLER_PID is alive but not logging
     ($POLL_LOG stuck at $N1 lines). Stop it and investigate before launching."
printf '  poller alive AND logging: PID %s, %s -> %s lines\n' "$POLLER_PID" "$N1" "$N2"

# 3. memory logger --------------------------------------------------------------
printf '  starting memory logger...\n'
nohup python -u analysis/phase4b_mem_log.py log --out "$MEM_LOG" --interval 30 \
  > /dev/null 2>&1 &
disown || true
sleep 2
MEM_PID="$(pypids phase4b_mem_log | head -1)"
[[ -n "$MEM_PID" ]] || die "memory logger did not start"
printf '  memory logger: PID %s -> %s\n' "$MEM_PID" "$MEM_LOG"

# 4. sweep ----------------------------------------------------------------------
printf '  starting sweep...\n'
export DATASET_PATH_OVERRIDE="$DATASET"
nohup python -u experiments/runner.py \
  --mode full --fault latency --topology linear \
  --only-ids "$IDS_DST" --replicates "$REPLICATES" \
  --seed "$SEED" --machine-id "$MACHINE_ID" \
  > "$SWEEP_LOG" 2>&1 &
disown || true
sleep 5
SWEEP_PID="$(pypids 'experiments/runner.py' | head -1)"
[[ -n "$SWEEP_PID" ]] || die "sweep did not start -- see $SWEEP_LOG"

# 5. PIDs -----------------------------------------------------------------------
{
  printf '# Phase 4B real Windows python.exe PIDs, launched %s\n' "$LAUNCH_TS"
  printf 'poller=%s\n' "$POLLER_PID"
  printf 'mem_logger=%s\n' "$MEM_PID"
  printf 'sweep=%s\n' "$SWEEP_PID"
} > "$PIDFILE"

printf '\n----------------------------------------------------------------\n'
printf ' LAUNCHED  %s\n' "$LAUNCH_TS"
printf '   poller       PID %-8s -> %s\n' "$POLLER_PID" "$POLL_LOG"
printf '   mem logger   PID %-8s -> %s\n' "$MEM_PID"    "$MEM_LOG"
printf '   sweep        PID %-8s -> %s\n' "$SWEEP_PID"  "$SWEEP_LOG"
printf '   PIDs saved   %s\n' "$PIDFILE"
printf '   manifest     %s\n' "$MANIFEST"
printf '----------------------------------------------------------------\n'
printf ' These are real Windows python.exe PIDs, not shell job numbers.\n'
printf ' Stop commands: manifest section 5.\n'
