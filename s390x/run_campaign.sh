#!/usr/bin/env bash
# run_campaign.sh — build and deploy the Nous s390x container to a remote IBM Z host
#
# The image is built NATIVELY on the remote s390x machine — no cross-compilation.
# Flow: rsync Dockerfile → remote podman build → remote podman run (foreground,
#       streaming stdout/stderr live back to this terminal) → rsync artifacts back.
#
# Output:
#   Terminal output  — nous stdout/stderr streams live through SSH to your terminal.
#   Campaign artifacts — rsynced from the remote to LOCAL_ARTIFACTS_DIR when the
#                        run finishes (or manually via ./run_campaign.sh sync).
#
# Usage:
#   ./run_campaign.sh deploy            # build + clone repo + run; streams output live (default)
#   ./run_campaign.sh build             # sync Dockerfile + build image on remote only
#   ./run_campaign.sh sync              # rsync campaign artifacts from remote to LOCAL_ARTIFACTS_DIR
#   ./run_campaign.sh stop              # stop and remove the container on the remote host
#   ./run_campaign.sh restart           # stop + deploy on the remote host
#   ./run_campaign.sh status            # show container status on the remote host
#   ./run_campaign.sh logs              # tail container logs on the remote host (detached runs)
#   ./run_campaign.sh shell             # open an interactive shell on the remote host inside the container
#
# Environment:
#   Variables are loaded from .env (gitignored, created from .env.example).
#   Any variable already set in the calling shell takes precedence.

set -euo pipefail

# ── Locate script directory ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: ${ENV_FILE} not found."
    echo "       Create it from the template:"
    echo "         cp ${ENV_EXAMPLE} ${ENV_FILE}"
    echo "       Then fill in ANTHROPIC_API_KEY at minimum."
    exit 1
fi

# Export variables from .env without overriding anything already in the environment.
# Lines starting with # or that are blank are skipped.
while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line//[[:space:]]/}" ]]  && continue
    varname="${line%%=*}"
    if [[ -z "${!varname+x}" ]]; then
        export "${line?}"
    fi
done < "${ENV_FILE}"

