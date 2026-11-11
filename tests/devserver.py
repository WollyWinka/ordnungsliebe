"""Entwicklungs-Server: Oberfläche im normalen Browser mit echtem Programmkern (Test-KI).

Aufruf:  ORDNUNGSLIEBE_FAKE_AI=1 python tests/devserver.py [port]
"""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api import Api  # noqa: E402
from app.events import bus  # noqa: E402

UI = ROOT / "ui"
api = Api()
events: list = []
lock = threading.Lock()


def collect(name, payload):
    with lock:
        events.append([name, payload])


bus.subscribe(collect)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/events":
            with lock:
                out = list(events)
                events.clear()
            return self._send(200, json.dumps(out, default=str).encode())
        rel = self.path.split("?")[0].lstrip("/") or "index.html"
        f = (UI / rel).resolve()
        if UI not in f.parents and f != UI / "index.html" or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._send(404, b"{}")
        name = self.path[5:]
        length = int(self.headers.get("Content-Length", 0))
        args = json.loads(self.rfile.read(length) or b"[]")
        fn = getattr(api, name, None)
        if fn is None or name.startswith("_"):
            return self._send(404, json.dumps({"ok": False, "error": "unbekannt"}).encode())
        res = fn(*args)
        self._send(200, json.dumps(res, default=str).encode())


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    api.start_background()
    print(f"http://127.0.0.1:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
