import os
import sys
import time
import argparse
import subprocess
import csv
import random
import socket
import statistics
import urllib.request
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from breaker_observer import BreakerObserver
from fault_injector import ToxiproxyClient
from resumable_runner import load_completed, is_done, append_row

# Toxiproxy Client
toxiproxy = ToxiproxyClient()

# Get project root directory dynamically
BASE_DIR = Path(__file__).resolve().parent.parent

# CSV Dataset Schema
DATASET_PATH = BASE_DIR / "data" / "master_dataset.csv"
CANARY_DATASET_PATH = BASE_DIR / "data" / "canary_runs.csv"
SWEEP_DATASET_PATH = BASE_DIR / "data" / "crash_toxicity_sweep.csv"
OCCUPANCY_DATASET_PATH = BASE_DIR / "data" / "occupancy_dataset.csv"
STATUS_PATH = BASE_DIR / "data" / "run_status.json"
ENV_PATH = BASE_DIR / "infra" / ".env"
COMPOSE_FILE_PATH = BASE_DIR / "infra" / "docker-compose.yml"

DATASET_HEADERS = [
    "experiment_id", "topology", "fault_type", "window_type",
    "threshold", "window_size", "wait_duration", "permitted_calls_half_open",
    "environment", "mode", "replicate", "run_timestamp",
    "blast_radius", "time_to_open", "time_to_recover",
    "error_rate", "throughput_loss",
    # Task 2: request-level blast radius (real observed failure), kept ALONGSIDE the
    # legacy CB-state blast_radius above so the two definitions can be compared.
    "real_blast_radius",
    # Raw per-leg failure rates behind real_blast_radius ("svc:rate;svc:rate", each 0-1), so a
    # different TAU_LEG can be applied post-hoc from the CSV without re-running the sweep.
    "leg_failure_rates",
    # Breaker-state-reset precondition (highest-priority harness bug found: CB state observed
    # carrying over between replicates of an IDENTICAL config -- e.g. one replicate tripping in
    # 0.303s against 6.2s+ for its siblings, consistent with a breaker that started this run
    # already OPEN rather than one that tripped fresh). precondition_ok=False rows have every
    # outcome column above left BLANK -- the run was aborted before fault injection, so they
    # measured nothing and MUST be excluded from training/analysis, not read as "0.0" / "safe".
    "precondition_ok",
    "precondition_fail_reason",
    # Wall-clock seconds spent polling all six services' /actuator/health before the run
    # proceeded (or the readiness deadline was hit). Recorded even on timeout.
    "readiness_wait_s",
    # Per-breaker state read from GET /actuator/circuitbreakers right after the pre-run
    # reset, serialized "service:breaker=STATE;...". Ground truth for "did the reset work",
    # not an inference from health or container-recreate having merely been *attempted*.
    "cb_state_pre",
    # Per-breaker bufferedCalls from the same read, serialized "service:breaker=N;...". On a
    # genuinely fresh container this is 0 for every breaker; non-zero is the direct signal
    # that update_containers()'s force-recreate did NOT actually reset that service's JVM.
    "buffered_calls_pre",
    # JIT warmup (discard phase, run before baseline/fault load -- see the "JIT warmup"
    # comment block near LOAD_RATE_RPS). Proves the warmup dose actually ran rather than
    # just asserting it: a cold JVM's 100ms+ per-request artifacts are noise on a DV whose
    # real effects are single-digit seconds.
    "warmup_requests",
    "warmup_duration_s",
    # Run-order randomization: sequential execution of a long sweep on one host confounds
    # treatment (config) with thermal/memory drift over the sweep's wall-clock duration --
    # later configs would systematically run on a warmer/more-fragmented host. main() builds
    # the full run list up front and shuffles it with random.Random(run_order_seed), so
    # execution order is decorrelated from config order. Never null: every row, including
    # PRECONDITION_FAIL/READINESS_TIMEOUT aborts, has a definite position in the sequence.
    "run_order_seed",
    "run_index",
    # Achieved-vs-requested arrival rate (lambda), measured at the gateway over the
    # fault window's generate_load() call, not the paced interval_s schedule the
    # dispatcher was asked to hit. A saturated thread pool (or a slow/crashing
    # backend under fault) queues each request behind the last, so the *offered*
    # rate can silently diverge from the *requested* one -- exactly the confound
    # that would make a config look "safe" only because it never actually received
    # the load a config elsewhere in the sweep did. lambda_target is the requested
    # rate (plan["target_rps"]); lambda_achieved is measured from actual per-request
    # dispatch timestamps (count / span); lambda_cv is the coefficient of variation
    # across those requests' inter-dispatch intervals -- a high CV means the offered
    # rate was bursty/uneven even if its mean matched target. All three are blank on
    # aborted runs (never measured a real window) and blank if too few requests were
    # dispatched to compute a rate (see LAMBDA_MIN_REQUESTS_FOR_RATE below).
    "lambda_target",
    "lambda_achieved",
    "lambda_cv",
    # True when lambda_achieved deviates from lambda_target by more than
    # LAMBDA_DEVIATION_THRESHOLD -- nominal-vs-achieved rate divergence would
    # quietly destroy any hypothesis compared across configs at their nominal rate.
    # Blank (not False) when lambda_achieved itself couldn't be measured.
    "lambda_deviation_flag",
    # Effective horizon H: calls actually available to the sliding window during the
    # fault window, in the same "number of calls" unit CB_MINIMUM_CALLS is evaluated
    # against. H = window_size for COUNT_BASED (already denominated in calls);
    # H = lambda_achieved * window_size for TIME_BASED (denominated in seconds, so
    # the achieved -- not requested -- rate determines how many calls actually
    # landed in the trailing window). H < CB_MINIMUM_CALLS means the breaker never
    # had enough calls to evaluate at all during this run, a harness artifact
    # indistinguishable from a genuine "safe" outcome without this column. Blank on
    # a precondition_ok=False row, and blank for TIME_BASED when lambda_achieved
    # itself is blank (see compute_effective_horizon).
    "effective_horizon",
    # Which machine/Codespace produced this row. Nullable string, blank when the harness
    # didn't record one. Added for D6 cross-machine calibration: runs split across hosts
    # otherwise confound host with treatment, and there is no way to recover which host a
    # row came from after the fact. Sits immediately BEFORE excluded_reason -- see the
    # note below on why that column stays last (D14).
    "machine_id",
    # Quarantine marker, written by analysis/quarantine.py -- NOT by a run. Empty means the
    # row is analysable; anything else is a "+"-joined list of exclusion codes (see
    # data/DATA_DICTIONARY.md). Rows are marked rather than deleted so a reviewer can see
    # what was dropped and why. A live run always writes it empty, and it is deliberately
    # LAST: it is assigned post-hoc, so keeping it at the end means a re-quarantine never
    # shifts a column the harness wrote.
    #
    # Distinct from precondition_ok above, which they are easy to conflate: precondition_ok
    # marks a run that never happened (aborted before fault injection, every outcome column
    # blank), while excluded_reason marks a run that happened and produced numbers that
    # turned out not to be trustworthy. Analyses must drop both.
    "excluded_reason",
]


def _with_extra_columns(extra):
    """DATASET_HEADERS with `extra` spliced in immediately before excluded_reason.

    excluded_reason is deliberately the last column of every header (D8, D14): it is
    assigned post-hoc by analysis/quarantine.py, so anything appended after it would
    shift the one column a re-quarantine writes. Mode-specific additions therefore go
    before it, not on the end.
    """
    cut = DATASET_HEADERS.index("excluded_reason")
    return DATASET_HEADERS[:cut] + list(extra) + DATASET_HEADERS[cut:]


# Crash toxicity sweep (mode="sweep"): same 35 columns as master, plus the configured
# toxicity setpoint. A separate header/file so a new column never touches the master
# schema -- see get_dataset_path/log_results.
SWEEP_DATASET_HEADERS = _with_extra_columns(["injected_toxicity"])

# Occupancy-ratio sweep (mode="occupancy", D7 -- lambda is a variable, not a single
# fixed value): same 35 columns as master, plus the occupancy diagnostic pair. A
# separate header/file for the same reason as SWEEP_DATASET_HEADERS above -- adding
# these directly to the shared DATASET_HEADERS would retroactively column-mismatch
# the already-collected data/master_dataset.csv (20 columns on disk, 80 rows) -- exactly
# the incident resumable_runner.py's load_completed() now fails loudly on instead of
# silently.
OCCUPANCY_DATASET_HEADERS = _with_extra_columns(["occupancy_ratio", "inert"])

# (experiment_id, str(replicate)) pairs already written to the current run's dataset
# file -- populated once at the top of main() via resumable_runner.load_completed(),
# and grown by log_results() after each successful append_row(). Lets a restarted
# run skip cells it already has instead of re-running (and re-appending) them.
completed_runs = set()

# How many replicates per config (min 3 for variance estimation)
N_REPLICATES = 3
ENVIRONMENT = os.environ.get("ENVIRONMENT", "LOCAL")  # override to AWS on cloud runs
# D6: which physical machine produced this row. Auto-captured (not a flag someone has to
# remember to pass) because the cross-machine confound this exists to catch is exactly the
# kind that goes unnoticed when it depends on operator discipline -- see
# docs/paper/decision-log.md D16. Override only when hostname alone doesn't disambiguate
# (e.g. identically-named containers).
MACHINE_ID = os.environ.get("MACHINE_ID", socket.gethostname())

# No-fault control condition (fault_type=NONE): without it, a config reading blast_radius=0
# under a real fault is not distinguishable from a config that would read 0 regardless of
# whether anything actually happened -- "safe" is only a meaningful claim relative to a
# baseline false-trip rate (phi), which requires actually running the mesh with no fault
# injected. Enforced as a hard floor, not a suggestion: undersampling the control condition
# defeats the entire point of collecting it.
MIN_NONE_FAULT_REPLICATES = 10

# Sidecar log of real Resilience4j state-transition events, keyed to each CSV row
# by experiment_id/replicate/mode. Exists because error_rate/blast_radius alone
# cannot tell us whether an *interior* breaker (order/inventory/payment/notification's
# own CBs on their downstream calls) actually opened: Resilience4j trips on the
# slow-call-rate path independently of the failure-rate path, and a >2s call that
# still returns 200 scores 0% failure rate while counting fully toward slow-call
# rate. Only the actual STATE_TRANSITION events settle that.
CB_TRANSITIONS_PATH = BASE_DIR / "data" / "cb_transitions.jsonl"
CANARY_CB_TRANSITIONS_PATH = BASE_DIR / "data" / "canary_cb_transitions.jsonl"

