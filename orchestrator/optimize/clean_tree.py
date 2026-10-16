"""Clean-checkout verification: measure the RECORDED mechanism, not the agent's tree.

Checks that run in the same tree as agent-authored code cannot be tamper-proof:
that code runs again at verify (the test command) and in every epoch run (the
run command), and can rewrite records, re-edit protected files after a one-time
check, plant caches, or leave hidden files. The standard remedy, from
reproducible builds, is to verify the recorded artifact in a clean environment.

The model:

1. **Capture** (end of the build stage, ``capture``). The mechanism is exactly
   the diff of ``build_checks.mechanism_paths`` against the PRE-BUILD commit:
   ``mechanism.clean.patch``, binary-safe, new and deleted files included, taken
   through a private index so the repo's own index is untouched and ignored
   files (caches) are not part of it. Its sha256 is the mechanism hash the
   policy is compiled with. A patch that touches a protected path (the
   benchmark harness, a pre-existing declared test) is refused unless that path
   is listed exactly in ``mechanism_paths``. The pre-build tree must have no
   tracked modifications, because the clean tree is built from the commit.
2. **Clean tree** (``ensure``). A fresh ``git worktree`` of the pre-build commit
   in the work_dir (outside the repo), with the patch applied. Verify's test
   runs, the baseline re-measurement, the 2(d) mutants and EVERY epoch
   measurement run there, never in the agent's working tree. Out-of-scope
   writes, protected-file edits, commits, hidden or ignored files, symlink swaps
   and planted caches in the agent's tree are simply absent from it.
3. **Integrity** (``ensure`` at every later stage). Before each iteration the
   clean tree must still be base + patch: the mechanism paths diff to the same
   patch, no tracked file outside them changed, and no untracked CODE file
   appeared outside them. Target code that modifies the checkout it is measured
   in aborts the campaign. A missing clean tree (a resume on another machine, a
   cleaned scratch dir) is recreated deterministically from the recorded commit
   and patch.

What it does not cover: target code can still modify the clean tree WITHIN one
iteration and restore it before the next check, and it can reach anything
outside the repo (the home directory, system libraries). The integrity check
reads only tracked files and untracked code files (``CODE_SUFFIXES``); a planted
data file is not detected.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

RECORD = "clean_tree.json"
PATCH = "mechanism.clean.patch"
TREE = "clean-tree"
CODE_SUFFIXES = frozenset({".py", ".pth", ".pyc", ".go", ".rs", ".js", ".mjs", ".cjs",
                           ".ts", ".java", ".rb", ".sh", ".so", ".dylib", ".dll"})


class CleanTreeError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, env: dict | None = None, binary: bool = False):
    try:
        proc = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(cwd),
                              capture_output=True, timeout=600,
                              env={**os.environ, **(env or {})})
    except (OSError, subprocess.SubprocessError) as exc:
        raise CleanTreeError(f"git {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise CleanTreeError(f"git {' '.join(args)} exited {proc.returncode}: "
                             f"{proc.stderr.decode(errors='replace').strip()[:400]}")
    return proc.stdout if binary else proc.stdout.decode(errors="replace")


def active(campaign: dict, work_dir: Path) -> bool:
    """The clean-checkout model applies to every campaign with a build stage."""
    from orchestrator.optimize.build_scope import build_declared

    return build_declared(campaign) or (Path(work_dir) / RECORD).exists()


def require_clean_base(repo: Path) -> str:
    """The pre-build commit; refuses a tree with tracked modifications."""
    head = _git(repo, "rev-parse", "HEAD").strip()
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no").strip()
    if dirty:
        raise CleanTreeError(
            "a build stage needs the target's tracked files committed before it runs: "
            "the mechanism is verified in a clean checkout of the pre-build COMMIT, so "
            f"uncommitted edits would silently vanish from what is measured. Dirty:\n{dirty}")
    return head


def _diff_against(tree: Path, base: str, paths: list[str], index: Path) -> tuple[bytes, list[str]]:
    env = {"GIT_INDEX_FILE": str(index)}
    _git(tree, "read-tree", base, env=env)
    present = [p for p in paths if (tree / p).exists()
               or _git(tree, "ls-tree", "--name-only", base, "--", p).strip()]
    if present:
        _git(tree, "add", "-A", "--", *present, env=env)
    patch = _git(tree, "diff", "--cached", "--binary", "--full-index", base, "--",
                 *present, env=env, binary=True) if present else b""
    names = _git(tree, "diff", "--cached", "--name-only", base, "--", *present,
                 env=env).split() if present else []
    try:
        index.unlink()
    except OSError:
        pass
    return patch, sorted(names)


def capture(campaign: dict, repo: Path, work_dir: Path, base: str,
            *, protected: set[str]) -> dict:
    """Record the mechanism patch; refuse one that touches a protected path."""
    from orchestrator.optimize.build_scope import mechanism_scope

    paths = [p.strip("/") for p in mechanism_scope(campaign)]
    patch, names = _diff_against(Path(repo), base, paths, Path(work_dir) / ".clean_index")
    listed = {str(p).strip("/") for p in paths}
    bad = sorted(n for n in names if n in protected and n not in listed)
    if bad:
        raise CleanTreeError(
            f"the mechanism patch touches protected path(s) {bad} (the benchmark "
            f"harness or a pre-existing declared test). List each one by exact path in "
            f"build_checks.mechanism_paths if editing it is part of the mechanism.")
    (Path(work_dir) / PATCH).write_bytes(patch)
    rec = {"base_sha": base, "patch_sha256": hashlib.sha256(patch).hexdigest(),
           "paths": paths, "touched": names}
    (Path(work_dir) / RECORD).write_text(json.dumps(rec, indent=2))
    return rec


def read_record(work_dir: Path) -> dict:
    p = Path(work_dir) / RECORD
    if not p.exists() or not (Path(work_dir) / PATCH).exists():
        raise CleanTreeError(
            f"{RECORD} / {PATCH} are missing: this build campaign has no recorded "
            f"mechanism to verify in a clean checkout. Re-run the build stage.")
    rec = json.loads(p.read_text())
    if hashlib.sha256((Path(work_dir) / PATCH).read_bytes()).hexdigest() != rec["patch_sha256"]:
        raise CleanTreeError(f"{PATCH} no longer matches the hash in {RECORD}")
    return rec


def _remove(repo: Path, dest: Path) -> None:
    try:
        _git(repo, "worktree", "remove", "--force", str(dest))
    except CleanTreeError:
        pass
    shutil.rmtree(dest, ignore_errors=True)
    try:
        _git(repo, "worktree", "prune")
    except CleanTreeError:
        pass


def _create(repo: Path, work_dir: Path, rec: dict) -> Path:
    dest = Path(work_dir) / TREE
    if dest.exists():
        _remove(repo, dest)
    _git(repo, "worktree", "add", "--detach", "--force", str(dest), rec["base_sha"])
    patch = Path(work_dir) / PATCH
    if patch.stat().st_size:
        _git(dest, "apply", "--binary", "--whitespace=nowarn", str(patch.resolve()))
    return dest


def integrity_problems(work_dir: Path, rec: dict) -> list[str]:
    dest = Path(work_dir) / TREE
    out = []
    head = _git(dest, "rev-parse", "HEAD").strip()
    if head != rec["base_sha"]:
        out.append(f"HEAD moved to {head}")
    patch, _ = _diff_against(dest, rec["base_sha"], rec["paths"], Path(work_dir) / ".clean_index2")
    if hashlib.sha256(patch).hexdigest() != rec["patch_sha256"]:
        out.append("the mechanism paths no longer diff to the recorded patch")
    excl = [f":(exclude){p}" for p in rec["paths"]]
    changed = _git(dest, "diff", "--name-only", rec["base_sha"], "--", ".", *excl).split()
    if changed:
        out.append(f"tracked files outside the mechanism changed: {changed[:10]}")
    others = _git(dest, "ls-files", "--others", "--exclude-standard", "--", ".", *excl).split()
    code = [o for o in others if Path(o).suffix in CODE_SUFFIXES]
    if code:
        out.append(f"untracked code files appeared outside the mechanism: {code[:10]}")
    return out


def ensure(repo: Path, work_dir: Path, *, fresh: bool = False) -> Path:
    """The clean tree, created (``fresh`` or missing) or integrity-checked."""
    rec = read_record(work_dir)
    dest = Path(work_dir) / TREE
    if fresh or not dest.exists():
        dest = _create(Path(repo), Path(work_dir), rec)
        problems = integrity_problems(work_dir, rec)
        if problems:
            raise CleanTreeError("the clean tree could not be rebuilt from the recorded "
                                 "commit and patch: " + "; ".join(problems))
        return dest
    problems = integrity_problems(work_dir, rec)
    if problems:
        raise CleanTreeError(
            "the clean checkout the epoch measures was modified (" + "; ".join(problems)
            + "). Target code changed the tree it is measured in; the measurements "
            "since the last check describe a different system. Start a new campaign.")
    return dest
