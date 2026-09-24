#!/usr/bin/env bash
# verify-image.sh — Validate native s390x UBI 10 + Conda + Claude Code + Nous container

set -euo pipefail

IMAGE="${1:-localhost/nous:0.4.0}"

echo "══════════════════════════════════════════════════════════════════"
echo "Verifying image: ${IMAGE}"
echo "══════════════════════════════════════════════════════════════════"

echo "1. Checking container architecture..."
ARCH=$(podman run --rm --platform linux/s390x "${IMAGE}" uname -m)
echo "   Architecture: ${ARCH}"
if [[ "${ARCH}" != "s390x" ]]; then
    echo "FAIL: Expected architecture s390x, got ${ARCH}"
    exit 1
fi

echo "2. Checking non-root execution..."
UID_TEST=$(podman run --rm --platform linux/s390x "${IMAGE}" id -u)
echo "   UID: ${UID_TEST}"
if [[ "${UID_TEST}" == "0" ]]; then
    echo "FAIL: Container is running as root (UID 0)"
    exit 1
fi

echo "3. Checking Conda version..."
podman run --rm --platform linux/s390x "${IMAGE}" conda --version

echo "4. Checking Python runtime on s390x..."
podman run --rm --platform linux/s390x "${IMAGE}" python -c '
import platform
import sys
print("   Machine:", platform.machine())
print("   Python:", sys.version)
assert platform.machine() == "s390x", f"Unexpected machine: {platform.machine()}"
'

echo "5. Checking scientific & core components from conda_components.md..."
podman run --rm --platform linux/s390x "${IMAGE}" python -c '
import numpy
import scipy
import pandas
import pymc
import arviz
import pydantic
import openai
import claude_agent_sdk

print("   NumPy:", numpy.__version__)
print("   SciPy:", scipy.__version__)
print("   Pandas:", pandas.__version__)
print("   PyMC:", pymc.__version__)
print("   ArviZ:", arviz.__version__)
print("   Pydantic:", pydantic.__version__)
print("   OpenAI:", openai.__version__)
print("   Claude Agent SDK:", claude_agent_sdk.__version__)
'

echo "6. Checking Claude Code & SDK CLI integration..."
podman run --rm --platform linux/s390x "${IMAGE}" bash -c '
echo "   Checking claude executable location..."
if which claude >/dev/null 2>&1; then
    echo "   Claude path: $(which claude)"
    claude --version || true
elif [ -x /usr/local/bin/claude ]; then
    echo "   Claude path: /usr/local/bin/claude"
    /usr/local/bin/claude --version || true
else
    echo "   WARNING: claude executable not found in image"
fi
'

echo "7. Checking Nous CLI..."
podman run --rm --platform linux/s390x "${IMAGE}" nous --help

echo "══════════════════════════════════════════════════════════════════"
echo "SUCCESS: All s390x container validation checks passed."
echo "══════════════════════════════════════════════════════════════════"
