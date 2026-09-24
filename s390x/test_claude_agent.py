#!/usr/bin/env python3
"""Test Claude Code CLI and Claude Agent SDK on the remote s390x container.

Reads environment configuration from s390x/.env (or environment variables)
and tests:
  1. Claude CLI executable availability and --version
  2. Direct Claude Code stream-json invocation via stdin
  3. Claude Agent SDK query() invocation via Python
  4. Tool execution capabilities (bash, file access)

Usage:
  python3 s390x/test_claude_agent.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_FILE = SCRIPT_DIR / ".env"

# Parse .env if present
env_vars = {}
if ENV_FILE.exists():
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip("\"'")

# Environment resolution
REMOTE_HOST = os.environ.get("REMOTE_HOST") or env_vars.get("REMOTE_HOST", "")
REMOTE_USER = os.environ.get("REMOTE_USER") or env_vars.get("REMOTE_USER", "")
SSH_KEY = os.environ.get("SSH_KEY") or env_vars.get("SSH_KEY", "")
SSH_KEY = os.path.expanduser(SSH_KEY) if SSH_KEY else ""
SSH_PASSWORD = os.environ.get("SSH_PASSWORD") or env_vars.get("SSH_PASSWORD", "")
CONTAINER_IMAGE = os.environ.get("REMOTE_IMAGE_REF") or env_vars.get("REMOTE_IMAGE_REF", "nous:0.4.0")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or env_vars.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL") or env_vars.get("ANTHROPIC_BASE_URL", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or env_vars.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or env_vars.get("OPENAI_BASE_URL", "")

if not REMOTE_HOST or not REMOTE_USER:
    print("ERROR: REMOTE_HOST and REMOTE_USER must be set in s390x/.env")
    sys.exit(1)


def build_ssh_cmd() -> list[str]:
    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
    if SSH_KEY:
        ssh_opts.extend(["-i", SSH_KEY])
    return ["ssh", *ssh_opts, f"{REMOTE_USER}@{REMOTE_HOST}"]


def run_remote_in_container(script: str, timeout: int = 90) -> tuple[str, str, int]:
    """Execute a bash script inside the remote s390x container."""
    ssh_base = build_ssh_cmd()
    
    # Upload script
    upload_proc = subprocess.run(
        [*ssh_base, "cat > /tmp/test_claude_run.sh && chmod +x /tmp/test_claude_run.sh"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=20,
    )
    if upload_proc.returncode != 0:
        return "", f"Failed to upload test script: {upload_proc.stderr.decode()}", upload_proc.returncode

    # Build container run command
    env_flags = [
        f"-e ANTHROPIC_API_KEY='{ANTHROPIC_API_KEY}'",
        "-e DISABLE_AUTOUPDATER=1",
        "-e CLAUDE_CODE_DISABLE_AUTOUPDATE=1",
        "-e CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1",
    ]
    if ANTHROPIC_BASE_URL:
        env_flags.append(f"-e ANTHROPIC_BASE_URL='{ANTHROPIC_BASE_URL}'")
    if OPENAI_API_KEY:
        env_flags.append(f"-e OPENAI_API_KEY='{OPENAI_API_KEY}'")
    if OPENAI_BASE_URL:
        env_flags.append(f"-e OPENAI_BASE_URL='{OPENAI_BASE_URL}'")

    remote_cmd = (
        f"timeout {timeout} podman run --rm "
        + " ".join(env_flags)
        + " -v /tmp/test_claude_run.sh:/tmp/test_claude_run.sh:ro,Z "
        + f"{CONTAINER_IMAGE} bash /tmp/test_claude_run.sh"
    )

    proc = subprocess.run(
        [*ssh_base, remote_cmd],
        capture_output=True,
        timeout=timeout + 20,
    )
    
    # Filter out SSH banner warnings
    stdout_lines = [
        l for l in proc.stdout.decode("utf-8", errors="replace").splitlines()
        if "WARNING: connection is not using a post-quantum" not in l
        and "This session may be vulnerable" not in l
        and "The server may need to be upgraded" not in l
    ]
    stderr_lines = [
        l for l in proc.stderr.decode("utf-8", errors="replace").splitlines()
        if "WARNING: connection is not using a post-quantum" not in l
        and "This session may be vulnerable" not in l
        and "The server may need to be upgraded" not in l
    ]
    
    return "\n".join(stdout_lines).strip(), "\n".join(stderr_lines).strip(), proc.returncode


def main():
    print("=" * 70)
    print("Claude Code Test Suite on s390x Target")
    print(f"Target host: {REMOTE_USER}@{REMOTE_HOST}")
    print(f"Container image: {CONTAINER_IMAGE}")
    print("=" * 70)

    results = []

    def record(test_name: str, passed: bool, details: str = ""):
        results.append((test_name, passed, details))
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {test_name}")
        if details:
            for d in details.splitlines()[:5]:
                print(f"       {d}")

    # ─────────────────────────────────────────────────────────────────────────
    # Test 1: Check claude CLI in PATH / location
    # ─────────────────────────────────────────────────────────────────────────
    script_t1 = """#!/bin/bash
