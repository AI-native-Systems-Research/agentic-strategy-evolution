"""Per-run localhost pass-through proxy to the LLM gateway (the sandbox only allows localhost).

The request body is forwarded unchanged (no model, prompt, or thinking changes). Every request opens a fresh upstream
connection (the gateway drops idle keep-alive sockets). A request that sends no byte for 120 s is retried on a fresh
connection, up to 6 tries. Logs one line per request (path, model, status, bytes) for auditing.

Usage: proxy.py <port> <upstream_url> <log_file>
"""
import http.client
import json
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

UP = None
LOG = None
FIRST_BYTE_T, IDLE_T, TRIES = 120.0, 600.0, 6


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self, method):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else b""
        try:
            model = json.loads(body).get("model") if body else None
        except ValueError:
            model = None
        fwd = {k: v for k, v in self.headers.items()
               if k.lower() not in ("host", "content-length", "connection", "keep-alive", "accept-encoding",
                                    "proxy-connection")}
        fwd.update({"Host": UP.hostname, "Connection": "close", "Accept-Encoding": "identity"})
        for attempt in range(1, TRIES + 1):
            t0 = time.time()
            conn = None
            try:
                conn = http.client.HTTPSConnection(UP.hostname, UP.port or 443, timeout=FIRST_BYTE_T,
                                                   context=ssl.create_default_context())
                conn.request(method, self.path, body=body, headers=fwd)
                resp = conn.getresponse()
                if conn.sock:
                    conn.sock.settimeout(IDLE_T)
                first = resp.read(1)
            except Exception as e:  # noqa: BLE001
                log(f"{method} {self.path} model={model} attempt={attempt} EXC {type(e).__name__} after {time.time()-t0:.0f}s")
                if conn:
                    conn.close()
                continue
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            sent = 0
            try:
                if first:
                    self.wfile.write(first)
                    sent += 1
                while True:
                    c = resp.read(4096)
                    if not c:
                        break
                    self.wfile.write(c)
                    self.wfile.flush()
                    sent += len(c)
            except Exception as e:  # noqa: BLE001
                log(f"{method} {self.path} model={model} stream EXC {type(e).__name__}")
            finally:
                conn.close()
            log(f"{method} {self.path} model={model} status={resp.status} bytes={sent} t={time.time()-t0:.0f}s attempt={attempt}")
            return
        self.send_response(502)
        self.send_header("Connection", "close")
        self.end_headers()
        log(f"{method} {self.path} model={model} FAILED after {TRIES} tries")

    def do_POST(self):
        self._go("POST")

    def do_GET(self):
        self._go("GET")


if __name__ == "__main__":
    port, UP, LOG = int(sys.argv[1]), urlparse(sys.argv[2]), sys.argv[3]
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
