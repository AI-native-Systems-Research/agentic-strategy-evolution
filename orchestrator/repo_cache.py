"""Repo-level knowledge cache (issue #156).

Persists a small, factual set of repo facts at ``<target_repo>/.nous/repo/``
so subsequent campaigns can skip the most expensive part of DESIGN —
rediscovering the same build commands, knob locations, and metric
sources every time. The interpretive layer (what the bottleneck is,
which mechanism explains a metric) is **not** cached; that's the
campaign's job, every time.

Layout:

  <repo>/.nous/repo/
    exploration.md         narrative tour for the planner to read first
    knobs.yaml             discovered tunables (name, location, type, range)
    metrics.yaml           observable metrics (capture mechanics)
    build.yaml             build/test/run commands and prerequisites
    schema_version.txt     forward-compat anchor
    last_verified_at.txt   "<git_sha>\\n<iso_timestamp>\\n" — drives freshness

This module is pure Python with no LLM call. Higher-level code (the
campaign-end writer in ``campaign.py`` and the design-time loader)
adds the bridges to disk-level cache content. The verify-before-use
discipline is enforced by ``is_fresh`` — when ``last_verified_at`` does
not match HEAD, the cache is considered stale and callers fall back
to today's behavior (full Explore re-discovery).
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import jsonschema
import yaml

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
CACHE_SUBDIR = Path(".nous") / "repo"

_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def cache_dir_for(repo_path: Path) -> Path:
    """Return the absolute path to the repo cache directory."""
    return Path(repo_path) / CACHE_SUBDIR


def _read_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text())
        return loaded if isinstance(loaded, dict) else None
    except (OSError, yaml.YAMLError):
        return None


def _validate_against_def(payload: dict | None, def_name: str) -> bool:
    """Validate ``payload`` against ``$defs/<def_name>`` in the cache schema.

    Returns True iff the payload is non-None and conforms. The schema
    file is the same one shipped with the orchestrator; a malformed
    cache file is treated as missing rather than fatal.
    """
    if not isinstance(payload, dict):
        return False
    try:
        schema = yaml.safe_load((_SCHEMAS_DIR / "repo_cache.schema.yaml").read_text())
    except (OSError, yaml.YAMLError):
        return False
    sub = schema.get("$defs", {}).get(def_name)
    if not sub:
        return False
    try:
        jsonschema.validate(payload, sub)
    except jsonschema.ValidationError:
        return False
    return True


def _git_head_sha(repo_path: Path) -> str | None:
    """Best-effort `git rev-parse HEAD`. None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


@dataclass
class RepoCache:
    """In-memory view of a repo cache directory.

    The ``fresh`` flag is computed at read time using ``head_sha`` (the
    current HEAD of the target repo) and ``verified_sha`` (the sha
    recorded when the cache was last written). Treat ``fresh=False``
    as "do not trust" and fall back to full re-discovery — the cache
    is an optimisation, never authoritative.
    """

    exploration: str = ""
    knobs: list[dict] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    build: dict = field(default_factory=dict)
    verified_sha: str | None = None
    verified_at: str | None = None
    head_sha: str | None = None
    fresh: bool = False

    def is_empty(self) -> bool:
        return not (self.exploration or self.knobs or self.metrics or self.build)

    def to_dict(self) -> dict:
        """Stable dict view, suitable for assertions in tests."""
        return {
            "exploration": self.exploration,
            "knobs": self.knobs,
            "metrics": self.metrics,
            "build": self.build,
            "verified_sha": self.verified_sha,
            "verified_at": self.verified_at,
            "head_sha": self.head_sha,
            "fresh": self.fresh,
        }


