"""PGARA Compiler Studio: a zero-dependency web server for the GUI.

    python3 server.py [--port 8765] [--no-browser]

If the port is taken, the next free one (up to 19 higher) is used.

Serves the single-page interface in web/ and a small JSON API:
    GET  /api/examples     benchmark programs with their train/test inputs
    POST /api/compile      {source, k, opt_level, train_inputs, test_inputs}
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from pgara.pipeline import compile_source  # noqa: E402
from pgara.bench import SUITE, load  # noqa: E402
from pgara.regalloc import ALLOCATOR_NAMES  # noqa: E402

WEB = os.path.join(ROOT, "web")
MAX_BODY = 1_000_000


def examples():
    out = []
    for name, title, train, test in SUITE:
        out.append({"name": name, "title": title, "source": load(name), "train": train, "test": test})
    return out


def parse_inputs(value):
    if isinstance(value, list):
        return [int(x) for x in value]
    if isinstance(value, str):
        return [int(x) for x in value.replace(",", " ").split()]
    return []


class Handler(BaseHTTPRequestHandler):
    server_version = "PgaraStudio/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=list).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/examples":
            self.send_json({"examples": examples(), "allocators": ALLOCATOR_NAMES})
            return
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(WEB) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/compile":
            self.send_error(404, "Not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.send_json({"ok": False, "fatal": "request body missing or too large"}, 400)
            return
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            k = max(1, min(16, int(req.get("k", 4))))
            opts = {
                "k": k,
                "opt_level": max(0, min(2, int(req.get("opt_level", 2)))),
                "train_inputs": parse_inputs(req.get("train_inputs", [])),
                "test_inputs": parse_inputs(req.get("test_inputs", [])),
            }
            report = compile_source(str(req.get("source", "")), opts)
            self.send_json(report)
        except (ValueError, TypeError) as exc:
            self.send_json({"ok": False, "fatal": f"bad request: {exc}"}, 400)
        except Exception as exc:  # report internal errors to the GUI instead of dropping the connection
            traceback.print_exc()
            self.send_json({"ok": False, "fatal": f"internal compiler error: {exc}"}, 500)


def main():
    ap = argparse.ArgumentParser(description="PGARA Compiler Studio")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    httpd = None
    for port in range(args.port, args.port + 20):
        try:
            httpd = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError:
            print(f"Port {port} is busy, trying {port + 1}...")
    if httpd is None:
        sys.exit(f"No free port between {args.port} and {args.port + 19}; pass --port to choose another.")
    url = f"http://{args.host}:{httpd.server_address[1]}/"
    print(f"PGARA Compiler Studio running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