# service -> (actuator port, [circuit breaker instance names]), from each service's
# application.yml `resilience4j.circuitbreaker.instances`. shared-db-service has no
# breakers of its own (it's a call target, not a caller) so it's excluded.
SERVICE_BREAKERS = {
    "gateway":      (8080, ["orderServiceCB", "inventoryServiceCB", "paymentServiceCB"]),
    "order":        (8081, ["inventoryServiceCB", "sharedDbCB"]),
    "inventory":    (8082, ["paymentServiceCB", "sharedDbCB"]),
    "payment":      (8083, ["notificationServiceCB", "sharedDbCB"]),
    "notification": (8084, ["sharedDbCB"]),
}
# Resilience4j's actuator event buffer is ONE ring per breaker shared across every event
# type (SUCCESS/ERROR/NOT_PERMITTED/STATE_TRANSITION), not a STATE_TRANSITION-only log.
# Load fairness (below) deliberately sustains traffic through the whole wait_duration --
# every call rejected while OPEN emits its own NOT_PERMITTED event into this same ring --
# so a long OPEN period floods and evicts the original CLOSED_TO_OPEN transition before
# BreakerObserver.collect() ever reads it (confirmed on real data: wait_duration=30 runs
# retained only their latest OPEN_TO_HALF_OPEN event, no CLOSED_TO_OPEN, making D12's
# precise recovery metric silently NEVER_OPEN them). Worst case across every mode this
# runs in: occupancy's rps=20/window=20/n_min=200 TIME_BASED cell offers
# ~(10*20+15+10)*20 = 4500 requests in one run. 5000 gives headroom above that at a
# memory cost (a few hundred bytes/event) too small to matter.
CB_EVENT_BUFFER_SIZE = 5000  # must match application.yml's event-consumer-buffer-size

# All six services in the call chain, for the readiness gate. shared-db-service has no
# circuit breaker of its own (see SERVICE_BREAKERS above) but every other service calls
# into it, so an unhealthy/still-starting shared-db silently corrupts every other
# service's measurements even though it never appears in SERVICE_BREAKERS.
ALL_SERVICE_PORTS = {
    "gateway": 8080, "order": 8081, "inventory": 8082,
    "payment": 8083, "notification": 8084, "shared-db": 8085,
}

# Configuration Parameter Values for Sweeps (3*3*3*2 = 54 configs per fault × 2 faults × 3 replicates = 324 total runs)
PARAM_VALUES = {
    "failureRateThreshold": [30, 50, 70],
    "slidingWindowSize": [5, 10, 20],
    "waitDurationInOpenState": [5, 15, 30],  # Seconds
    "slidingWindowType": ["COUNT_BASED", "TIME_BASED"],
}
PERMITTED_CALLS_HALF_OPEN = 5  # fixed baseline, not swept
# Resilience4j defaults minimumNumberOfCalls to 100. With sliding windows of 5-20 and a
# short load, that threshold is never reached, so the breaker never evaluates and never
# trips -- especially for TIME_BASED windows. We expose it (default 5) so it is actually
# reachable within every swept window. See fix/measurement-validity + application.yml.
CB_MINIMUM_CALLS = 5  # fixed baseline for full/canary/sweep modes (occupancy mode sweeps it instead)

# ---- Load fairness (Task 1) --------------------------------------------------
# COUNT_BASED and TIME_BASED interpret slidingWindowSize in different units (calls vs
# seconds). A fixed ~50-request burst fills a COUNT_BASED window but never fills a
# TIME_BASED window of 5-20s, so TIME_BASED breakers never evaluate -- making their
# "0% blast radius" an artifact of the harness, not a property of the breaker. We size
# the offered load per window type so BOTH get a fair chance to fill, trip, sit OPEN,
# and transition to HALF_OPEN:
#   * TIME_BASED : sustain load for slidingWindowSize + waitDurationInOpenState + margin
#                  seconds, so the trailing time-window fills and a HALF_OPEN probe fires.
#   * COUNT_BASED: fire enough calls to turn the ring buffer over several times.
LOAD_RATE_RPS = 10                 # steady offered request rate (requests/second)
LOAD_CONCURRENCY = 5
TIME_BASED_MARGIN_S = 10           # safety margin on top of window + wait duration
COUNT_BASED_WINDOW_MULTIPLE = 3    # fire >= this * slidingWindowSize calls
COUNT_BASED_MIN_REQUESTS = 40      # floor: keep error-rate estimate statistically stable
INERTNESS_WINDOW_MULTIPLE = 10     # occupancy mode's TIME_BASED load duration = this * window
                                    # + wait + margin (vs full/canary's flat "window + wait +
                                    # margin") -- a high-n_min occupancy cell (e.g. n_min=200)
                                    # needs several window passes' worth of load for calls to
                                    # accumulate, not just one.

# Achieved-vs-requested arrival rate (see the "lambda_target/lambda_achieved" comment
# block in DATASET_HEADERS). Flag a run when the measured rate misses the requested
# one by more than this fraction -- 15% is a coarse tripwire, not a precision bound.
LAMBDA_DEVIATION_THRESHOLD = 0.15
# Below this many dispatched requests, span/interval-based rate and CV estimates are
# too noisy to trust (e.g. a 2-request window has exactly one interval -- a CV of
# either 0.0 or undefined depending on luck, not a real measurement). generate_load's
# baseline call (20 requests) clears this; only exists as a documented floor, not
# because any current call site is expected to fall under it.
LAMBDA_MIN_REQUESTS_FOR_RATE = 3

# ---- JIT warmup (discard phase) ------------------------------------------------
# A cold Spring Boot JVM (interpreted bytecode, C1/C2 JIT not yet compiled the hot
# path) can add 100ms+ latency to individual requests -- noise on the same order as,
# or larger than, some of what's measured, and real contamination of a DV
# (time_to_open, time_to_recover) whose true effects are single-digit seconds. Run
# BEFORE the baseline throughput measurement, so that measurement isn't itself
# contaminated by JIT warmup. Results are discarded; only the dose actually
# delivered (warmup_requests, warmup_duration_s) is kept, so the dataset can prove
# the warmup ran rather than merely assert it. "Whichever is longer" means BOTH
# floors must be met, not either one alone.
WARMUP_MIN_REQUESTS = 200
WARMUP_MIN_DURATION_S = 10.0

# ---- Real (request-level) blast radius (Task 2) ------------------------------
# SUBJECT SET = the four CB-bearing downstream services whose real per-leg failure we
# observe from Resilience4j call outcomes (NOT circuit-breaker OPEN/CLOSED state). This is
# the denominator for real_blast_radius and it MATCHES BlastRadiusService.SERVICE_ACTUATOR_URLS
# so the two blast-radius metrics range over the same nodes -> {0, 0.25, 0.5, 0.75, 1.0}.
#
# Deliberately EXCLUDED from the denominator:
#   * gateway-service — it is the MEASUREMENT PLANE, not an experimental subject. An edge
#     breaker sees the summed chain latency and trips first (the gateway CB confound); its
#     breaker is now pinned never-open via the measurement-plane config, and including it
#     here would have let one saturated node dominate blast radius. (Poll it separately for
#     diagnostics if ever needed, but keep it out of the count.)
#   * shared-db-service — a leaf with no outbound calls / no @CircuitBreaker, so it can
#     never have an open breaker and only dilutes the denominator.
# Ports are published by docker-compose.
CB_METRIC_TARGETS = {
    "order-service": "http://localhost:8081",
    "inventory-service": "http://localhost:8082",
    "payment-service": "http://localhost:8083",
    "notification-service": "http://localhost:8084",
}
# A leg counts as "degraded" if its observed error rate over the fault window exceeds this.
# OPEN QUESTION -- threshold to be signed off; see docs/proposals/blast-radius-redefinition.md
REAL_BLAST_LEG_ERROR_THRESHOLD = 0.50


def run_command(args, cwd=None):
    """Helper to run system commands."""
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(args)}\nError: {result.stderr}", file=sys.stderr)
    return result

def write_env_file(config):
    """Writes the current R4J config parameters to the infra/.env file.

    config['minimumNumberOfCalls'] is normalized onto every config by
    generate_combinations: CB_MINIMUM_CALLS for full/canary/sweep, swept
    explicitly for occupancy."""
    env_content = f"""# Auto-generated by CascadeShield Experiment Runner
CB_SLIDING_WINDOW_SIZE={config['slidingWindowSize']}
CB_SLIDING_WINDOW_TYPE={config['slidingWindowType']}
CB_FAILURE_RATE_THRESHOLD={config['failureRateThreshold']}
CB_WAIT_DURATION_OPEN={config['waitDurationInOpenState']}s
CB_PERMITTED_CALLS_HALF_OPEN={PERMITTED_CALLS_HALF_OPEN}
CB_EVENT_BUFFER_SIZE={CB_EVENT_BUFFER_SIZE}
CB_MINIMUM_CALLS={config['minimumNumberOfCalls']}
"""
    os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
    with open(ENV_PATH, "w") as f:
        f.write(env_content)
    print(f"Updated {ENV_PATH.name} with: {config}")

def update_containers():
    """Forces docker compose to recreate services with the new environment variables."""
    print("Recreating Spring Boot containers to apply new configuration...")
    # Recreate only the services using Resilience4j to save time
    services = ["gateway-service", "order-service", "inventory-service", "payment-service", "notification-service", "shared-db-service"]
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE_PATH), "up", "-d", "--no-deps", "--force-recreate"] + services
    result = run_command(cmd)
    if result.returncode != 0:
        print("Docker compose failed to recreate containers. Aborting run.", file=sys.stderr)
        return False
    return True

def wait_for_readiness(timeout=90):
    """Polls /actuator/health on all SIX services until every one reports UP, or
    a hard deadline is hit. Supersedes the old "just check gateway + notification
    and infer the rest" shortcut -- that inference is exactly the kind of
    unverified assumption the breaker-reset precondition below exists to stop
    making; shared-db-service in particular has no circuit breaker of its own
    but sits in every call chain, so a still-starting shared-db silently
    corrupts every other service's measurements.

    Returns (all_healthy, elapsed_s). elapsed_s is recorded on timeout too --
    a run that barely made the deadline and one that never did are both
    evidence worth keeping in the dataset, not just a pass/fail bit.
    """
    start_time = time.time()
    healthy = {name: False for name in ALL_SERVICE_PORTS}
    while time.time() - start_time < timeout:
        for name, port in ALL_SERVICE_PORTS.items():
            if healthy[name]:
                continue
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/actuator/health", timeout=2) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode("utf-8"))
                        if data.get("status") == "UP":
                            print(f"{name}-service is healthy!")
                            healthy[name] = True
            except Exception:
                pass
        if all(healthy.values()):
            return True, round(time.time() - start_time, 3)
        time.sleep(2)
    not_ready = [name for name, ok in healthy.items() if not ok]
    print(f"Timeout waiting for services to become healthy: {not_ready} never reported UP.", file=sys.stderr)
    return False, round(time.time() - start_time, 3)