def write_repo_cache(
    repo_path: Path,
    *,
    exploration: str | None = None,
    knobs: list[dict] | None = None,
    metrics: list[dict] | None = None,
    build: dict | None = None,
    git_sha: str | None = None,
    now: datetime | None = None,
    head_sha_fn: Callable[[Path], str | None] | None = None,
) -> Path:
    """Write the cache directory atomically. Returns the cache dir path.

    The on-disk shape is the documented layout; ``schema_version.txt``
    and ``last_verified_at.txt`` are always written so freshness is
    always answerable. Writes only the files for which the caller
    supplied content — partial caches are valid (e.g. exploration-only
    on the first campaign that runs).
    """
    repo_path = Path(repo_path)
    cache_dir = cache_dir_for(repo_path)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if exploration:
        atomic_write(cache_dir / "exploration.md", exploration)

    if knobs is not None:
        payload = {"schema_version": SCHEMA_VERSION, "knobs": knobs}
        atomic_write(
            cache_dir / "knobs.yaml",
            yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        )

    if metrics is not None:
        payload = {"schema_version": SCHEMA_VERSION, "metrics": metrics}
        atomic_write(
            cache_dir / "metrics.yaml",
            yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        )

    if build is not None:
        payload = {"schema_version": SCHEMA_VERSION, **build}
        atomic_write(
            cache_dir / "build.yaml",
            yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        )

    atomic_write(cache_dir / "schema_version.txt", f"{SCHEMA_VERSION}\n")

    sha = git_sha
    if sha is None:
        sha_fn = head_sha_fn or _git_head_sha
        sha = sha_fn(repo_path)
    sha = sha or "unknown"
    ts = (now or datetime.now(timezone.utc)).isoformat()
    atomic_write(cache_dir / "last_verified_at.txt", f"{sha}\n{ts}\n")

    logger.info(
        "Wrote repo cache to %s (sha=%s, knobs=%d, metrics=%d)",
        cache_dir, sha,
        len(knobs or []), len(metrics or []),
    )
    return cache_dir


def read_repo_cache(
    repo_path: Path,
    *,
    head_sha_fn: Callable[[Path], str | None] | None = None,
) -> RepoCache | None:
    """Load the cache. Returns None if the cache directory does not exist.

    A directory with corrupt or missing files yields a partially-populated
    ``RepoCache``; callers should check ``is_empty()`` before trusting it.
    Freshness is computed against the target repo's HEAD via
    ``head_sha_fn`` (defaults to ``git rev-parse HEAD``).
    """
    cache_dir = cache_dir_for(repo_path)
    if not cache_dir.is_dir():
        return None

    cache = RepoCache()

    explore_path = cache_dir / "exploration.md"
    if explore_path.exists():
        try:
            cache.exploration = explore_path.read_text()
        except OSError:
            cache.exploration = ""

    knobs_payload = _read_yaml(cache_dir / "knobs.yaml")
    if _validate_against_def(knobs_payload, "knobs_file") and knobs_payload:
        cache.knobs = knobs_payload.get("knobs", []) or []

    metrics_payload = _read_yaml(cache_dir / "metrics.yaml")
    if _validate_against_def(metrics_payload, "metrics_file") and metrics_payload:
        cache.metrics = metrics_payload.get("metrics", []) or []

    build_payload = _read_yaml(cache_dir / "build.yaml")
    if _validate_against_def(build_payload, "build_file") and build_payload:
        cache.build = {k: v for k, v in build_payload.items() if k != "schema_version"}

    verified_path = cache_dir / "last_verified_at.txt"
    if verified_path.exists():
        try:
            lines = [ln for ln in verified_path.read_text().splitlines() if ln.strip()]
            if lines:
                cache.verified_sha = lines[0].strip()
            if len(lines) >= 2:
                cache.verified_at = lines[1].strip()
        except OSError:
            pass

    sha_fn = head_sha_fn or _git_head_sha
    cache.head_sha = sha_fn(repo_path)
    cache.fresh = bool(
        cache.verified_sha
        and cache.head_sha
        and cache.verified_sha == cache.head_sha
        and cache.verified_sha != "unknown"
    )

    return cache


def is_fresh(repo_path: Path, *, head_sha_fn: Callable[[Path], str | None] | None = None) -> bool:
    """Top-level convenience: is the cache present and at HEAD?"""
    cache = read_repo_cache(repo_path, head_sha_fn=head_sha_fn)
    return bool(cache and cache.fresh)


def render_cache_for_design_prompt(cache: RepoCache) -> str:
    """Render the cache as a markdown block to include in DESIGN context.

    Used both by CLAUDE.md-style auto-loading and by direct prompt
    composition. Empty caches render as an empty string so callers
    can ``if rendered:`` cleanly.
    """
    if cache.is_empty() or not cache.fresh:
        return ""
    parts: list[str] = ["## Repo cache (verified, skip rediscovery)\n"]
    if cache.exploration:
        parts.append(cache.exploration.strip() + "\n")
    if cache.knobs:
        parts.append("### Known knobs")
        for k in cache.knobs:
            location = f" (`{k['location']}`)" if k.get("location") else ""
            type_str = f" — _{k['type']}_" if k.get("type") else ""
            parts.append(f"- **{k['name']}**{location}{type_str}")
        parts.append("")
    if cache.metrics:
        parts.append("### Known metrics")
        for m in cache.metrics:
            unit = f" [{m['unit']}]" if m.get("unit") else ""
            capture = f" — {m['capture']}" if m.get("capture") else ""
            parts.append(f"- **{m['name']}**{unit}{capture}")
        parts.append("")
    if cache.build:
        parts.append("### Build")
        for key in ("build_command", "test_command", "run_command"):
            if cache.build.get(key):
                parts.append(f"- {key.replace('_', ' ')}: `{cache.build[key]}`")
        if cache.build.get("prerequisites"):
            prereqs = ", ".join(cache.build["prerequisites"])
            parts.append(f"- prerequisites: {prereqs}")
        if cache.build.get("env_vars"):
            envs = ", ".join(cache.build["env_vars"])
            parts.append(f"- env vars: {envs}")
        parts.append("")
    return "\n".join(parts) + "\n"


