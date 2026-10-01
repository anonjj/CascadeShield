"""
recovery_control.py -- R2 "equal exposure" recovery-control mode.

WHY THIS EXISTS. run_experiment_run() (runner.py) sizes the fault-phase load call by
window type (compute_load_plan) and clears the fault only after that load call
returns (toxiproxy.reset_all() at runner.py's step 6, after generate_load's step 5).
At LOAD_RATE_RPS=10, COUNT_BASED's dispatch window is ~4-6s (COUNT_BASED_WINDOW_MULTIPLE
* window, floored at COUNT_BASED_MIN_REQUESTS=40 requests) -- shorter than every swept
waitDurationInOpenState (5/15/30s) except the smallest. TIME_BASED's dispatch window is
10*(window + wait + TIME_BASED_MARGIN_S) = 20-60s -- deliberately sized to outlast
wait_duration so the window can fill. The practical effect: TIME_BASED's still-running
load call keeps probing the breaker with real traffic all the way through OPEN, the
HALF_OPEN transition, and its probe calls, all while the fault is STILL ACTIVE (fault
clears only after generate_load returns). COUNT_BASED's load call finishes and clears
the fault BEFORE wait_duration has typically even elapsed, so its HALF_OPEN probes (via
BreakerObserver.observe_recovery's post-load poll/probe loop) only ever happen AFTER the
fault is gone. The two arms are not measuring the same thing. Independently documented
in docs/paper/h3-postd25-analysis-plan.md section 9.1 (the lambda_achieved noise-budget
table), which shows the same dispatch-window asymmetry from a different angle.

NAMING NOTE, stated plainly rather than left implicit. The task that specified this
module referred to "Decision D28" for the above. No decision-log entry by that number
exists -- not on `main`, not on the `h3-evidence-audit` branch this module was branched
from (highest filed decision there is D26). The underlying technical finding above IS
real and independently verifiable in the code and in h3-postd25-analysis-plan.md 9.1;
only the specific "D28" citation is unconfirmed. Filing the actual decision-log entry
is left to whoever reviews this for a live run -- this commit makes no data claim of its
own (implementation + self-tests only, no mesh runs).

THE FIX. Instead of sizing load by window type and clearing the fault on a timer tied
to that load call's own duration, this mode: (1) polls order-service's actual breaker
state directly to detect OPEN (never infers it from blast_radius or a fixed dispatch
window), (2) clears the fault on a timer anchored ONLY on the observed OPEN instant and
the config's own waitDurationInOpenState -- compute_fault_clear_at takes no window-type
or window-size argument, so it cannot itself introduce the asymmetry it exists to
remove -- and (3) keeps load flowing continuously (generate_load's new optional
stop_event parameter) until HALF_OPEN_TO_CLOSED lands *after* that clear, or a ceiling.
Both arms get identical fault exposure and identical post-OPEN traffic by construction.

DESIGN CHOICE: standalone script, not a runner.py --mode. runner.py's main() dispatches
through generate_combinations()/build_shuffled_run_list()/resumable_runner -- machinery
sized for a fixed grid of fixed-duration runs. This mode's stopping condition is
event-driven, not duration-sized, and doesn't fit that shape without either forcing it
in (spurious duration/requests_count fields) or adding real branching to main()'s
existing dispatch (the "every line outside the new path must be justified" constraint
this task set). Importing runner.py's pieces (SERVICE_BREAKERS, write_env_file,
update_containers, wait_for_readiness, reset_all_breakers, check_breaker_precondition,
warmup_phase, generate_load, inject_fault, resolve_inject_point, toxiproxy,
make_experiment_id, _now_iso, _with_extra_columns, _get_circuit_breakers, and several
constants) keeps this mode fully opt-in -- nothing in runner.py's existing modes changes
except generate_load's one new optional parameter (see that function's docstring), and
nothing calls into this file unless a caller explicitly runs it.

OUTPUTS: data/r2_equal_exposure.csv (own header, via _with_extra_columns -- never
touches master_dataset.csv or any existing schema) and data/r2_cb_transitions.jsonl
(own sidecar, via BreakerObserver.log -- never touches data/cb_transitions.jsonl).
"""
import argparse
import inspect
import math
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner as R
from breaker_observer import BreakerObserver
from resumable_runner import append_row

# --------------------------------------------------------------------------- constants