# Must match fault_injector.ToxiproxyClient.setup_default_proxies' proxy names exactly.
INJECT_POINT_CHOICES = [
    "order-service-proxy", "inventory-service-proxy", "payment-service-proxy",
    "notification-service-proxy", "shared-db-service-proxy",
]

def inject_fault(fault_type, toxicity=1.0, inject_point=None):
    """Injects the appropriate fault profile into Toxiproxy.

    inject_point overrides which proxy the fault lands on for EITHER fault type
    (D4's supplementary check needs latency/crash injected at a service other than
    the historical default). None preserves the pre-existing hardcoded target per
    fault type, so every existing call site is unaffected unless it opts in. Must
    be one of INJECT_POINT_CHOICES (matches fault_injector.setup_default_proxies'
    proxy names).

    toxicity only affects the crash branch; a no-op for the other fault types."""
    toxiproxy.reset_all()

    if fault_type == "latency":
        # Inject high latency (3000ms) on the target proxy (inventory-service-proxy
        # by default) -- simulates a slow downstream dependency.
        toxiproxy.inject_latency(inject_point or "inventory-service-proxy", delay_ms=3000, toxicity=1.0)

    elif fault_type == "crash":
        # Reset a fraction (toxicity) of connections to the target proxy, simulating a
        # graded crash. toxicity=1.0 resets every connection (full outage, matching the
        # pre-sweep behavior of disabling the proxy outright).
        toxiproxy.inject_reset_peer(inject_point or "payment-service-proxy", timeout_ms=0, toxicity=toxicity)

    elif fault_type == "none":
        # Deliberate no-op: this is a control replicate. toxiproxy.reset_all() above already
        # guarantees every proxy is clean, so the "fault window" is a pure healthy-baseline
        # window -- exactly the point. Not an error case; do not fall through to the else.
        pass

    else:
        print(f"No fault injected. Type '{fault_type}' is unknown.", file=sys.stderr)


def resolve_inject_point(inject_point, mode):
    """The actual injection point a run will use, given an explicit --inject-point
    (which always wins) and the mode-specific default otherwise. Factored out of
    run_experiment_run so main()'s resumability check (make_experiment_id) and the
    real fault injection agree on the same value -- computing this twice, once per
    call site, is exactly the kind of duplicated-derivation risk that already bit
    effective_horizon elsewhere in this file."""
    return inject_point or ("inventory-service-proxy" if mode == "sweep" else None)

def compute_load_plan(config, target_rps=LOAD_RATE_RPS, mode=None):
    """Sizes the offered load per window type so both COUNT_BASED and TIME_BASED windows
    get a fair chance to fill, trip, sit OPEN, and transition to HALF_OPEN.

    target_rps is the target arrival rate (lambda) -- previously hardcoded to
    LOAD_RATE_RPS inside this function, now an explicit parameter so a caller can vary
    the offered rate without touching the sizing logic itself. Defaults to LOAD_RATE_RPS,
    so the existing call site in run_experiment_run() is unaffected unless it opts in.

    mode selects the INERTNESS_WINDOW_MULTIPLE gate below -- the actual mode string,
    not a proxy inferred from config's shape (every config now carries
    minimumNumberOfCalls/targetRps unconditionally, see generate_combinations, so
    key-presence is no longer a usable "is this occupancy" signal).

    See the "Load fairness (Task 1)" comment block near the top of this module for the
    window-fill rationale. Returns dict(requests_count, interval_s, concurrency,
    duration_s, target_rps).
    """
    interval_s = 1.0 / target_rps
    window = int(config["slidingWindowSize"])
    wait = int(config["waitDurationInOpenState"])
    # minimumNumberOfCalls is normalized onto every config by generate_combinations --
    # CB_MINIMUM_CALLS for canary/full/sweep, swept explicitly for occupancy.
    n_min = int(config["minimumNumberOfCalls"])

    if config["slidingWindowType"] == "TIME_BASED":
        # Sustain load long enough for the trailing time-window (seconds) to fill, the
        # breaker to sit OPEN for wait_duration, and an automatic HALF_OPEN probe to fire.
        # Occupancy-mode configs use INERTNESS_WINDOW_MULTIPLE instead of a single window
        # pass, since a high-n_min cell (e.g. n_min=200) needs several window passes'
        # worth of load for calls to actually accumulate. Gated on mode == "occupancy"
        # (not applied unconditionally) so full/canary/sweep's load sizing -- and
        # therefore their run duration and byte-identical default behavior -- is
        # completely unaffected.
        window_multiple = INERTNESS_WINDOW_MULTIPLE if mode == "occupancy" else 1
        duration_s = window_multiple * window + wait + TIME_BASED_MARGIN_S
        requests_count = max(int(duration_s * target_rps), n_min + 1)
    else:  # COUNT_BASED -- window is measured in calls
        requests_count = max(window * COUNT_BASED_WINDOW_MULTIPLE,
                             n_min * 3, COUNT_BASED_MIN_REQUESTS)
        duration_s = requests_count * interval_s

    return {"requests_count": requests_count, "interval_s": interval_s,
            "concurrency": LOAD_CONCURRENCY, "duration_s": duration_s,
            "target_rps": target_rps}


def compute_lambda_deviation_flag(lambda_achieved, lambda_target, threshold=LAMBDA_DEVIATION_THRESHOLD):
    """True when the achieved arrival rate misses the target by more than `threshold`
    (a fraction, e.g. 0.15 = 15%). Returns None -- not False -- when lambda_achieved
    is None, since "couldn't measure it" is not the same claim as "no deviation"."""
    if lambda_achieved is None:
        return None
    return abs(lambda_achieved - lambda_target) / lambda_target > threshold


def compute_effective_horizon(window_type, window_size, lambda_achieved):
    """Effective horizon H: how many calls the sliding window actually had a chance
    to observe during the fault window, in the same "number of calls" unit
    minimumNumberOfCalls (CB_MINIMUM_CALLS) is evaluated against.

    COUNT_BASED windows are already denominated in calls, so H = W (window_size)
    directly -- every call that lands is one slot in the window, independent of
    how fast or slow they arrived. TIME_BASED windows are denominated in seconds,
    so a window's actual call count depends on the ACHIEVED arrival rate, not the
    requested one: H = lambda_achieved * T (window_size, seconds). A TIME_BASED
    run with H < CB_MINIMUM_CALLS never had enough calls in its trailing window
    to evaluate the breaker at all, regardless of failure rate -- an artifact
    this column makes visible instead of silently confounding with a real "safe"
    outcome. Returns None when window_type is TIME_BASED and lambda_achieved is
    None (can't compute an achieved-rate-based horizon without a measured rate)."""
    if window_type == "COUNT_BASED":
        return float(window_size)
    if window_type == "TIME_BASED":
        if lambda_achieved is None:
            return None
        return lambda_achieved * window_size
    return None


def compute_occupancy_ratio(effective_horizon, min_calls):
    """Occupancy ratio rho: how full the sliding window was relative to the minimum
    evaluation threshold (minimumNumberOfCalls) -- rho = effective_horizon / min_calls.
    rho >= 1 means the window had enough calls to even evaluate the breaker; rho < 1
    means it structurally could not, regardless of failure rate. This is the quantity
    H2's inertness boundary is tested against (D7 -- does `inert` flip to True at
    rho* = 1?).

    Takes the already-computed effective_horizon directly rather than recomputing it
    from window_type/window_size/lambda_achieved -- run_experiment_run already calls
    compute_effective_horizon once per run and stores it in metrics; this is the only
    call site, so there's no reuse case served by a second internal computation of the
    same value from the same inputs. Returns None when the horizon itself is None
    (TIME_BASED with no measured lambda_achieved)."""
    if effective_horizon is None:
        return None
    return effective_horizon / min_calls


def generate_load(endpoint_url, requests_count=50, concurrency=5, interval_s=0.05):
    """Lightweight built-in HTTP load generator to test the mesh.

    requests_count requests are dispatched spaced by interval_s (steady offered rate),
    so the same function drives both the short baseline warm-up and the longer,
    duration-sized fault load (via compute_load_plan).

    Also measures the ACHIEVED arrival rate, not just the requested one: interval_s
    is what the dispatch loop below asks for, but a saturated thread pool (worker
    still busy on a slow/hanging request under fault) queues send_request behind the
    last one, so what actually reaches the gateway can drift from what was asked
    for. lambda_achieved is computed from each request's real dispatch timestamp
    (count / span, not requests_count / interval_s), and lambda_cv is the
    coefficient of variation across those requests' inter-dispatch intervals -- high
    CV means the offered rate was bursty/uneven even when its mean lands on target.
    Both are None when fewer than LAMBDA_MIN_REQUESTS_FOR_RATE requests were sent."""
    print(f"Generating load: {requests_count} requests to {endpoint_url} "
          f"@ ~{1.0/interval_s:.0f} req/s (~{requests_count*interval_s:.1f}s dispatch)...")

    success_count = 0
    failure_count = 0
    latencies = []
    dispatch_timestamps = []
    lock = threading.Lock()

    t0 = time.time()
    last_completion = t0  # updated by each request as it finishes

    def send_request():
        nonlocal success_count, failure_count, last_completion
        start = time.time()  # actual dispatch instant, post any thread-pool queueing
        success = False
        try:
            req = urllib.request.Request(endpoint_url)
            with urllib.request.urlopen(req, timeout=5) as res:
                res.read()
                if res.status == 200:
                    success = True
        except Exception:
            pass

        latency = (time.time() - start) * 1000
        with lock:
            if success:
                success_count += 1
            else:
                failure_count += 1
            latencies.append(latency)
            dispatch_timestamps.append(start)
            last_completion = time.time()  # true last-completion timestamp

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for _ in range(requests_count):
            executor.submit(send_request)
            time.sleep(interval_s)  # Pacing: steady rate, avoids thundering-herd
    # executor.__exit__ blocks until ALL futures complete.

    # Execution window = first dispatch to last completion.
    # Avoids the pacing-overhead subtraction which over-corrects under fast-fail.
    execution_time = max(last_completion - t0, 0.001)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    throughput = success_count / execution_time
    error_rate = (failure_count / requests_count) * 100 if requests_count else 0

    dispatch_timestamps.sort()
    n_dispatched = len(dispatch_timestamps)
    lambda_achieved = None
    lambda_cv = None
    if n_dispatched >= LAMBDA_MIN_REQUESTS_FOR_RATE:
        span = dispatch_timestamps[-1] - dispatch_timestamps[0]
        if span > 0:
            lambda_achieved = (n_dispatched - 1) / span
        intervals = [dispatch_timestamps[i + 1] - dispatch_timestamps[i]
                     for i in range(n_dispatched - 1)]
        mean_interval = statistics.mean(intervals)
        if mean_interval > 0:
            lambda_cv = statistics.stdev(intervals) / mean_interval

    print(f"Load Results - Successes: {success_count}, Failures: {failure_count}, Avg Latency: {avg_latency:.2f}ms, Throughput: {throughput:.2f} TPS, Error Rate: {error_rate:.2f}%")
    if lambda_achieved is not None:
        print(f"Arrival rate - achieved: {lambda_achieved:.2f} req/s (requested ~{1.0/interval_s:.2f} req/s), CV: {lambda_cv:.3f}" if lambda_cv is not None else
              f"Arrival rate - achieved: {lambda_achieved:.2f} req/s (requested ~{1.0/interval_s:.2f} req/s)")
    return throughput, error_rate, avg_latency, lambda_achieved, lambda_cv

