#!/usr/bin/env python3
"""Local pass-through proxy that meters OpenAI-format LLM spend per response.

Used to give real Engram (which only logs its cost every 5 iterations) the same per-call iso-cost
ruler as Nous/Claude: tokens x $15 in / $75 out, cache reads $1.50, cache writes $18.75 per M.
Streaming requests get ``stream_options.include_usage`` so the final chunk carries usage.
"""
import http.client, json, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6


def usage_cost(u):
    prompt = u.get("prompt_tokens", 0) or 0
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0) or (u.get("cache_read_input_tokens", 0) or 0)
    cwrite = u.get("cache_creation_input_tokens", 0) or 0
    fresh = max(prompt - cached - cwrite, 0)
    return fresh * R_IN + cached * R_CR + cwrite * R_CW + (u.get("completion_tokens", 0) or 0) * R_OUT


class Meter:
    def __init__(self): self.cost = 0.0; self.calls = 0; self.lock = threading.Lock()
    def add(self, u):
        with self.lock: self.cost += usage_cost(u); self.calls += 1


def start(upstream, port=0):
    """Start the proxy in a daemon thread; returns (server, meter, base_url)."""
    up = urllib.parse.urlparse(upstream.rstrip("/"))
    meter = Meter()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            streaming = False
            try:
                req = json.loads(body)
                if req.get("stream"):
                    streaming = True
                    req.setdefault("stream_options", {})["include_usage"] = True
                    body = json.dumps(req).encode()
            except (ValueError, AttributeError):
                pass
            hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection", "accept-encoding")}
            hdrs["Content-Length"] = str(len(body)); hdrs["Connection"] = "close"
            C = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
            conn = C(up.netloc, timeout=900)
            try:
                conn.request("POST", up.path + self.path, body=body, headers=hdrs)
                r = conn.getresponse()
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                        self.send_header(k, v)
                self.send_header("Connection", "close")
                if streaming and r.status == 200:
                    self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
                    buf = b""
                    while True:
                        chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                        if not chunk: break
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk)); self.wfile.flush()
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            if line.startswith(b"data:") and b'"usage"' in line:
                                try:
                                    u = json.loads(line[5:].strip()).get("usage")
                                    if u: meter.add(u)
                                except ValueError: pass
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    data = r.read()
                    self.send_header("Content-Length", str(len(data))); self.end_headers()
                    self.wfile.write(data)
                    if r.status == 200:
                        try:
                            u = json.loads(data).get("usage")
                            if u: meter.add(u)
                        except ValueError: pass
            finally:
                conn.close()
            self.close_connection = True

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, meter, f"http://127.0.0.1:{srv.server_address[1]}"
