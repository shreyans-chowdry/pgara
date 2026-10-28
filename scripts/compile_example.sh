#!/usr/bin/env bash
# Compile one MiniC program from the command line and print a summary and the PGARA assembly.
#   scripts/compile_example.sh benchmarks/05_rarebranch.mc 4 "7 10" "13 10"
set -e
cd "$(dirname "$0")/.."
${PYTHON:-python3} scripts/sample_outputs.py --file "${1:-benchmarks/05_rarebranch.mc}" --k "${2:-4}" \
  --train "${3:-7 10}" --test "${4:-13 10}" --print
