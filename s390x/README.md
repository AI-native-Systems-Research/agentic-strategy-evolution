# s390x — Nous on IBM Z

This directory contains everything needed to build and run the Nous agentic research framework natively on an IBM Z (s390x) host using Podman containers.

The image is **built natively on the remote machine** — no cross-compilation or emulation. All orchestration runs from your local machine over SSH; the container itself executes on the IBM Z host.

---

## How it works

```
Local machine                         Remote IBM Z host (s390x)
─────────────────────────────────     ──────────────────────────────────────────
run_campaign.sh deploy
  │
  ├─ rsync Dockerfile + build context ──► podman build (native s390x)
  │
  ├─ scp campaign.yaml ─────────────────► /remote-workdir/campaign/campaign.yaml
  │
  ├─ git clone / pull target repo ──────► TARGET_REPO_PATH (e.g. ~/nous/flask)
  │
  └─ podman run (foreground via SSH) ───► nous run /campaign/campaign.yaml
       streams stdout/stderr live            │
       back to your terminal                 └─ writes artifacts to
                                               NOUS_CAMPAIGN_HOST_DIR
  rsync artifacts ◄────────────────────── (rsynced back when run finishes)
  → LOCAL_ARTIFACTS_DIR
```

### Container internals

The [`Dockerfile`](Dockerfile) builds a single image from **Red Hat UBI 10** (`linux/s390x`) that contains:

| Layer | What it installs |
|---|---|
| System packages | GCC / G++ / gfortran, Rust, Clang, LLVM, CMake, OpenSSL, Node.js |
| Claude Code CLI | `@anthropic-ai/claude-code` (via npm) — baked into the image |
| Miniconda | Python 3.12 environment for s390x (`environment.yml`) |
| Python packages | NumPy, SciPy, Pandas, PyMC, ArviZ, Pydantic, OpenAI SDK, `claude-agent-sdk`, and more |
| Nous | Installed in editable mode from the local repo (`orchestrator/`, `prompts/`, `pyproject.toml`) |

The container runs as a **non-root user** (UID 1001) and writes campaign artifacts to `/opt/app-root/src/campaigns` (bind-mounted from the host).

---

## Prerequisites

| Requirement | Where |
|---|---|
| SSH access to an IBM Z machine | Key-based auth recommended (`SSH_KEY`); password auth supported via `sshpass` |
| `podman` installed on the remote host | Required to build and run the image natively |
| `rsync` and `scp` on your local machine | Used to transfer files |
| An Anthropic API key | Required — Nous will not start without it |

---

## Quick start

### 1. Create your `.env`

```bash
cp s390x/.env.example s390x/.env
```

Edit `s390x/.env` and fill in at minimum:

```
REMOTE_HOST=your-ibm-z-host.example.com
REMOTE_USER=yourusername
SSH_KEY=~/.ssh/id_rsa

ANTHROPIC_API_KEY=sk-ant-...

TARGET_REPO_PATH=/home/yourusername/nous/flask
```

All other variables have sensible defaults. See [`.env.example`](.env.example) for the full reference and inline documentation.

### 2. Deploy and run

```bash
./s390x/run_campaign.sh deploy
```

This performs the full flow in one command:
1. Syncs the build context to the remote host
2. Builds the container image natively on the IBM Z machine
3. Runs the image verification suite
4. Clones or updates the target repository
5. Launches the container (output streams live to your terminal)
6. Rsyncs campaign artifacts back to `s390x/campaigns/` when finished

---

## `run_campaign.sh` subcommands

| Command | What it does |
|---|---|
| `deploy` | Full flow: build + clone repo + run (default) |
| `build` | Sync build context + build image on remote only |
| `verify` | Run the image verification suite on the remote host |
| `sync` | Rsync campaign artifacts from remote → `LOCAL_ARTIFACTS_DIR` |
| `stop` | Stop and remove the running container on the remote host |
| `restart` | `stop` + `deploy` |
| `status` | Print container name, state, and image on the remote host |
| `logs` | Tail container logs (useful when run detached) |
| `shell` | Open an interactive bash shell inside the running container |
| `exec <cmd>` | Run an arbitrary command on the remote host via SSH |

