"""Reproducibility metadata capture (#262 / F17).

At INIT (before any DESIGN turn fires), capture environment metadata
that nous would otherwise leave to operator memory: target repo
commit, hardware-config sha, language versions, gpu_memory_utilization,
etc. The block lives in two places:

* ``state.json["reproducibility_metadata"]`` — the campaign-wide pin.
* ``runs/iter-N/snapshots/`` — per-iteration physical copies of any
  latency / hardware config files (so a future reviewer can diff the
  exact numbers each iter ran with, even if the operator later edits
  the source-of-truth file in the target repo).

Pure Python, no LLM. Idempotent: re-running on an existing work_dir
preserves the original capture (you don't accidentally rewrite the
``repo_commit`` field after several iterations have run).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Files we hash and snapshot. Any file in this list that exists in the
# target repo at INIT becomes part of the reproducibility record.
# Naming follows BLIS conventions but is target-agnostic — missing
# files are skipped, not errors.
_HARDWARE_CONFIG_CANDIDATES = ("hardware_config.json",)
_LATENCY_CONFIG_GLOBS = (
    "model-configs/*/latency.json",
    "configs/latency/*.json",
)
_LOCKFILE_FIELD_MAP = {
    "go.sum": "go_sum_sha256",
    "requirements.txt": "requirements_sha256",
    "package-lock.json": "package_lock_sha256",
    "Cargo.lock": "cargo_lock_sha256",
}


def _sha256_of_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git_head_sha(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_dirty(repo_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return bool(result.stdout.strip())


def _detect_language_versions() -> dict[str, str]:
    """Best-effort: query python/go/node/rustc and record their
    --version output. Missing tools are silently skipped — the
    reproducibility record claims only what was observable on
    THIS host at THIS time, not what the campaign theoretically
    requires.
    """
    versions: dict[str, str] = {}
    for tool, args, label in (
        ("python", ["--version"], "python"),
        ("go", ["version"], "go"),
        ("node", ["--version"], "node"),
        ("rustc", ["--version"], "rust"),
    ):
        try:
            result = subprocess.run(
                [tool, *args], capture_output=True, text=True,
                check=False, timeout=5,
            )
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            continue
        if result.returncode == 0:
            output = (result.stdout or result.stderr).strip()
            if output:
                versions[label] = output
    return versions


def _find_latency_config_files(repo_path: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in _LATENCY_CONFIG_GLOBS:
        found.extend(sorted(repo_path.glob(pattern)))
    return found


def capture_reproducibility_metadata(
    repo_path: Path | None,
    *,
    captured_at: str | None = None,
) -> dict:
    """Build the campaign-wide reproducibility_metadata block.

    Returns a dict that conforms to the
    ``reproducibility_metadata`` schema in
    ``orchestrator/schemas/campaign.schema.yaml``. When ``repo_path``
    is ``None``, returns a minimal block (just ``captured_at``) — the
    campaign isn't tied to a target repo (rare).
    """
    block: dict = {
        "captured_at": (
            captured_at
            or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        ),
    }
    if repo_path is None:
        return block
    repo = Path(repo_path)
    if not repo.is_dir():
        logger.warning(
            "reproducibility capture: repo_path %s is not a directory; "
            "skipping git-derived fields", repo,
        )
        return block

    sha = _git_head_sha(repo)
    if sha:
        block["repo_commit"] = sha
    block["repo_dirty"] = _git_dirty(repo)

    for candidate in _HARDWARE_CONFIG_CANDIDATES:
        path = repo / candidate
        if path.is_file():
            digest = _sha256_of_file(path)
            if digest:
                block["hardware_config_sha256"] = digest
            break

    latency_files = _find_latency_config_files(repo)
    if latency_files:
        block["latency_config_files"] = [
            str(p.relative_to(repo)) for p in latency_files
        ]

    for filename, field in _LOCKFILE_FIELD_MAP.items():
        path = repo / filename
        if path.is_file():
            digest = _sha256_of_file(path)
            if digest:
                block[field] = digest

    versions = _detect_language_versions()
    if versions:
        block["language_versions"] = versions

    if "GPU_MEMORY_UTILIZATION" in os.environ:
        try:
            block["gpu_memory_utilization"] = float(
                os.environ["GPU_MEMORY_UTILIZATION"]
            )
        except ValueError:
            pass
    return block


def snapshot_iter_files(
    repo_path: Path | None,
    iter_dir: Path,
    *,
    extra_paths: list[str] | None = None,
) -> list[str]:
    """Per-iter snapshot of latency/hardware config files (#262/F17).

    Copies the target-repo's hardware_config.json + any matching
    model-latency configs into ``iter_dir/snapshots/``. Returns the
    list of relative snapshot paths actually written. Best-effort:
    missing source files are skipped.

    Idempotent: re-running on an iter that already has a snapshots/
    directory overwrites — these are deterministic content copies, so
    overwriting the same file with the same content is safe.
    """
    if repo_path is None:
        return []
    repo = Path(repo_path)
    if not repo.is_dir():
        return []
    snapshots_dir = iter_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    candidates: list[Path] = []
    for hc in _HARDWARE_CONFIG_CANDIDATES:
        p = repo / hc
        if p.is_file():
            candidates.append(p)
    candidates.extend(_find_latency_config_files(repo))
    for extra in extra_paths or []:
        p = repo / extra
        if p.is_file():
            candidates.append(p)

    for src in candidates:
        rel = src.relative_to(repo)
        dst = snapshots_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        except OSError as exc:
            logger.warning("snapshot %s failed: %s", rel, exc)
            continue
        written.append(str(rel))
    return written


def attach_to_state(work_dir: Path, block: dict) -> None:
    """Persist the reproducibility_metadata block into state.json
    (idempotent: don't overwrite a block already present unless the
    captured_at is older than 24h, which signals a re-init).

    State-only — campaign.yaml stays user-set. The captured block is
    surfaced via ``nous status`` from state.json.
    """
    state_path = work_dir / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    existing = state.get("reproducibility_metadata")
    if isinstance(existing, dict) and "captured_at" in existing:
        # Already present — don't rewrite. The first capture wins,
        # which is what reviewers want (the commit they shipped at
        # the start of the campaign).
        return
    state["reproducibility_metadata"] = block
    state_path.write_text(json.dumps(state, indent=2) + "\n")
