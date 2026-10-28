#!/usr/bin/env bash
# One-time setup check for a fresh environment.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
$PY - <<'P'
import sys
assert sys.version_info >= (3, 8), "PGARA needs Python 3.8 or newer"
print("Python", sys.version.split()[0], "OK")
P
$PY -m pip install -r requirements.txt >/dev/null 2>&1 || true   # no runtime dependencies
$PY scripts/prepare_datasets.py
echo "Setup complete. Next: scripts/run_tests.sh, scripts/run_gui.sh or scripts/run_experiments.sh"