---

## Campaign configuration

[`campaign.yaml`](campaign.yaml) defines what Nous investigates. The included example studies **Flask request routing overhead** — it measures whether the number of registered routes causes measurable per-request latency regression, and at what threshold the overhead exceeds 5%.

Key fields:

```yaml
research_question: "..."       # The question Nous will try to answer
target_system:
  repo_path: /workspace        # Path inside the container (bind-mounted from TARGET_REPO_PATH)
max_iterations: 5              # How many experiment iterations to run
max_turns:
  design: 60                   # Claude turn budget for the design phase
  execute_analyze: 80          # Claude turn budget for the execute/analyse phase
```

To run a different campaign, either edit `campaign.yaml` or set `LOCAL_CAMPAIGN_YAML` in `.env` to point to a different file.

---

## Environment variables reference

All variables are documented inline in [`.env.example`](.env.example). Key groups:

| Group | Variables |
|---|---|
| **Remote host** | `REMOTE_HOST`, `REMOTE_USER`, `SSH_KEY`, `SSH_PASSWORD`, `REMOTE_WORKDIR` |
| **Image** | `IMAGE_NAME`, `IMAGE_TAG`, `CLAUDE_CODE_VERSION` |
| **Anthropic / Claude** | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` |
| **OpenAI-compatible LLM** | `OPENAI_API_KEY`, `OPENAI_BASE_URL` (used for gate summaries and reports) |
| **Nous framework** | `NOUS_CAMPAIGN_HOST_DIR`, `NOUS_CAMPAIGN_PARENT`, `NOUS_ALLOW_AUTO_APPROVE` |
| **Target repo** | `TARGET_REPO_GIT_URL`, `TARGET_REPO_BRANCH`, `TARGET_REPO_TOKEN`, `TARGET_REPO_PATH` |
| **Run parameters** | `NOUS_MAX_ITERATIONS`, `NOUS_TIMEOUT`, `NOUS_MAX_CLI_RETRIES` |
| **Output** | `LOCAL_ARTIFACTS_DIR` — where artifacts land locally after `sync` |

---

## Verification

[`verify-image.sh`](verify-image.sh) is automatically run after every `build`. It confirms:

1. Container architecture is `s390x`
2. Container runs as a non-root user
3. Conda is available and functional
4. Python reports `platform.machine() == 's390x'`
5. All scientific and core Python packages import correctly (`numpy`, `scipy`, `pandas`, `pymc`, `arviz`, `pydantic`, `openai`, `claude_agent_sdk`)
6. The `claude` CLI binary is present and reports its version
7. The `nous` CLI is available and responds to `--help`

Run it manually at any time:

```bash
./s390x/run_campaign.sh verify
```

---

## Integration test

[`test_claude_agent.py`](test_claude_agent.py) runs a four-test suite against the live container on the remote host over SSH. It reads connection details from `s390x/.env` and tests:

1. Claude CLI binary is discoverable in `$PATH`
2. `claude --version` returns a valid version string
3. Claude CLI can execute a `stream-json` query end-to-end
4. `claude-agent-sdk` Python `query()` call completes successfully

```bash
python3 s390x/test_claude_agent.py
```

---

## Artifact outputs

After a run, `s390x/campaigns/` (or `LOCAL_ARTIFACTS_DIR`) will contain:

| File | Description |
|---|---|
| `state.json` | Full campaign state including all iterations |
| `findings.json` | Distilled empirical findings from each iteration |
| `principles.json` | Generalised principles extracted across iterations |
| `ledger.json` | Token and cost accounting per phase |
| `report.md` | Human-readable campaign report |
