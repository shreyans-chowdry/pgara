#!/usr/bin/env bash
# Reproduce every result of the manuscript (writes results/v2/*.json).
# Full run: about 15-25 minutes on a laptop. Pass study names to run a subset, e.g.
#   scripts/run_experiments.sh main inputs
set -e
cd "$(dirname "$0")/.."
${PYTHON:-python3} -m pgara.experiments "$@" --config configs/experiments.json --out results/v2
${PYTHON:-python3} scripts/summarise_results.py
