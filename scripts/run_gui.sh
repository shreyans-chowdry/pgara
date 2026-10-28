#!/usr/bin/env bash
# Start the PGARA Compiler Studio (web GUI) at http://127.0.0.1:8765/
set -e
cd "$(dirname "$0")/.."
[ -f configs/server.env ] && . configs/server.env
PORT=${PGARA_PORT:-8765}
FLAGS=""
[ "${PGARA_OPEN_BROWSER:-1}" = "0" ] && FLAGS="--no-browser"
exec ${PYTHON:-python3} server.py --port "$PORT" $FLAGS
