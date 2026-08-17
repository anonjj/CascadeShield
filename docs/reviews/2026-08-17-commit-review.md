# Commit Review — 2026-08-17 (run 2, commit-only mode)

Scope: commits in the last 24 hours. Focus areas: `experiments/`, `ml/`, `services/`.

## Commits inspected

| Commit | Author | Subject |
| --- | --- | --- |
| `eb10d48` | Jay Joshi | feat: update dataset schema to include mode and permitted_calls_half_open, and refine blast radius normalization |
| `c465232` | (review bot) | chore(review): automated review 2026-08-16 (run 2) — skipped (own automated commit) |

Only `eb10d48` carries source changes. It touches `experiments/runner.py` and `infra/docker-compose.yml`. `python -m py_compile experiments/runner.py` passes.

---

## Findings

### 1. `CB_EVENT_BUFFER_SIZE` now injected as 2000, breaking the "must match application.yml" contract — HIGH
`experiments/runner.py:254`, `experiments/runner.py:272` (and orphaned `experiments/runner.py:152`)

The commit adds a new module-level constant and re-points the `.env` template at it:

```python
# line 152 (pre-existing, still present)
CB_EVENT_BUFFER_SIZE = 50  # must match application.yml's event-consumer-buffer-size
# line 254 (new)
EVENT_BUFFER_SIZE = 2000   # module-level, beside PERMITTED_CALLS_HALF_OPEN
# line 272 (changed)
CB_EVENT_BUFFER_SIZE={EVENT_BUFFER_SIZE}   # was {CB_EVENT_BUFFER_SIZE}
```

**Problem:** the value the runner writes into the generated `.env` jumped from **50 → 2000** (a 40× increase). Every service pins `event-consumer-buffer-size: ${CB_EVENT_BUFFER_SIZE:50}` (gateway/notification/inventory/payment/order `application.yml`) and `infra/docker-compose.yml:8` defaults to `${CB_EVENT_BUFFER_SIZE:-50}`. Because the runner-generated `.env` *overrides* those defaults, every runner-driven experiment now silently runs the circuit breakers with a buffer of 2000 instead of the 50 the whole codebase is documented and defaulted around. The comment on line 152 explicitly states the value *must match* application.yml (50); this change violates that invariant.

**Fix:** either revert the injected value to 50, or — if 2000 is genuinely intended — bump every `application.yml` `event-consumer-buffer-size` default and the docker-compose default to 2000 in the same change so the contract holds. Whichever way, keep a single source of truth for the number.

### 2. Dead constant left behind after the rename — MEDIUM
`experiments/runner.py:152`

`CB_EVENT_BUFFER_SIZE = 50` is no longer referenced by anything after line 272 was switched to `EVENT_BUFFER_SIZE`. It's now dead code that also *contradicts* the live value (50 vs 2000), which is a trap for the next reader. Also note the new constant's naming breaks the `CB_`-prefixed convention used by every sibling constant (`CB_MINIMUM_CALLS`, `PERMITTED_CALLS_HALF_OPEN` is the lone other exception).

**Fix:** delete line 152 and rename `EVENT_BUFFER_SIZE` → `CB_EVENT_BUFFER_SIZE` (there's no reason for the rename; the original name matched the emitted env key). This collapses the two constants back into one and removes the value contradiction from finding #1.

### 3. Commit message does not describe the diff — MEDIUM (process)
The message advertises "update dataset schema to include mode and permitted_calls_half_open, and refine blast radius normalization." None of that appears in the diff: there is no dataset-schema change, no `mode` column, no `permitted_calls_half_open` schema change, and no blast-radius normalization change. The actual diff is (a) the event-buffer-size constant swap, (b) wiring `CB_MINIMUM_CALLS` into the compose anchor, and (c) cosmetic YAML reformatting. A message this mismatched makes `git log`/`git bisect` archaeology unreliable — worth a follow-up commit note or an amended message on the branch before it propagates.

### 4. De-indented config entry in `generate_combinations` — LOW
`experiments/runner.py:1250`

```python
            {"failureRateThreshold": 30, ... "slidingWindowType": "COUNT_BASED"},
        {"failureRateThreshold": 30, ... "slidingWindowType": "TIME_BASED"},   # 8 spaces vs 12
```

The `TIME_BASED` entry was de-indented from 12 to 8 spaces, misaligning it with every other element of the `configs` list. It's inside a list literal so it compiles and behaves identically, but it reads as an accidental edit. **Fix:** restore 12-space alignment.

---

## Positive note

`infra/docker-compose.yml:7` adds `CB_MINIMUM_CALLS: ${CB_MINIMUM_CALLS:-5}` to the `x-cb-env` anchor. The runner already emits `CB_MINIMUM_CALLS` into the `.env` (`runner.py:273`), but the compose anchor previously dropped it, so services fell back to their hard-coded default. This correctly closes that gap. The healthcheck `test: [...]` reformatting is cosmetic and harmless.

---

_Automated commit-review run. No source files modified._
