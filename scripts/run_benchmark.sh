#!/usr/bin/env bash
# Quick study with the four GUI allocators (k = 3..8); writes results/results.json and results.csv.
set -e
cd "$(dirname "$0")/.."
${PYTHON:-python3} -m pgara.bench "$@"
