#!/usr/bin/env python3
"""Minimal repro: opus-4-6 with extended *thinking* enabled gets ZERO response bytes for >90s on the
IBM litellm gateway, while the IDENTICAL request with thinking disabled answers in ~10-40s.

Hand this to the litellm/gateway admins. It sends two streaming POST /v1/messages requests that differ
ONLY by the `thinking` field, over FRESH connections (Connection: close), and prints time-to-first-byte.

Hypothesis it demonstrates: the gateway appears to BUFFER the model's thinking phase (emits no bytes
until the first visible output). On a hard prompt the thinking exceeds some ~60s idle/first-byte
timeout on an intermediate hop, so the silent connection is killed before any byte is sent. A normal
streaming response (no thinking, or thinking streamed incrementally) sends bytes within seconds and is
fine. We would like the gateway to either (a) stream thinking deltas incrementally, or (b) emit SSE
keep-alive pings during thinking, or (c) raise the first-byte/idle timeout for thinking requests.

Observed 2026-10-07 (vpc-int, claude-opus-4-6):
  thinking ENABLED  -> 0 bytes, times out (>90s)
  thinking DISABLED -> first byte in ~10-40s, streams normally

NOTE: the stall is INTERMITTENT and scales with think duration. A light prompt may think only ~15s and
not trip the ~60s cut. For a strong, faithful trigger, point LLM_REQ_FILE at a real captured Claude Code
request body (a 100KB+ multi-turn request on a hard problem); the script will send it as-is (thinking
on) vs with `thinking` stripped. It also loops each variant LLM_TRIES times to surface the intermittency.

Usage (key is read from env, never hardcode it):
  export LLM_URL=https://ete-litellm.ai-models.vpc-int.res.ibm.com
  export LLM_KEY=sk-...            # your litellm key, sent as x-api-key
  # optional, strongest repro: a real captured heavy request body (JSON of a /v1/messages POST)
  export LLM_REQ_FILE=/path/to/captured_request.json
  export LLM_TRIES=4               # attempts per variant (default 4)
  python3 repro_thinking_stall.py
"""
import http.client
import json
import os
import ssl
import sys
import time
from urllib.parse import urlparse

URL = os.environ.get("LLM_URL")
KEY = os.environ.get("LLM_KEY")
MODEL = os.environ.get("LLM_MODEL", "claude-opus-4-6")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
if not URL or not KEY:
    sys.exit("set LLM_URL and LLM_KEY environment variables")

u = urlparse(URL)
HOST = u.hostname
PORT = u.port or (443 if u.scheme == "https" else 80)
TRIES = int(os.environ.get("LLM_TRIES", "4"))
REQ_FILE = os.environ.get("LLM_REQ_FILE")

PROMPT = (
    "You are entering a hard research problem. Think about it as exhaustively as possible BEFORE writing "
    "anything. Problem: design a provably-optimal exact algorithm to pack N arbitrary polyominoes "
    "(reflections + all four rotations allowed) into a minimum-area axis-aligned bounding box. "
    "Work through, step by step and at great length: (1) a precise formalization and all edge cases; "
    "(2) an ILP formulation with every constraint derived; (3) an exact branch-and-bound with "
    "dominance rules and symmetry breaking, each rule proven correct; (4) tight complexity bounds with "
    "proofs; (5) at least a dozen concrete worked micro-examples; (6) correctness and optimality proofs "
    "in full. Do not summarize; expand every step with complete reasoning before giving a final answer."
)


def make_body(thinking):
    if REQ_FILE:
        body = json.load(open(REQ_FILE))
        body["stream"] = True
        if thinking:
            body.setdefault("thinking", {"type": "adaptive"})
            body.setdefault("output_config", {"effort": "high"})
        else:
            body.pop("thinking", None)
    else:
        body = {"model": MODEL, "max_tokens": 64000, "stream": True,
                "messages": [{"role": "user", "content": PROMPT}]}
        if thinking:
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": "high"}
    return json.dumps(body).encode()


def probe(thinking):
    data = make_body(thinking)
    headers = {"x-api-key": KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json", "connection": "close"}
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(HOST, PORT, timeout=TIMEOUT, context=ctx)
    t0 = time.time()
    try:
        conn.request("POST", "/v1/messages", body=data, headers=headers)
        resp = conn.getresponse()
        first = resp.read(1)
        dt = time.time() - t0
        flag = "" if first else "   <-- NO BODY"
        return f"HTTP {resp.status}, first byte {dt:5.1f}s{flag}"
    except Exception as e:
        dt = time.time() - t0
        return f"FAILED after {dt:5.1f}s ({type(e).__name__})   <-- STALL"
    finally:
        try:
            conn.close()
        except Exception:
            pass


src = f"captured body {REQ_FILE} ({len(make_body(True))} bytes)" if REQ_FILE else "synthetic prompt"
print(f"gateway = {HOST}:{PORT}   model = {MODEL}   timeout = {TIMEOUT:.0f}s   tries = {TRIES}")
print(f"request = {src}")
print("identical streaming requests, differing only by the `thinking` field:\n")
for i in range(1, TRIES + 1):
    print(f"  try {i}  thinking-ON  : {probe(True)}")
    print(f"  try {i}  thinking-OFF : {probe(False)}")
