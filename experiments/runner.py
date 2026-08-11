import os
import sys
import time
import argparse
import subprocess
import csv
import random
import urllib.request
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fault_injector import ToxiproxyClient

# Toxiproxy Client
toxiproxy = ToxiproxyClient()

# Get project root directory dynamically
BASE_DIR = Path(__file__).resolve().parent.parent

# CSV Dataset Schema
DATASET_PATH = BASE_DIR / "data" / "master_dataset.csv"
CANARY_DATASET_PATH = BASE_DIR / "data" / "canary_runs.csv"
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
]

# How many replicates per config (min 3 for variance estimation)
N_REPLICATES = 3
ENVIRONMENT = os.environ.get("ENVIRONMENT", "LOCAL")  # override to AWS on cloud runs

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
CB_EVENT_BUFFER_SIZE = 50  # must match application.yml's event-consumer-buffer-size

# All six services in the call chain, for the readiness gate. shared-db-service has no
# circuit breaker of its own (see SERVICE_BREAKERS above) but every other service calls
# into it, so an unhealthy/still-starting shared-db silently corrupts every other
# service's measurements even though it never appears in SERVICE_BREAKERS.
ALL_SERVICE_PORTS = {
    "gateway": 8080, "order": 8081, "inventory": 8082,
    "payment": 8083, "notification": 8084, "shared-db": 8085,
}

