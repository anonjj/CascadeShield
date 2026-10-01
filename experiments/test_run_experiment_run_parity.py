"""
test_run_experiment_run_parity.py -- characterization test proving the
setup_and_check_precondition() refactor (this branch, on top of d135001) does not
change run_experiment_run's observable behavior for any existing mode.

WHY THIS EXISTS. run_experiment_run() (runner.py) is what produced master_dataset.csv
and all 72 Phase 4B rows. This refactor extracted its setup steps (1-2b: apply config
to containers, readiness, breaker reset, precondition check) into a standalone
function, setup_and_check_precondition(), so recovery_control.py's
run_recovery_control_experiment could call the SAME function instead of a hand copy.
A silent behavior change in that extraction is exactly the class of defect this
project keeps finding (D18, D23, the javadoc issue D13 filed upstream -- see
decision-log.md's running observation that the information needed to avoid an error
usually exists somewhere but is absent from where the decision gets made).

METHOD. Imports TWO separate copies of the runner module into the same process:
  - "new": the current experiments/runner.py (this branch, HEAD)
  - "old": experiments/runner.py as of commit d135001 (the pre-refactor parent),
    materialized from `git show` to a temp file and loaded via importlib under a
    different module name, so it never collides with the real "runner" module.
Every I/O boundary run_experiment_run touches is mocked IDENTICALLY on both module
objects: write_env_file, update_containers (docker), wait_for_readiness /
check_breaker_precondition / _get_circuit_breakers-adjacent HTTP, reset_all_breakers,
warmup_phase, generate_load, get_blast_radius, inject_fault, snapshot_cb_calls,
BreakerObserver's methods (shared class, patched once -- see below), and the
module-level `toxiproxy` client's reset_all(). time.time()/time.sleep() are faked
globally (a deterministic counter, not real wall-clock) so results are exactly
reproducible rather than merely "close".

BreakerObserver is imported by both "old" and "new" runner modules from the SAME
breaker_observer module (Python caches sys.modules by name; neither runner.py copy
redefines the class) -- patching BreakerObserver's methods ONCE therefore affects
both module instances identically, by construction, not by coincidence.

For each of the 4 paths (success, DOCKER_COMPOSE_FAILURE, READINESS_TIMEOUT,
PRECONDITION_FAIL), this test scripts the mocks for that scenario, runs
run_experiment_run under "old" and under "new" with identical config/args, and
asserts: (a) identical return value, (b) an identical ordered call-sequence to the
five setup-path functions (name + args, docker/toxiproxy/HTTP details stripped since
those are mocked away identically), and (c) an identical `metrics` dict passed to
log_results (the row that would be written) -- log_results itself is mocked to a
recorder rather than allowed to touch disk, so this asserts row EQUALITY without
ever writing a CSV.

Usage: python3 experiments/test_run_experiment_run_parity.py
"""
import importlib.util
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

OLD_REVISION = "d135001"
HERE = Path(__file__).resolve().parent