R2_CLEAR_OFFSET_S = 5          # seconds past open_detected_at + wait_duration before clearing
OPEN_POLL_INTERVAL_S = 0.1     # /actuator/circuitbreakers poll cadence for OPEN detection
CEILING_MULTIPLE = 3           # same shape as breaker_observer.half_open_probe_deadline_s
CEILING_FLOOR_S = 60           # (different anchor: OPEN detection, not HALF_OPEN entry --
                                # kept as its own constant rather than importing that one)

ORDER_SERVICE = "order"
ORDER_PORT = R.SERVICE_BREAKERS[ORDER_SERVICE][0]
ORDER_WATCH_BREAKER = "inventoryServiceCB"

# R2_DATASET_PATH/R2_TRANSITIONS_PATH/R2_EXTRA_COLUMNS/R2_DATASET_HEADERS now live in
# runner.py (R.R2_*), not here -- so runner.py's get_dataset_path() and main()'s
# --mode recovery-control resumability dispatch can reference them directly, the same
# way every other mode's dataset path/headers are owned by that file. Referenced via
# the R. prefix throughout this module rather than re-imported under a bare name, so
# it's always visually obvious which constants are shared with runner.py.


# =============================================================================
# Pure logic -- no I/O, no sleeping, no mesh. Everything below this line and
# above the "live orchestration" marker is what --self-test exercises (T1-T5).
# =============================================================================

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z")


def parse_java_ts(s):
    """Same fix as analysis/window_type_recovery_leak.py's _parse_java_ts (Resilience4j's
    actuator API appends a bracketed zone id, e.g. "...986004462Z[Etc/UTC]", that plain
    ISO-8601 parsing chokes on) -- reimplemented here rather than imported, since
    analysis/ consumes experiments/'s output and importing the other direction would be
    a layering inversion. Returns epoch seconds (float); this module has no pandas
    dependency and doesn't need one for a single subtraction."""
    m = _TS_RE.match(s)
    if not m:
        raise ValueError(f"unrecognized Resilience4j timestamp: {s!r}")
    base, frac = m.group(1), m.group(2) or ""
    micros = (frac + "000000")[1:7] if frac else "000000"
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
        microsecond=int(micros), tzinfo=timezone.utc)
    return dt.timestamp()


def compute_fault_clear_at(open_detected_at, wait_duration_s, offset_s=R2_CLEAR_OFFSET_S):
    """The equal-exposure rule, as a pure function: clear_at = open_detected_at +
    wait_duration_s + offset_s. Deliberately takes ONLY these arguments -- no config
    dict, no window_type, no window_size -- so it is structurally incapable of
    reintroducing the asymmetry this module exists to remove. T1 checks this via the
    function's own signature, not just by example."""
    return open_detected_at + wait_duration_s + offset_s


def compute_ceiling_at(open_detected_at, wait_duration_s):
    """Hard stop for a run that opened but whose breaker never closes: t_open + 3*D_w +
    60s. Same shape as breaker_observer.half_open_probe_deadline_s (3*wait+60), kept as
    its own constant pair (CEILING_MULTIPLE/CEILING_FLOOR_S) rather than importing that
    function directly -- that one's anchor is HALF_OPEN entry (its own probe-driving
    loop's start); this one's anchor is OPEN detection (this mode's load-stop clock).
    Same shape, different anchor, not accidentally the same number."""
    return open_detected_at + CEILING_MULTIPLE * wait_duration_s + CEILING_FLOOR_S


def compute_pre_open_ceiling_s(config):
    """Safety bound for the 'breaker never opened at all' path (requirement 2's no_open
    case) -- distinct from compute_fault_clear_at's equal-exposure rule, which only
    applies once OPEN has actually been observed. Sized off TIME_BASED's own
    compute_load_plan formula (window + wait + TIME_BASED_MARGIN_S) regardless of this
    run's actual window type: COUNT_BASED reliably opens far faster than this under any
    reasonable window size once load is flowing, so this is a shared safety ceiling
    against a genuinely stuck run, not part of the equal-exposure comparison itself.
    Unlike compute_fault_clear_at, this one only runs BEFORE open_detected_at exists, so
    it can't retroactively bias the post-OPEN comparison the way a window-size-dependent
    clear rule would."""
    window = int(config["slidingWindowSize"])
    wait = int(config["waitDurationInOpenState"])
    return window + wait + R.TIME_BASED_MARGIN_S


