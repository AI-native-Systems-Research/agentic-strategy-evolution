"""Campaign index — pure functions over the on-disk artifact tree (#126).

These functions are the contract that ``nous-mcp`` (a stdio MCP server,
shipped in a follow-up phase) exposes as resources and tools. Keeping
them pure and import-free of MCP itself means:

  * They're trivially testable without spinning up an MCP transport.
  * The CLI can use them too (``nous list``, ``nous find-principle``)
    without coupling to the MCP runtime.
  * A future Routines invocation (#134) can use the same functions to
    publish findings into a shared store.

Conventions:

  * A "campaign root" is a directory containing ``state.json``,
    ``ledger.json``, ``principles.json``. Typically ``<repo>/.nous/<run-id>``.
  * A "search root" is a directory under which we walk to find campaign
    roots. Searches are bounded to depth 4 so we don't accidentally walk
    a giant repo.
  * Functions return plain ``dict``/``list`` JSON-friendly structures so
    MCP serialization is a no-op.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_MAX_DEPTH = 4


def _walk_campaign_roots(search_root: Path, max_depth: int = _MAX_DEPTH) -> Iterable[Path]:
    """Yield directories under ``search_root`` that look like campaign roots."""
    search_root = Path(search_root)
    if not search_root.is_dir():
        return
    stack: list[tuple[Path, int]] = [(search_root, 0)]
    while stack:
        path, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(path.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            # Heuristic: a campaign root has state.json + ledger.json.
            if (entry / "state.json").exists() and (entry / "ledger.json").exists():
                yield entry
                # Don't descend further inside a campaign root — its
                # subdirs (runs/iter-N) aren't themselves campaigns.
                continue
            stack.append((entry, depth + 1))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


@dataclass
class CampaignSummary:
    run_id: str
    path: str
    phase: str
    iteration: int
    completed_iterations: int
    active_principles: int
    repo: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": self.path,
            "phase": self.phase,
            "iteration": self.iteration,
            "completed_iterations": self.completed_iterations,
            "active_principles": self.active_principles,
            "repo": self.repo,
        }


def _summarize(root: Path) -> CampaignSummary | None:
    state = _read_json(root / "state.json")
    if not isinstance(state, dict):
        return None
    ledger = _read_json(root / "ledger.json")
    completed = 0
    if isinstance(ledger, dict):
        rows = ledger.get("iterations", [])
        if isinstance(rows, list):
            completed = sum(
                1 for r in rows
                if isinstance(r, dict) and isinstance(r.get("iteration"), int)
                and r["iteration"] >= 1
            )
    principles = _read_json(root / "principles.json")
    active = 0
    if isinstance(principles, dict):
        plist = principles.get("principles", [])
        if isinstance(plist, list):
            active = sum(
                1 for p in plist
                if isinstance(p, dict) and p.get("status", "active") == "active"
            )
    # Best-effort: target repo is the great-grandparent when work_dir
    # was created as <repo>/.nous/<run-id>.
    repo: str | None = None
    if root.parent.name == ".nous":
        repo = str(root.parent.parent.resolve())
    # #236: read via helper so legacy ``phase`` keys still resolve.
    from orchestrator.engine import read_phase_field
    return CampaignSummary(
        run_id=state.get("run_id", root.name),
        path=str(root.resolve()),
        phase=read_phase_field(state, default="UNKNOWN"),
        iteration=int(state.get("iteration", 0) or 0),
        completed_iterations=completed,
        active_principles=active,
        repo=repo,
    )


# ─── list_campaigns ─────────────────────────────────────────────────────────


def list_campaigns(
    search_root: Path,
    *,
    query: str | None = None,
    status: str | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """List campaign summaries under ``search_root``.

    Args:
      search_root: directory to walk.
      query: case-insensitive substring filter against run_id.
      status: filter on state.phase (``DONE``, ``EXECUTE_ANALYZE``, etc.).
      repo: filter on resolved repo path (substring match).

    Returns: list of summary dicts, sorted by run_id.
    """
    out: list[dict[str, Any]] = []
    for root in _walk_campaign_roots(Path(search_root)):
        summary = _summarize(root)
        if summary is None:
            continue
        if query and query.lower() not in summary.run_id.lower():
            continue
        if status and summary.phase != status:
            continue
        if repo:
            if not summary.repo or repo not in summary.repo:
                continue
        out.append(summary.as_dict())
    out.sort(key=lambda d: d["run_id"])
    return out


# ─── search_principles ────────────────────────────────────────────────────


@dataclass
class PrincipleHit:
    run_id: str
    path: str  # campaign root
    principle: dict[str, Any]
    score: float = 1.0  # placeholder for future semantic search

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": self.path,
            "score": self.score,
            "principle": self.principle,
        }


def search_principles(
    search_root: Path,
    text: str,
    *,
    only_active: bool = True,
) -> list[dict[str, Any]]:
    """Find principles whose statement/description matches ``text``.

    Phase A is plain case-insensitive substring matching; the issue notes
    embedding-based search as an optional follow-up gated on
    ``OPENAI_API_KEY``.
    """
    needle = text.lower().strip()
    if not needle:
        return []
    hits: list[PrincipleHit] = []
    for root in _walk_campaign_roots(Path(search_root)):
        principles = _read_json(root / "principles.json")
        if not isinstance(principles, dict):
            continue
        plist = principles.get("principles", [])
        if not isinstance(plist, list):
            continue
        state = _read_json(root / "state.json") or {}
        run_id = state.get("run_id", root.name)
        for p in plist:
            if not isinstance(p, dict):
                continue
            if only_active and p.get("status", "active") != "active":
                continue
            haystack = " ".join(
                str(p.get(field, "")) for field in
                ("statement", "description", "category", "id")
            ).lower()
            if needle in haystack:
                hits.append(PrincipleHit(
                    run_id=run_id, path=str(root.resolve()),
                    principle=p,
                ))
    # Stable order: by run_id, then principle id.
    hits.sort(key=lambda h: (h.run_id, str(h.principle.get("id", ""))))
    return [h.as_dict() for h in hits]


# ─── get_arm_results ──────────────────────────────────────────────────────


def get_arm_results(
    campaign_root: Path,
    iteration: int,
    arm: str,
) -> dict[str, Any]:
    """Aggregate results for one arm of one iteration.

    Returns: ``{"arm": ..., "iteration": N, "seeds": [{"seed": ..., "files": [...]}]}``.
    Seeds and their result files are read from ``runs/iter-N/results/<arm>/<seed>/``.
    """
    campaign_root = Path(campaign_root)
    arm_dir = campaign_root / "runs" / f"iter-{iteration}" / "results" / arm
    seeds: list[dict[str, Any]] = []
    if arm_dir.is_dir():
        for seed_dir in sorted(arm_dir.iterdir()):
            if not seed_dir.is_dir():
                continue
            files = sorted(
                str(p.relative_to(campaign_root))
                for p in seed_dir.rglob("*") if p.is_file()
            )
            seeds.append({"seed": seed_dir.name, "files": files})
    return {"arm": arm, "iteration": iteration, "seeds": seeds}


# ─── compare_iterations ───────────────────────────────────────────────────


def compare_iterations(
    campaign_root: Path,
    iter_a: int,
    iter_b: int,
) -> dict[str, Any]:
    """Deterministic diff between two iterations' findings.

    Returns the high-level shape:
      ``{"a": <findings>, "b": <findings>, "delta": {...}}``.

    The delta names which arms changed status (e.g. CONFIRMED → REFUTED)
    and which principles were added between the two iterations. No
    timestamps, no stochastic ordering — calling this twice on the same
    data must produce byte-equal output.
    """
    campaign_root = Path(campaign_root)

    def _findings(n: int) -> dict[str, Any] | None:
        f = _read_json(campaign_root / "runs" / f"iter-{n}" / "findings.json")
        return f if isinstance(f, dict) else None

    a = _findings(iter_a) or {}
    b = _findings(iter_b) or {}

    def _arm_status_map(f: dict) -> dict[str, str]:
        out: dict[str, str] = {}
        for arm in f.get("arms", []) or []:
            if isinstance(arm, dict):
                out[str(arm.get("arm_id", ""))] = str(arm.get("status", ""))
        return dict(sorted(out.items()))

    delta = {
        "iter_a": iter_a,
        "iter_b": iter_b,
        "arm_status_changes": _arm_status_diff(_arm_status_map(a), _arm_status_map(b)),
        "principles_added": _principles_added(campaign_root, iter_a, iter_b),
    }
    return {"a": a, "b": b, "delta": delta}


def _arm_status_diff(a: dict[str, str], b: dict[str, str]) -> list[dict[str, str]]:
    changes = []
    for arm_id in sorted(set(a) | set(b)):
        sa = a.get(arm_id, "absent")
        sb = b.get(arm_id, "absent")
        if sa != sb:
            changes.append({"arm_id": arm_id, "from": sa, "to": sb})
    return changes


def _principles_added(root: Path, iter_a: int, iter_b: int) -> list[str]:
    def _ids(n: int) -> set[str]:
        u = _read_json(root / "runs" / f"iter-{n}" / "principle_updates.json")
        if not isinstance(u, list):
            return set()
        return {str(p.get("id", "")) for p in u if isinstance(p, dict) and "id" in p}
    return sorted(_ids(iter_b) - _ids(iter_a))


# ─── Resource paths (the strings the MCP server publishes as resources) ──


def resource_uri_for_campaign(run_id: str) -> str:
    return f"nous://campaigns/{run_id}"


def resource_uri_for_state(run_id: str) -> str:
    return f"nous://campaigns/{run_id}/state"


def resource_uri_for_principles(run_id: str) -> str:
    return f"nous://campaigns/{run_id}/principles"


def resource_uri_for_iter_findings(run_id: str, iteration: int) -> str:
    return f"nous://campaigns/{run_id}/iter/{iteration}/findings"