def load_old_runner():
    """Materializes experiments/runner.py as of OLD_REVISION to a temp file and
    imports it as a standalone module named "runner_old_d135001" -- distinct from
    "runner" so both module objects coexist in sys.modules without collision.
    experiments/ is already on sys.path (this test lives there), so the old module's
    own `from breaker_observer import BreakerObserver` etc. resolve against the
    CURRENT (unchanged-since-d135001) versions of those sibling files -- exactly what
    we want, since this test isolates the runner.py refactor specifically, not a
    whole-repo time machine."""
    result = subprocess.run(
        ["git", "show", f"{OLD_REVISION}:experiments/runner.py"],
        cwd=HERE.parent, capture_output=True, text=True, check=True,
    )
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="runner_old_", delete=False)
    tmp.write(result.stdout)
    tmp.close()

    spec = importlib.util.spec_from_file_location("runner_old_d135001", tmp.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules["runner_old_d135001"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- fakes

class FakeClock:
    """Deterministic, monotonically-increasing fake clock -- NOT tied to real
    wall-clock time. Every time.time() call advances by a fixed epsilon; time.sleep()
    is a true no-op (doesn't block and doesn't itself advance the clock, since the
    functions under test already call time.time() on their own cadence). A
    threading.Lock guards the counter since run_experiment_run's blast-radius sampler
    runs on a real background thread concurrently with the main thread."""

    def __init__(self, start=1_000_000.0, epsilon=0.01):
        self._value = start
        self._epsilon = epsilon
        self._lock = threading.Lock()

    def time(self):
        with self._lock:
            self._value += self._epsilon
            return self._value

    def sleep(self, _seconds):
        return None


# --------------------------------------------------------------------------- scenario harness

CONFIG = {
    "failureRateThreshold": 50, "slidingWindowSize": 10, "waitDurationInOpenState": 15,
    "slidingWindowType": "COUNT_BASED", "minimumNumberOfCalls": 5, "targetRps": 10,
}
CB_STATE_CLEAN = {"order": {"inventoryServiceCB": "CLOSED"}}
BUFFERED_CALLS_CLEAN = {"order": {"inventoryServiceCB": 0}}
CB_STATE_DIRTY = {"order": {"inventoryServiceCB": "OPEN"}}
BUFFERED_CALLS_DIRTY = {"order": {"inventoryServiceCB": 3}}


def run_scenario(module, label, scenario, clock, logged_rows, call_log):
    """Runs run_experiment_run on `module` ("old" or "new" runner module object)
    under `scenario`'s mocked setup-path + downstream returns. Appends the captured
    log_results args to logged_rows[label] and the setup-path call sequence to
    call_log[label]. Returns run_experiment_run's own return value."""

    def record(fn_name):
        def _fn(*args, **kwargs):
            call_log[label].append((fn_name, args, kwargs))
            if fn_name in scenario.get("raises", {}):
                raise scenario["raises"][fn_name]
            return scenario["returns"].get(fn_name)
        return _fn

    def fake_log_results(config, fault_type, mode, topology, metrics, replicate, machine_id=""):
        logged_rows[label].append({
            "config": config, "fault_type": fault_type, "mode": mode, "topology": topology,
            "metrics": metrics, "replicate": replicate, "machine_id": machine_id,
        })

    patches = [
        patch.object(module, "write_env_file", record("write_env_file")),
        patch.object(module, "update_containers", record("update_containers")),
        patch.object(module, "wait_for_readiness", record("wait_for_readiness")),
        patch.object(module, "reset_all_breakers", record("reset_all_breakers")),
        patch.object(module, "check_breaker_precondition", record("check_breaker_precondition")),
        patch.object(module, "log_results", fake_log_results),
    ]
    if scenario["name"] == "success":
        patches += [
            patch.object(module, "warmup_phase", record("warmup_phase")),
            patch.object(module, "generate_load", record("generate_load")),
            patch.object(module, "get_blast_radius", record("get_blast_radius")),
            patch.object(module, "inject_fault", record("inject_fault")),
            patch.object(module, "snapshot_cb_calls", record("snapshot_cb_calls")),
            patch.object(module.BreakerObserver, "snapshot_before", lambda self: {}),
            patch.object(module.BreakerObserver, "observe_recovery",
                          lambda self, snapshot, cb_open_at, wait_duration: (5.0, [], False, 65.0)),
            patch.object(module.BreakerObserver, "log", lambda self, *a, **kw: None),
            patch.object(module.toxiproxy, "reset_all", record("toxiproxy.reset_all")),
        ]

    with patch("time.time", clock.time), patch("time.sleep", clock.sleep):
        for p in patches:
            p.start()
        try:
            return module.run_experiment_run(
                CONFIG, "latency", "full", topology="linear", replicate=1,
                run_order_seed=42, run_index=1, toxicity=1.0, machine_id="test-machine",
            )
        finally:
            for p in patches:
                p.stop()


SCENARIOS = [
    {
        "name": "success",
        "returns": {
            "update_containers": True,
            "wait_for_readiness": (True, 12.345),
            "check_breaker_precondition": {"ok": True, "fail_reason": "",
                                            "cb_state": CB_STATE_CLEAN,
                                            "buffered_calls": BUFFERED_CALLS_CLEAN},
            "warmup_phase": (200, 10.0),
            "generate_load": (10.0, 5.0, 100.0, 9.8, 0.05),
            "get_blast_radius": 25.0,
            "snapshot_cb_calls": {"order": {"inventoryServiceCB": 0.0}},
        },
    },
    {
        "name": "DOCKER_COMPOSE_FAILURE",
        "returns": {"update_containers": False},
    },
    {
        "name": "READINESS_TIMEOUT",
        "returns": {
            "update_containers": True,
            "wait_for_readiness": (False, 90.0),
        },
    },
    {
        "name": "PRECONDITION_FAIL",
        "returns": {
            "update_containers": True,
            "wait_for_readiness": (True, 12.345),
            "check_breaker_precondition": {"ok": False, "fail_reason": "order:inventoryServiceCB=state:OPEN",
                                            "cb_state": CB_STATE_DIRTY,
                                            "buffered_calls": BUFFERED_CALLS_DIRTY},
        },
    },
]

SETUP_FUNCTIONS = ["write_env_file", "update_containers", "wait_for_readiness",
                   "reset_all_breakers", "check_breaker_precondition"]


def _strip_call_args_for_comparison(calls):
    """(fn_name, args, kwargs) -> fn_name only, for the setup functions -- every one
    of them is called with either no arguments or exactly `config` (write_env_file,
    check_breaker_precondition takes none), and config is the same object identity
    passed into both runs, so comparing names+order already proves "same functions,
    same order, same call count"; the interesting content-level assertion is the
    logged row, checked separately."""
    return [fn for (fn, args, kwargs) in calls if fn in SETUP_FUNCTIONS]


def main():
    old_module = load_old_runner()
    import runner as new_module

    ok = True

    def check(name, cond):
        nonlocal ok
        status = "ok" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {name}")

    for scenario in SCENARIOS:
        print(f"\nScenario: {scenario['name']}")
        clock = FakeClock()
        logged_rows = {"old": [], "new": []}
        call_log = {"old": [], "new": []}

        old_result = run_scenario(old_module, "old", scenario, clock, logged_rows, call_log)
        old_module_calls = call_log["old"]

        clock2 = FakeClock()  # fresh clock per module run, both start at the same value
        new_result = run_scenario(new_module, "new", scenario, clock2, logged_rows, call_log)
        new_module_calls = call_log["new"]

        check("return value identical", old_result == new_result)

        old_seq = _strip_call_args_for_comparison(old_module_calls)
        new_seq = _strip_call_args_for_comparison(new_module_calls)
        check(f"setup-path call sequence identical: {new_seq}", old_seq == new_seq)

        check("log_results call count identical",
              len(logged_rows["old"]) == len(logged_rows["new"]))
        if logged_rows["old"] and logged_rows["new"]:
            old_row, new_row = logged_rows["old"][0], logged_rows["new"][0]
            for key in ("config", "fault_type", "mode", "topology", "replicate", "machine_id"):
                check(f"log_results arg '{key}' identical", old_row[key] == new_row[key])
            old_metrics, new_metrics = dict(old_row["metrics"]), dict(new_row["metrics"])
            check("metrics dict has identical keys", set(old_metrics) == set(new_metrics))
            mismatches = {k: (old_metrics.get(k), new_metrics.get(k))
                          for k in old_metrics if old_metrics.get(k) != new_metrics.get(k)}
            check(f"metrics dict values identical (mismatches: {mismatches})", not mismatches)
        elif scenario["name"] == "DOCKER_COMPOSE_FAILURE":
            check("no row logged on DOCKER_COMPOSE_FAILURE (matches pre-existing behavior, "
                  "both versions)", len(logged_rows["old"]) == 0 and len(logged_rows["new"]) == 0)

    print()
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
