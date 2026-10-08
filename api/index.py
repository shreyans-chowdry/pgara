"""Vercel Serverless Function entry point for PGARA Compiler Studio."""

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

# Ensure root repository directory is in sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pgara.pipeline import compile_source
from pgara.bench import SUITE, load
from pgara.regalloc import ALLOCATOR_NAMES

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


class handler(BaseHTTPRequestHandler):
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
        if path == "/api/examples" or path.endswith("/examples"):
            self.send_json({"examples": examples(), "allocators": ALLOCATOR_NAMES})
            return
        self.send_error(404, "Not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/compile" and not path.endswith("/compile"):
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
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"ok": False, "fatal": f"internal compiler error: {exc}"}, 500)
