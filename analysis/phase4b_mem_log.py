"""Free-physical-memory sampler for the Phase 4B sweep. DIAGNOSTIC ONLY.

READ-ONLY with respect to every experimental artifact. It reads a kernel counter and
appends one line to a log under a gitignored path. It touches no dataset, no sidecar, no
poll log, and nothing under version control.

**This is not an exclusion rule and it changes no pre-registered rule.** Nothing it records
may remove a run from the analysis, reweight one, or alter any threshold in
`docs/paper/h3-postd25-analysis-plan.md` (frozen at 3e4ad1e). If it shows memory pressure
during the sweep, that is **reported as a limitation** alongside the results -- exactly as
§8 already reports the database-state and single-machine limitations. It is evidence about
the host, not about the breakers.

Log format, one line per sample:

    2026-09-21T10:24:06+05:30 free_mb=1967.1

Why ctypes and not psutil or a PowerShell subprocess: `GlobalMemoryStatusEx` is the same
counter `Win32_OperatingSystem.FreePhysicalMemory` reports, reachable from the standard
library with no dependency and no process spawn every 30 s. On a non-Windows host the
sampler falls back to /proc/meminfo so the script is still runnable for review.

Subcommands:

    log      append a sample every --interval seconds, forever (the sweep-long logger)
    sample   take N samples and report min/median/max; with --min-free-mb, exit non-zero
             if the MEDIAN is below it. The launch script's RAM assertion uses this, so
             the gate and the log share one implementation and cannot drift apart.

The `sample` subcommand exists because a single instantaneous reading of this counter is
not a usable gate on this host: six readings taken 10 s apart during Phase 4B preparation
ranged 1334.3-1944.6 MB, a ~610 MB swing, so one sample could pass or fail at random.
Median-of-N is the gate; min and max are always printed so the volatility stays visible.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import statistics
import sys
import time


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_mb():
    """Free physical memory in MB. Same counter as Win32_OperatingSystem.FreePhysicalMemory."""
    if os.name == "nt":
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            raise OSError("GlobalMemoryStatusEx failed")
        return st.ullAvailPhys / 1048576.0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    raise OSError("could not read free memory")


def total_mb():
    if os.name == "nt":
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPhys / 1048576.0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                return float(line.split()[1]) / 1024.0
    return float("nan")


def stamp():
    """Local time, ISO-8601 with UTC offset, e.g. 2026-09-21T10:24:06+05:30."""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def cmd_log(a):
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "a", encoding="utf-8") as f:
        f.write(f"# phase4b mem logger start {stamp()} "
                f"interval={a.interval}s total_mb={total_mb():.1f} pid={os.getpid()}\n")
        f.flush()
        while True:
            t0 = time.time()
            f.write(f"{stamp()} free_mb={free_mb():.1f}\n")
            f.flush()
            time.sleep(max(0.0, a.interval - (time.time() - t0)))


def cmd_sample(a):
    vals = []
    for i in range(a.n):
        vals.append(free_mb())
        if i < a.n - 1:
            time.sleep(a.gap)
    med = statistics.median(vals)
    print(f"  samples ({a.n} over ~{a.gap * (a.n - 1):.0f}s): "
          + ", ".join(f"{v:.1f}" for v in vals))
    print(f"  min={min(vals):.1f} MB  median={med:.1f} MB  max={max(vals):.1f} MB  "
          f"total={total_mb():.1f} MB")
    if a.min_free_mb is None:
        return 0
    ok = med >= a.min_free_mb
    print(f"  gate: median {med:.1f} MB {'>=' if ok else '<'} required {a.min_free_mb:.1f} MB"
          f" -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    if min(vals) < a.min_free_mb:
        print(f"  NOTE: the minimum sample ({min(vals):.1f} MB) is below the threshold. The "
              f"gate is the median;\n        this host's reading is volatile. Reported, not "
              f"treated as a failure.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="append a sample every --interval seconds, forever")
    p.add_argument("--out", default=os.path.join("logs", "phase4b_mem.log"))
    p.add_argument("--interval", type=float, default=30.0)

    s = sub.add_parser("sample", help="N samples; min/median/max, optional gate")
    s.add_argument("-n", type=int, default=5)
    s.add_argument("--gap", type=float, default=2.0)
    s.add_argument("--min-free-mb", type=float, default=None)

    a = ap.parse_args()
    return cmd_log(a) if a.cmd == "log" else cmd_sample(a)


if __name__ == "__main__":
    sys.exit(main())
