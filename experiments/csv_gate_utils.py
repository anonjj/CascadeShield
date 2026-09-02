"""Shared stdlib-only CSV helpers for compute_phi.py and validate_gate.py.

No pandas -- both callers are deliberately standalone/dependency-free (see
their own module docstrings), so this stays stdlib-only too.
"""
import csv


def load_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def safe_float(raw):
    """Parse a CSV cell as a float, or None for blank/unparseable input.

    Shared by validate_gate.py::is_unsafe and compute_phi.py::tripped, which
    both treat a blank or "None" blast_radius (a skipped/failed/unreachable
    run) as "not tripped" rather than raising or fabricating a 0.0."""
    raw = (raw or "").strip()
    if raw in ("", "None"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None