# ─── Heuristic builder from existing campaign artifacts ──────────────────


def _extract_handoff_section(handoff_md: str, *header_options: str) -> str:
    """Pull a named section out of a handoff.md by markdown header."""
    if not handoff_md:
        return ""
    lines = handoff_md.splitlines()
    for option in header_options:
        target = option.strip().lower()
        for i, line in enumerate(lines):
            stripped = line.strip().lstrip("#").strip().lower()
            if stripped == target:
                # Capture until next heading at same or higher level
                level = len(line) - len(line.lstrip("#"))
                buf: list[str] = []
                for follow in lines[i + 1:]:
                    if follow.lstrip().startswith("#"):
                        next_level = len(follow) - len(follow.lstrip("#"))
                        if next_level <= level:
                            break
                    buf.append(follow)
                return "\n".join(buf).strip()
    return ""


def build_cache_from_campaign(
    work_dir: Path, campaign: dict,
) -> tuple[str, list[dict], list[dict], dict]:
    """Build cache content from completed-campaign artifacts.

    Pure-Python heuristic. The caller (campaign.py end-of-run) feeds
    these into ``write_repo_cache``. Notes:

      * ``exploration.md`` is sourced from the latest ``handoff.md``,
        truncated to the most useful sections — the LLM's narrative,
        not principles.
      * ``knobs.yaml`` and ``metrics.yaml`` are seeded from
        campaign.yaml's declared lists; the planner can refine them
        in subsequent campaigns.
      * ``build.yaml`` pulls from the System Interface section of
        handoff.md when present.
    """
    work_dir = Path(work_dir)

    # Exploration.md from handoff.md — the campaign-level living doc.
    handoff_path = work_dir / "handoff.md"
    handoff_text = handoff_path.read_text() if handoff_path.exists() else ""
    exploration = handoff_text.strip()

    # Knobs / metrics — bootstrap from campaign.yaml. These are the
    # declared facts the campaign told us; on subsequent runs the
    # planner may augment them.
    target = campaign.get("target_system", {}) if isinstance(campaign, dict) else {}
    knobs: list[dict] = []
    for raw in target.get("controllable_knobs", []) or []:
        if isinstance(raw, str):
            knobs.append({"name": raw})
        elif isinstance(raw, dict) and "name" in raw:
            knobs.append({k: v for k, v in raw.items() if k in {
                "name", "location", "type", "default", "range", "notes",
            }})

    metrics: list[dict] = []
    for raw in target.get("observable_metrics", []) or []:
        if isinstance(raw, str):
            metrics.append({"name": raw})
        elif isinstance(raw, dict) and "name" in raw:
            metrics.append({k: v for k, v in raw.items() if k in {
                "name", "unit", "capture", "source", "notes",
            }})

    # Build — pull System Interface section from handoff.md.
    build: dict = {}
    sys_iface = _extract_handoff_section(
        handoff_text, "System Interface", "## System Interface",
    )
    if sys_iface:
        # Heuristic: scan the section for `Build:`, `Run baseline:`, etc.
        for line in sys_iface.splitlines():
            stripped = line.strip().lstrip("-*").strip()
            for label, key in (
                ("Build:", "build_command"),
                ("Test:", "test_command"),
                ("Run baseline:", "run_command"),
                ("Run:", "run_command"),
            ):
                if stripped.startswith(label) or stripped.startswith(f"**{label}"):
                    val = stripped.split(":", 1)[-1].strip()
                    # Clean markdown decoration: leading `**` (bold close)
                    # and surrounding backticks.
                    val = val.lstrip("*").strip()
                    val = val.strip("`").strip()
                    if val and key not in build:
                        build[key] = val
                    break

    return exploration, knobs, metrics, build