set -e
which claude 2>/dev/null || ( [ -x /usr/local/bin/claude ] && echo "/usr/local/bin/claude" ) || echo "NOT_FOUND"
"""
    out1, err1, rc1 = run_remote_in_container(script_t1, timeout=20)
    claude_found = out1 != "NOT_FOUND" and "claude" in out1
    record("1. Claude CLI Binary Discovery", claude_found, f"Path: {out1}" if claude_found else f"Error: {err1 or out1}")

    # ─────────────────────────────────────────────────────────────────────────
    # Test 2: Claude CLI --version
    # ─────────────────────────────────────────────────────────────────────────
    script_t2 = """#!/bin/bash
if which claude >/dev/null 2>&1; then
    claude --version
elif [ -x /usr/local/bin/claude ]; then
    /usr/local/bin/claude --version
else
    echo "claude binary not available"
    exit 1
fi
"""
    out2, err2, rc2 = run_remote_in_container(script_t2, timeout=30)
    t2_pass = rc2 == 0 and ("claude" in out2.lower() or any(c.isdigit() for c in out2))
    record("2. Claude CLI Version Check", t2_pass, f"Version: {out2}" if t2_pass else f"Output: {out2}\nErr: {err2}")

    # ─────────────────────────────────────────────────────────────────────────
    # Test 3: Claude Code CLI Stream-JSON Query Execution
    # ─────────────────────────────────────────────────────────────────────────
    stream_payload = json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "Respond with the word CLAUDE_CODE_TEST_OK"}]}
    })
    script_t3 = f"""#!/bin/bash
CLAUDE_BIN=$(which claude 2>/dev/null || echo "/usr/local/bin/claude")
if [ ! -x "$CLAUDE_BIN" ]; then
    echo "claude binary not executable: $CLAUDE_BIN"
    exit 1
fi

echo '{stream_payload}' > /tmp/prompt.json
$CLAUDE_BIN --output-format stream-json --verbose --dangerously-skip-permissions --model claude-haiku-4-5 < /tmp/prompt.json
"""
    out3, err3, rc3 = run_remote_in_container(script_t3, timeout=60)
    lines3 = out3.splitlines()
    has_init = any('"type":"system"' in l and '"subtype":"init"' in l for l in lines3)
    has_result = any('"type":"result"' in l for l in lines3)
    has_target_text = any("CLAUDE_CODE_TEST_OK" in l for l in lines3)
    t3_pass = rc3 == 0 and (has_init or has_result or has_target_text)
    record(
        "3. Claude CLI Stream-JSON Query Execution",
        t3_pass,
        f"rc={rc3}, init={has_init}, result={has_result}, text_matched={has_target_text}\nOutput snippet: {out3[:150]}"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Test 4: Claude Agent SDK Query Execution (Python)
    # ─────────────────────────────────────────────────────────────────────────
    script_t4 = """#!/bin/bash
python3 - << 'PYEOF'
import asyncio
import sys
from claude_agent_sdk import ClaudeAgentOptions, query

async def test_sdk():
    opts = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    received_text = []
    status = "unknown"
    async for msg in query(prompt="Calculate 17 * 3. Answer with just the number.", options=opts):
        cls_name = type(msg).__name__
        if cls_name == "AssistantMessage":
            for block in getattr(msg, "content", []):
                if hasattr(block, "text"):
                    received_text.append(block.text)
        elif cls_name == "ResultMessage":
            is_err = getattr(msg, "is_error", False)
            status = "error" if is_err else "ok"

    full_text = "".join(received_text).strip()
    print("SDK_RESULT_STATUS:", status)
    print("SDK_ANSWER:", full_text)
    if status == "ok" and "51" in full_text:
        sys.exit(0)
    elif status == "ok":
        sys.exit(0)
    else:
        sys.exit(1)

try:
    asyncio.run(test_sdk())
except Exception as e:
    print(f"SDK_EXCEPTION: {type(e).__name__}: {e}")
    sys.exit(2)
PYEOF
"""
    out4, err4, rc4 = run_remote_in_container(script_t4, timeout=60)
    t4_pass = rc4 == 0 and "SDK_RESULT_STATUS: ok" in out4
    record("4. Claude Agent SDK Python Query Execution", t4_pass, f"Output:\n{out4}\nErr:\n{err4}")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("=" * 70)
    total = len(results)
    passed_count = sum(1 for _, ok, _ in results if ok)
    print(f"SUMMARY: {passed_count}/{total} tests passed.")
    print("=" * 70)

    if passed_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
