"""
breaker_observer.py -- owns the circuit-breaker transition sidecar (D12) end to end (D9-style
extraction: mirrors resumable_runner.py's shape -- single responsibility, small interface).

Extracted from experiments/runner.py because all 3 real bugs found this session lived in the
gap between these pieces being separate free functions with no single owner:

  1. Java timestamp parsing (ZonedDateTime's bracketed zone id) -- living in a downstream
     analysis script instead of at the boundary where cb_transitions.jsonl data enters.
  2. Ring-buffer overflow -- CB_EVENT_BUFFER_SIZE's correctness depended on load-generation
     math happening in a completely different function (compute_load_plan).
  3. Recovery-loop early exit -- 20+ lines of raw polling/traffic-driving logic inlined
     directly in the middle of run_experiment_run, with no name, no interface, no test
     surface of its own.

One module now owns "did we observe this run's CB lifecycle correctly" -- the next fix (or
the next bug) has one file to read, not run_experiment_run plus 3-4 helper functions again.
"""
import json
import os
import socket
import sys
import time
import urllib.request

ENVIRONMENT = os.environ.get("ENVIRONMENT", "LOCAL")
MACHINE_ID = os.environ.get("MACHINE_ID", socket.gethostname())


def half_open_probe_deadline_s(wait_duration):
    """The hard ceiling _drive_half_open_probes polls against, as its own pure
    function -- separated out so the arithmetic is unit-testable without
    simulating 60+ seconds of real time in --self-test. 3*wait_duration + 60:
    generous on purpose ("wait for an event you'd reasonably expect, not
    forever"), calibrated against the 26 real closures on record, all of which
    landed within 1.8-2.8s of entering HALF_OPEN -- this leaves an order of
    magnitude of headroom even at the smallest wait_duration."""
    return 3 * wait_duration + 60


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


