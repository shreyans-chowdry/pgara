#!/usr/bin/env bash
# Run the 27 unit and end-to-end tests (about 1-3 minutes).
set -e
cd "$(dirname "$0")/.."
${PYTHON:-python3} -m unittest -v tests.test_compiler
