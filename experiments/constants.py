"""Constants shared between the live harness (runner.py) and offline analysis
(analysis/canary_readout.py).

Split out of runner.py so analysis code can import a value like
LAMBDA_DEVIATION_THRESHOLD without triggering runner.py's module-scope
Toxiproxy import, which can fail in an analysis-only environment. Keep this
file stdlib-only -- nothing here should ever need a fallback/try-except at
the import site again.
"""

# Achieved-vs-requested arrival rate (see the "lambda_target/lambda_achieved" comment
# block in runner.py's DATASET_HEADERS). Flag a run when the measured rate misses the
# requested one by more than this fraction -- 15% is a coarse tripwire, not a precision
# bound.
LAMBDA_DEVIATION_THRESHOLD = 0.15