# Configuration Parameter Values for Sweeps (3*3*3*2 = 54 configs per fault × 3 faults × 3 replicates = 486 total runs)
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
CB_MINIMUM_CALLS = 5  # fixed baseline, not swept (must be <= smallest slidingWindowSize)

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
#     diagnostics if needed — see GATEWAY_DIAGNOSTIC_TARGET — but keep it out of the count.)
#   * shared-db-service — a leaf with no outbound calls / no @CircuitBreaker, so it can
#     never have an open breaker and only dilutes the denominator.
# Ports are published by docker-compose.
CB_METRIC_TARGETS = {
    "order-service": "http://localhost:8081",
    "inventory-service": "http://localhost:8082",
    "payment-service": "http://localhost:8083",
    "notification-service": "http://localhost:8084",
}
# Optional diagnostics only — NEVER part of the real_blast_radius denominator.
GATEWAY_DIAGNOSTIC_TARGET = {"gateway-service": "http://localhost:8080"}
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
    """Writes the current R4J config parameters to the infra/.env file."""
    env_content = f"""# Auto-generated by CascadeShield Experiment Runner
CB_SLIDING_WINDOW_SIZE={config['slidingWindowSize']}
CB_SLIDING_WINDOW_TYPE={config['slidingWindowType']}
CB_FAILURE_RATE_THRESHOLD={config['failureRateThreshold']}
CB_WAIT_DURATION_OPEN={config['waitDurationInOpenState']}s
CB_PERMITTED_CALLS_HALF_OPEN={PERMITTED_CALLS_HALF_OPEN}
CB_EVENT_BUFFER_SIZE={CB_EVENT_BUFFER_SIZE}
CB_MINIMUM_CALLS={CB_MINIMUM_CALLS}
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

def inject_fault(fault_type):
    """Injects the appropriate fault profile into Toxiproxy."""
    toxiproxy.reset_all()
    
    if fault_type == "latency":
        # Inject high latency (3000ms) on inventory-service-proxy
        # This simulates a slow inventory downstream dependency
        toxiproxy.inject_latency("inventory-service-proxy", delay_ms=3000, toxicity=1.0)
        
    elif fault_type == "crash":
        # Disable payment-service-proxy completely (simulates a crashed instance)
        toxiproxy.set_enabled("payment-service-proxy", False)
        
    elif fault_type == "throttle":
        # Limit database proxy bandwidth to 1 KB/s (simulates DB connection/resource limits)
        toxiproxy.inject_bandwidth_limit("shared-db-service-proxy", rate_kbps=1, toxicity=1.0)
        
    else:
        print(f"No fault injected. Type '{fault_type}' is unknown.", file=sys.stderr)

def compute_load_plan(config):
    """Sizes the offered load per window type so both COUNT_BASED and TIME_BASED windows
    get a fair chance to fill, trip, sit OPEN, and transition to HALF_OPEN.

    See the "Load fairness (Task 1)" comment block near the top of this module for the
    rationale. Returns dict(requests_count, interval_s, concurrency, duration_s).
    """
    interval_s = 1.0 / LOAD_RATE_RPS
    window = int(config["slidingWindowSize"])
    wait = int(config["waitDurationInOpenState"])

    if config["slidingWindowType"] == "TIME_BASED":
        # Sustain load long enough for the trailing time-window (seconds) to fill, the
        # breaker to sit OPEN for wait_duration, and an automatic HALF_OPEN probe to fire.
        duration_s = window + wait + TIME_BASED_MARGIN_S
        requests_count = max(int(duration_s * LOAD_RATE_RPS), CB_MINIMUM_CALLS + 1)
    else:  # COUNT_BASED -- window is measured in calls
        requests_count = max(window * COUNT_BASED_WINDOW_MULTIPLE,
                             CB_MINIMUM_CALLS * 3, COUNT_BASED_MIN_REQUESTS)
        duration_s = requests_count * interval_s

    return {"requests_count": requests_count, "interval_s": interval_s,
            "concurrency": LOAD_CONCURRENCY, "duration_s": duration_s}


def generate_load(endpoint_url, requests_count=50, concurrency=5, interval_s=0.05):
    """Lightweight built-in HTTP load generator to test the mesh.

    requests_count requests are dispatched spaced by interval_s (steady offered rate),
    so the same function drives both the short baseline warm-up and the longer,
    duration-sized fault load (via compute_load_plan)."""
    print(f"Generating load: {requests_count} requests to {endpoint_url} "
          f"@ ~{1.0/interval_s:.0f} req/s (~{requests_count*interval_s:.1f}s dispatch)...")

    success_count = 0
    failure_count = 0
    latencies = []
    lock = threading.Lock()

    t0 = time.time()
    last_completion = t0  # updated by each request as it finishes

    def send_request():
        nonlocal success_count, failure_count, last_completion
        start = time.time()
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

    print(f"Load Results - Successes: {success_count}, Failures: {failure_count}, Avg Latency: {avg_latency:.2f}ms, Throughput: {throughput:.2f} TPS, Error Rate: {error_rate:.2f}%")
    return throughput, error_rate, avg_latency

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

def _fetch_breaker_events(port, breaker_name):
    """Raw STATE_TRANSITION events currently in `breaker_name`'s actuator ring
    buffer, oldest first. Returns [] on any failure -- this is diagnostic
    instrumentation and must never abort a run."""
    url = f"http://localhost:{port}/actuator/circuitbreakerevents/{breaker_name}"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Failed to fetch {breaker_name} CB events (port {port}): {e}", file=sys.stderr)
        return []
    return [e for e in data.get("circuitBreakerEvents", []) if e.get("type") == "STATE_TRANSITION"]

def snapshot_breaker_event_counts():
    """{(service, breaker): event count right now}, taken before the fault so
    collect_new_transitions() can slice off just the events this run adds.

    In practice each run's containers are force-recreated (see update_containers),
    so every breaker's ring buffer already starts empty -- this snapshot is a
    defensive baseline, not load-bearing, in case that recreate-per-run behavior
    ever changes.
    """
    return {
        (service, breaker): len(_fetch_breaker_events(port, breaker))
        for service, (port, breakers) in SERVICE_BREAKERS.items()
        for breaker in breakers
    }

def collect_new_transitions(before_counts):
    """STATE_TRANSITION events added to any breaker's buffer since `before_counts`,
    merged across services and ordered chronologically.

    Ordering relies on creationTime sorting correctly as a plain string: every
    service is the same JVM timezone offset and Jackson's ISO-8601 serialization
    is fixed-width, so lexicographic order == chronological order here without
    needing to parse Java's ZonedDateTime format.
    """
    transitions = []
    for service, (port, breakers) in SERVICE_BREAKERS.items():
        for breaker in breakers:
            events = _fetch_breaker_events(port, breaker)
            before = before_counts.get((service, breaker), 0)
            for event in events[before:]:
                transitions.append({
                    "service": service,
                    "breaker": breaker,
                    "state_transition": event.get("stateTransition"),
                    "creation_time": event.get("creationTime"),
                })
    transitions.sort(key=lambda t: t["creation_time"] or "")
    return transitions

def log_cb_transitions(experiment_id, topology, fault_type, config, mode, replicate,
                        fault_injected_at, fault_cleared_at, transitions):
    """Appends one JSON line per run recording every circuit breaker's real
    CLOSED/OPEN/HALF_OPEN transitions -- kept as a sidecar (not master_dataset.csv
    columns) because the transition list is variable-length per run and a CSV
    cell can't hold an ordered, multi-service event list cleanly. Join back to
    the CSV row via experiment_id + replicate + mode.
    """
    path = CANARY_CB_TRANSITIONS_PATH if mode == "canary" else CB_TRANSITIONS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {
        "experiment_id": experiment_id,
        "topology": topology.upper(),
        "fault_type": fault_type.upper(),
        "window_type": config["slidingWindowType"],
        "environment": ENVIRONMENT,
        "mode": mode,
        "replicate": replicate,
        "fault_injected_at": fault_injected_at,
        "fault_cleared_at": fault_cleared_at,
        "transitions": transitions,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")

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
    re-run the 486-run sweep if the threshold changes after sign-off. Returns {} if nothing
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

def make_experiment_id(topology, fault_type, config):
    """Builds a deterministic ID matching experiment_matrix.csv e.g. LIN-LAT-CNT-T50-W10-D15."""
    topo_map  = {"linear": "LIN", "fanout": "FAN", "mesh": "MSH"}
    fault_map = {"latency": "LAT", "crash": "CRS", "throttle": "THR"}
    wtype_map = {"COUNT_BASED": "CNT", "TIME_BASED": "TIM"}
    topo  = topo_map.get(topology, topology[:3].upper())
    fault = fault_map.get(fault_type, fault_type[:3].upper())
    wtype = wtype_map.get(config["slidingWindowType"], config["slidingWindowType"][:3])
    return (f"{topo}-{fault}-{wtype}"
            f"-T{config['failureRateThreshold']}"
            f"-W{config['slidingWindowSize']}"
            f"-D{config['waitDurationInOpenState']}")

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
    """canary writes to a disposable file; full writes to the real research dataset."""
    return CANARY_DATASET_PATH if mode == "canary" else DATASET_PATH

def log_results(config, fault_type, mode, topology, metrics, replicate):
    """Appends experiment run results to master_dataset.csv (full mode) or
    canary_runs.csv (canary mode) -- 28-col schema, same DATASET_HEADERS either way.

    metrics only needs to carry the keys a given call actually has: a
    PRECONDITION_FAIL row (aborted before fault injection, before warmup even
    runs) passes just the precondition_* / readiness_wait_s / cb_state_pre /
    buffered_calls_pre / run_order_seed / run_index keys, and every outcome
    column below (blast_radius, error_rate, warmup_requests, ...) is written
    blank rather than KeyError-ing or fabricating a 0.0. run_order_seed and
    run_index are the two exceptions expected on every row regardless of
    outcome -- a run's position in the shuffled execution order is known the
    moment it starts, independent of what happens during it."""
    dataset_path = get_dataset_path(mode)
    os.makedirs(os.path.dirname(dataset_path), exist_ok=True)
    file_exists = os.path.exists(dataset_path)

    if file_exists:
        with open(dataset_path, newline="") as f:
            existing_header = next(csv.reader(f), [])
        if existing_header != DATASET_HEADERS:
            print(
                f"{os.path.basename(dataset_path)} header does not match the current DATASET_HEADERS "
                f"(expected {DATASET_HEADERS}, found {existing_header}). Refusing to "
                "append — this would silently shift columns for every downstream row. "
                "Move or rename the stale file first.",
                file=sys.stderr,
            )
            return

    experiment_id = make_experiment_id(topology, fault_type, config)
    time_to_open = metrics.get("time_to_open")
    time_to_recover = metrics.get("time_to_recover")

    with open(dataset_path, mode="a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(DATASET_HEADERS)

        writer.writerow([
            experiment_id,
            topology.upper(),
            fault_type.upper(),
            config["slidingWindowType"],
            config["failureRateThreshold"],
            config["slidingWindowSize"],
            config["waitDurationInOpenState"],
            config.get("permittedCallsInHalfOpenState", 5),
            ENVIRONMENT,
            mode,
            replicate,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            f"{metrics.get('blast_radius', ''):.4f}" if metrics.get('blast_radius') is not None else "",
            time_to_open if time_to_open is not None else "",   # "" = CB never opened (meaningful null)
            time_to_recover if time_to_recover is not None else "",  # "" = system did not recover (meaningful null)
            f"{metrics['error_rate']:.4f}" if metrics.get('error_rate') is not None else "",
            f"{metrics['throughput_loss']:.4f}" if metrics.get('throughput_loss') is not None else "",
            f"{metrics['real_blast_radius']:.4f}" if metrics.get('real_blast_radius') is not None else "",  # "" = no leg observable (measurement gap)
            ";".join(f"{svc}:{rate:.4f}" for svc, rate in (metrics.get('leg_failure_rates') or {}).items()),  # raw per-leg rates; "" = none observed
            metrics.get("precondition_ok", ""),
            metrics.get("precondition_fail_reason", ""),
            f"{metrics['readiness_wait_s']:.3f}" if metrics.get('readiness_wait_s') is not None else "",
            metrics.get("cb_state_pre", ""),
            metrics.get("buffered_calls_pre", ""),
            metrics.get("warmup_requests", ""),
            f"{metrics['warmup_duration_s']:.3f}" if metrics.get('warmup_duration_s') is not None else "",
            metrics.get("run_order_seed", ""),
            metrics.get("run_index", ""),
        ])
    print(f"Saved run metrics to {dataset_path}")

def run_experiment_run(config, fault_type, mode, topology="linear", replicate=1,
                        run_order_seed=None, run_index=None):
    """Orchestrates a single configuration and fault run.

    run_order_seed/run_index describe this run's place in the sweep's shuffled
    execution order (see main()) -- attached to every log_results call in this
    function, including both abort paths, so a run's position is recoverable
    even when it never got far enough to produce an outcome."""
    print("\n" + "="*60)
    print(f"STARTING EXPERIMENT: Mode={mode}, Topology={topology}, Fault={fault_type}, Replicate={replicate}")
    print(f"Config: {config}")
    print("="*60)
    
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
        }, replicate)
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
        }, replicate)
        return False

    # Snapshot each interior breaker's actuator ring buffer before the fault, so
    # collect_new_transitions() can isolate just this run's real state transitions
    # further down -- this is what actually answers "did order's breaker open",
    # which error_rate/blast_radius cannot (see SERVICE_BREAKERS docstring above).
    before_cb_counts = snapshot_breaker_event_counts()

    # 2c. JIT warmup (discard phase) -- BEFORE the baseline measurement below, so
    #    that measurement isn't itself contaminated by cold-JVM artifacts. See the
    #    "JIT warmup" comment block near LOAD_RATE_RPS for the full rationale.
    endpoint = f"http://localhost:8080/api/v1/{topology}"
    warmup_requests, warmup_duration_s = warmup_phase(endpoint)

    # 3. Measure pre-fault baseline throughput (against an already-warm JVM)
    print("Measuring pre-fault baseline...")
    baseline_throughput, _, _ = generate_load(endpoint, requests_count=20, concurrency=3)
    if baseline_throughput <= 0:
        print("Baseline throughput is zero — mesh unhealthy pre-fault, skipping run.", file=sys.stderr)
        return False

    # 4. Inject fault into Toxiproxy
    fault_injected_at = _now_iso()
    try:
        inject_fault(fault_type)
    except Exception as e:
        print(f"Fault injection failed: {e} — skipping run.", file=sys.stderr)
        toxiproxy.reset_all()
        return False

    # 5. Size the fault load per window type so TIME_BASED windows can actually fill
    #    (Task 1). Snapshot per-leg CB call counters just before the fault window so the
    #    real (request-level) blast radius is a clean delta over the window (Task 2).
    plan = compute_load_plan(config)
    print(f"Load plan ({config['slidingWindowType']}): {plan['requests_count']} requests "
          f"over ~{plan['duration_s']:.0f}s @ {LOAD_RATE_RPS} req/s")
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
        # Final read after the deadline: for latency/throttle faults, each request
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
    throughput, error_rate, avg_latency = generate_load(
        endpoint, requests_count=plan["requests_count"],
        concurrency=plan["concurrency"], interval_s=plan["interval_s"])
    sampler.join(timeout=sample_deadline_s + 5)

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
    #    time_to_recover is ONLY computed when a breaker was confirmed open
    #    (cb_opened=True). Running the recovery phase unconditionally produces
    #    the corrupt combination: time_to_open=null + time_to_recover=0.5 s.
    time_to_open = None
    time_to_recover = None

    if cb_opened:
        time_to_open = round(cb_open_at[0] - load_start, 3)

        # Poll for recovery, driving light traffic each iteration. Two caveats,
        # documented rather than silently glossed over:
        #  1. Resilience4j auto-transitions OPEN -> HALF_OPEN purely on elapsed
        #     wait_duration, with no traffic required, and the Gateway's
        #     blast-radius endpoint (BlastRadiusService.hasOpenCircuitBreaker)
        #     only flags the literal "CIRCUIT_OPEN" status -- so blast_radius
        #     reads 0.0 the moment the breaker LEAVES OPEN, before it has
        #     necessarily reached CLOSED. Without traffic, a HALF_OPEN breaker
        #     can't even attempt its permitted probe calls, so we send a few
        #     real requests each iteration to give it that chance.
        #  2. This still can't perfectly distinguish "HALF_OPEN, about to
        #     re-open" from "genuinely CLOSED" using only the aggregate
        #     blast-radius endpoint polled here in real time. The precise
        #     per-breaker STATE_TRANSITION events ARE captured (see
        #     collect_new_transitions() / cb_transitions.jsonl below), but as a
        #     post-hoc record for analysis, not as a synchronous gate on this
        #     loop's recovery decision. To reduce (not eliminate) false-early
        #     recovery reads here, require the reading to stay at 0.0 across
        #     two consecutive probes, one second apart, before declaring
        #     recovery.
        recovery_deadline = time.time() + config["waitDurationInOpenState"] + 10
        consecutive_zero_reads = 0
        while time.time() < recovery_deadline:
            time.sleep(1.0)
            try:
                with urllib.request.urlopen(endpoint, timeout=5) as res:
                    res.read()
            except Exception:
                pass
            current_br = get_blast_radius()
            if current_br is not None and current_br == 0.0:
                consecutive_zero_reads += 1
                if consecutive_zero_reads >= 2:
                    time_to_recover = round(time.time() - cb_open_at[0], 3)
                    break
            else:
                consecutive_zero_reads = 0
        # If we exit the loop without recovering, time_to_recover stays None
        # (meaningful null: system did not return to baseline within the window).

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
    }
    log_results(config, fault_type, mode, topology, metrics, replicate)

    # Record real per-service breaker transitions for this run regardless of what
    # blast_radius/cb_opened concluded -- catching the case where the aggregate
    # signal says "nothing opened" but an interior breaker tripped via the
    # slow-call path is the entire point of this sidecar.
    transitions = collect_new_transitions(before_cb_counts)
    log_cb_transitions(
        make_experiment_id(topology, fault_type, config), topology, fault_type, config,
        mode, replicate, fault_injected_at, fault_cleared_at, transitions,
    )
    return True

def generate_combinations(mode):
    """Generates configuration combinations depending on the mode."""
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
    else:
        # Full Sweep: 3*3*3*2 = 54 configs per fault × 3 faults × 3 replicates = 486 total runs
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

def main():
    parser = argparse.ArgumentParser(description="CascadeShield Parameter Sweep Automation Runner")
    parser.add_argument("--mode", choices=["canary", "full"], default="canary", help="canary (5 configs × 3 replicates = 15 runs) or full (54 configs × 3 replicates = 162 runs per fault type; 486 total across 3 faults)")
    parser.add_argument("--fault", choices=["latency", "crash", "throttle"], default="latency", help="Fault type to inject")
    parser.add_argument("--topology", choices=["linear", "fanout", "mesh"], default="linear", help="Service mesh topology pattern")
    parser.add_argument("--replicates", type=int, default=N_REPLICATES, help=f"Number of replicates per config (default: {N_REPLICATES})")
    parser.add_argument("--seed", type=int, default=None,
                         help="Seed for the run-order shuffle (default: a fresh random seed each "
                              "invocation, printed and persisted to run_order_seed). Pass an explicit "
                              "value to reproduce a specific execution order.")

    args = parser.parse_args()
    
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

    # Randomize run order (see build_shuffled_run_list): sequential execution of a long
    # sweep on one host confounds treatment (config) with thermal/memory drift over the
    # sweep's wall-clock duration -- later configs would systematically run on a
    # warmer/more-fragmented host, biasing exactly the comparison the sweep exists to
    # make. run_index below is the run's position in this shuffled sequence, not its
    # position in configs.
    run_order_seed, run_list = build_shuffled_run_list(configs, args.replicates, args.seed)
    print(f"Run order shuffled with seed {run_order_seed} ({len(run_list)} runs). "
          f"Pass --seed {run_order_seed} to reproduce this exact order.")

    started_at = _now_iso()
    success_runs = 0
    failed_runs = 0
    write_status({
        "mode": args.mode, "fault_type": args.fault, "topology": args.topology,
        "replicates": args.replicates, "total_configs": len(configs), "total_runs": total_runs,
        "run_number": 0, "config_index": None, "current_config": None, "replicate": None,
        "success_runs": 0, "failed_runs": 0,
        "phase": "running", "started_at": started_at, "updated_at": started_at,
    })

    for run_index, (i, config, rep) in enumerate(run_list, start=1):
        run_number = run_index  # execution sequence position, not config/replicate order
        print(f"\nProgress: Run {run_number} of {total_runs} (config {i+1}/{len(configs)}, replicate {rep}/{args.replicates})")
        write_status({
            "mode": args.mode, "fault_type": args.fault, "topology": args.topology,
            "replicates": args.replicates, "total_configs": len(configs), "total_runs": total_runs,
            "run_number": run_number, "config_index": i, "current_config": config, "replicate": rep,
            "success_runs": success_runs, "failed_runs": failed_runs,
            "phase": "running", "started_at": started_at, "updated_at": _now_iso(),
        })
        success = run_experiment_run(config, args.fault, args.mode, args.topology, replicate=rep,
                                      run_order_seed=run_order_seed, run_index=run_index)
        if success:
            success_runs += 1
        else:
            failed_runs += 1
        write_status({
            "mode": args.mode, "fault_type": args.fault, "topology": args.topology,
            "replicates": args.replicates, "total_configs": len(configs), "total_runs": total_runs,
            "run_number": run_number, "config_index": i, "current_config": config, "replicate": rep,
            "success_runs": success_runs, "failed_runs": failed_runs,
            "phase": "running", "started_at": started_at, "updated_at": _now_iso(),
        })

    print("\n" + "="*60)
    print(f"SWEEP COMPLETED: {success_runs}/{total_runs} runs executed successfully.")
    print(f"Master dataset: {get_dataset_path(args.mode)}")
    print("="*60)
    write_status({
        "mode": args.mode, "fault_type": args.fault, "topology": args.topology,
        "replicates": args.replicates, "total_configs": len(configs), "total_runs": total_runs,
        "run_number": total_runs, "config_index": len(configs) - 1 if configs else None,
        "current_config": None, "replicate": None,
        "success_runs": success_runs, "failed_runs": failed_runs,
        "phase": "completed", "started_at": started_at, "updated_at": _now_iso(),
    })

if __name__ == "__main__":
    main()
