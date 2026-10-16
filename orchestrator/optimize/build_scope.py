"""The build agent's write scope, CHECKED by diffing what the build changed,
and the integrity of Nous's own build-gate records.

The build agent runs with ``bypassPermissions`` and its cwd is the target repo
(and the default work_dir ``<repo>/.nous/<run>/`` is inside its reach). The
prompt TELLS it where it may write; this module CHECKS what it did, and every
check fails CLOSED: an unreadable state is a violation, never a pass.

What is snapshotted, immediately before and immediately after the agent call
(``snapshot``):

* the bytes of every TRACKED file (hashed directly from the worktree, so a
  ``git update-index --skip-worktree`` / ``--assume-unchanged`` cannot hide an
  edit) and of every untracked-not-ignored file;
* IGNORED files that hold source or configuration (``SOURCE_SUFFIXES``), by
  size and mtime -- a ``conftest.py`` hidden through ``.git/info/exclude`` is
  still a write; tool caches and dependency/build-output trees are skipped;
* symlinks by their target (never followed) and submodules (gitlinks) by their
  HEAD and status;
* git metadata the agent could use to hide work: ``HEAD`` and the branch it
  names, ``refs/stash``, the index entries (``ls-files -s``), the per-file
  flags (``ls-files -v``), ``.git/info/exclude`` and ``core.excludesFile``;
* the digests of Nous's gate records in the work_dir (``GATE_RECORDS``): the
  agent must not edit the evidence the verify-stage oracles read.

``check`` then fails the build on: any git read that worked before and fails
after; HEAD, the branch or the stash moving (a commit, checkout or stash makes
every later diff blind); a change to the flags, the exclude files, or a gate
record; and any changed path outside ``build_checks.mechanism_paths`` or on a
PROTECTED input (``protected_paths``: every tracked file the ``run_command``
names or lives under a directory / module it names, and every pre-existing
declared test file), unless listed by exact path in ``mechanism_paths``.
``build_checks.allow_out_of_scope_writes: "<why>"`` waives the PATH rules only,
never the integrity rules. ``build_scope.json`` records everything, including
the gate-record digests taken around the agent call; the records themselves
are sealed and re-verified at verify by ``gate_records``.

What it cannot see: writes outside the repo (a ``$HOME`` config, a system
library), changes the agent makes and reverts within its own call, and edits
under the skipped trees (``SKIP_DIRS``). A non-git target has no diff at all;
that is recorded as ``applicable: false`` and listed as a waiver in
report.json, not as a pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from orchestrator.optimize.build import _in_allowlist, _nous_owned_prefixes

TOOL_CACHE_PARTS = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    ".tox", ".nox", ".coverage",
})
#: Ignored trees that hold dependencies or build outputs, never authored source.
SKIP_DIRS = frozenset({"node_modules", ".venv", "venv", ".git", "target", "dist",
                       "build", ".gradle", ".next"})
#: Ignored files with these suffixes (or names) are watched: they can be code or
#: configuration a run_command or test runner picks up.
SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".go", ".rs", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".java",
    ".kt", ".c", ".h", ".cc", ".cpp", ".hpp", ".rb", ".sh", ".toml", ".yaml",
    ".yml", ".json", ".cfg", ".ini", ".pth", ".mk",
})
SOURCE_NAMES = frozenset({"Makefile", "makefile", "GNUmakefile", "Dockerfile",
                          "conftest.py", "pytest.ini", "setup.cfg", "tox.ini"})

#: Nous's own gate records in the work_dir, and the keys of each that the
#: BUILD stage wrote (verify later adds keys to baseline_equivalence.json, so its
#: digest covers only what build wrote).
GATE_RECORDS = {
    "pre_build_tests.json": None,
    "baseline_equivalence.json": ("levels", "pre", "pre_mean", "pre_unavailable",
                                  "tolerance_pct", "workload_seeds",
                                  "workload_seed_env"),
}


class BuildScopeViolation(RuntimeError):
    """The build wrote outside its scope, or tampered with what is checked."""


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> str | None:
    """stdout, or None when ``check`` is False and git failed. With ``check``
    a failure raises :class:`GitError` carrying git's stderr."""
    try:
        proc = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(repo),
                              capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            raise GitError(f"git {' '.join(args)}: {exc}") from exc
        return None
    if proc.returncode != 0:
        if check:
            raise GitError(f"git {' '.join(args)} exited {proc.returncode}: "
                           f"{(proc.stderr or '').strip()[:400]}")
        return None
    return proc.stdout


