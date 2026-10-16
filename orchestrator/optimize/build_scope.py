"""The build agent's write scope, enforced by diffing what the build changed.

The build prompt TELLS the agent where it may write; before this module
nothing CHECKED it (audit Q10): the tree was snapshotted after the build, so
anything the agent touched -- the benchmark harness included -- silently
became "the mechanism". Now the stage records the dirty-file state of the
target immediately before the agent call and again immediately after, and the
difference is what the build wrote. Two rules:

1. **Declared scope.** When ``optimization.build_checks.mechanism_paths`` is
   declared, every path the build wrote must fall under it (the same
   component-prefix rule the drift oracle uses, ``build._in_allowlist``).
2. **Protected inputs**, always, unless explicitly listed in
   ``mechanism_paths``: a file the ``run_command`` names that existed before
   the build (the benchmark harness that produces the objective), and the file
   of every declared native test that already RAN before the build (a
   pre-existing relation test the agent could weaken).

A violation aborts the campaign before ``verify`` and is recorded in
``build_scope.json`` -- unless ``build_checks.allow_out_of_scope_writes``
waives it with a reason, which is recorded there and in report.json's
``provenance.waivers``.

Nous's own outputs (``.nous*`` and the work_dir) and well-known tool caches
(``__pycache__``, ``.pytest_cache`` ...) never count: no mechanism lives in
them, and an agent that runs the tests produces them. A non-git target has no
diff, so the gate is recorded as not applicable rather than passed.
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path

from orchestrator.optimize.build import _in_allowlist, _nous_owned_prefixes

TOOL_CACHE_PARTS = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    ".tox", ".nox", ".coverage",
})


class BuildScopeViolation(RuntimeError):
    """The build wrote outside the scope the campaign allows."""


def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                              text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _ignored(rel: str, owned: list[str]) -> bool:
    parts = rel.split("/")
    if any(p in TOOL_CACHE_PARTS for p in parts) or rel.endswith((".pyc", ".pyo")):
        return True
    return _in_allowlist(rel, owned)


def tree_state(repo: Path, work_dir: Path | None = None) -> dict[str, str] | None:
    """``{repo-relative path: sha256 of its bytes | "<deleted>"}`` for every
    path git reports as differing from HEAD (tracked edits, deletions and
    untracked-not-ignored files). None when ``repo`` is not a git work tree."""
    out = _git(Path(repo), "status", "--porcelain=v1", "-z", "-uall", "--no-renames")
    if out is None:
        return None
    owned = _nous_owned_prefixes(Path(repo), work_dir)
    state: dict[str, str] = {}
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        rel = entry[3:]
        if _ignored(rel, owned):
            continue
        p = Path(repo) / rel
        if p.is_file():
            state[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif not p.exists():
            state[rel] = "<deleted>"
    return state


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths whose state differs: written, created, deleted, or reverted."""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def protected_paths(repo: Path, campaign: dict, pre_ran: list[str]) -> set[str]:
    """Files the build must not touch unless ``mechanism_paths`` lists them:
    pre-existing files the run_command names, and the files of declared native
    tests that already ran before the build."""
    opt = (campaign or {}).get("optimization") or {}
    tracked = set((_git(Path(repo), "ls-files") or "").splitlines())
    out: set[str] = set()
    try:
        tokens = shlex.split(str(opt.get("run_command") or ""))
    except ValueError:
        tokens = []
    for tok in tokens:
        cand = tok.split("=", 1)[-1] if tok.startswith("--") else tok
        cand = cand.removeprefix("./")
        if cand in tracked:
            out.add(cand)
    for t in pre_ran or ():
        f = str(t).split("::", 1)[0]
        if f in tracked:
            out.add(f)
    return out


def check(campaign: dict, repo: Path, work_dir: Path, before: dict[str, str] | None,
          *, pre_ran: list[str] | None = None) -> dict:
    """Compare the post-build tree with ``before``; write ``build_scope.json``;
    raise :class:`BuildScopeViolation` on an unwaived violation."""
    import json

    record: dict = {"applicable": before is not None}
    after = tree_state(repo, work_dir) if before is not None else None
    if before is None or after is None:
        record["why_not"] = "target is not a git work tree; no diff to check"
        (Path(work_dir) / "build_scope.json").write_text(json.dumps(record, indent=2))
        return record
    bc = ((campaign.get("optimization") or {}).get("build_checks")) or {}
    scope = [str(p) for p in (bc.get("mechanism_paths") or []) if str(p).strip()]
    protected = protected_paths(repo, campaign, list(pre_ran or ()))
    written = changed_paths(before, after)
    outside = [p for p in written if scope and not _in_allowlist(p, scope)]
    touched_protected = [p for p in written if p in protected
                         and not (scope and _in_allowlist(p, scope)
                                  and any(str(e).strip("/") == p for e in scope))]
    record.update({
        "written": written, "mechanism_paths": scope or None,
        "protected": sorted(protected),
        "outside_scope": outside, "protected_touched": touched_protected,
    })
    bad = sorted(set(outside) | set(touched_protected))
    waiver = bc.get("allow_out_of_scope_writes")
    if bad and isinstance(waiver, str) and waiver.strip():
        record["waived"] = waiver.strip()
    record["ok"] = not bad or "waived" in record
    (Path(work_dir) / "build_scope.json").write_text(json.dumps(record, indent=2))
    if bad and "waived" not in record:
        parts = []
        if outside:
            parts.append(f"outside build_checks.mechanism_paths {scope}: {outside}")
        if touched_protected:
            parts.append("to the benchmark harness or a pre-existing relation test "
                         f"(protected unless listed by exact path in mechanism_paths): "
                         f"{touched_protected}")
        raise BuildScopeViolation(
            "the build wrote " + "; and ".join(parts) + ". The epoch would measure "
            "a system whose instrument the build agent was free to change. Revert "
            "those edits and re-run the build, widen mechanism_paths if the edit is "
            "genuinely part of the mechanism, or waive in writing with "
            "optimization.build_checks.allow_out_of_scope_writes: \"<why>\" "
            "(recorded in report.json). See build_scope.json."
        )
    return record