# ── Defaults ──────────────────────────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-nous}"
IMAGE_TAG="${IMAGE_TAG:-0.4.0}"
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.112}"
CONTAINER_NAME="${CONTAINER_NAME:-nous-s390x}"
# Host-side directory for campaign artifacts (created on remote host, bind-mounted into container)
NOUS_CAMPAIGN_HOST_DIR="${NOUS_CAMPAIGN_HOST_DIR:-/home/${REMOTE_USER:-}/nous-campaigns}"
# Container-internal path — must match the directory created in the Dockerfile
NOUS_CAMPAIGN_PARENT="${NOUS_CAMPAIGN_PARENT:-/opt/app-root/src/campaigns}"
CAMPAIGN_YAML="${CAMPAIGN_YAML:-/campaign/campaign.yaml}"
NOUS_MAX_ITERATIONS="${NOUS_MAX_ITERATIONS:-1}"
NOUS_TIMEOUT="${NOUS_TIMEOUT:-3600}"
NOUS_MAX_CLI_RETRIES="${NOUS_MAX_CLI_RETRIES:--1}"
NOUS_ALLOW_AUTO_APPROVE="${NOUS_ALLOW_AUTO_APPROVE:-1}"
LOCAL_CAMPAIGN_YAML="${LOCAL_CAMPAIGN_YAML:-${SCRIPT_DIR}/campaign.yaml}"
# Resolve relative path against the script directory
[[ "${LOCAL_CAMPAIGN_YAML}" != /* ]] && LOCAL_CAMPAIGN_YAML="${SCRIPT_DIR}/${LOCAL_CAMPAIGN_YAML#./}"
# Local directory where campaign artifacts are rsynced after the run completes
LOCAL_ARTIFACTS_DIR="${LOCAL_ARTIFACTS_DIR:-${SCRIPT_DIR}/campaigns}"
[[ "${LOCAL_ARTIFACTS_DIR}" != /* ]] && LOCAL_ARTIFACTS_DIR="${SCRIPT_DIR}/${LOCAL_ARTIFACTS_DIR#./}"
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_WORKDIR="${REMOTE_WORKDIR:-/tmp/nous}"
# Expand tilde in SSH_KEY so it works in arrays
SSH_KEY="${SSH_KEY:-}"
SSH_KEY="${SSH_KEY/#\~/${HOME}}"
SSH_PASSWORD="${SSH_PASSWORD:-}"
TARGET_REPO_GIT_URL="${TARGET_REPO_GIT_URL:-}"
TARGET_REPO_BRANCH="${TARGET_REPO_BRANCH:-main}"
TARGET_REPO_TOKEN="${TARGET_REPO_TOKEN:-}"

# Image tag built and used on the remote host
REMOTE_IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[run_campaign.sh] $*"; }
warn() { echo "[run_campaign.sh] WARN: $*" >&2; }
die()  { echo "[run_campaign.sh] ERROR: $*" >&2; exit 1; }

require_var() {
    local var="$1" label="$2"
    [[ -n "${!var:-}" ]] || die "${var} is not set. ${label}"
}

# Build the SSH options array (no subshell — sets SSH_OPTS in caller's scope)
_build_ssh_opts() {
    SSH_OPTS=(-o StrictHostKeyChecking=no -o ConnectTimeout=10)
    if [[ -n "${SSH_KEY}" ]]; then
        SSH_OPTS+=(-i "${SSH_KEY}" -o BatchMode=yes)
    elif [[ -n "${SSH_PASSWORD}" ]]; then
        command -v sshpass &>/dev/null \
            || die "sshpass is required for password auth. Install it or set SSH_KEY in ${ENV_FILE}."
    else
        die "Set SSH_KEY (or SSH_PASSWORD) in ${ENV_FILE} to connect to the remote host."
    fi
}

# Run a command on the remote host; all arguments are passed as a single remote command.
remote() {
    local SSH_OPTS=()
    _build_ssh_opts
    if [[ -n "${SSH_PASSWORD}" && -z "${SSH_KEY}" ]]; then
        SSHPASS="${SSH_PASSWORD}" sshpass -e ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    else
        ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    fi
}

# Copy a local file to the remote host.
remote_copy() {
    local src="$1" dst="$2"
    local SSH_OPTS=()
    _build_ssh_opts
    if [[ -n "${SSH_PASSWORD}" && -z "${SSH_KEY}" ]]; then
        SSHPASS="${SSH_PASSWORD}" sshpass -e scp "${SSH_OPTS[@]}" "${src}" "${REMOTE_USER}@${REMOTE_HOST}:${dst}"
    else
        scp "${SSH_OPTS[@]}" "${src}" "${REMOTE_USER}@${REMOTE_HOST}:${dst}"
    fi
}

# ── Sub-commands ──────────────────────────────────────────────────────────────

cmd_copy_campaign() {
    [[ -f "${LOCAL_CAMPAIGN_YAML}" ]] || \
        die "campaign.yaml not found at '${LOCAL_CAMPAIGN_YAML}'. Set LOCAL_CAMPAIGN_YAML in ${ENV_FILE} or create ${SCRIPT_DIR}/campaign.yaml."

    local remote_campaign_dir="${REMOTE_WORKDIR}/campaign"
    log "Copying campaign.yaml to ${REMOTE_USER}@${REMOTE_HOST}:${remote_campaign_dir}/ ..."
    remote "mkdir -p ${remote_campaign_dir}"
    remote_copy "${LOCAL_CAMPAIGN_YAML}" "${remote_campaign_dir}/campaign.yaml"
    log "campaign.yaml staged at ${remote_campaign_dir}/campaign.yaml."

    # Export for use in cmd_deploy's podman run
    REMOTE_CAMPAIGN_DIR="${remote_campaign_dir}"
}

cmd_clone_repo() {
    # No-op when TARGET_REPO_GIT_URL is not set — repo is assumed pre-placed.
    [[ -n "${TARGET_REPO_GIT_URL}" ]] || return 0

    require_var TARGET_REPO_PATH "Set TARGET_REPO_PATH in ${ENV_FILE}."

    # Build the authenticated URL: inject token into HTTPS URLs only.
    # SSH URLs (git@...) are passed through unchanged — the remote host's
    # SSH key handles auth.
    local auth_url="${TARGET_REPO_GIT_URL}"
    if [[ -n "${TARGET_REPO_TOKEN}" && "${TARGET_REPO_GIT_URL}" == https://* ]]; then
        # Strip any existing credentials then inject the token as the username.
        # GitHub/GitLab accept:  https://<token>@github.com/org/repo.git
        local stripped="${TARGET_REPO_GIT_URL#https://}"
        # Remove any existing user:pass@ prefix
        stripped="${stripped#*@}"
        auth_url="https://${TARGET_REPO_TOKEN}@${stripped}"
    fi

    log "Provisioning target repo on ${REMOTE_HOST}:${TARGET_REPO_PATH} ..."

    # Clone or update — token is injected into the remote URL only (never passed
    # as a shell variable visible in `ps`). Note: `git remote set-url` writes the
    # authenticated URL into .git/config on the remote host; rotate or revoke the
    # token if the remote host is untrusted.
    remote bash -s << EOF
set -euo pipefail
if [ -d "${TARGET_REPO_PATH}/.git" ]; then
    echo "[repo] Updating existing clone..."
    # Reconfigure the remote URL (token may have changed) then fetch+reset.
    git -C "${TARGET_REPO_PATH}" remote set-url origin '${auth_url}'
    git -C "${TARGET_REPO_PATH}" fetch origin
    git -C "${TARGET_REPO_PATH}" checkout "${TARGET_REPO_BRANCH}" 2>/dev/null \
        || git -C "${TARGET_REPO_PATH}" checkout -b "${TARGET_REPO_BRANCH}" --track "origin/${TARGET_REPO_BRANCH}"
    git -C "${TARGET_REPO_PATH}" reset --hard "origin/${TARGET_REPO_BRANCH}"
    echo "[repo] Updated to \$(git -C '${TARGET_REPO_PATH}' rev-parse --short HEAD)."
else
    echo "[repo] Cloning ${TARGET_REPO_GIT_URL} (branch: ${TARGET_REPO_BRANCH})..."
    mkdir -p "$(dirname '${TARGET_REPO_PATH}')"
    git clone --branch "${TARGET_REPO_BRANCH}" --single-branch \
        '${auth_url}' '${TARGET_REPO_PATH}'
    echo "[repo] Cloned to \$(git -C '${TARGET_REPO_PATH}' rev-parse --short HEAD)."
fi
EOF
    log "Target repo ready at ${TARGET_REPO_PATH}."
}

cmd_build() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."

    # ── Step 1: sync Dockerfile and build context to remote ───────────────────
    local remote_build_dir="${REMOTE_WORKDIR}/nous-build"
    log "Syncing build context to ${REMOTE_USER}@${REMOTE_HOST}:${remote_build_dir} ..."
    remote "mkdir -p ${remote_build_dir}"

    local SSH_OPTS=()
    _build_ssh_opts
    local rsh_opt
    if [[ -n "${SSH_PASSWORD}" && -z "${SSH_KEY}" ]]; then
        export SSHPASS="${SSH_PASSWORD}"
        rsh_opt="sshpass -e ssh ${SSH_OPTS[*]}"
    else
        rsh_opt="ssh ${SSH_OPTS[*]}"
    fi

    # Sync Dockerfile, environment.yml, verify script, and local codebase to the build context root
    rsync -az \
        -e "${rsh_opt}" \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 's390x/campaigns' \
        "${REPO_ROOT}/orchestrator" \
        "${REPO_ROOT}/prompts" \
        "${REPO_ROOT}/pyproject.toml" \
        "${SCRIPT_DIR}/Dockerfile" \
        "${SCRIPT_DIR}/environment.yml" \
        "${SCRIPT_DIR}/verify-image.sh" \
        "${REMOTE_USER}@${REMOTE_HOST}:${remote_build_dir}/"
    log "Build context synced."

    # ── Step 2: build natively on the remote s390x host ──────────────────────
    log "Building image ${REMOTE_IMAGE_REF} on ${REMOTE_HOST} (native s390x) ..."
    local build_arg_claude_version=""
    [[ -n "${CLAUDE_CODE_VERSION}" ]] && build_arg_claude_version="--build-arg CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}"
    remote "podman build \
        --tag ${REMOTE_IMAGE_REF} \
        ${build_arg_claude_version} \
        ${remote_build_dir}"
    log "Build complete: ${REMOTE_IMAGE_REF} on ${REMOTE_HOST}."

    # ── Step 3: verify image on remote s390x host ────────────────────────────
    log "Running verification suite on remote s390x host..."
    remote "bash ${remote_build_dir}/verify-image.sh ${REMOTE_IMAGE_REF}"
    log "Verification passed successfully on ${REMOTE_HOST}."
}

cmd_deploy() {
    require_var REMOTE_HOST    "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER    "Set REMOTE_USER in ${ENV_FILE}."
    require_var ANTHROPIC_API_KEY "Set ANTHROPIC_API_KEY in ${ENV_FILE}."
    require_var TARGET_REPO_PATH \
        "Set TARGET_REPO_PATH in ${ENV_FILE} to the absolute path on the REMOTE host."

    # ── Step 1: copy campaign.yaml to remote ─────────────────────────────────
    cmd_copy_campaign

    # ── Step 2: build natively on remote ─────────────────────────────────────
    cmd_build

    # ── Step 3: clone / update the target repository ─────────────────────────
    cmd_clone_repo

    # ── Step 4: prepare remote host directories ───────────────────────────────
    # Create the campaign output dir world-writable so the container (which runs
    # as a subUID-mapped UID under rootless --userns=keep-id) can write to it
    # and the host user can read/rsync the artifacts afterward.
    remote "mkdir -p ${NOUS_CAMPAIGN_HOST_DIR} && chmod 0777 ${NOUS_CAMPAIGN_HOST_DIR}"

    # Fix ownership and permissions across target repo using podman unshare
    remote "podman unshare chmod -R a+rwX ${TARGET_REPO_PATH} 2>/dev/null || true"

    # ── Step 5: stop any existing container ──────────────────────────────────
    log "Removing any existing container '${CONTAINER_NAME}' on ${REMOTE_HOST} ..."
    remote "podman rm -f ${CONTAINER_NAME} 2>/dev/null || true"

    # ── Step 5: launch container ──────────────────────────────────────────────
    #           it as a single quoted string to avoid word-splitting secrets ──
    local auto_approve_flag=""
    [[ "${NOUS_ALLOW_AUTO_APPROVE}" == "1" ]] && auto_approve_flag="--auto-approve"

    # Run in FOREGROUND (no --detach) so stdout/stderr stream live through SSH
    # back to this terminal. The here-doc keeps secrets out of `ps` output.
    # --rm removes the container automatically when nous exits.
    log "Running container '${CONTAINER_NAME}' on ${REMOTE_HOST} — output streaming live ..."
    log "  Campaign artifacts will be rsynced to: ${LOCAL_ARTIFACTS_DIR}"
    log "────────────────────────────────────────────────────────────────"
    local run_exit=0
    remote << EOF || run_exit=$?
podman run \
    --rm \
    --name ${CONTAINER_NAME} \
    --userns=keep-id \
    -e ANTHROPIC_API_KEY='${ANTHROPIC_API_KEY}' \
    -e NOUS_CAMPAIGN_PARENT='${NOUS_CAMPAIGN_PARENT}' \
    -e OPENAI_API_KEY='${OPENAI_API_KEY:-}' \
    -e OPENAI_BASE_URL='${OPENAI_BASE_URL:-}' \
    -e NOUS_ALLOW_AUTO_APPROVE='${NOUS_ALLOW_AUTO_APPROVE}' \
    $( [[ -n "${ANTHROPIC_BASE_URL:-}" ]] && echo "-e ANTHROPIC_BASE_URL='${ANTHROPIC_BASE_URL}'" ) \
    $( [[ -n "${ROUTINES_API_BASE:-}" ]] && echo "-e ROUTINES_API_BASE='${ROUTINES_API_BASE}'" ) \
    -v ${TARGET_REPO_PATH}:/workspace:Z \
    -v ${NOUS_CAMPAIGN_HOST_DIR}:${NOUS_CAMPAIGN_PARENT}:Z \
    -v ${REMOTE_CAMPAIGN_DIR}:/campaign:Z \
    ${REMOTE_IMAGE_REF} \
    nous run ${CAMPAIGN_YAML} \
        --agent sdk \
        --max-iterations ${NOUS_MAX_ITERATIONS} \
        --timeout ${NOUS_TIMEOUT} \
        --max-cli-retries ${NOUS_MAX_CLI_RETRIES} \
        ${auto_approve_flag}
EOF
    log "────────────────────────────────────────────────────────────────"

    # ── Step 6: fix artifact permissions so the host user can read them ───────
    # The container runs as a subUID-mapped user; files it writes appear owned
    # by a high subUID on the host.  Use 'podman unshare' to open and chmod the
    # tree from inside the user namespace where those UIDs map back to the
    # container UID, making files readable by the host user.
    log "Fixing campaign artifact permissions ..."
    remote "podman unshare chmod -R o+rX ${NOUS_CAMPAIGN_HOST_DIR} 2>/dev/null || true"

    # ── Step 7: sync campaign artifacts back to local machine ────────────────
    cmd_sync

    if [[ "${run_exit:-0}" -ne 0 ]]; then
        die "Campaign failed with exit code ${run_exit}. Artifacts (if any) are in: ${LOCAL_ARTIFACTS_DIR}"
    fi
    log "Campaign complete. Artifacts in: ${LOCAL_ARTIFACTS_DIR}"
}

cmd_sync() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."

    mkdir -p "${LOCAL_ARTIFACTS_DIR}"

    local SSH_OPTS=()
    _build_ssh_opts
    local rsh_opt
    if [[ -n "${SSH_PASSWORD}" && -z "${SSH_KEY}" ]]; then
        export SSHPASS="${SSH_PASSWORD}"
        rsh_opt="sshpass -e ssh ${SSH_OPTS[*]}"
    else
        rsh_opt="ssh ${SSH_OPTS[*]}"
    fi

    log "Syncing campaign artifacts from ${REMOTE_HOST}:${NOUS_CAMPAIGN_HOST_DIR}/ → ${LOCAL_ARTIFACTS_DIR}/ ..."
    rsync -az --progress \
        -e "${rsh_opt}" \
        "${REMOTE_USER}@${REMOTE_HOST}:${NOUS_CAMPAIGN_HOST_DIR}/" \
        "${LOCAL_ARTIFACTS_DIR}/"
    log "Artifacts synced to: ${LOCAL_ARTIFACTS_DIR}"
    log ""
    log "Key files:"
    # Print any state.json and findings.json that landed locally
    find "${LOCAL_ARTIFACTS_DIR}" \
        \( -name "state.json" -o -name "findings.json" -o -name "principles.json" -o -name "report.md" \) \
        -printf "  %p\n" 2>/dev/null \
        | sort || true
}

cmd_stop() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."
    log "Stopping container '${CONTAINER_NAME}' on ${REMOTE_HOST} ..."
    remote "podman rm -f ${CONTAINER_NAME} 2>/dev/null && echo 'removed' || echo 'not running'"
}

cmd_restart() {
    cmd_stop
    cmd_deploy
}

cmd_status() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."
    log "Container status on ${REMOTE_HOST}:"
    remote "podman inspect --format \
        'Name: {{.Name}}  State: {{.State.Status}}  Image: {{.ImageName}}' \
        ${CONTAINER_NAME} 2>/dev/null || echo '${CONTAINER_NAME}: not found'"
}

cmd_logs() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."
    log "Tailing logs for '${CONTAINER_NAME}' on ${REMOTE_HOST} (Ctrl-C to stop) ..."
    remote "podman logs -f ${CONTAINER_NAME}"
}

cmd_shell() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."
    log "Opening shell in container '${CONTAINER_NAME}' on ${REMOTE_HOST} ..."
    # Use -t to allocate a pseudo-TTY end-to-end
    local SSH_OPTS=()
    _build_ssh_opts
    if [[ -n "${SSH_PASSWORD}" && -z "${SSH_KEY}" ]]; then
        SSHPASS="${SSH_PASSWORD}" sshpass -e ssh -t "${SSH_OPTS[@]}" \
            "${REMOTE_USER}@${REMOTE_HOST}" \
            "podman exec -it ${CONTAINER_NAME} /bin/bash"
    else
        ssh -t "${SSH_OPTS[@]}" \
            "${REMOTE_USER}@${REMOTE_HOST}" \
            "podman exec -it ${CONTAINER_NAME} /bin/bash"
    fi
}

cmd_verify() {
    require_var REMOTE_HOST "Set REMOTE_HOST in ${ENV_FILE}."
    require_var REMOTE_USER "Set REMOTE_USER in ${ENV_FILE}."
    local remote_build_dir="${REMOTE_WORKDIR}/nous-build"
    log "Running verification test suite on ${REMOTE_HOST} ..."
    remote "bash ${remote_build_dir}/verify-image.sh ${REMOTE_IMAGE_REF}"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
CMD="${1:-deploy}"

case "${CMD}" in
    deploy)  cmd_deploy  ;;
    build)   cmd_build   ;;
    verify)  cmd_verify  ;;
    sync)    cmd_sync    ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    status)  cmd_status  ;;
    logs)    cmd_logs    ;;
    shell)   cmd_shell   ;;
    exec)    shift; remote "$@" ;;
    *)
        echo "Usage: $(basename "$0") {deploy|build|verify|sync|stop|restart|status|logs|shell|exec <cmd>}"
        exit 1
        ;;
esac
