#!/bin/sh
# Start PGARA Compiler Studio: finds Python 3, starts the local server and
# opens the GUI in the default browser.  Needs no packages beyond Python 3.
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3.8 or newer is required but was not found."
  echo "On macOS, run:  xcode-select --install   (or install Python from https://www.python.org/downloads/)"
  exit 1
fi

echo "Using $($PY --version 2>&1)"
exec "$PY" server.py "$@"
