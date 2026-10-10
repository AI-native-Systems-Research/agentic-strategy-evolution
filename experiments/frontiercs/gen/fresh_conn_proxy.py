#!/usr/bin/env python3
"""Fresh-connection reverse proxy for the IBM litellm gateway.

WHY (diagnosed 2026-10-07): the bundled/standalone `claude` CLI (a Bun binary) reuses a keep-alive
socket that the gateway/LB silently drops during the between-turn idle gap (e.g. while a C++ compile
runs). The next request reuses the dead socket and the CLI's retries never recover, even though a
BRAND-NEW connection (plain curl) to the gateway is always fast. In-process env tweaks
(DISABLE_IO_POOL, HTTP_IDLE_TIMEOUT, MAX_RETRIES, newer CLI 2.1.292) did NOT fix recovery.

FIX: point the CLI at this local proxy (ANTHROPIC_BASE_URL=http://127.0.0.1:<port>). For every request
the proxy opens a FRESH https connection to the real gateway (Connection: close, no upstream keep-alive)
and streams the SSE response back. The CLI's connection is to localhost (never dropped); the gateway
only ever sees fresh connections (like curl) -> no dead-socket reuse, no stall.

Usage:
  python fresh_conn_proxy.py --port 8900 --upstream https://ete-litellm.ai-models.vpc.res.ibm.com
Then run the CLI/runner with ANTHROPIC_BASE_URL=http://127.0.0.1:8900 (API key header is passed through).
"""
import argparse, http.client, ssl, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

UP_HOST = None
UP_PORT = 443


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # quiet

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length", 0) or 0)
        te = self.headers.get("Transfer-Encoding", "")
        body = self.rfile.read(length) if length else b""
        _info = ""
        try:
            import json as _j
            _b = _j.loads(body) if body else {}
            _info = (f"stream={_b.get('stream')} max_tokens={_b.get('max_tokens')} "
                     f"msgs={len(_b.get('messages', []))} tools={len(_b.get('tools', []))} "
                     f"sys_type={type(_b.get('system')).__name__}")
        except Exception:
            _info = "(body not json)"
        print(f"[proxy] REQ {method} {self.path} clen={length} te={te!r} bodylen={len(body)} | {_info}",
              flush=True)
        if body and "/v1/messages" in self.path:
            try:
                open("/tmp/claude_lastreq.json", "wb").write(body)
            except Exception:
                pass
            # FIX (2026-10-07, root-caused by request replay): opus with thinking={"type":"adaptive"}
            # makes this litellm->Bedrock gateway BUFFER the entire thinking phase before emitting any
            # byte. On a hard problem that exceeds the gateway's ~60s first-byte cut, so the request
            # NEVER returns (0 bytes @ 90s). The identical request with `thinking` removed answers in
            # ~24s. The gateway cannot stream thinking incrementally (infra limitation), so we strip it
            # here -> the Claude baseline runs WITHOUT extended thinking. Content-Length is recomputed
            # by http.client from the mutated body (we don't forward the original content-length).
            try:
                import json as _jj
                _obj = _jj.loads(body)
                if isinstance(_obj, dict) and _obj.pop("thinking", None) is not None:
                    body = _jj.dumps(_obj).encode()
                    print(f"[proxy] stripped thinking -> bodylen={len(body)}", flush=True)
            except Exception:
                pass
        fwd = {}
        for k, v in self.headers.items():
            if k.lower() in ("host", "content-length", "connection", "proxy-connection",
                             "keep-alive", "accept-encoding"):
                continue
            fwd[k] = v
        fwd["Host"] = UP_HOST
        fwd["Connection"] = "close"          # NO upstream keep-alive -> fresh socket every time
        fwd["Accept-Encoding"] = "identity"  # don't let upstream gzip the SSE stream
        ctx = ssl.create_default_context()

        # First-byte latency here is dominated by the MODEL: opus on a hard problem with large context
        # can take tens of seconds to emit the first token (thinking). A short first-byte cutoff kills
        # these valid slow generations and retries forever (that was the real churn, NOT dead backends:
        # 20/20 fresh curls with max_tokens=8 all returned 200 while big-generation requests "hung").
        # So FIRST_BYTE_T must comfortably exceed real first-token latency; only a backend that is
        # genuinely wedged (no byte for minutes) gets dropped and retried on a fresh connection.
        # Measured 2026-10-07: a HEALTHY first byte is always <20s (direct curl: trivial/large/stream/
        # effort=high all 2-13s; through this proxy 13-19s). A request that has sent nothing by ~55s is
        # wedged, not slow -- and the gateway/LB itself RSTs it at ~60s ("RemoteDisconnected"). So wait
        # just under that cut, then re-dial a FRESH connection; a healthy attempt almost always lands
        # within a few tries. (The old 240s wait burned 4 min per wedge for no benefit.) IDLE_T stays
        # generous because a flowing stream is healthy and a full heavy generation runs ~100-185s.
        FIRST_BYTE_T = 55.0
        IDLE_T = 300.0
        MAX_TRIES = 12
        import time as _t
        for attempt in range(1, MAX_TRIES + 1):
            conn = None
            try:
                _t0 = _t.time()
                conn = http.client.HTTPSConnection(UP_HOST, UP_PORT, timeout=FIRST_BYTE_T, context=ctx)
                conn.request(method, self.path, body=body, headers=fwd)
                resp = conn.getresponse()            # blocks for headers; raises on FIRST_BYTE_T timeout
                sock = getattr(conn, "sock", None)   # relax timeout for the stream once headers are in
                if sock is not None:
                    sock.settimeout(IDLE_T)
                first = resp.read(1)                 # ensure a real first body byte
                print(f"[proxy] UP {self.path} attempt {attempt} status={resp.status} "
                      f"first_byte={_t.time()-_t0:.1f}s", flush=True)
            except Exception as e:
                print(f"[proxy] UP {self.path} attempt {attempt} EXC after "
                      f"{_t.time()-_t0:.1f}s: {type(e).__name__}: {e}", flush=True)
                try:
                    if conn: conn.close()
                except Exception:
                    pass
                print(f"[proxy] attempt {attempt}/{MAX_TRIES} dead-backend ({type(e).__name__}: {e}), retrying fresh", flush=True)
                continue
            # healthy backend: stream it through
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                    continue
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                if first:
                    self.wfile.write(first); self.wfile.flush()
                while True:
                    chunk = resp.read(2048)
                    if not chunk:
                        break
                    self.wfile.write(chunk); self.wfile.flush()
            finally:
                conn.close()
            return
        # all attempts hit dead backends
        try:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"proxy: all upstream attempts hit dead backends")
        except Exception:
            pass

    def do_POST(self):
        self._proxy("POST")

    def do_GET(self):
        self._proxy("GET")


def main():
    global UP_HOST, UP_PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--upstream", default="https://ete-litellm.ai-models.vpc.res.ibm.com")
    args = ap.parse_args()
    u = urlparse(args.upstream)
    UP_HOST = u.hostname
    UP_PORT = u.port or (443 if u.scheme == "https" else 80)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[proxy] 127.0.0.1:{args.port} -> {UP_HOST}:{UP_PORT} (fresh connection per request)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