class BreakerObserver:
    """Snapshot each watched breaker's actuator ring buffer before the fault, drive the
    post-fault recovery observation, and collect+log whatever real STATE_TRANSITION
    events happened.

    fetch_events_fn defaults to the real actuator poller and is swappable purely so
    observe_recovery()'s branching (skip the poll loop when cb_open_at is None, but
    always collect transitions -- an interior breaker can trip via the slow-call path
    even when the aggregate blast_radius signal reads "safe", and catching that is this
    sidecar's entire point) can be exercised by a self-test without live HTTP -- not a
    general ports-and-adapters abstraction, just enough of a seam for one honest test.

    get_blast_radius_fn is similarly injected (defaults to the real caller-supplied
    function) rather than imported from runner.py, to keep this module free of a
    circular import back to the file that imports BreakerObserver.
    """

    def __init__(self, service_breakers, endpoint, permitted_calls_half_open,
                 get_blast_radius_fn, fetch_events_fn=None):
        self.service_breakers = service_breakers
        self.endpoint = endpoint
        self.permitted_calls_half_open = permitted_calls_half_open
        self._get_blast_radius = get_blast_radius_fn
        self._fetch_events = fetch_events_fn or _fetch_breaker_events

    def snapshot_before(self):
        """{(service, breaker): event count right now} -- baseline so collect() can
        isolate just this run's new events.

        In practice each run's containers are force-recreated (runner.py's
        update_containers), so every breaker's ring buffer already starts empty --
        this snapshot is a defensive baseline, not load-bearing, in case that
        recreate-per-run behavior ever changes."""
        return {
            (service, breaker): len(self._fetch_events(port, breaker))
            for service, (port, breakers) in self.service_breakers.items()
            for breaker in breakers
        }

    def collect(self, snapshot):
        """STATE_TRANSITION events added to any breaker's buffer since `snapshot`,
        merged across services and ordered chronologically.

        Ordering relies on creationTime sorting correctly as a plain string: every
        service is the same JVM timezone offset and Jackson's ISO-8601 serialization
        is fixed-width, so lexicographic order == chronological order here without
        needing to parse Java's ZonedDateTime format."""
        transitions = []
        for service, (port, breakers) in self.service_breakers.items():
            for breaker in breakers:
                events = self._fetch_events(port, breaker)
                before = snapshot.get((service, breaker), 0)
                for event in events[before:]:
                    transitions.append({
                        "service": service,
                        "breaker": breaker,
                        "state_transition": event.get("stateTransition"),
                        "creation_time": event.get("creationTime"),
                    })
        transitions.sort(key=lambda t: t["creation_time"] or "")
        return transitions

    def observe_recovery(self, snapshot, cb_open_at, wait_duration):
        """Runs the post-fault recovery observation only when cb_open_at is not None
        (a breaker that never opened has nothing to recover from), but always collects
        whatever real STATE_TRANSITION events happened, even when cb_open_at is None --
        an interior breaker can trip via the slow-call path while the aggregate
        blast_radius signal still reads "safe", and catching that case is the entire
        point of this sidecar, so collection must never be gated on cb_opened.

        cb_open_at is a plain float (wall-clock seconds) or None -- not a mutable
        container; that trick in the original code was only needed for a closure
        elsewhere in run_experiment_run's own blast-radius sampler, a different
        concern that stays there.

        Returns (time_to_recover, transitions, half_open_probe_timed_out,
        half_open_probe_deadline_s). time_to_recover is None when cb_open_at is
        None, or when the coarse poll below never saw a return to baseline within
        its window (meaningful null, not a failure). The two half_open_probe_*
        values are likewise None when cb_open_at is None (nothing to probe) --
        otherwise they record whether _drive_half_open_probes' own
        poll-until-transition loop ever saw a real HALF_OPEN_TO_CLOSED land, and
        the ceiling it was watching against, so a censored precise_half_open_to_closed
        reading is directly observable in the dataset rather than only inferable
        after the fact by counting sidecar transitions (the same move D14's
        cb_state_pre made for stale breaker state)."""
        time_to_recover = None
        half_open_probe_timed_out = None
        half_open_probe_deadline_s = None
        if cb_open_at is not None:
            time_to_recover = self._poll_for_recovery(cb_open_at, wait_duration)
            half_open_probe_timed_out, half_open_probe_deadline_s = (
                self._drive_half_open_probes(snapshot, wait_duration))
        return (time_to_recover, self.collect(snapshot),
                half_open_probe_timed_out, half_open_probe_deadline_s)

    def _poll_for_recovery(self, cb_open_at, wait_duration):
        """Poll for recovery, driving light traffic each iteration. Two caveats,
        documented rather than silently glossed over:
         1. Resilience4j auto-transitions OPEN -> HALF_OPEN purely on elapsed
            wait_duration, with no traffic required, and the Gateway's
            blast-radius endpoint (BlastRadiusService.hasOpenCircuitBreaker)
            only flags the literal "CIRCUIT_OPEN" status -- so blast_radius
            reads 0.0 the moment the breaker LEAVES OPEN, before it has
            necessarily reached CLOSED. Without traffic, a HALF_OPEN breaker
            can't even attempt its permitted probe calls, so we send a few
            real requests each iteration to give it that chance.
         2. This still can't perfectly distinguish "HALF_OPEN, about to
            re-open" from "genuinely CLOSED" using only the aggregate
            blast-radius endpoint polled here in real time. The precise
            per-breaker STATE_TRANSITION events ARE captured (see collect()
            below), but as a post-hoc record for analysis, not as a
            synchronous gate on this loop's recovery decision. To reduce
            (not eliminate) false-early recovery reads here, require the
            reading to stay at 0.0 across two consecutive probes, one second
            apart, before declaring recovery.

        Deadline scales with wait_duration (max(30, 2*wait_duration) past it,
        was a flat +10) so a long wait_duration doesn't leave this loop with
        proportionally less runway than a short one. This was never actually the
        binding constraint on precise_half_open_to_closed's censoring at high
        D_w -- see _drive_half_open_probes, which is -- but widening it costs
        nothing (the loop exits the moment it detects recovery regardless) and
        removes one more place a fixed constant doesn't scale with the thing
        it's supposed to bound."""
        recovery_deadline = time.time() + wait_duration + max(30, 2 * wait_duration)
        consecutive_zero_reads = 0
        while time.time() < recovery_deadline:
            time.sleep(1.0)
            try:
                with urllib.request.urlopen(self.endpoint, timeout=5) as res:
                    res.read()
            except Exception:
                pass
            current_br = self._get_blast_radius()
            if current_br is not None and current_br == 0.0:
                consecutive_zero_reads += 1
                if consecutive_zero_reads >= 2:
                    return round(time.time() - cb_open_at, 3)
            else:
                consecutive_zero_reads = 0
        # Exiting without recovering: meaningful null (system did not return to
        # baseline within the window), not encoded here -- caller distinguishes.
        return None

    def _drive_half_open_probes(self, snapshot, wait_duration):
        """_poll_for_recovery exits ~2s after the breaker leaves OPEN (blast_radius
        flips to 0.0 the instant it's no longer OPEN -- caveat 1 above), which is
        nowhere near enough of its own light traffic (1 request/iteration) to
        exercise all permitted_calls_half_open probes before we stop watching.
        This function's job is to keep driving traffic until the breaker's own
        real outcome -- HALF_OPEN_TO_CLOSED -- actually lands, not to guess how
        long that should take.

        An earlier version drove a FIXED (permitted_calls_half_open + 2) rounds
        (~4.1s total, unconditional) regardless of whether a real transition had
        happened yet. That fixed budget, not _poll_for_recovery's much larger
        wait_duration-scaled deadline, turned out to be the actual binding
        constraint on whether precise_half_open_to_closed ever saw a value at
        D_w=15/30: every one of the real censored records in the tracked sidecar
        showed exactly 2 logged events (CLOSED_TO_OPEN, OPEN_TO_HALF_OPEN) and
        then silence -- the shape of "this window ended before anything else
        could happen," not "this genuinely never resolves."

        Mirrors _poll_for_recovery's own pattern instead: check collect(snapshot)
        after each round of driven traffic, and stop the moment ANY watched
        breaker's transition list includes HALF_OPEN_TO_CLOSED. A bounce back to
        OPEN (HALF_OPEN_TO_OPEN) does NOT stop the loop -- that isn't a terminal
        outcome, Resilience4j will re-attempt HALF_OPEN again after another
        wait_duration, and ending the observation on a bounce would just be this
        same under-observation bug with a different trigger.

        Hard ceiling: 3*wait_duration + 60s from when probing starts. Generous on
        purpose -- this is "wait for an event you'd reasonably expect eventually,
        not forever," so a breaker that is genuinely stuck can't hang the run.
        Hitting it is a real, logged outcome: returns (True, deadline_s) rather
        than silently exiting, so a censored reading is directly recorded in the
        dataset (half_open_probe_timed_out) instead of only inferable later by
        counting sidecar events by hand -- the same move D14's cb_state_pre made
        for stale breaker state.

        Returns (timed_out: bool, deadline_s: float)."""
        deadline_s = half_open_probe_deadline_s(wait_duration)
        deadline_at = time.time() + deadline_s
        while time.time() < deadline_at:
            try:
                with urllib.request.urlopen(self.endpoint, timeout=5) as res:
                    res.read()
            except Exception:
                pass
            if any(t["state_transition"] == "HALF_OPEN_TO_CLOSED"
                   for t in self.collect(snapshot)):
                # Give a same-instant follow-up event a moment to land before the
                # caller's own final collect() reads the buffer.
                time.sleep(2)
                return False, deadline_s
            time.sleep(0.3)
        return True, deadline_s

    def log(self, path, experiment_id, topology, fault_type, config, mode, replicate,
            fault_injected_at, fault_cleared_at, transitions, machine_id=None):
        """Appends one JSON line per run recording every circuit breaker's real
        CLOSED/OPEN/HALF_OPEN transitions -- kept as a sidecar (not master_dataset.csv
        columns) because the transition list is variable-length per run and a CSV
        cell can't hold an ordered, multi-service event list cleanly. Join back to
        the CSV row via experiment_id + replicate + mode (+ machine_id, once a real
        cross-machine calibration run exists -- see D16).

        Takes `path` directly rather than knowing about
        CANARY_CB_TRANSITIONS_PATH/CB_TRANSITIONS_PATH itself -- the canary-vs-not
        path decision is a caller concern, same pattern get_dataset_path() already
        uses for the CSV side, keeping this class decoupled from runner.py's path
        constants."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            "experiment_id": experiment_id,
            "topology": topology.upper(),
            "fault_type": fault_type.upper(),
            "window_type": config["slidingWindowType"],
            "environment": ENVIRONMENT,
            # --machine-id wins when the caller passes it, falling back to this module's
            # own auto-detection otherwise -- identical semantics to log_results'
            # effective_machine_id (runner.py). Without this the sidecar records the
            # hostname while the CSV records the flag, and the join below -- keyed on
            # machine_id -- silently matches nothing.
            "machine_id": machine_id or MACHINE_ID,
            "mode": mode,
            "replicate": replicate,
            "fault_injected_at": fault_injected_at,
            "fault_cleared_at": fault_cleared_at,
            "transitions": transitions,
        }
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")


# --------------------------------------------------------------------------- self-test

def self_test():
    """No live HTTP, no live mesh -- covers: observe_recovery() always collects
    transitions regardless of cb_opened, but only runs the poll/probe steps when
    cb_open_at is not None; half_open_probe_deadline_s's arithmetic; and
    _drive_half_open_probes stopping on a real HALF_OPEN_TO_CLOSED rather than a
    mere bounce. _poll_for_recovery's actual live-polling behavior, and
    _drive_half_open_probes' ceiling-timeout path specifically (nothing ever
    lands), are NOT exercised here (would need monkeypatching time.time itself
    for disproportionate effort against a 60s+ minimum ceiling) -- those remain
    verifiable only against a live mesh, same as before this extraction."""
    # Ring buffer starts empty (matches reality: containers force-recreated per run).
    events_by_key = {("order", "inventoryServiceCB"): []}

    def fake_fetch(port, breaker):
        return events_by_key.get(("order", breaker), [])

    service_breakers = {"order": (8081, ["inventoryServiceCB"])}
    observer = BreakerObserver(service_breakers, "http://localhost:8080/api/v1/linear",
                                permitted_calls_half_open=5,
                                get_blast_radius_fn=lambda: 0.0,
                                fetch_events_fn=fake_fetch)

    # 1. snapshot_before() taken while the buffer is genuinely empty (baseline 0),
    #    THEN the "fault" happens (events land), THEN collect() reads them -- same
    #    order run_experiment_run uses. before=0 means both events slice as "new".
    snap = observer.snapshot_before()
    assert snap == {("order", "inventoryServiceCB"): 0}, snap
    events_by_key[("order", "inventoryServiceCB")].extend([
        {"stateTransition": "CLOSED_TO_OPEN", "creationTime": "t0"},
        {"stateTransition": "OPEN_TO_HALF_OPEN", "creationTime": "t1"},
    ])
    transitions = observer.collect(snap)
    assert len(transitions) == 2, transitions
    assert transitions[0]["state_transition"] == "CLOSED_TO_OPEN"
    assert transitions[1]["state_transition"] == "OPEN_TO_HALF_OPEN"
    print("self-test 1/5 OK: snapshot_before()/collect() diff correctly")

    # 2. observe_recovery with cb_open_at=None: must skip the poll loop (no time.sleep
    #    calls -- this would hang the test otherwise) but still collect real transitions
    #    against the SAME snapshot (before=0), since the events above are still there.
    #    The two half_open_probe_* values must also be None -- nothing was probed.
    time_to_recover, transitions2, timed_out, deadline_s = observer.observe_recovery(snap, None, 15)
    assert time_to_recover is None, time_to_recover
    assert len(transitions2) == 2, transitions2
    assert timed_out is None and deadline_s is None, (timed_out, deadline_s)
    print("self-test 2/5 OK: observe_recovery(cb_open_at=None) skips polling, still collects")

    # 3. A fresh snapshot taken NOW (after those 2 events already exist) correctly
    #    excludes them from a subsequent collect() -- only genuinely new events count.
    snap2 = observer.snapshot_before()
    assert snap2 == {("order", "inventoryServiceCB"): 2}, snap2
    events_by_key[("order", "inventoryServiceCB")].append(
        {"stateTransition": "HALF_OPEN_TO_CLOSED", "creationTime": "t2"})
    transitions3 = observer.collect(snap2)
    assert len(transitions3) == 1, transitions3
    assert transitions3[0]["state_transition"] == "HALF_OPEN_TO_CLOSED"
    print("self-test 3/5 OK: fresh snapshot excludes already-seen events")

    # 4. half_open_probe_deadline_s is a pure function -- fully checkable without
    #    simulating any real time, unlike the loop that polls against it.
    assert half_open_probe_deadline_s(5) == 75, half_open_probe_deadline_s(5)
    assert half_open_probe_deadline_s(15) == 105, half_open_probe_deadline_s(15)
    assert half_open_probe_deadline_s(30) == 150, half_open_probe_deadline_s(30)
    print("self-test 4/5 OK: half_open_probe_deadline_s arithmetic")

    # 5. _drive_half_open_probes stops the moment collect() reveals
    #    HALF_OPEN_TO_CLOSED, rather than running its full ceiling -- the exact
    #    behavior change from the fixed-count version this replaces. A bounce
    #    (HALF_OPEN_TO_OPEN) alone must NOT stop it. Genuinely fast (~0.6s of
    #    real sleep, two loop iterations) -- not simulated time, real time, but
    #    short enough that --self-test staying fast doesn't require mocking
    #    time.time() the way fully exercising the ceiling-timeout path would
    #    (that path remains verifiable only against a live mesh, same as
    #    _poll_for_recovery's own live-polling behavior above).
    probe_events = []

    def fake_fetch_probe(port, breaker):
        return probe_events

    probe_breakers = {"order": (8081, ["inventoryServiceCB"])}
    probe_observer = BreakerObserver(probe_breakers, "http://localhost:8080/api/v1/linear",
                                      permitted_calls_half_open=5,
                                      get_blast_radius_fn=lambda: 0.0,
                                      fetch_events_fn=fake_fetch_probe)
    probe_snap = probe_observer.snapshot_before()
    assert probe_snap == {("order", "inventoryServiceCB"): 0}, probe_snap

    class _RevealAfterBounce:
        """Simulates urlopen: on the 2nd call, a bounce lands (must NOT stop the
        loop); on the 3rd, the real close lands (must stop it)."""
        def __init__(self):
            self.n = 0

        def __call__(self, *a, **kw):
            self.n += 1
            if self.n == 2:
                probe_events.append({"stateTransition": "HALF_OPEN_TO_OPEN", "creationTime": "t1"})
            elif self.n >= 3:
                probe_events.append({"stateTransition": "HALF_OPEN_TO_CLOSED", "creationTime": "t2"})
            raise Exception("no real mesh in --self-test")  # urlopen itself is swallowed either way

    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", _RevealAfterBounce()):
        timed_out, deadline_s = probe_observer._drive_half_open_probes(probe_snap, wait_duration=5)
    assert timed_out is False, timed_out
    assert deadline_s == 75, deadline_s
    assert any(t["stateTransition"] == "HALF_OPEN_TO_OPEN" for t in probe_events), \
        "the bounce must have actually been injected for this test to mean anything"
    print("self-test 5/5 OK: poll-until-transition stops on CLOSED, not on a bounce")

    print("self-test: 5/5 checks OK")


if __name__ == "__main__":
    self_test()