def decide_load_stop(now, open_detected_at, fault_cleared_at, closed_seen, wait_duration_s):
    """Pure stop decision -- no I/O, no sleeping -- so T2/T3 can exercise it directly
    with a fake `now` instead of simulating real elapsed time. Only meaningful once a
    run has opened (open_detected_at is not None); the no_open path is a separate
    top-level timeout owned by the live orchestrator, not this function.

    Returns (stop: bool, reason: str | None, censored: bool).
      - HALF_OPEN_TO_CLOSED seen AND the fault has already been cleared -> stop,
        "half_open_to_closed", not censored. This is the real, uncensored outcome.
      - HALF_OPEN_TO_CLOSED seen but the fault has NOT yet been cleared -> do NOT stop.
        Resilience4j auto-transitions OPEN -> HALF_OPEN -> (probe outcome) purely on
        elapsed time, with no dependency on this module's own clear-timer thread, so a
        close landing before this mode's own clear_at is a shouldn't-happen shape the
        caller should log, not a signal to stop early on (T2).
      - the ceiling is reached -> stop, "ceiling", always censored=True -- never a
        fabricated recovery_event_s (T3).
      - otherwise -> keep going.
    """
    if closed_seen and fault_cleared_at is not None:
        return True, "half_open_to_closed", False
    if open_detected_at is not None and now >= compute_ceiling_at(open_detected_at, wait_duration_s):
        return True, "ceiling", True
    return False, None, False


def compute_bounce_and_recovery(transitions, service=ORDER_SERVICE, breaker=ORDER_WATCH_BREAKER):
    """transitions: BreakerObserver.collect()'s output -- a list of {"service","breaker",
    "state_transition","creation_time"} dicts, any order (sorted here, not assumed).
    Filters to `service`/`breaker` only: this mode is scoped to order:inventoryServiceCB's
    own recovery, not every breaker in the mesh.

    bounce_count: every HALF_OPEN_TO_OPEN seen anywhere in the filtered record (a probe
    round that failed and sent the breaker back to OPEN).
    recovery_event_s: seconds from the FIRST CLOSED_TO_OPEN to the FINAL (last-seen, not
    first) HALF_OPEN_TO_CLOSED -- both real event timestamps parsed via parse_java_ts,
    not wall-clock poll reads. None (never a fabricated number) when either endpoint is
    missing from the record, e.g. a censored run with no close at all (T5c)."""
    watched = sorted(
        (t for t in transitions
         if t.get("service") == service and t.get("breaker") == breaker),
        key=lambda t: t["creation_time"],
    )
    t_open = None
    t_closed = None
    bounces = 0
    for t in watched:
        st = t.get("state_transition")
        if st == "CLOSED_TO_OPEN" and t_open is None:
            t_open = t["creation_time"]
        elif st == "HALF_OPEN_TO_OPEN":
            bounces += 1
        elif st == "HALF_OPEN_TO_CLOSED":
            t_closed = t["creation_time"]  # keep overwriting: the FINAL close, not the first
    recovery_event_s = None
    if t_open is not None and t_closed is not None:
        recovery_event_s = round(parse_java_ts(t_closed) - parse_java_ts(t_open), 3)
    return bounces, recovery_event_s


# =============================================================================
# Live orchestration -- requires a running mesh. NOT exercised by --self-test.
# Not wired into any existing CLI/mode dispatch; only runs if explicitly invoked.
# =============================================================================

def _poll_for_open(port, breaker, stop_polling, poll_interval=OPEN_POLL_INTERVAL_S):
    """Blocks until `breaker` reports OPEN on `port`'s /actuator/circuitbreakers, or
    stop_polling (threading.Event) fires first. Returns the wall-clock time.time() OPEN
    was first observed, or None if stop_polling fired first (the no_open path)."""
    while not stop_polling.is_set():
        state = R._get_circuit_breakers(port).get(breaker, {}).get("state")
        if state == "OPEN":
            return time.time()
        time.sleep(poll_interval)
    return None