def warmup_phase(endpoint_url, min_requests=WARMUP_MIN_REQUESTS, min_duration_s=WARMUP_MIN_DURATION_S,
                  interval_s=1.0 / LOAD_RATE_RPS, concurrency=LOAD_CONCURRENCY):
    """Discard-phase requests to steady state, run before any measurement or fault
    injection (see the "JIT warmup" comment block above LOAD_RATE_RPS for why).
    Responses are read and thrown away -- this exists to warm the JIT, not to
    measure anything -- but the actual dose delivered (count, elapsed time) is
    returned so the caller can log it rather than just assert the phase ran.

    Runs until BOTH min_requests have completed AND min_duration_s has elapsed --
    "200 requests or 10s, whichever is longer" means neither floor may be skipped,
    not that meeting either alone is sufficient.
    """
    print(f"Warming up JIT: discarding responses from {endpoint_url} for >= {min_requests} "
          f"requests and >= {min_duration_s:.0f}s (whichever is longer)...")
    start = time.time()
    requests_sent = 0

    def send_and_discard():
        try:
            with urllib.request.urlopen(endpoint_url, timeout=5) as res:
                res.read()
        except Exception:
            pass  # discard phase -- failures here are not measured or logged as errors

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while requests_sent < min_requests or (time.time() - start) < min_duration_s:
            executor.submit(send_and_discard)
            requests_sent += 1
            time.sleep(interval_s)
    # executor.__exit__ blocks until every in-flight request completes, so the
    # elapsed time below reflects genuine JVM activity, not just dispatch time.
    elapsed = round(time.time() - start, 3)
    print(f"Warmup complete: {requests_sent} requests over {elapsed:.1f}s.")
    return requests_sent, elapsed

def get_blast_radius():
    """Queries the Gateway's custom aggregator endpoint for the current blast radius.

    Returns the blast radius as a float in [0.0, 1.0], or None if the
    measurement failed.  Returning None (rather than 0.0) ensures failed
    measurements are distinguishable from a genuinely healthy mesh with no
    open circuit breakers in the CSV dataset.

    The Java BlastRadiusService returns values on a 0–100 scale (percent).
    We normalise to 0.0–1.0 here so every downstream consumer (preprocessing,
    DATA_DICTIONARY, Isolation Forest) sees a consistent fraction.
    """
    url = "http://localhost:8080/api/v1/blast-radius"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                raw = data.get("blastRadius", 0.0)   # Java returns 0–100
                return round(raw / 100.0, 6)          # normalise → 0.0–1.0
    except Exception as e:
        print(f"Failed to query blast radius from Gateway: {e}", file=sys.stderr)
    return None  # Sentinel: distinguishable from a real 0.0 (healthy mesh)

# ---- Breaker-state-reset precondition -----------------------------------------
# update_containers() already force-recreates every container before every run, which
# SHOULD reset Resilience4j's in-memory CircuitBreakerRegistry (a fresh JVM has no
# accumulated state) -- but that has been observed NOT to hold: a replicate can start
# with a breaker already OPEN/near-tripped from the prior run, tripping in ~0.3s
# instead of the ~6s its identical siblings take on a genuine cold start. The functions
# below make the reset explicit (rather than trusting force-recreate blindly) and then
# verify it against ground truth before any fault is injected, so a run that can't be
# trusted is aborted instead of silently written as if it started clean.
#
# Verified against the actual resilience4j-spring-boot3 2.2.0 jar this project depends
# on (decompiled CircuitBreakerEndpoint.class) rather than assumed from memory:
#   GET  /actuator/circuitbreakers            -> {"circuitBreakers": {name: {"state":
#        "CLOSED"|"OPEN"|..., "bufferedCalls": int, ...}}}   (@ReadOperation)
#   POST /actuator/circuitbreakers/{name}     body {"updateState": "CLOSE"}  ->
#        calls CircuitBreaker.transitionToClosedState()      (@WriteOperation)
# Deliberately NOT using /actuator/health for the read: management.health.circuitbreakers
# .enabled is opt-in, and if it were ever turned off, health would report a bare "UP" with
# no breaker detail and this assertion would pass vacuously -- the exact failure mode this
# precondition exists to prevent. /actuator/circuitbreakers needs no such opt-in and is
# already in every service's management.endpoints.web.exposure.include.

def _get_circuit_breakers(port):
    """GET /actuator/circuitbreakers: {breaker_name: {"state": ..., "bufferedCalls": ...}}.
    Returns {} on any failure -- callers must treat that as "could not verify" (fail
    closed), never as "no breakers configured"."""
    url = f"http://localhost:{port}/actuator/circuitbreakers"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("circuitBreakers", {})
    except Exception as e:
        print(f"Failed to read circuit breakers (port {port}): {e}", file=sys.stderr)
        return {}

