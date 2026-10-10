#!/bin/bash
# Runs INSIDE a swefficiency task container to prepare it for a NATIVE agent run.
#   - map litellm host to loopback (reached via the VM's reverse SSH tunnel to the laptop)
#   - install pytest/hypothesis into the testbed env so the agent can run covering tests
#   - install Node + the Claude CLI into the base (py3.11) conda env
# Nous mode additionally:
#   - uninstalls the editable target package so a worktree's source is picked up via PYTHONPATH
#     (the editable egg-link otherwise pins every import to /testbed regardless of PYTHONPATH)
#   - installs the Nous package into base
# Claude mode keeps the editable install intact (plain Claude edits /testbed directly, which the
# editable install measures with no PYTHONPATH tricks) and skips Nous.
# Args: $1 = pip package name (sympy|numpy|scipy)   $2 = mode (nous|claude, default nous)
set -uo pipefail
PKG="$1"
MODE="${2:-nous}"
LITELLM_HOST="ete-litellm.ai-models.vpc-int.res.ibm.com"
CONDA_SH=/opt/miniconda3/etc/profile.d/conda.sh

grep -q "$LITELLM_HOST" /etc/hosts || echo "127.0.0.1 $LITELLM_HOST" >> /etc/hosts

source "$CONDA_SH"

# testbed env: test deps; Nous mode also drops the editable install
conda activate testbed
if [ "$MODE" = "nous" ]; then
  pip uninstall -y "$PKG" -q 2>/dev/null || true
fi
pip install -q pytest hypothesis 2>/dev/null || true
conda deactivate

# base env (py3.11): Node + Claude CLI (+ Nous in nous mode)
conda activate base
if ! command -v node >/dev/null 2>&1; then
  conda install -n base -y -c conda-forge 'nodejs>=20' >/tmp/node_install.log 2>&1
fi
npm install -g @anthropic-ai/claude-code >/tmp/claude_install.log 2>&1
if [ "$MODE" = "nous" ]; then
  pip install -e /opt/nous_repo -q >/tmp/nous_install.log 2>&1
fi
echo "mode=$MODE node=$(node --version 2>/dev/null) claude=$(command -v claude) nous=$(command -v nous || echo n/a)"