def run_recovery_control_experiment(config, topology, replicate, fault_type="latency",
                                     machine_id="", inject_point=None,
                                     run_order_seed=None, run_index=None):
    """One R2 run. Setup (steps 1-2b: apply config to containers, readiness, breaker
    reset, precondition check) calls runner.setup_and_check_precondition -- the EXACT
    same function run_experiment_run calls, not a hand copy -- so the two paths cannot
    silently drift out of parity (see that function's own docstring for what it does
    and what it returns). Only steps 5-7 (compute_load_plan-sized load, then
    observer.observe_recovery's poll/probe pair) are replaced, with this mode's own
    continuous-load + OPEN-poll + clear-timer + stop-watcher machinery.

    run_order_seed/run_index mirror run_experiment_run's own parameters of the same
    name -- this run's place in the shuffled execution order, attached to every
    written row (including the abort path) for the same resumability/audit reason.

    Never called by any existing mode's code path -- only runs via --mode
    recovery-control (runner.py main()) or a caller that imports and calls this
    function directly."""
    effective_inject_point = R.resolve_inject_point(inject_point, "recovery-control")

    setup = R.setup_and_check_precondition(config)
    readiness_wait_s = setup["readiness_wait_s"]
    if not setup["ok"]:
        if setup["fail_reason"] == "DOCKER_COMPOSE_FAILURE":
            # Matches run_experiment_run exactly: update_containers() failing has
            # never produced a logged row at this call site either.
            return False
        row = {
            "experiment_id": R.make_experiment_id(topology, fault_type, config, mode="recovery-control"),
            "topology": topology.upper(),
            "fault_type": fault_type.upper(),
            "window_type": config["slidingWindowType"],
            "threshold": config["failureRateThreshold"],
            "window_size": config["slidingWindowSize"],
            "wait_duration": config["waitDurationInOpenState"],
            "permitted_calls_half_open": R.PERMITTED_CALLS_HALF_OPEN,
            "environment": R.ENVIRONMENT,
            "mode": "recovery-control",
            "replicate": replicate,
            "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "precondition_ok": False,
            "precondition_fail_reason": setup["fail_reason"],
            "readiness_wait_s": f"{readiness_wait_s:.3f}" if readiness_wait_s is not None else "",
            "machine_id": machine_id or R.MACHINE_ID,
        }
        if setup["cb_state_pre"] is not None:
            row["cb_state_pre"] = R._serialize_cb_map(setup["cb_state_pre"])
            row["buffered_calls_pre"] = R._serialize_cb_map(setup["buffered_calls_pre"])
        os.makedirs(R.R2_DATASET_PATH.parent, exist_ok=True)
        append_row(R.R2_DATASET_PATH, row, R.R2_DATASET_HEADERS)
        return False

    endpoint = f"http://localhost:8080/api/v1/{topology}"
    observer = BreakerObserver(R.SERVICE_BREAKERS, endpoint, R.PERMITTED_CALLS_HALF_OPEN,
                                get_blast_radius_fn=R.get_blast_radius)
    before_cb_counts = observer.snapshot_before()

    warmup_requests, warmup_duration_s = R.warmup_phase(endpoint)

    baseline_throughput, _, _, _, _ = R.generate_load(endpoint, requests_count=20, concurrency=3)
    if baseline_throughput <= 0:
        print("Baseline throughput is zero — mesh unhealthy pre-fault, skipping run.",
              file=sys.stderr)
        return False

    fault_injected_at = R._now_iso()
    try:
        R.inject_fault(fault_type, toxicity=1.0, inject_point=effective_inject_point)
    except Exception as e:
        print(f"Fault injection failed: {e} — skipping run.", file=sys.stderr)
        R.toxiproxy.reset_all()
        return False

    wait_duration_s = int(config["waitDurationInOpenState"])
    target_rps = config.get("targetRps", R.LOAD_RATE_RPS)
    interval_s = 1.0 / target_rps
    max_expected_latency_s = R.FAULT_MAX_LATENCY_S.get(fault_type, max(R.FAULT_MAX_LATENCY_S.values()))
    concurrency = max(R.LOAD_CONCURRENCY_MIN,
                       math.ceil(target_rps * max_expected_latency_s * R.LOAD_CONCURRENCY_SAFETY))
    pre_open_ceiling_s = compute_pre_open_ceiling_s(config)

    stop_polling = threading.Event()
    stop_load = threading.Event()
    state = {"open_detected_at": None, "fault_cleared_at": None,
             "load_stop_reason": None, "recovery_censored": False}

    load_start = time.time()

    def _open_watcher():
        opened = _poll_for_open(ORDER_PORT, ORDER_WATCH_BREAKER, stop_polling)
        if opened is not None:
            state["open_detected_at"] = opened

    def _clear_and_stop_watcher():
        deadline = load_start + pre_open_ceiling_s
        while state["open_detected_at"] is None and time.time() < deadline:
            time.sleep(OPEN_POLL_INTERVAL_S)
        stop_polling.set()  # stop the open-poller either way

        if state["open_detected_at"] is None:
            # no_open path (requirement 4): clear the fault, flag, let the caller write
            # the row -- never hang the run waiting for an OPEN that isn't coming.
            state["load_stop_reason"] = "no_open"
            R.toxiproxy.reset_all()
            state["fault_cleared_at"] = time.time()
            stop_load.set()
            return

        clear_at = compute_fault_clear_at(state["open_detected_at"], wait_duration_s)
        while True:
            now = time.time()
            closed_seen = any(
                t["state_transition"] == "HALF_OPEN_TO_CLOSED"
                for t in observer.collect(before_cb_counts)
                if t["service"] == ORDER_SERVICE and t["breaker"] == ORDER_WATCH_BREAKER
            )
            if state["fault_cleared_at"] is None and now >= clear_at:
                R.toxiproxy.reset_all()
                state["fault_cleared_at"] = time.time()
            stop, reason, censored = decide_load_stop(
                now, state["open_detected_at"], state["fault_cleared_at"],
                closed_seen, wait_duration_s)
            if stop:
                if state["fault_cleared_at"] is None:
                    R.toxiproxy.reset_all()
                    state["fault_cleared_at"] = time.time()
                state["load_stop_reason"] = reason
                state["recovery_censored"] = censored
                stop_load.set()
                return
            time.sleep(0.1)

    threading.Thread(target=_open_watcher, daemon=True).start()
    watcher_thread = threading.Thread(target=_clear_and_stop_watcher, daemon=True)
    watcher_thread.start()

    # Continuous load: a large requests_count upper bound, real stopping governed by
    # stop_load (see generate_load's stop_event parameter).
    throughput, error_rate, avg_latency, lambda_achieved, lambda_cv = R.generate_load(
        endpoint, requests_count=10_000_000, concurrency=concurrency,
        interval_s=interval_s, stop_event=stop_load)

    watcher_thread.join(timeout=10)

    transitions = observer.collect(before_cb_counts)
    bounce_count, recovery_event_s = compute_bounce_and_recovery(transitions)
    open_event_at = next(
        (t["creation_time"] for t in transitions
         if t["service"] == ORDER_SERVICE and t["breaker"] == ORDER_WATCH_BREAKER
         and t["state_transition"] == "CLOSED_TO_OPEN"),
        None,
    )

    time_to_open = (round(state["open_detected_at"] - load_start, 3)
                     if state["open_detected_at"] is not None else None)
    fault_on_after_open_s = (
        round(state["fault_cleared_at"] - state["open_detected_at"], 3)
        if state["open_detected_at"] is not None and state["fault_cleared_at"] is not None
        else None
    )

    experiment_id = R.make_experiment_id(topology, fault_type, config, mode="recovery-control")
    row = {
        "experiment_id": experiment_id,
        "topology": topology.upper(),
        "fault_type": fault_type.upper(),
        "window_type": config["slidingWindowType"],
        "threshold": config["failureRateThreshold"],
        "window_size": config["slidingWindowSize"],
        "wait_duration": config["waitDurationInOpenState"],
        "permitted_calls_half_open": R.PERMITTED_CALLS_HALF_OPEN,
        "environment": R.ENVIRONMENT,
        "mode": "recovery-control",
        "replicate": replicate,
        "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "time_to_open": time_to_open if time_to_open is not None else "",
        "precondition_ok": True,
        "precondition_fail_reason": "",
        "readiness_wait_s": f"{readiness_wait_s:.3f}",
        "cb_state_pre": R._serialize_cb_map(setup["cb_state_pre"]),
        "buffered_calls_pre": R._serialize_cb_map(setup["buffered_calls_pre"]),
        "warmup_requests": warmup_requests,
        "warmup_duration_s": f"{warmup_duration_s:.3f}",
        "lambda_target": target_rps,
        "lambda_achieved": lambda_achieved if lambda_achieved is not None else "",
        "lambda_cv": lambda_cv if lambda_cv is not None else "",
        "machine_id": machine_id or R.MACHINE_ID,
        "run_order_seed": run_order_seed if run_order_seed is not None else "",
        "run_index": run_index if run_index is not None else "",
        "open_detected_at": state["open_detected_at"] if state["open_detected_at"] is not None else "",
        "open_event_at": open_event_at or "",
        "fault_clear_offset_s": R2_CLEAR_OFFSET_S,
        "fault_cleared_at": state["fault_cleared_at"] if state["fault_cleared_at"] is not None else "",
        "fault_on_after_open_s": fault_on_after_open_s if fault_on_after_open_s is not None else "",
        "bounce_count": bounce_count,
        "recovery_event_s": recovery_event_s if recovery_event_s is not None else "",
        "load_stop_reason": state["load_stop_reason"] or "",
        "recovery_censored": state["recovery_censored"],
    }
    os.makedirs(R.R2_DATASET_PATH.parent, exist_ok=True)
    append_row(R.R2_DATASET_PATH, row, R.R2_DATASET_HEADERS)
    observer.log(R.R2_TRANSITIONS_PATH, experiment_id, topology, fault_type, config,
                 "recovery-control", replicate, fault_injected_at,
                 R._now_iso() if state["fault_cleared_at"] is not None else "",
                 transitions, machine_id=machine_id)
    return True