def _transition_breaker_to_closed(port, breaker_name):
    """POST /actuator/circuitbreakers/{name} {"updateState": "CLOSE"} -- forces an
    immediate, explicit reset to CLOSED, independent of (and a belt-and-suspenders
    complement to) the per-run container force-recreate in update_containers().
    Best-effort: the real gate is check_breaker_precondition() re-reading ground
    truth afterward, not this call succeeding."""
    url = f"http://localhost:{port}/actuator/circuitbreakers/{breaker_name}"
    body = json.dumps({"updateState": "CLOSE"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status == 200
    except Exception as e:
        print(f"Failed to reset {breaker_name} to CLOSED (port {port}): {e}", file=sys.stderr)
        return False

def reset_all_breakers():
    """Best-effort: force every known breaker (SERVICE_BREAKERS) to CLOSED via the
    actuator write endpoint before check_breaker_precondition() asserts the result."""
    for service, (port, breakers) in SERVICE_BREAKERS.items():
        for breaker in breakers:
            _transition_breaker_to_closed(port, breaker)

def _serialize_cb_map(nested):
    """{service: {breaker: value}} -> "service:breaker=value;service:breaker=value",
    matching the "svc:rate;svc:rate" convention already used for leg_failure_rates."""
    return ";".join(
        f"{service}:{breaker}={value}"
        for service, breakers in nested.items()
        for breaker, value in breakers.items()
    )

def check_breaker_precondition():
    """Reset-then-verify: reads every known breaker's ACTUAL state and bufferedCalls
    straight from /actuator/circuitbreakers and asserts both are clean. Fails closed --
    an unreachable service counts as a failure, not a pass.

    Two independent checks, because they catch different failures:
      * state != CLOSED       -- the reset didn't take, or something re-tripped it
        between the reset call and this read.
      * bufferedCalls != 0    -- on a genuinely fresh container this is always 0.
        Non-zero is the direct test of whether force-recreate is doing what
        update_containers()'s docstring assumes: a breaker can already read CLOSED
        again (Resilience4j resets bufferedCalls per sliding-window slot, not just on
        state transitions) while still carrying calls from the PRIOR run's window --
        state alone would miss that carryover.
    """
    cb_state = {}
    buffered_calls = {}
    fail_reasons = []

    for service, (port, breakers) in SERVICE_BREAKERS.items():
        details = _get_circuit_breakers(port)
        cb_state[service] = {}
        buffered_calls[service] = {}
        for breaker in breakers:
            info = details.get(breaker)
            if info is None:
                cb_state[service][breaker] = "UNREACHABLE"
                buffered_calls[service][breaker] = "UNREACHABLE"
                fail_reasons.append(f"{service}:{breaker}=UNREACHABLE")
                continue
            state = info.get("state", "UNKNOWN")
            buffered = info.get("bufferedCalls", -1)
            cb_state[service][breaker] = state
            buffered_calls[service][breaker] = buffered
            if state != "CLOSED":
                fail_reasons.append(f"{service}:{breaker}=state:{state}")
            if buffered != 0:
                fail_reasons.append(f"{service}:{breaker}=buffered:{buffered}")

    return {
        "ok": not fail_reasons,
        "fail_reason": "; ".join(fail_reasons),
        "cb_state": cb_state,
        "buffered_calls": buffered_calls,
    }

# _fetch_breaker_events, snapshot_breaker_event_counts, collect_new_transitions, and
# log_cb_transitions moved to breaker_observer.py's BreakerObserver class (D12
# architecture cleanup) -- they had no callers outside run_experiment_run below, and
# all 3 of this session's real CB-observation bugs lived in the gap between these
# being separate free functions with no single owner. See breaker_observer.py.

# ---- Real (request-level) blast radius (Task 2) ------------------------------
# The legacy get_blast_radius() above measures breaker STATE (% of services with an OPEN
# CB). A service can fail every request with its breaker still CLOSED and score 0% there.
# The functions below instead measure REAL observed failures per leg, from Resilience4j
# call-outcome counters (failed + not_permitted vs successful) -- actual call results, not
# the OPEN/CLOSED state. not_permitted (calls short-circuited by an OPEN breaker) is counted
# as damage: the canary showed that omitting it made latency faults read 0% real blast
# radius despite 70-94% gateway error rate. See docs/proposals/blast-radius-redefinition.md.

def _get_cb_metric_count(base_url, metric, kind):
    """Sum of a resilience4j circuit-breaker COUNT metric across a service's CB instances,
    filtered by kind, via its actuator metrics endpoint. Returns float, or None if
    unreachable / metric absent."""
    url = f"{base_url}/actuator/metrics/{metric}?tag=kind:{kind}"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                for m in data.get("measurements", []):
                    if m.get("statistic") == "COUNT":
                        return float(m.get("value", 0.0))
    except Exception:
        pass  # metric absent / service unreachable -> None (not measurable), never fabricate
    return None

def snapshot_cb_calls():
    """Per-service cumulative call outcomes from Resilience4j counters:
      success  = calls{kind=successful}   (includes slow-but-completed calls)
      failed   = calls{kind=failed}       (recorded exceptions)
      rejected = not.permitted.calls      (calls short-circuited while the breaker is OPEN)
    'ignored' calls (business 4xx rejections) are deliberately excluded -- they are not
    infrastructure failures. Returns {service: {...}} or {service: None} when a service
    exposes no CB metric / is unreachable."""
    snap = {}
    for svc, base in CB_METRIC_TARGETS.items():
        success = _get_cb_metric_count(base, "resilience4j.circuitbreaker.calls", "successful")
        failed = _get_cb_metric_count(base, "resilience4j.circuitbreaker.calls", "failed")
        rejected = _get_cb_metric_count(base, "resilience4j.circuitbreaker.not.permitted.calls", "not_permitted")
        snap[svc] = None if (success is None and failed is None and rejected is None) else {
            "success": success or 0.0, "failed": failed or 0.0, "rejected": rejected or 0.0}
    return snap

def compute_leg_failure_rates(before, after):
    """Per-leg failure rate over the fault window, for each CB leg that was exercised and
    measurable in both snapshots: {service: rate_0_to_1}.

        leg_failure_rate = (failed + rejected(not_permitted)) / (successful + failed + rejected)

    A call short-circuited by an OPEN breaker never reached the downstream, so from the
    caller's perspective it is propagated failure, not success; slow-but-completed calls stay
    success. This RAW per-leg breakdown is persisted (leg_failure_rates column) so
    real_blast_radius can be recomputed at ANY TAU_LEG straight from the CSV -- no need to
    re-run the 324-run sweep if the threshold changes after sign-off. Returns {} if nothing
    observable (measurement gap). See docs/proposals/blast-radius-redefinition.md."""
    rates = {}
    if not before or not after:
        return rates
    for svc in CB_METRIC_TARGETS:
        b, a = before.get(svc), after.get(svc)
        if not b or not a:
            continue  # leg not measurable this run
        d_success = max(a["success"] - b["success"], 0.0)
        d_failed = max(a["failed"] - b["failed"], 0.0)
        d_rejected = max(a["rejected"] - b["rejected"], 0.0)
        total = d_success + d_failed + d_rejected
        if total <= 0:
            continue  # leg not exercised during the window
        rates[svc] = (d_failed + d_rejected) / total
    return rates


def real_blast_radius_from_rates(rates, tau=REAL_BLAST_LEG_ERROR_THRESHOLD):
    """Fraction (0.0-1.0, same scale as the normalised blast_radius) of observed legs whose
    failure rate exceeded tau. Returns None if no leg was observable -- a meaningful null,
    never a fabricated 0.0."""
    if not rates:
        return None
    return sum(1 for r in rates.values() if r > tau) / len(rates)


def compute_real_blast_radius(before, after, tau=REAL_BLAST_LEG_ERROR_THRESHOLD):
    """Convenience: leg failure rates -> scalar real blast radius. Derived from
    compute_leg_failure_rates so the scalar and the persisted raw column never disagree."""
    return real_blast_radius_from_rates(compute_leg_failure_rates(before, after), tau)

def make_experiment_id(topology, fault_type, config, toxicity=1.0, inject_point=None, mode=None):
    """Builds a deterministic ID matching experiment_matrix.csv e.g. LIN-LAT-CNT-T50-W10-D15.

    toxicity/inject_point default to the values every historical run implicitly used
    (full toxicity, no override), so every existing ID is byte-identical unless a
    caller explicitly varies one of these -- same "appended conditionally" contract
    as the -M/-L suffixes below. Passing the real per-run values here (not just for
    display) is what makes resumability's (experiment_id, replicate) key actually
    distinguish e.g. two crash-toxicity-sweep invocations at different --toxicity.

    mode gates the -M/-L suffix below by the actual mode string, not by config's
    shape -- every config now carries minimumNumberOfCalls/targetRps unconditionally
    (see generate_combinations), so key-presence can no longer signal "is this
    occupancy" without appending -M/-L to every full/canary/sweep ID too."""
    topo_map  = {"linear": "LIN", "fanout": "FAN", "mesh": "MSH"}
    fault_map = {"latency": "LAT", "crash": "CRS", "none": "NON"}
    wtype_map = {"COUNT_BASED": "CNT", "TIME_BASED": "TIM"}
    topo  = topo_map.get(topology, topology[:3].upper())
    fault = fault_map.get(fault_type, fault_type[:3].upper())
    wtype = wtype_map.get(config["slidingWindowType"], config["slidingWindowType"][:3])
    experiment_id = (f"{topo}-{fault}-{wtype}"
                      f"-T{config['failureRateThreshold']}"
                      f"-W{config['slidingWindowSize']}"
                      f"-D{config['waitDurationInOpenState']}")
    # -M/-L only apply to mode="occupancy" (minimumNumberOfCalls/targetRps are swept
    # there); appended conditionally on mode so every other mode's IDs are unchanged.
    if mode == "occupancy":
        experiment_id += f"-M{config['minimumNumberOfCalls']}"
        experiment_id += f"-L{int(config['targetRps'])}"
    # -X only when toxicity deviates from every historical run's implicit 1.0 (full
    # outage) -- e.g. distinct --toxicity 0.3 vs 0.6 crash-sweep invocations.
    if toxicity != 1.0:
        experiment_id += f"-X{toxicity}"
    # -I only when an explicit/effective inject_point overrides the fault-type default
    # (see resolve_inject_point) -- short-code matches the topo/fault/wtype 3-letter style.
    if inject_point is not None:
        experiment_id += f"-I{inject_point[:3].upper()}"
    return experiment_id

def _now_iso():
    """UTC timestamp in the same format log_results() uses for run_timestamp,
    so the dashboard can compare run_status.json times without a tz mismatch."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def write_status(status):
    """Atomically writes sweep progress to data/run_status.json for the dashboard's
    /live route to poll. Writes to a .tmp file in the same directory, then
    os.replace()'s it into place, so readers never observe a partial write."""
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    tmp_path = str(STATUS_PATH) + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp_path, STATUS_PATH)

def get_dataset_path(mode):
    """canary writes to a disposable file, sweep/occupancy write to their own isolated
    files, and full writes to the real research dataset."""
    if mode == "canary":
        return CANARY_DATASET_PATH
    if mode == "sweep":
        return SWEEP_DATASET_PATH
    if mode == "occupancy":
        return OCCUPANCY_DATASET_PATH
    return DATASET_PATH

def _fmt(metrics, key, decimals=4):
    """Format metrics[key] to `decimals` places, or "" if absent/None -- the
    write-blank-not-fabricate-zero convention every numeric column in
    log_results' row dict follows."""
    val = metrics.get(key)
    return f"{val:.{decimals}f}" if val is not None else ""


def log_results(config, fault_type, mode, topology, metrics, replicate, machine_id=""):
    """Appends experiment run results to master_dataset.csv (full mode), canary_runs.csv
    (canary mode), crash_toxicity_sweep.csv (sweep mode -- DATASET_HEADERS plus
    injected_toxicity), or occupancy_dataset.csv (occupancy mode -- DATASET_HEADERS plus
    occupancy_ratio/inert). Both extensions are kept out of the master schema.

    metrics only needs to carry the keys a given call actually has: a
    PRECONDITION_FAIL row (aborted before fault injection, before warmup even
    runs) passes just the precondition_* / readiness_wait_s / cb_state_pre /
    buffered_calls_pre / run_order_seed / run_index keys, and every outcome
    column below (blast_radius, error_rate, warmup_requests, ...) is written
    blank rather than KeyError-ing or fabricating a 0.0. run_order_seed and
    run_index are the two exceptions expected on every row regardless of
    outcome -- a run's position in the shuffled execution order is known the
    moment it starts, independent of what happens during it.

    machine_id (D14) is the same kind of exception, but arrives as an argument
    rather than through metrics: it comes from --machine-id and describes the
    host, not the run, so it is known before the run starts and is written on
    abort rows too. Passed explicitly rather than left to append_row's
    restval="" blank-fill -- but an omitted flag is not left blank either: it
    falls back to MACHINE_ID's own auto-detection (D6), so a row only goes
    blank if MACHINE_ID's own hostname lookup fails too, never merely because
    --machine-id wasn't passed.

    The header-mismatch guard now lives in resumable_runner.load_completed(),
    called once at the top of main() -- a mismatch there raises SystemExit
    (loud, before any run starts) instead of this function silently refusing
    to write per-row (the bug that ate the occupancy-ratio run: a stale
    on-disk header made every call here a no-op while the sweep kept
    "succeeding"). A row is only added to completed_runs when
    precondition_ok is True -- an aborted run (READINESS_TIMEOUT,
    PRECONDITION_FAIL) carries no real measurement and must stay eligible
    for a real attempt on the next resume, not get permanently stuck."""
    dataset_path = get_dataset_path(mode)
    if mode == "sweep":
        headers = SWEEP_DATASET_HEADERS
    elif mode == "occupancy":
        headers = OCCUPANCY_DATASET_HEADERS
    else:
        headers = DATASET_HEADERS
    os.makedirs(os.path.dirname(dataset_path), exist_ok=True)

    experiment_id = make_experiment_id(
        topology, fault_type, config,
        metrics.get("injected_toxicity", 1.0), metrics.get("inject_point"), mode)
    time_to_open = metrics.get("time_to_open")
    time_to_recover = metrics.get("time_to_recover")
    # --machine-id wins when passed; omitting it falls back to MACHINE_ID's own
    # auto-detection (env var or hostname, see MACHINE_ID's definition) rather than
    # going blank -- a bare "" here would silently defeat the whole point of
    # auto-detecting in the first place (D6/D14).
    effective_machine_id = machine_id or MACHINE_ID

    row = {
        "experiment_id": experiment_id,
        "topology": topology.upper(),
        "fault_type": fault_type.upper(),
        "window_type": config["slidingWindowType"],
        "threshold": config["failureRateThreshold"],
        "window_size": config["slidingWindowSize"],
        "wait_duration": config["waitDurationInOpenState"],
        "permitted_calls_half_open": PERMITTED_CALLS_HALF_OPEN,
        "environment": ENVIRONMENT,
        "mode": mode,
        "replicate": replicate,
        "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blast_radius": _fmt(metrics, "blast_radius"),
        "time_to_open": time_to_open if time_to_open is not None else "",   # "" = CB never opened (meaningful null)
        "time_to_recover": time_to_recover if time_to_recover is not None else "",  # "" = system did not recover (meaningful null)
        "error_rate": _fmt(metrics, "error_rate"),
        "throughput_loss": _fmt(metrics, "throughput_loss"),
        "real_blast_radius": _fmt(metrics, "real_blast_radius"),  # "" = no leg observable (measurement gap)
        "leg_failure_rates": ";".join(f"{svc}:{rate:.4f}" for svc, rate in (metrics.get('leg_failure_rates') or {}).items()),  # raw per-leg rates; "" = none observed
        "precondition_ok": metrics.get("precondition_ok", ""),
        "precondition_fail_reason": metrics.get("precondition_fail_reason", ""),
        "readiness_wait_s": _fmt(metrics, "readiness_wait_s", 3),
        "cb_state_pre": metrics.get("cb_state_pre", ""),
        "buffered_calls_pre": metrics.get("buffered_calls_pre", ""),
        "warmup_requests": metrics.get("warmup_requests", ""),
        "warmup_duration_s": _fmt(metrics, "warmup_duration_s", 3),
        "run_order_seed": metrics.get("run_order_seed", ""),
        "run_index": metrics.get("run_index", ""),
        "lambda_target": _fmt(metrics, "lambda_target"),
        "lambda_achieved": _fmt(metrics, "lambda_achieved"),
        "lambda_cv": _fmt(metrics, "lambda_cv"),
        "lambda_deviation_flag": metrics.get("lambda_deviation_flag") if metrics.get("lambda_deviation_flag") is not None else "",
        "effective_horizon": _fmt(metrics, "effective_horizon"),
        "machine_id": effective_machine_id,  # --machine-id if passed, else auto-detected MACHINE_ID (D14/D6)
        "excluded_reason": "",  # always empty at write time; only analysis/quarantine.py fills it
    }
    if mode == "sweep":
        row["injected_toxicity"] = _fmt(metrics, "injected_toxicity")
    elif mode == "occupancy":
        occupancy_ratio = compute_occupancy_ratio(metrics.get("effective_horizon"), config["minimumNumberOfCalls"])
        row["occupancy_ratio"] = f"{occupancy_ratio:.4f}" if occupancy_ratio is not None else ""
        # inert: observed signal -- True when the breaker never opened AND the lambda
        # measurement is trustworthy. Blank when lambda_deviation_flag is set (rate
        # measurement unreliable) or unmeasured (aborted run) -- never fabricated from an
        # untrustworthy or missing rate. This is what H2's inertness boundary (does
        # `inert` flip to True at occupancy_ratio*=1?) is regressed against.
        lambda_deviation_flag = metrics.get("lambda_deviation_flag")
        if lambda_deviation_flag is None or lambda_deviation_flag:
            row["inert"] = ""
        else:
            row["inert"] = time_to_open is None

    append_row(dataset_path, row, headers)
    if metrics.get("precondition_ok") is True:
        completed_runs.add((experiment_id, str(replicate)))
    print(f"Saved run metrics to {dataset_path}")

def run_experiment_run(config, fault_type, mode, topology="linear", replicate=1,
                        run_order_seed=None, run_index=None, toxicity=1.0,
                        machine_id="", inject_point=None):
    """Orchestrates a single configuration and fault run.

    run_order_seed/run_index describe this run's place in the sweep's shuffled
    execution order (see main()) -- attached to every log_results call in this
    function, including both abort paths, so a run's position is recoverable
    even when it never got far enough to produce an outcome. machine_id (D14)
    is threaded the same way and for the same reason: which host produced a row
    is exactly as recoverable on an aborted run as on a completed one."""
    print("\n" + "="*60)
    print(f"STARTING EXPERIMENT: Mode={mode}, Topology={topology}, Fault={fault_type}, Replicate={replicate}")
    print(f"Config: {config}")
    print("="*60)

    # Resolved once, up front -- pure function of (inject_point, mode), no I/O -- so
    # every log_results call below (both abort paths and the success path) records
    # the same effective value make_experiment_id needs for resumability to actually
    # distinguish runs at a non-default inject point.
    effective_inject_point = resolve_inject_point(inject_point, mode)

    # 1. Update environments
    write_env_file(config)
    if not update_containers():
        print("Skipping run due to Docker compose failure.", file=sys.stderr)
        return False

    # 2. Verify all six containers came up -- including shared-db-service, which has
    #    no breaker of its own but sits in every call chain (see wait_for_readiness).
    all_ready, readiness_wait_s = wait_for_readiness()
    if not all_ready:
        print("Skipping run: not all six services became healthy within the readiness deadline.",
              file=sys.stderr)
        log_results(config, fault_type, mode, topology, {
            "precondition_ok": False,
            "precondition_fail_reason": "READINESS_TIMEOUT",
            "readiness_wait_s": readiness_wait_s,
                        "run_order_seed": run_order_seed,
            "run_index": run_index,
            "injected_toxicity": toxicity,
        }, replicate, machine_id=machine_id)
        return False

    # 2b. Breaker-state-reset precondition (see the "Breaker-state-reset precondition"
    #    block above get_blast_radius() for the full rationale). update_containers()
    #    already force-recreates every container every run, which SHOULD reset
    #    Resilience4j's in-memory registry to CLOSED -- this makes that explicit via
    #    the actuator instead of trusting it blindly, then verifies the result before
    #    any fault is injected. A run that fails this check measures nothing real and
    #    is aborted rather than silently recorded as if it started clean.
    reset_all_breakers()
    precondition = check_breaker_precondition()
    if not precondition["ok"]:
        print(f"PRECONDITION_FAIL: {precondition['fail_reason']}", file=sys.stderr)
        log_results(config, fault_type, mode, topology, {
            "precondition_ok": False,
            "precondition_fail_reason": precondition["fail_reason"],
            "readiness_wait_s": readiness_wait_s,
            "cb_state_pre": _serialize_cb_map(precondition["cb_state"]),
            "buffered_calls_pre": _serialize_cb_map(precondition["buffered_calls"]),
                        "run_order_seed": run_order_seed,
            "run_index": run_index,
            "injected_toxicity": toxicity,
        }, replicate, machine_id=machine_id)
        return False

    # Snapshot each interior breaker's actuator ring buffer before the fault, via
    # BreakerObserver (breaker_observer.py) -- this is what actually answers "did
    # order's breaker open", which error_rate/blast_radius cannot (see
    # SERVICE_BREAKERS docstring above).
    endpoint = f"http://localhost:8080/api/v1/{topology}"
    observer = BreakerObserver(SERVICE_BREAKERS, endpoint, PERMITTED_CALLS_HALF_OPEN,
                                get_blast_radius_fn=get_blast_radius)
    before_cb_counts = observer.snapshot_before()

    # 2c. JIT warmup (discard phase) -- BEFORE the baseline measurement below, so
    #    that measurement isn't itself contaminated by cold-JVM artifacts. See the
    #    "JIT warmup" comment block near LOAD_RATE_RPS for the full rationale.
    warmup_requests, warmup_duration_s = warmup_phase(endpoint)

    # 3. Measure pre-fault baseline throughput (against an already-warm JVM)
    print("Measuring pre-fault baseline...")
    baseline_throughput, _, _, _, _ = generate_load(endpoint, requests_count=20, concurrency=3)
    if baseline_throughput <= 0:
        print("Baseline throughput is zero — mesh unhealthy pre-fault, skipping run.", file=sys.stderr)
        return False

    # 4. Inject fault into Toxiproxy
    fault_injected_at = _now_iso()
    # Sweep mode retargets crash to inventory-service-proxy (the same target latency
    # uses) so mechanism, not service position, is the only thing varying -- unless the
    # caller explicitly asked for a different --inject-point, which wins over that default.
    # (effective_inject_point resolved once, near the top of this function.)
    try:
        inject_fault(fault_type, toxicity=toxicity, inject_point=effective_inject_point)
    except Exception as e:
        print(f"Fault injection failed: {e} — skipping run.", file=sys.stderr)
        toxiproxy.reset_all()
        return False

    # 5. Size the fault load per window type so TIME_BASED windows can actually fill
    #    (Task 1). Snapshot per-leg CB call counters just before the fault window so the
    #    real (request-level) blast radius is a clean delta over the window (Task 2).
    #    config['targetRps'] is normalized onto every config by generate_combinations.
    plan = compute_load_plan(config, target_rps=config["targetRps"], topology=topology, mode=mode)
    print(f"Load plan ({config['slidingWindowType']}): {plan['requests_count']} requests "
          f"over ~{plan['duration_s']:.0f}s @ {plan['target_rps']} req/s")
    cb_calls_before = snapshot_cb_calls()

    # Sample blast radius mid-load via a thread so the CB is still OPEN (not recovering)
    # when we read it. The sampling window tracks the (now variable) load duration so
    # longer TIME_BASED runs are covered, not cut off at a fixed 12s.
    cb_open_at = [None]           # wall-clock time when CB first opened (for time_to_open)
    blast_radius_container = [None]
    sample_deadline_s = plan["duration_s"] + TIME_BASED_MARGIN_S

    def _sample_blast_radius():
        # Poll until blast_radius > 0 (CB has opened) or the load window elapses.
        # NOTE: time_to_open is stamped at poll-success time, not the true CB open
        # event, so it carries up to ~1 poll-interval + HTTP timeout of upward bias.
        # A precise value needs a Resilience4j CB event listener; this poll cadence
        # keeps that bias small rather than eliminating it. The deadline tracks the
        # (variable) load duration so longer TIME_BASED runs aren't cut off at 12s.
        deadline = time.time() + sample_deadline_s
        while time.time() < deadline:
            time.sleep(0.2)
            result = get_blast_radius()
            if result is not None and result > 0.0:
                blast_radius_container[0] = result
                cb_open_at[0] = time.time()   # record when we first saw an open CB
                return
        # Final read after the deadline: for latency faults, each request
        # can take 3-5s, so the CB may not trip until after the 12s poll window.
        # If this read finds a nonzero blast radius, stamp cb_open_at here too —
        # otherwise we'd write a row with blast_radius > 0 but time_to_open = null,
        # a logically impossible combination that corrupts the ML outcome columns.
        final = get_blast_radius()
        if final is None and blast_radius_container[0] is None:
            # Every poll returned None — gateway was unreachable throughout the
            # trip window.  Leave blast_radius_container[0] as None so the run
            # is aborted below rather than written as a fabricated healthy row.
            return
        blast_radius_container[0] = final if final is not None else 0.0
        if final is not None and final > 0.0:
            cb_open_at[0] = time.time()

    sampler = threading.Thread(target=_sample_blast_radius, daemon=True)
    sampler.start()
    load_start = time.time()   # reference for time_to_open (cb_open_at - load_start)
    throughput, error_rate, avg_latency, lambda_achieved, lambda_cv = generate_load(
        endpoint, requests_count=plan["requests_count"],
        concurrency=plan["concurrency"], interval_s=plan["interval_s"])
    sampler.join(timeout=sample_deadline_s + 5)

    # Nominal-vs-achieved rate divergence check (see the "lambda_target/lambda_achieved"
    # comment block in DATASET_HEADERS). lambda_target is this run's requested rate;
    # lambda_deviation_flag stays None (not False) when lambda_achieved couldn't be
    # measured at all, rather than fabricating a "no deviation" reading.
    lambda_target = plan["target_rps"]
    lambda_deviation_flag = compute_lambda_deviation_flag(lambda_achieved, lambda_target)
    if lambda_deviation_flag:
        print(
            f"WARNING: achieved arrival rate {lambda_achieved:.2f} req/s deviates "
            f"> {LAMBDA_DEVIATION_THRESHOLD*100:.0f}% from target {lambda_target} req/s "
            "-- offered load did not match the requested rate for this run.",
            file=sys.stderr,
        )

    # Effective horizon H: calls actually available to the sliding window (see
    # compute_effective_horizon docstring). Diagnoses TIME_BASED windows that never
    # filled -- distinct from, and a likely cause of, a spuriously "safe" reading.
    effective_horizon = compute_effective_horizon(
        config["slidingWindowType"], config["slidingWindowSize"], lambda_achieved)
    n_min_for_horizon = config["minimumNumberOfCalls"]
    if effective_horizon is not None and effective_horizon < n_min_for_horizon:
        print(
            f"WARNING: effective horizon {effective_horizon:.2f} calls < "
            f"minimumNumberOfCalls ({n_min_for_horizon}) -- the sliding window likely never "
            "filled enough to evaluate the breaker during this run.",
            file=sys.stderr,
        )

    # Snapshot per-leg CB counters again at the end of the fault window (Task 2).
    cb_calls_after = snapshot_cb_calls()
    leg_failure_rates = compute_leg_failure_rates(cb_calls_before, cb_calls_after)
    real_blast_radius = real_blast_radius_from_rates(leg_failure_rates)

    blast_radius = blast_radius_container[0]
    # Bug #3 guard: if every blast-radius poll returned None the gateway was
    # unreachable for the entire trip window.  Writing a 0.0 blast row here
    # would fabricate a "healthy mesh" observation — abort instead.
    if blast_radius is None:
        print(
            "Blast radius measurement failed (gateway unreachable throughout trip window) "
            "— aborting run to avoid writing a fabricated healthy-mesh row.",
            file=sys.stderr,
        )
        toxiproxy.reset_all()
        return False

    # Determine whether a circuit breaker actually opened during this run.
    # Used to gate the recovery-phase timing so we never write a row with
    # time_to_open=null but time_to_recover=non-null (logically impossible).
    cb_opened = cb_open_at[0] is not None

    # 6. Reset Toxiproxy
    toxiproxy.reset_all()
    fault_cleared_at = _now_iso()

    # 7. Measure time_to_open and time_to_recover.
    #    time_to_open is ONLY computed when a breaker was confirmed open
    #    (cb_opened=True) -- running that computation unconditionally would
    #    produce the corrupt combination: time_to_open=null + a real value.
    #    time_to_recover's observation (the poll loop + HALF_OPEN probe-driving,
    #    now owned by BreakerObserver -- see breaker_observer.py for the full
    #    rationale) is delegated unconditionally: it internally skips the
    #    poll/probe steps when cb_open_at is None, but ALWAYS collects real
    #    transitions regardless of cb_opened -- an interior breaker can trip via
    #    the slow-call path while the aggregate blast_radius signal still reads
    #    "safe", and catching that is this sidecar's entire point.
    time_to_open = None
    if cb_opened:
        time_to_open = round(cb_open_at[0] - load_start, 3)

    time_to_recover, transitions = observer.observe_recovery(
        before_cb_counts, cb_open_at[0], config["waitDurationInOpenState"])

    # 8. Save results
    throughput_loss = max(0.0, 1.0 - (throughput / baseline_throughput))
    metrics = {
        "blast_radius": blast_radius,                 # normalised 0.0-1.0 by get_blast_radius()
        "real_blast_radius": real_blast_radius,       # Task 2: fraction of legs failing real requests
        "leg_failure_rates": leg_failure_rates,       # raw per-leg rates (for post-hoc TAU_LEG)
        "throughput_loss": throughput_loss,
        "error_rate": error_rate / 100.0,   # convert % → fraction
        "avg_latency_ms": avg_latency,
        "time_to_open": time_to_open,
        "time_to_recover": time_to_recover,
        "precondition_ok": True,
        "precondition_fail_reason": "",
        "readiness_wait_s": readiness_wait_s,
        "cb_state_pre": _serialize_cb_map(precondition["cb_state"]),
        "buffered_calls_pre": _serialize_cb_map(precondition["buffered_calls"]),
        "warmup_requests": warmup_requests,
        "warmup_duration_s": warmup_duration_s,
        "run_order_seed": run_order_seed,
        "run_index": run_index,
        "lambda_target": lambda_target,
        "lambda_achieved": lambda_achieved,
        "lambda_cv": lambda_cv,
        "lambda_deviation_flag": lambda_deviation_flag,
        "effective_horizon": effective_horizon,
        "injected_toxicity": toxicity,
        "inject_point": effective_inject_point,
    }
    log_results(config, fault_type, mode, topology, metrics, replicate, machine_id=machine_id)

    # transitions already collected above (observer.observe_recovery), regardless of
    # what blast_radius/cb_opened concluded -- catching the case where the aggregate
    # signal says "nothing opened" but an interior breaker tripped via the slow-call
    # path is the entire point of this sidecar.
    cb_transitions_path = CANARY_CB_TRANSITIONS_PATH if mode == "canary" else CB_TRANSITIONS_PATH
    observer.log(cb_transitions_path, make_experiment_id(topology, fault_type, config, mode=mode),
                 topology, fault_type, config, mode, replicate,
                 fault_injected_at, fault_cleared_at, transitions)
    return True

def generate_occupancy_combinations():
    """Occupancy-ratio study (D7 -- lambda is a variable the theory is about, not a
    single fixed value). Isolated from the main matrix: LINEAR + LATENCY only (set by
    the CLI, not this function); failureRateThreshold and waitDurationInOpenState held
    fixed since they aren't part of the occupancy story -- only window_size x
    minimumNumberOfCalls x targetRps (lambda) vary.

    54 unique configs: 36 TIME_BASED cells (3 lambda x 3 window x 4 n_min) + 18
    COUNT_BASED control cells (2 lambda x 3 window x 3 n_min). COUNT_BASED already
    fills/trips regardless of arrival rate (its window is calls, not wall-clock time),
    so it's swept narrower here purely as a negative control on H2's inertness claim,
    not as a symmetric arm."""
    combos = []
    fixed_threshold = 50
    fixed_wait = 15
    # TIME_BASED phase grid: lambda x window x n_min = 3*3*4 = 36 cells
    for rps in (5, 10, 20):
        for window in (5, 10, 20):
            for n_min in (5, 50, 100, 200):
                combos.append({
                    "failureRateThreshold": fixed_threshold, "slidingWindowSize": window,
                    "waitDurationInOpenState": fixed_wait, "slidingWindowType": "TIME_BASED",
                    "minimumNumberOfCalls": n_min, "targetRps": rps,
                })
    # COUNT_BASED control arm: lambda x window x n_min = 2*3*3 = 18 cells
    for rps in (5, 20):
        for window in (5, 10, 20):
            for n_min in (5, 50, 200):
                combos.append({
                    "failureRateThreshold": fixed_threshold, "slidingWindowSize": window,
                    "waitDurationInOpenState": fixed_wait, "slidingWindowType": "COUNT_BASED",
                    "minimumNumberOfCalls": n_min, "targetRps": rps,
                })
    return combos

def generate_combinations(mode):
    """Generates configuration combinations depending on the mode.

    Every returned config carries minimumNumberOfCalls/targetRps (defaulted for
    canary/full/sweep, swept explicitly by occupancy) so downstream code never
    has to re-derive "is this an occupancy config" from dict-key presence."""
    if mode == "occupancy":
        configs = generate_occupancy_combinations()
        return _with_config_defaults(configs)

    configs = []

    if mode == "canary":
        # 5 representative configs spanning the parameter space (aggressive, conservative, midpoint)
        configs = [
            # Extreme Aggressive
            {"failureRateThreshold": 30, "slidingWindowSize": 5, "waitDurationInOpenState": 5, "slidingWindowType": "COUNT_BASED"},
        {"failureRateThreshold": 30, "slidingWindowSize": 5, "waitDurationInOpenState": 5, "slidingWindowType": "TIME_BASED"},
            # Extreme Conservative
            {"failureRateThreshold": 70, "slidingWindowSize": 20, "waitDurationInOpenState": 30, "slidingWindowType": "COUNT_BASED"},
            {"failureRateThreshold": 70, "slidingWindowSize": 20, "waitDurationInOpenState": 30, "slidingWindowType": "TIME_BASED"},
            # Midpoint config
            {"failureRateThreshold": 50, "slidingWindowSize": 10, "waitDurationInOpenState": 15, "slidingWindowType": "COUNT_BASED"},
        ]
    elif mode == "sweep":
        # Crash toxicity sweep: window_type/window_size/wait fixed at the canonical
        # midpoint config so toxicity is the only thing varying run-to-run; only
        # failureRateThreshold varies here (the second swept factor, alongside
        # --toxicity). [20, 40, 60, 80] is provisional -- confirm before the real
        # Phase 4 run.
        configs = [
            {"failureRateThreshold": t, "slidingWindowSize": 10, "waitDurationInOpenState": 15, "slidingWindowType": "COUNT_BASED"}
            for t in [20, 40, 60, 80]
        ]
    else:
        # Full Sweep: 3*3*3*2 = 54 configs per fault × 2 faults × 3 replicates = 324 total runs
        for threshold in PARAM_VALUES["failureRateThreshold"]:
            for window in PARAM_VALUES["slidingWindowSize"]:
                for wait in PARAM_VALUES["waitDurationInOpenState"]:
                    for wtype in PARAM_VALUES["slidingWindowType"]:
                        configs.append({
                            "failureRateThreshold": threshold,
                            "slidingWindowSize": window,
                            "waitDurationInOpenState": wait,
                            "slidingWindowType": wtype,
                        })
    return _with_config_defaults(configs)


def _with_config_defaults(configs):
    """Defaults minimumNumberOfCalls/targetRps onto every config that doesn't
    already set them (occupancy configs set both explicitly and are unaffected).
    Called once, at generate_combinations' return points, so write_env_file,
    compute_load_plan, log_results, run_experiment_run, and make_experiment_id
    can all read config["minimumNumberOfCalls"]/config["targetRps"] directly
    instead of independently re-deriving "is this occupancy" from key presence."""
    for config in configs:
        config.setdefault("minimumNumberOfCalls", CB_MINIMUM_CALLS)
        config.setdefault("targetRps", LOAD_RATE_RPS)
    return configs

def build_shuffled_run_list(configs, replicates, seed=None):
    """Builds the full (config_index, config, replicate) run list and shuffles it
    with a dedicated random.Random instance (not the global random module, so
    nothing else in this process can perturb the sequence) -- sequential execution
    of a long sweep on one host confounds treatment (config) with thermal/memory
    drift over the sweep's wall-clock duration, so execution order must be
    decorrelated from config order.

    Returns (run_order_seed, run_list). If seed is None, a fresh seed is drawn from
    OS entropy (random.SystemRandom -- unpredictable and independent of any prior
    random.seed() call elsewhere) so each invocation gets a genuinely different
    order by default; the caller persists run_order_seed to every dataset row so
    the resulting order is reconstructable after the fact.
    """
    run_order_seed = seed if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
    run_list = [(i, config, rep) for i, config in enumerate(configs) for rep in range(1, replicates + 1)]
    random.Random(run_order_seed).shuffle(run_list)
    return run_order_seed, run_list


def apply_run_limit(run_list, limit):
    """Truncate an already-shuffled run_list to its first `limit` entries.

    Applied AFTER build_shuffled_run_list's shuffle, not before -- slicing an
    unshuffled list would always run the same handful of early configs (a
    biased sample), while slicing post-shuffle keeps --limit N a genuine
    random N-run subset of the full sweep, useful for a smoke test that
    should look like a real (if tiny) run rather than a hand-picked one.
    limit=None is not a valid input here; main() only calls this when the
    user passed --limit, so there is nothing to truncate to otherwise."""
    return run_list[:limit]

def _status_snapshot(args, total_configs, total_runs, started_at, success_runs, failed_runs,
                      phase, updated_at, **overrides):
    """Builds one write_status() dict. main()'s 4 call sites share this same shape,
    differing only in run_number/config_index/current_config/replicate/phase/
    updated_at (and the final call's skipped_runs) -- passed as overrides."""
    snapshot = {
        "mode": args.mode, "fault_type": args.fault, "topology": args.topology,
        "replicates": args.replicates, "total_configs": total_configs, "total_runs": total_runs,
        "success_runs": success_runs, "failed_runs": failed_runs,
        "phase": phase, "started_at": started_at, "updated_at": updated_at,
    }
    snapshot.update(overrides)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="CascadeShield Parameter Sweep Automation Runner")
    parser.add_argument("--mode", choices=["canary", "full", "sweep", "occupancy"], default="canary",
                         help="canary (5 configs × 3 replicates = 15 runs), full (54 configs × 3 replicates "
                              "= 162 runs per fault type; 324 total across 2 faults), sweep (crash toxicity "
                              "sweep -- writes to data/crash_toxicity_sweep.csv, not master; use with "
                              "--fault crash --toxicity), or occupancy (D7 lambda-sweep, 54 configs × "
                              "replicates -- writes to data/occupancy_dataset.csv, not master; use with "
                              "--fault latency --topology linear)")
    parser.add_argument("--fault", choices=["latency", "crash", "none"], default="latency",
                         help="Fault type to inject. 'none' is the no-fault control condition -- "
                              f"requires --replicates >= {MIN_NONE_FAULT_REPLICATES} (see MIN_NONE_FAULT_REPLICATES).")
    parser.add_argument("--topology", choices=["linear", "fanout", "mesh"], default="linear", help="Service mesh topology pattern")
    parser.add_argument("--toxicity", type=float, default=1.0,
                         help="Fraction of connections affected by the crash fault's reset_peer toxic "
                              "(0.0-1.0). Only meaningful for --fault crash. Default 1.0 matches today's "
                              "full-outage crash behavior.")
    parser.add_argument("--inject-point", choices=INJECT_POINT_CHOICES, default=None,
                         help="Toxiproxy target for the fault (D4's supplementary check). Default: "
                              "inventory-service-proxy for --fault latency, payment-service-proxy for "
                              "--fault crash (inventory-service-proxy in --mode sweep). Passing this "
                              "overrides those mode/fault-type defaults for either fault type.")
    parser.add_argument("--replicates", type=int, default=N_REPLICATES, help=f"Number of replicates per config (default: {N_REPLICATES})")
    parser.add_argument("--seed", type=int, default=None,
                         help="Seed for the run-order shuffle (default: a fresh random seed each "
                              "invocation, printed and persisted to run_order_seed). Pass an explicit "
                              "value to reproduce a specific execution order.")
    parser.add_argument("--limit", type=int, default=None,
                         help="Cap the (already shuffled) run list to the first N runs -- e.g. "
                              "--limit 1 for a single-run smoke test instead of a full sweep. "
                              "Applied after shuffling, so it does not bias which config runs.")
    parser.add_argument("--machine-id", default="",
                         help="Label identifying which machine/Codespace produced this run's rows, "
                              "e.g. 'soham-codespace' or 'soham-local'. Written to the machine_id "
                              "column; falls back to MACHINE_ID's own auto-detection if omitted "
                              "(env var or hostname), not left blank.")

    args = parser.parse_args()

    # Enforced, not advisory: a no-fault sweep run below the floor produces a control
    # sample too thin to establish phi (the baseline false-trip rate), which is the entire
    # reason to collect it -- silently under-sampling here would defeat the point rather
    # than just being a smaller version of it.
    if args.fault == "none" and args.replicates < MIN_NONE_FAULT_REPLICATES:
        print(f"--fault none requires --replicates >= {MIN_NONE_FAULT_REPLICATES} "
              f"(got {args.replicates}). Every config needs enough no-fault replicates to "
              "establish a baseline false-trip rate -- a thinner control sample defeats the "
              "purpose of collecting it.", file=sys.stderr)
        sys.exit(1)

    print(f"Starting CascadeShield Runner in '{args.mode}' mode targeting '{args.topology}' topology with '{args.fault}' fault.")
    
    # Verify Toxiproxy is reachable
    try:
        toxiproxy.setup_default_proxies()
        toxiproxy.reset_all()
    except Exception:
        print("Toxiproxy is not running or unreachable on http://localhost:8474. Make sure Docker is running.", file=sys.stderr)
        sys.exit(1)
        
    configs = generate_combinations(args.mode)
    if args.mode == "canary" and CANARY_DATASET_PATH.exists():
        CANARY_DATASET_PATH.unlink()
        print(f"Cleared previous canary run data at {CANARY_DATASET_PATH}")
    if args.mode == "canary" and CANARY_CB_TRANSITIONS_PATH.exists():
        CANARY_CB_TRANSITIONS_PATH.unlink()
        print(f"Cleared previous canary CB transitions at {CANARY_CB_TRANSITIONS_PATH}")
    total_runs = len(configs) * args.replicates
    print(f"Generated {len(configs)} configs × {args.replicates} replicates = {total_runs} total runs.")

    # Resumability (D9): load whatever (experiment_id, replicate) pairs the dataset file
    # already has, once, up front. A header mismatch raises SystemExit here -- loudly,
    # before any run starts -- rather than log_results() silently refusing every write
    # while the loop keeps reporting "progress" (the bug that ate the occupancy run).
    global completed_runs
    dataset_path = get_dataset_path(args.mode)
    if args.mode == "sweep":
        dataset_headers = SWEEP_DATASET_HEADERS
    elif args.mode == "occupancy":
        dataset_headers = OCCUPANCY_DATASET_HEADERS
    else:
        dataset_headers = DATASET_HEADERS
    completed_runs = load_completed(dataset_path, dataset_headers)
    if completed_runs:
        print(f"Resuming {dataset_path}: {len(completed_runs)} (experiment_id, replicate) "
              "cell(s) already recorded and will be skipped.")

    # Randomize run order (see build_shuffled_run_list): sequential execution of a long
    # sweep on one host confounds treatment (config) with thermal/memory drift over the
    # sweep's wall-clock duration -- later configs would systematically run on a
    # warmer/more-fragmented host, biasing exactly the comparison the sweep exists to
    # make. run_index below is the run's position in this shuffled sequence, not its
    # position in configs.
    run_order_seed, run_list = build_shuffled_run_list(configs, args.replicates, args.seed)
    print(f"Run order shuffled with seed {run_order_seed} ({len(run_list)} runs). "
          f"Pass --seed {run_order_seed} to reproduce this exact order.")

    # Resumability filter runs BEFORE --limit, not after: filtering post-truncation
    # means an already-partly-done sweep's --limit N can pick N slots that are mostly
    # already-completed, silently executing fewer than N (sometimes 0) new runs while
    # still reporting success. Filtering first guarantees --limit N always means "up
    # to N new runs," matching what the flag says on the tin.
    effective_inject_point = resolve_inject_point(args.inject_point, args.mode)
    pending = []
    skipped_runs = 0
    for i, config, rep in run_list:
        experiment_id = make_experiment_id(args.topology, args.fault, config,
                                            args.toxicity, effective_inject_point, args.mode)
        if is_done(experiment_id, rep, completed_runs):
            print(f"Skipping: {experiment_id} replicate {rep} already in {dataset_path}.")
            skipped_runs += 1
        else:
            pending.append((i, config, rep))
    run_list = pending

    if args.limit is not None:
        run_list = apply_run_limit(run_list, args.limit)
        total_runs = len(run_list)
        print(f"--limit {args.limit}: truncated to {total_runs} new run(s) (post-shuffle, "
              f"post-resume-filter, so this does not bias which config gets run and always "
              f"means up to {args.limit} NEW runs, not {args.limit} raw slots).")
    else:
        total_runs = len(run_list)

    started_at = _now_iso()
    success_runs = 0
    failed_runs = 0
    write_status(_status_snapshot(
        args, len(configs), total_runs, started_at, 0, 0, "running", started_at,
        run_number=0, config_index=None, current_config=None, replicate=None))

    for run_index, (i, config, rep) in enumerate(run_list, start=1):
        run_number = run_index  # execution sequence position, not config/replicate order
        print(f"\nProgress: Run {run_number} of {total_runs} (config {i+1}/{len(configs)}, replicate {rep}/{args.replicates})")

        write_status(_status_snapshot(
            args, len(configs), total_runs, started_at, success_runs, failed_runs, "running", _now_iso(),
            run_number=run_number, config_index=i, current_config=config, replicate=rep))
        success = run_experiment_run(config, args.fault, args.mode, args.topology, replicate=rep,
                                      run_order_seed=run_order_seed, run_index=run_index,
                                      toxicity=args.toxicity, machine_id=args.machine_id,
                                      inject_point=args.inject_point)
        if success:
            success_runs += 1
        else:
            failed_runs += 1
        write_status(_status_snapshot(
            args, len(configs), total_runs, started_at, success_runs, failed_runs, "running", _now_iso(),
            run_number=run_number, config_index=i, current_config=config, replicate=rep))

    print("\n" + "="*60)
    print(f"SWEEP COMPLETED: {success_runs}/{total_runs} runs executed successfully "
          f"({skipped_runs} skipped as already-recorded on resume).")
    print(f"Master dataset: {get_dataset_path(args.mode)}")
    print("="*60)
    write_status(_status_snapshot(
        args, len(configs), total_runs, started_at, success_runs, failed_runs, "completed", _now_iso(),
        run_number=total_runs, config_index=len(configs) - 1 if configs else None,
        current_config=None, replicate=None, skipped_runs=skipped_runs))

if __name__ == "__main__":
    main()