def is_git_tree(repo: Path) -> bool:
    out = _git(Path(repo), "rev-parse", "--is-inside-work-tree", check=False)
    return (out or "").strip() == "true"


def _skipped(rel: str, owned: list[str]) -> bool:
    parts = rel.split("/")
    if any(p in TOOL_CACHE_PARTS for p in parts) or rel.endswith((".pyc", ".pyo")):
        return True
    return _in_allowlist(rel, owned)


def _sha_file(p: Path) -> str:
    if p.is_symlink():
        return "link:" + os.readlink(p)
    if not p.exists():
        return "<deleted>"
    if p.is_dir():
        return "<dir>"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def record_digest(work_dir: Path, name: str) -> str | None:
    """Digest of a gate record (of the build-written keys only, where listed);
    None when absent; ``"<unreadable>"`` when it does not parse."""
    p = Path(work_dir) / name
    if not p.exists():
        return None
    keys = GATE_RECORDS.get(name)
    if keys is None:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError):
        return "<unreadable>"
    sub = {k: doc.get(k) for k in keys if k in doc}
    return hashlib.sha256(json.dumps(sub, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(repo: Path, work_dir: Path | None) -> dict:
    """Everything ``check`` compares. ``{"git": False, "error": ...}`` when the
    tree cannot be read as git."""
    repo = Path(repo)
    snap: dict = {"git": False, "gate_records": {
        n: record_digest(work_dir, n) for n in GATE_RECORDS} if work_dir else {}}
    if not is_git_tree(repo):
        snap["error"] = "not a git work tree"
        return snap
    try:
        owned = _nous_owned_prefixes(repo, work_dir)
        snap["head"] = (_git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
                        or "").strip() or None
        snap["branch"] = (_git(repo, "symbolic-ref", "-q", "HEAD", check=False) or "").strip()
        snap["stash"] = (_git(repo, "rev-parse", "-q", "--verify", "refs/stash",
                              check=False) or "").strip() or None
        index: dict[str, str] = {}
        gitlinks: list[str] = []
        for ent in _git(repo, "ls-files", "-s", "-z").split("\0"):
            if not ent:
                continue
            meta, path = ent.split("\t", 1)
            index[path] = meta
            if meta.startswith("160000"):
                gitlinks.append(path)
        flags = {}
        for ent in _git(repo, "ls-files", "-v", "-z").split("\0"):
            if ent and ent[0] != "H":
                flags[ent[2:]] = ent[0]
        files: dict[str, str] = {}
        for path in index:
            if path in gitlinks or _skipped(path, owned):
                continue
            files[path] = _sha_file(repo / path)
        for path in _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
            if path and not _skipped(path, owned):
                files[path] = _sha_file(repo / path)
        for path in _git(repo, "ls-files", "--others", "--ignored", "--exclude-standard",
                         "--directory", "-z").split("\0"):
            if not path or _skipped(path.rstrip("/"), owned):
                continue
            top = path.rstrip("/").split("/")
            if any(t in SKIP_DIRS for t in top):
                continue
            base = repo / path
            cands = [base] if base.is_file() or base.is_symlink() else [
                q for q in base.rglob("*") if q.is_file()
                and not (set(q.relative_to(repo).parts) & SKIP_DIRS)]
            for q in cands:
                rel = q.relative_to(repo).as_posix()
                if _skipped(rel, owned):
                    continue
                if q.suffix in SOURCE_SUFFIXES or q.name in SOURCE_NAMES:
                    st = q.lstat()
                    files[rel] = f"ignored:{st.st_size}:{st.st_mtime_ns}"
        subs = {}
        for g in gitlinks:
            sub = repo / g
            h = _git(sub, "rev-parse", "HEAD", check=False) if sub.exists() else None
            stt = _git(sub, "status", "--porcelain", check=False) if sub.exists() else None
            subs[g] = f"{(h or '').strip()}:{hashlib.sha256((stt or '').encode()).hexdigest()}"
        ex = (_git(repo, "rev-parse", "--git-path", "info/exclude") or "").strip()
        exp = (repo / ex) if ex and not Path(ex).is_absolute() else Path(ex)
        xf = (_git(repo, "config", "--get", "core.excludesFile", check=False) or "").strip()
        xfp = Path(os.path.expanduser(xf)) if xf else None
        snap.update({
            "git": True, "index": index, "flags": flags, "files": files,
            "gitlinks": subs,
            "info_exclude": _sha_file(exp) if ex else None,
            "excludes_file": f"{xf}:{_sha_file(xfp) if xfp else ''}",
        })
    except (GitError, OSError) as exc:
        snap["git"] = False
        snap["error"] = str(exc)
    return snap


def protected_paths(repo: Path, campaign: dict, pre_ran: list[str]) -> set[str]:
    """Tracked files the build must not touch unless listed by exact path in
    ``mechanism_paths``: every tracked file the run_command names, lives under a
    directory it names, or that a ``-m pkg.mod`` / ``make <target>`` reaches
    (the module's file or package, the Makefile); plus every pre-existing
    declared test file."""
    opt = (campaign or {}).get("optimization") or {}
    tracked = set((_git(Path(repo), "ls-files", check=False) or "").splitlines())
    out: set[str] = set()
    try:
        tokens = shlex.split(str(opt.get("run_command") or ""))
    except ValueError:
        tokens = []

    def _add(cand: str):
        cand = cand.removeprefix("./").rstrip("/")
        if not cand or cand in (".", ".."):
            return
        if cand in tracked:
            out.add(cand)
        out.update(t for t in tracked if t.startswith(cand + "/"))

    for i, tok in enumerate(tokens):
        if tok.startswith("--") and "=" in tok:
            tok = tok.split("=", 1)[1]
        if i > 0 and tokens[i - 1] == "-m":
            mod = tok.replace(".", "/")
            _add(mod + ".py")
            _add(mod)
            continue
        if tokens[0] in ("make", "gmake") or Path(tokens[0]).name in ("make", "gmake"):
            for mk in ("Makefile", "makefile", "GNUmakefile"):
                if mk in tracked:
                    out.add(mk)
        _add(tok)
    for t in pre_ran or ():
        f = str(t).split("::", 1)[0]
        if f in tracked:
            out.add(f)
    return out


def _diff(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def check(campaign: dict, repo: Path, work_dir: Path, before: dict,
          *, pre_ran: list[str] | None = None) -> dict:
    """Compare the post-build state with ``before``; write ``build_scope.json``;
    raise :class:`BuildScopeViolation` on any unwaived violation."""
    after = snapshot(repo, work_dir)
    record: dict = {"applicable": bool(before.get("git")),
                    "head_before": before.get("head"),
                    "gate_records": after["gate_records"]}
    integrity: list[str] = []
    changed_records = [n for n in GATE_RECORDS
                       if before["gate_records"].get(n) != after["gate_records"].get(n)]
    if changed_records:
        integrity.append(f"Nous's gate record(s) {changed_records} changed during the "
                         f"build: the evidence verify reads was edited")
    if not before.get("git"):
        record["why_not"] = (f"no diff to check: {before.get('error')}"
                             if before.get("error") else "no diff to check")
    elif not after.get("git"):
        integrity.append(f"the tree was readable before the build and is not after "
                         f"it ({after.get('error')}); an unreadable tree is not a "
                         f"clean one")
    written: list[str] = []
    if before.get("git") and after.get("git"):
        for k, what in (("head", "HEAD"), ("branch", "the checked-out branch"),
                        ("stash", "refs/stash")):
            if before.get(k) != after.get(k):
                integrity.append(f"{what} moved during the build ({before.get(k)} -> "
                                 f"{after.get(k)}): a commit, checkout or stash hides "
                                 f"the build's edits from every diff")
        fl = _diff(before["flags"], after["flags"])
        if fl:
            integrity.append(f"git per-file flags changed on {fl} (skip-worktree / "
                             f"assume-unchanged hide edits from git)")
        for k, what in (("info_exclude", ".git/info/exclude"),
                        ("excludes_file", "core.excludesFile")):
            if before.get(k) != after.get(k):
                integrity.append(f"{what} changed during the build (it can hide new files)")
        written = sorted(set(_diff(before["files"], after["files"]))
                         | set(_diff(before["index"], after["index"]))
                         | set(_diff(before["gitlinks"], after["gitlinks"])))
    bc = ((campaign.get("optimization") or {}).get("build_checks")) or {}
    scope = [str(p) for p in (bc.get("mechanism_paths") or []) if str(p).strip()]
    protected = protected_paths(repo, campaign, list(pre_ran or ())) if after.get("git") else set()
    outside = [p for p in written if scope and not _in_allowlist(p, scope)]
    touched_protected = [p for p in written if p in protected
                         and not any(str(e).strip("/") == p for e in scope)]
    record.update({
        "written": written, "mechanism_paths": scope or None,
        "protected": sorted(protected),
        "outside_scope": outside, "protected_touched": touched_protected,
        "integrity_violations": integrity,
    })
    bad = sorted(set(outside) | set(touched_protected))
    waiver = bc.get("allow_out_of_scope_writes")
    if bad and isinstance(waiver, str) and waiver.strip():
        record["waived"] = waiver.strip()
    record["ok"] = not integrity and (not bad or "waived" in record)
    (Path(work_dir) / "build_scope.json").write_text(json.dumps(record, indent=2))
    if integrity:
        raise BuildScopeViolation(
            "build integrity check failed (not waivable): " + "; ".join(integrity)
            + ". See build_scope.json.")
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


#: mechanism_paths entries that mean "the whole repo": refused (review C4).
WHOLE_REPO = frozenset({"", ".", "./", "/", "*", "**", "**/*"})


def mechanism_scope(campaign: dict) -> list[str]:
    """The declared ``mechanism_paths``; raises when a build would have no real
    scope (none declared, or an entry naming the whole repo)."""
    bc = ((campaign.get("optimization") or {}).get("build_checks")) or {}
    raw = bc.get("mechanism_paths") if isinstance(bc, dict) else None
    paths = [str(p).strip() for p in (raw or [])]
    whole = [p for p in paths if p.rstrip("/") in WHOLE_REPO or p in WHOLE_REPO]
    paths = [p for p in paths if p]
    if not paths or whole:
        raise BuildScopeViolation(
            "a build stage needs build_checks.mechanism_paths naming the files and "
            "directories the mechanism may live in"
            + (f"; {whole} names the whole repo, which is no scope at all" if whole else "")
            + ". The mechanism verified and measured is exactly the diff of those "
            "paths against the pre-build commit.")
    return paths


def build_declared(campaign: dict) -> bool:
    from orchestrator.optimize.policy import pre_epoch_stages

    return "build" in pre_epoch_stages(campaign)


def validation_findings(campaign: dict) -> list[str]:
    """A campaign with a ``build`` stage must declare
    ``build_checks.mechanism_paths``: without it the write-scope check can only
    protect the inputs it can infer from the run_command, and an inferred
    protected set can be empty or miss an imported module."""
    opt = (campaign or {}).get("optimization") or {}
    stages = opt.get("stages") if isinstance(opt, dict) else None
    if not isinstance(stages, list) or "build" not in stages:
        return []
    bc = opt.get("build_checks") if isinstance(opt.get("build_checks"), dict) else {}
    paths = [p for p in (bc.get("mechanism_paths") or []) if str(p).strip()]
    whole = [p for p in paths if str(p).strip().rstrip("/") in WHOLE_REPO]
    if whole:
        return [f"build_checks.mechanism_paths entry {whole} names the whole repo; a "
                f"build's mechanism must be scoped to the files it may change."]
    if paths:
        return []
    return [
        "optimization.stages declares `build` but optimization.build_checks."
        "mechanism_paths is not declared. The build agent writes into the target "
        "repo; mechanism_paths is the only scope its writes are checked against "
        "(anything outside it aborts the campaign). Declare the files and "
        "directories the mechanism and its tests may live in, e.g. "
        "mechanism_paths: [src/mechanism.py, tests/test_mechanism.py]."
    ]