# --------------------------------------------------------------------------- self-test

def self_test():
    ok = True

    def check(name, cond):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    print("T1: fault-clear time is identical for both window types given the same "
          "(open_detected_at, wait_duration)")
    clear_a = compute_fault_clear_at(1000.0, 15)
    clear_b = compute_fault_clear_at(1000.0, 15)
    check("clear_at == open_detected_at + D_w + offset",
          math.isclose(clear_a, 1000.0 + 15 + R2_CLEAR_OFFSET_S))
    check("two calls with identical (open_detected_at, D_w) give an identical clear_at",
          clear_a == clear_b)
    sig = inspect.signature(compute_fault_clear_at)
    check("compute_fault_clear_at's signature has no window-type/size parameter "
          "at all (structurally cannot read one)",
          set(sig.parameters) <= {"open_detected_at", "wait_duration_s", "offset_s"})
    check("changing D_w (the only legitimate input besides open_detected_at) does "
          "change clear_at -- sanity check this isn't a constant function",
          compute_fault_clear_at(1000.0, 30) != clear_a)

    print("T2: HALF_OPEN_TO_CLOSED before the fault is cleared does not stop the load")
    stop, reason, censored = decide_load_stop(
        now=100.0, open_detected_at=50.0, fault_cleared_at=None,
        closed_seen=True, wait_duration_s=15)
    check("close-before-clear does not trigger a stop", stop is False)
    stop2, reason2, censored2 = decide_load_stop(
        now=100.0, open_detected_at=50.0, fault_cleared_at=90.0,
        closed_seen=True, wait_duration_s=15)
    check("close-after-clear stops with reason half_open_to_closed",
          stop2 is True and reason2 == "half_open_to_closed")
    check("close-after-clear is never censored", censored2 is False)

    print("T3: the ceiling path always produces recovery_censored=True, never a "
          "fabricated value")
    ceiling_at = compute_ceiling_at(open_detected_at=50.0, wait_duration_s=15)
    check("ceiling_at == open_detected_at + 3*D_w + 60",
          math.isclose(ceiling_at, 50.0 + 3 * 15 + 60))
    stop3, reason3, censored3 = decide_load_stop(
        now=ceiling_at, open_detected_at=50.0, fault_cleared_at=70.0,
        closed_seen=False, wait_duration_s=15)
    check("ceiling reached stops with reason ceiling", stop3 is True and reason3 == "ceiling")
    check("ceiling path is always censored=True", censored3 is True)
    stop4, _, _ = decide_load_stop(
        now=ceiling_at - 1, open_detected_at=50.0, fault_cleared_at=70.0,
        closed_seen=False, wait_duration_s=15)
    check("just before the ceiling, no stop yet", stop4 is False)

    print("T4: the no_open path (handled upstream of decide_load_stop)")
    check("pre_open_ceiling_s is a positive, finite, config-derived bound",
          compute_pre_open_ceiling_s(
              {"slidingWindowSize": 20, "waitDurationInOpenState": 15}
          ) == 20 + 15 + R.TIME_BASED_MARGIN_S)
    stop5, reason5, censored5 = decide_load_stop(
        now=99999.0, open_detected_at=None, fault_cleared_at=None,
        closed_seen=False, wait_duration_s=15)
    check("decide_load_stop never stops on its own when open_detected_at is None -- "
          "the no_open ceiling is a separate top-level timeout in the live "
          "orchestrator (_clear_and_stop_watcher), not this function's job",
          stop5 is False)

    print("T5: bounce_count and recovery_event_s from a synthetic event list "
          "(shape of a real Phase 4B TIME W20 D15 trace: open, half-open, one "
          "bounce, half-open again, close)")
    events = [
        {"service": "order", "breaker": "inventoryServiceCB", "state_transition": "CLOSED_TO_OPEN",
         "creation_time": "2026-09-29T10:00:00.000000000Z[Etc/UTC]"},
        {"service": "order", "breaker": "inventoryServiceCB", "state_transition": "OPEN_TO_HALF_OPEN",
         "creation_time": "2026-09-29T10:00:15.000000000Z[Etc/UTC]"},
        {"service": "order", "breaker": "inventoryServiceCB", "state_transition": "HALF_OPEN_TO_OPEN",
         "creation_time": "2026-09-29T10:00:16.500000000Z[Etc/UTC]"},
        {"service": "order", "breaker": "inventoryServiceCB", "state_transition": "OPEN_TO_HALF_OPEN",
         "creation_time": "2026-09-29T10:00:31.500000000Z[Etc/UTC]"},
        {"service": "order", "breaker": "inventoryServiceCB", "state_transition": "HALF_OPEN_TO_CLOSED",
         "creation_time": "2026-09-29T10:00:33.914004462Z[Etc/UTC]"},
        # Noise: a different service/breaker's events must never be counted.
        {"service": "gateway", "breaker": "orderServiceCB", "state_transition": "CLOSED_TO_OPEN",
         "creation_time": "2026-09-29T10:00:05.000000000Z[Etc/UTC]"},
    ]
    bounce_count, recovery_event_s = compute_bounce_and_recovery(events)
    check("bounce_count == 1", bounce_count == 1)
    check("recovery_event_s == 33.914s (first CLOSED_TO_OPEN -> final HALF_OPEN_TO_CLOSED)",
          recovery_event_s is not None and math.isclose(recovery_event_s, 33.914, abs_tol=1e-3))

    check("parse_java_ts strips the bracketed zone id and resolves sub-second precision "
          "(986004462ns -> 0.986004s, truncated to microseconds like every other parser "
          "in this codebase)",
          math.isclose(
              parse_java_ts("2026-08-27T09:31:15.986004462Z[Etc/UTC]") -
              parse_java_ts("2026-08-27T09:31:14.000000000Z[Etc/UTC]"),
              1.986004, abs_tol=1e-6))

    censored_events = events[:4]  # up through the second OPEN_TO_HALF_OPEN -- no close
    bc2, rec2 = compute_bounce_and_recovery(censored_events)
    check("bounce_count == 1 even without a close", bc2 == 1)
    check("recovery_event_s is None (never fabricated) without a HALF_OPEN_TO_CLOSED",
          rec2 is None)

    print()
    print("R2_DATASET_HEADERS sanity")
    check("R2 headers are DATASET_HEADERS + the 9 new columns, excluded_reason still last",
          R.R2_DATASET_HEADERS[-1] == "excluded_reason"
          and set(R.R2_EXTRA_COLUMNS) <= set(R.R2_DATASET_HEADERS)
          and len(R.R2_DATASET_HEADERS) == len(R.DATASET_HEADERS) + len(R.R2_EXTRA_COLUMNS))

    print()
    print("T6: the config applied to the containers differs between a TIME_BASED and a "
          "COUNT_BASED run in window type and size ONLY -- reads write_env_file's real "
          "output (via runner.ENV_PATH, monkeypatched to a temp file for this check "
          "only; the real infra/.env is never touched)")
    import tempfile
    real_env_path = R.ENV_PATH
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_env = Path(tmpdir) / "test.env"
        R.ENV_PATH = tmp_env
        try:
            count_config = {"slidingWindowType": "COUNT_BASED", "slidingWindowSize": 5,
                             "failureRateThreshold": 50, "waitDurationInOpenState": 15,
                             "minimumNumberOfCalls": 5}
            R.write_env_file(count_config)
            count_env = tmp_env.read_text()

            time_config = {"slidingWindowType": "TIME_BASED", "slidingWindowSize": 20,
                            "failureRateThreshold": 50, "waitDurationInOpenState": 15,
                            "minimumNumberOfCalls": 5}
            R.write_env_file(time_config)
            time_env = tmp_env.read_text()
        finally:
            R.ENV_PATH = real_env_path

    def parse_env(text):
        return dict(line.split("=", 1) for line in text.strip().splitlines()
                    if line and not line.startswith("#"))

    count_vars = parse_env(count_env)
    time_vars = parse_env(time_env)
    check("both configs produce the same set of CB_* keys",
          set(count_vars) == set(time_vars))
    differing_keys = {k for k in count_vars if count_vars[k] != time_vars.get(k)}
    check("exactly CB_SLIDING_WINDOW_TYPE and CB_SLIDING_WINDOW_SIZE differ",
          differing_keys == {"CB_SLIDING_WINDOW_TYPE", "CB_SLIDING_WINDOW_SIZE"})
    check("every other CB_* var (threshold, wait duration, minimum calls, "
          "permitted-calls-in-half-open, event buffer size) is identical across arms",
          all(count_vars[k] == time_vars[k] for k in count_vars
              if k not in ("CB_SLIDING_WINDOW_TYPE", "CB_SLIDING_WINDOW_SIZE")))
    check("CB_PERMITTED_CALLS_HALF_OPEN is present and sourced from the module constant "
          "(not swept, not config-dependent)",
          count_vars.get("CB_PERMITTED_CALLS_HALF_OPEN") == str(R.PERMITTED_CALLS_HALF_OPEN)
          == time_vars.get("CB_PERMITTED_CALLS_HALF_OPEN"))
    check("the real infra/.env was never touched (ENV_PATH restored)",
          R.ENV_PATH == real_env_path)

    print()
    print("T7: R2's config set is pinned to exactly the 24 Phase 4B experiment_ids -- "
          "runner.py's PHASE4B_ONLY_IDS_PATH / load_only_ids_file / "
          "validate_only_ids_subset (independent of argparse/main())")
    phase4b_ids = R.load_only_ids_file(R.PHASE4B_ONLY_IDS_PATH)
    check("PHASE4B_ONLY_IDS_PATH points at docs/paper/phase4b_only_ids.txt",
          R.PHASE4B_ONLY_IDS_PATH.name == "phase4b_only_ids.txt")
    check("the default set has exactly 24 ids", len(phase4b_ids) == 24)
    # Independent re-parse of the same file (not reusing load_only_ids_file), so this
    # isn't just checking the loader agrees with itself.
    with open(R.PHASE4B_ONLY_IDS_PATH) as f:
        raw_ids = {line.split("#", 1)[0].strip() for line in f}
    raw_ids.discard("")
    check("load_only_ids_file's output matches an independent line-by-line re-parse "
          "of the same file", phase4b_ids == raw_ids)
    check("a known real id (from the task's own canary list) is in the default set",
          "LIN-LAT-CNT-T50-W5-D5" in phase4b_ids)

    ok_subset, out_of_set = R.validate_only_ids_subset(
        {"LIN-LAT-CNT-T50-W5-D5", "LIN-LAT-TIM-T50-W5-D5"}, phase4b_ids)
    check("two real Phase 4B ids validate as a clean subset", ok_subset and not out_of_set)

    ok_bad, out_of_set_bad = R.validate_only_ids_subset(
        {"LIN-LAT-CNT-T50-W5-D5", "NOT-A-REAL-PHASE4B-ID"}, phase4b_ids)
    check("an out-of-set id is rejected", not ok_bad)
    check("the rejection names exactly the offending id, not the whole request",
          out_of_set_bad == {"NOT-A-REAL-PHASE4B-ID"})

    ok_all, out_of_set_all = R.validate_only_ids_subset(phase4b_ids, phase4b_ids)
    check("the full 24-id set validates against itself (the --mode recovery-control "
          "default with no --only-ids override)", ok_all and not out_of_set_all)

    return ok


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    parser = argparse.ArgumentParser(
        description="R2 equal-exposure recovery-control mode. Implementation + "
                     "self-tests only as of this checkpoint -- run_recovery_control_"
                     "experiment requires a live mesh and is not gated behind this "
                     "CLI yet; call it directly once a canary is approved.")
    parser.add_argument("--self-test", action="store_true", help="run T1-T5 (see above)")
    parser.parse_args()
    print("No live orchestration is wired to this CLI yet -- see the module docstring. "
          "Run with --self-test.")
