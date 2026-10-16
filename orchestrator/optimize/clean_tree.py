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
2. **Clean tree** (``ensure``). A PRIVATE tree (``materialize``): the pre-build
   commit's blobs read with ``ls-tree``/``cat-file`` (no hooks, filters or
   attributes apply), written as plain files into a directory under the Nous
   state home (``tree_root``, unrelated to the work_dir), committed to a fresh
   repository run with hardened git (no hooks, no fsmonitor, no global/system
   config, no excludes or attributes), checked to hash to the pre-build TREE
   recorded before the agent ran, and with the patch applied. It shares no
   ``.git`` with the agent's repo. Verify's test
   runs, the baseline re-measurement, the 2(d) mutants and EVERY epoch
   measurement run there, never in the agent's working tree. Out-of-scope
   writes, protected-file edits, commits, hidden or ignored files, symlink swaps
   and planted caches in the agent's tree are simply absent from it.
3. **Integrity** (``check``: before each stage, after every measurement batch,
   and at the terminal transition). Every file on disk is hashed and compared
   with the manifest recorded when the tree was created -- independent of the
   tree's own index and of any exclude file -- and a new file with a code
   suffix or name, or a new symlink, is a problem anywhere. Target code that modifies the checkout it is measured
   in aborts the campaign. A missing clean tree (a resume on another machine, a
   cleaned scratch dir) is recreated deterministically from the recorded commit
   and patch.

What it does not cover: target code can modify the clean tree WITHIN one batch
and restore it before the check after it; it can reach anything outside the
tree (the home directory, system libraries); a planted DATA file (no code suffix
or name) is not detected; and in-process tampering by in-scope mechanism code
(e.g. monkeypatching the harness's timer at import) leaves nothing on disk at
all -- only the build review can catch that.
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
MANIFEST = "clean_tree.manifest.json"
EXTRAS = "clean_tree.extras.json"
PROBE_RECORD = "clean_tree.probe.json"
TREE = "tree"
CODE_SUFFIXES = frozenset({".py", ".pth", ".pyc", ".go", ".rs", ".js", ".mjs", ".cjs",
                           ".ts", ".java", ".rb", ".sh", ".so", ".dylib", ".dll"})
CODE_NAMES = frozenset({"conftest.py", "sitecustomize.py", "usercustomize.py",
                        "Makefile", "go.mod", "package.json", "pytest.ini", "setup.cfg",
                        "tox.ini", "pyproject.toml"})


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


def _copy_scope(src: Path, dst: Path, paths: list[str]) -> None:
    """Copy the mechanism paths from ``src`` (the agent's tree) into ``dst`` by
    plain file reads -- no git command runs in the agent's repo, so none of its
    hooks, filters or fsmonitor can. Ignored caches are skipped; a symlink is
    copied as a symlink, never followed."""
    for rel in paths:
        s_, d_ = src / rel, dst / rel
        if d_.is_symlink() or d_.is_file():
            d_.unlink()
        elif d_.is_dir():
            shutil.rmtree(d_)
        if s_.is_symlink():
            d_.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(s_), d_)
        elif s_.is_file():
            d_.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(s_, d_)
        elif s_.is_dir():
            for q in s_.rglob("*"):
                r = q.relative_to(src)
                if set(r.parts) & {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"} \
                        or q.suffix in (".pyc", ".pyo"):
                    continue
                t = dst / r
                if q.is_symlink():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(os.readlink(q), t)
                elif q.is_file():
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(q, t)


def _diff_against(repo: Path, base: str, paths: list[str], scratch: Path,
                  expect_tree: str | None = None) -> tuple[bytes, list[str]]:
    """The mechanism patch, computed in a PRIVATE tree: materialize the base,
    copy the scope from the agent's tree by file reads, diff with hardened git."""
    if scratch.exists():
        shutil.rmtree(scratch)
    materialize(Path(repo), base, scratch, patch=None, expect_tree=expect_tree)
    _copy_scope(Path(repo), scratch, paths)
    tracked = set(_hgit(scratch, "ls-files", "-z").split("\0"))
    present = [p for p in paths if (scratch / p).exists() or os.path.lexists(scratch / p)
               or any(t == p or t.startswith(p.rstrip("/") + "/") for t in tracked)]
    if present:
        _hgit(scratch, "add", "-A", "-f", "--", *present)
    patch = _hgit(scratch, "diff", "--cached", "--binary", "--full-index", "HEAD", binary=True)
    names = [n for n in _hgit(scratch, "diff", "--cached", "--name-only", "-z", "HEAD")
             .split("\0") if n]
    shutil.rmtree(scratch, ignore_errors=True)
    return patch, sorted(names)


def capture(campaign: dict, repo: Path, work_dir: Path, base: str,
            *, protected: set[str], base_tree_sha: str | None = None,
            extras_pre: dict | None = None) -> dict:
    """Record the mechanism patch; refuse one that touches a protected path."""
    from orchestrator.optimize.build_scope import mechanism_scope

    paths = [p.strip("/") for p in mechanism_scope(campaign)]
    patch, names = _diff_against(Path(repo), base, paths, tree_root(work_dir) / "capture",
                                 expect_tree=base_tree_sha)
    listed = {str(p).strip("/") for p in paths}
    bad = sorted(n for n in names if n in protected and n not in listed)
    if bad:
        raise CleanTreeError(
            f"the mechanism patch touches protected path(s) {bad} (the benchmark "
            f"harness or a pre-existing declared test). List each one by exact path in "
            f"build_checks.mechanism_paths if editing it is part of the mechanism.")
    (Path(work_dir) / PATCH).write_bytes(patch)
    opt = (campaign.get("optimization") or {})
    rec = {"base_sha": base, "base_tree": base_tree_sha,
           "extras": list((campaign.get("target_system") or {}).get("worktree_extras") or []),
           "extras_pre": extras_pre,
           "probe_commands": [c for c in (opt.get("run_command"), opt.get("test_command")) if c],
           "patch_sha256": hashlib.sha256(patch).hexdigest(),
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


#: git, hardened: no hooks, no fsmonitor, no filters/attributes or excludes from
#: anywhere, no global or system config. Used for every command on a PRIVATE
#: tree (the clean tree and the mutants), which never shares a .git with the
#: agent's repo.
HARDENED_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
HARDENED_C = ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false",
              "-c", "core.untrackedCache=false", "-c", f"core.excludesFile={os.devnull}",
              "-c", f"core.attributesFile={os.devnull}", "-c", "commit.gpgsign=false",
              "-c", "user.name=nous", "-c", "user.email=nous@localhost",
              "-c", "core.autocrlf=false", "-c", "core.symlinks=true")


def _hgit(cwd: Path, *args: str, binary: bool = False, env: dict | None = None):
    try:
        proc = subprocess.run(["git", *HARDENED_C, *args], cwd=str(cwd), capture_output=True,
                              timeout=600, env={**os.environ, **HARDENED_ENV, **(env or {})})
    except (OSError, subprocess.SubprocessError) as exc:
        raise CleanTreeError(f"git {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise CleanTreeError(f"git {' '.join(args)} exited {proc.returncode}: "
                             f"{proc.stderr.decode(errors='replace').strip()[:400]}")
    return proc.stdout if binary else proc.stdout.decode(errors="replace")


def tree_root(work_dir: Path) -> Path:
    """Where the clean tree for ``work_dir`` lives: under the Nous state home,
    in a directory unrelated to the work_dir (so target code holding a path to
    one learns nothing about the other)."""
    from orchestrator.work_dir_resolver import STATE_HOME_ENV

    home = os.environ.get(STATE_HOME_ENV)
    base = (Path(home).expanduser() if home else Path.home() / ".nous") / "clean-trees"
    tag = hashlib.sha256(str(Path(work_dir).resolve()).encode()).hexdigest()[:16]
    return base / tag


def _read_objects(repo: Path, base_sha: str) -> list[tuple[str, str, bytes]]:
    """``[(mode, path, bytes)]`` for every entry of ``base_sha``'s tree, read with
    ``ls-tree`` + ``cat-file --batch`` (hardened): neither applies attributes,
    filters or hooks, unlike ``archive`` or ``checkout``."""
    ls = _hgit(Path(repo), "ls-tree", "-r", "-z", "--full-tree", base_sha)
    ents = []
    for e in ls.split("\0"):
        if not e:
            continue
        meta, path = e.split("\t", 1)
        mode, typ, sha = meta.split()
        ents.append((mode, typ, sha, path))
    blobs = [e for e in ents if e[1] == "blob"]
    if any(e[1] == "commit" for e in ents):
        raise CleanTreeError("the target has submodules; the clean-checkout model does "
                             "not support them")
    try:
        proc = subprocess.run(["git", *HARDENED_C, "cat-file", "--batch"], cwd=str(repo),
                              input=b"".join(e[2].encode() + b"\n" for e in blobs),
                              capture_output=True, timeout=600,
                              env={**os.environ, **HARDENED_ENV})
    except (OSError, subprocess.SubprocessError) as exc:
        raise CleanTreeError(f"git cat-file: {exc}") from exc
    if proc.returncode != 0:
        raise CleanTreeError(f"git cat-file exited {proc.returncode}")
    out, pos, data = [], 0, proc.stdout
    for mode, _t, sha, path in blobs:
        nl = data.index(b"\n", pos)
        hdr = data[pos:nl].decode().split()
        size = int(hdr[2])
        out.append((mode, path, data[nl + 1:nl + 1 + size]))
        pos = nl + 1 + size + 1
    return out


def base_tree(repo: Path, base_sha: str) -> str:
    return _hgit(Path(repo), "rev-parse", f"{base_sha}^{{tree}}").strip()


def materialize(repo: Path, base_sha: str, dest: Path, *, patch: Path | None,
                include: list[str] | None = None, expect_tree: str | None = None) -> None:
    """A PRIVATE tree at ``dest``: the blobs of ``base_sha`` written as files (no
    .git of the agent repo is ever used as the tree's repository), a fresh
    hardened repository committing them, then ``patch`` applied (only
    ``include`` paths when given). When ``expect_tree`` is given, the private
    commit's tree must hash to it -- the base recorded BEFORE the build -- so a
    rewritten object in the agent repo cannot change the base."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for mode, path, data in _read_objects(Path(repo), base_sha):
        t = dest / path
        t.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            os.symlink(data.decode(), t)
        else:
            t.write_bytes(data)
            if mode == "100755":
                t.chmod(0o755)
    _hgit(dest, "init", "-q")
    _hgit(dest, "add", "-A", "-f")
    _hgit(dest, "commit", "-q", "--allow-empty", "-m", f"nous clean base {base_sha}")
    if expect_tree is not None:
        got = _hgit(dest, "rev-parse", "HEAD^{tree}").strip()
        if got != expect_tree:
            raise CleanTreeError(f"the base rebuilt from the agent repo's objects hashes to "
                                 f"tree {got}, not the pre-build tree {expect_tree}: the "
                                 f"repository's objects were changed")
    if patch is not None and patch.stat().st_size:
        _hgit(dest, "apply", "--binary", "--whitespace=nowarn",
              *[f"--include={p}" for p in (include or [])], str(Path(patch).resolve()))


def _manifest(dest: Path) -> dict[str, str]:
    """``{path: sha256 | "link:<target>"}`` of every FILE on disk under ``dest``
    (``.git`` excluded), read from the filesystem -- not from any index."""
    out = {}
    for p in sorted(dest.rglob("*")):
        rel = p.relative_to(dest).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if p.is_symlink():
            out[rel] = "link:" + os.readlink(p)
        elif p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


_EXTRA_SKIP = ("__pycache__",)


def extras_digest(repo: Path, extras: list[str]) -> dict[str, str]:
    """``{path: sha256 | "link:<target>"}`` of every file of the declared
    ``worktree_extras`` IN THE AGENT'S REPO, bytecode caches excluded. Taken
    BEFORE the build so a copy into the clean tree can be required to equal what
    existed before the agent ran (round 4): a conftest.py or a patched module
    the agent planted in an ignored asset directory is then refused."""
    out: dict[str, str] = {}
    for rel in extras:
        rel = str(rel).strip().strip("/")
        src = Path(repo) / rel
        if not os.path.lexists(src):
            continue
        items = [src] if (src.is_symlink() or not src.is_dir()) else sorted(src.rglob("*"))
        for q in items:
            r = q.relative_to(repo).as_posix()
            if set(Path(r).parts) & set(_EXTRA_SKIP) or q.suffix in (".pyc", ".pyo"):
                continue
            if q.is_symlink():
                out[r] = "link:" + os.readlink(q)
            elif q.is_file():
                out[r] = hashlib.sha256(q.read_bytes()).hexdigest()
    return out


def copy_extras(repo: Path, dest: Path, extras: list[str]) -> dict[str, str]:
    """Copy ``target_system.worktree_extras`` (ignored assets: data, built
    binaries, a virtualenv) from the agent's repo into the clean tree. COPIED,
    never symlinked -- a symlink would let the measured tree read the agent's
    tree again (round 3, D2). Symlinks INSIDE an extra are copied as links.
    Returns ``{path: sha256}`` of every copied file, for the record."""
    out: dict[str, str] = {}
    for rel in extras:
        rel = str(rel).strip().strip("/")
        if not rel or rel.startswith("..") or os.path.isabs(rel):
            raise CleanTreeError(f"worktree_extras entry {rel!r} must be a path inside the repo")
        src = Path(repo) / rel
        if not os.path.lexists(src):
            raise CleanTreeError(f"worktree_extras entry {rel!r} does not exist in the repo")
        t = dest / rel
        if os.path.lexists(t):
            raise CleanTreeError(f"worktree_extras entry {rel!r} is tracked or in the "
                                 f"mechanism: extras are for ignored assets only")
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, t, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        else:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, t, follow_symlinks=False)
        repo_r = str(Path(repo).resolve())
        for q in ([t] if not t.is_dir() or t.is_symlink() else sorted(t.rglob("*"))):
            r = q.relative_to(dest).as_posix()
            if q.is_symlink():
                # A link that resolves into the AGENT'S repo would let the
                # measured tree read the agent's files again (round 4).
                target = os.path.realpath(q)
                if target == repo_r or target.startswith(repo_r + os.sep):
                    raise CleanTreeError(
                        f"worktree_extras {rel!r} contains a symlink {r} -> "
                        f"{os.readlink(q)} that resolves into the build agent's "
                        f"repository; extras are copied so the clean tree never reads "
                        f"the agent's tree. Replace the link with the files.")
                out[r] = "link:" + os.readlink(q)
            elif q.is_file():
                out[r] = hashlib.sha256(q.read_bytes()).hexdigest()
    return out


def _create(repo: Path, work_dir: Path, rec: dict) -> Path:
    dest = tree_root(work_dir) / TREE
    materialize(Path(repo), rec["base_sha"], dest, patch=Path(work_dir) / PATCH,
                expect_tree=rec.get("base_tree"))
    extras = copy_extras(Path(repo), dest, rec.get("extras") or [])
    pre = rec.get("extras_pre")
    if pre is not None and pre != extras:
        changed = sorted(k for k in set(pre) | set(extras) if pre.get(k) != extras.get(k))
        raise CleanTreeError(
            f"worktree_extras changed during the build ({changed[:10]}): what is copied "
            f"into the clean tree must be what existed before the build agent ran.")
    ep = Path(work_dir) / EXTRAS
    if ep.exists():
        if _sealed_json(work_dir, EXTRAS) != extras:
            raise CleanTreeError(
                "the worktree_extras copied into the rebuilt clean tree differ from the "
                "ones first copied (the agent's repo changed them since)")
    else:
        ep.write_text(json.dumps(extras, indent=1, sort_keys=True))
    probe_imports(dest, Path(repo), rec.get("probe_commands") or [],
                  work_dir=Path(work_dir))
    mf = _manifest(dest)
    mp = Path(work_dir) / MANIFEST
    if mp.exists():
        # A recreated tree must be byte-identical to the one first measured --
        # compared against the SEALED manifest, never an unsealed file.
        prev = _sealed_json(work_dir, MANIFEST)
        if prev != mf:
            raise CleanTreeError("the clean tree rebuilt from the recorded commit and "
                                 "patch differs from the one first created")
    else:
        mp.write_text(json.dumps(mf, indent=1, sort_keys=True))
    # Sealed right after creation, before the first measurement (round 4,
    # item 2), and kept in memory: every later integrity check compares with the
    # in-memory reference when this process created the tree, and with the
    # seal-verified file otherwise.
    from orchestrator.optimize import gate_records

    gate_records.seal(work_dir, (MANIFEST, EXTRAS))
    _REFERENCE[str(Path(work_dir).resolve())] = mf
    return dest


#: work_dir -> the manifest this process created (the in-memory reference).
_REFERENCE: dict[str, dict] = {}


def _sealed_json(work_dir: Path, name: str) -> dict:
    from orchestrator.optimize import gate_records

    st = gate_records.check(Path(work_dir), name)
    if st != "ok":
        raise CleanTreeError(f"{name} fails its seal ({st}): the reference the clean "
                             f"tree is checked against cannot be trusted")
    return json.loads((Path(work_dir) / name).read_text())


#: Probe run with each Python interpreter a target command names: prints every
#: import root the interpreter would read from (sys.path entries and the
#: locations of editable-install finders / .pth-mapped packages).
_PROBE = r"""
import json, sys, site, importlib.metadata as md
roots = [p for p in sys.path if p]
for d in md.distributions():
    try:
        du = d.read_text("direct_url.json")
    except Exception:
        du = None
    if du:
        try:
            u = json.loads(du).get("url", "")
            if u.startswith("file://"):
                roots.append(u[7:])
        except Exception:
            pass
    for f in (d.files or []):
        if str(f).endswith(".pth"):
            try:
                for ln in (d.locate_file(f).read_text().splitlines()):
                    if ln and not ln.startswith(("#", "import")):
                        roots.append(ln.strip())
            except Exception:
                pass
print(json.dumps(roots))
"""


#: Launchers that run ANOTHER program; the interpreter they end up running
#: cannot be read off the command line (round 4, item 3).
LAUNCHERS = frozenset({"uv", "uvx", "conda", "mamba", "micromamba", "poetry", "pipenv",
                       "pdm", "hatch", "rye", "make", "gmake", "sh", "bash", "zsh",
                       "env", "nix", "nix-shell", "docker", "podman", "npx", "npm",
                       "go", "cargo", "tox", "nox"})
#: Version-manager shims: a script that re-dispatches by configuration.
SHIM_DIRS = (".pyenv/shims", ".asdf/shims", ".rbenv/shims", "shims")


def _resolve_interpreter(tok: str, cwd: Path) -> tuple[str | None, str | None]:
    """``(executable, None)`` for a Python interpreter the command runs
    DIRECTLY, ``(None, reason)`` when what runs cannot be determined, and
    ``(None, None)`` when the token is not a Python launcher at all."""
    name = Path(tok).name
    if name in LAUNCHERS:
        return None, f"`{name}` launches another program; its interpreter is not known"
    is_py = name.startswith("python") or name in ("pytest", "py.test")
    if not is_py:
        return None, None
    exe = tok if os.path.isabs(tok) else (str(cwd / tok) if "/" in tok else shutil.which(tok))
    if not exe:
        return None, f"`{tok}` is not on PATH"
    real = os.path.realpath(exe)
    if any(sd in exe for sd in SHIM_DIRS) or any(sd in real for sd in SHIM_DIRS):
        return None, f"`{tok}` is a version-manager shim ({exe}); what it runs depends on configuration"
    if name in ("pytest", "py.test"):
        try:
            first = Path(exe).read_text(errors="replace").splitlines()[0]
        except (OSError, IndexError):
            return None, f"cannot read the interpreter of {exe}"
        if not first.startswith("#!"):
            return None, f"{exe} has no interpreter line"
        parts = first[2:].strip().split()
        if not parts or Path(parts[0]).name == "env":
            return None, f"{exe} runs `{first[2:].strip()}`; its interpreter is not fixed"
        exe = parts[0]
    return exe, None


def _interpreters(cmd: str, cwd: Path) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """``([(exe, flags)], undetermined_reasons)``. ``flags`` are the
    interpreter's own options (e.g. ``-S``, ``-I``) so the probe runs the same
    way the command will."""
    import shlex

    try:
        toks = shlex.split(cmd)
    except ValueError as exc:
        return [], [f"`{cmd[:60]}` cannot be parsed ({exc})"]
    if not toks:
        return [], []
    exe, why = _resolve_interpreter(toks[0], cwd)
    if why:
        return [], [why]
    if exe is None:
        return [], []                    # not a Python command: nothing to probe
    flags = []
    for t in toks[1:]:
        if t.startswith("-") and t not in ("-m", "-c") and len(t) <= 3:
            flags.append(t)
        else:
            break
    return [(exe, flags)], []


def probe_imports(dest: Path, repo: Path, commands: list[str], *,
                  work_dir: Path | None = None) -> None:
    """Refuse a clean tree whose Python would import from the AGENT's repo: an
    editable install, a ``.pth`` file or a PYTHONPATH entry pointing there
    measures the agent's tree silently (round 3, D1).

    FAILS CLOSED (round 4, item 3): a probe that cannot run, exits non-zero or
    prints something unparseable refuses the tree. A command whose interpreter
    cannot be determined (a launcher such as ``uv run`` or ``make``, a version-
    manager shim) is not refused -- such commands are legitimate -- but is
    recorded in ``clean_tree.probe.json`` and listed in report.json
    ``provenance.waivers`` as not probed."""
    from orchestrator.optimize.runner import target_env

    repo_r = str(Path(repo).resolve())
    env = target_env()
    record = {"probed": [], "not_probed": []}
    for cmd in commands:
        found, reasons = _interpreters(cmd, dest)
        for r in reasons:
            record["not_probed"].append({"command": cmd, "reason": r})
        for exe, flags in found:
            try:
                proc = subprocess.run([exe, *flags, "-c", _PROBE], cwd=str(dest), env=env,
                                      capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                raise CleanTreeError(f"the import probe for `{cmd[:60]}` could not run "
                                     f"({exc}); the clean tree cannot be shown to import "
                                     f"only from itself") from exc
            if proc.returncode != 0:
                raise CleanTreeError(
                    f"the import probe for `{cmd[:60]}` failed (exit {proc.returncode}: "
                    f"{proc.stderr.strip()[:200]}); the clean tree cannot be shown to "
                    f"import only from itself")
            try:
                roots = json.loads(proc.stdout.strip().splitlines()[-1])
                if not isinstance(roots, list):
                    raise ValueError("not a list")
            except (ValueError, IndexError) as exc:
                raise CleanTreeError(
                    f"the import probe for `{cmd[:60]}` printed something unparseable "
                    f"({exc}); the clean tree cannot be shown to import only from itself"
                ) from exc
            record["probed"].append({"command": cmd, "interpreter": exe, "flags": flags})
            bad = sorted({r for r in roots
                          if str(Path(r).resolve()) == repo_r
                          or str(Path(r).resolve()).startswith(repo_r + os.sep)})
            if bad:
                raise CleanTreeError(
                    f"the interpreter {exe} that `{cmd[:60]}` runs would import from the "
                    f"build agent's repository ({bad[:3]}): an editable install, a .pth "
                    f"file or a PYTHONPATH entry pointing at {repo}. The clean checkout "
                    f"would then measure the agent's tree, not the recorded mechanism. "
                    f"Install the package non-editably, or from the clean tree, and use "
                    f"target_system.worktree_extras for ignored assets.")
    if work_dir is not None:
        (Path(work_dir) / PROBE_RECORD).write_text(json.dumps(record, indent=2))
        from orchestrator.optimize import gate_records

        gate_records.seal(work_dir, (PROBE_RECORD,))


def integrity_problems(work_dir: Path, rec: dict | None = None) -> list[str]:
    """Compare the clean tree ON DISK with the manifest recorded when it was
    created. Independent of the tree's own index and of any exclude file: every
    file is hashed; a new file with a CODE suffix is a problem anywhere (data
    files a run writes are allowed, and listed nowhere)."""
    dest = tree_root(work_dir) / TREE
    mp = Path(work_dir) / MANIFEST
    if not dest.is_dir():
        return [f"the clean tree {dest} is missing"]
    want = _REFERENCE.get(str(Path(work_dir).resolve()))
    if want is None:
        if not mp.exists():
            return ["the clean-tree manifest is missing"]
        try:
            want = _sealed_json(work_dir, MANIFEST)
        except CleanTreeError as exc:
            return [str(exc)]
    have = _manifest(dest)
    out = []
    linked = _multiply_linked(dest)
    if linked:
        out.append(f"files with extra hard links (writable through another path): "
                   f"{linked[:10]}")
    changed = sorted(p for p in want if have.get(p) != want[p])
    if changed:
        out.append(f"files changed or removed: {changed[:10]}")
    new_code = sorted(p for p in have if p not in want and (
        Path(p).suffix in CODE_SUFFIXES or Path(p).name in CODE_NAMES
        or have[p].startswith("link:")))
    if new_code:
        out.append(f"new code files or symlinks appeared: {new_code[:10]}")
    return out


def _multiply_linked(dest: Path) -> list[str]:
    """Files in the tree with more than one hard link: their bytes can be
    changed through another path without touching this one (round 4)."""
    out = []
    for p in dest.rglob("*"):
        rel = p.relative_to(dest).as_posix()
        if rel == ".git" or rel.startswith(".git/") or p.is_symlink() or not p.is_file():
            continue
        try:
            if p.stat().st_nlink > 1:
                out.append(rel)
        except OSError:
            out.append(rel)
    return sorted(out)


def ensure(repo: Path, work_dir: Path, *, fresh: bool = False) -> Path:
    """The clean tree, created (``fresh`` or missing) or integrity-checked."""
    rec = read_record(work_dir)
    dest = tree_root(work_dir) / TREE
    if fresh or not dest.exists():
        return _create(Path(repo), Path(work_dir), rec)
    check(work_dir)
    return dest


def check(work_dir: Path) -> None:
    """Raise when the clean tree is not what was created (A4: called after
    every measurement batch and at the terminal transition, too)."""
    problems = integrity_problems(work_dir)
    if problems:
        raise CleanTreeError(
            "the clean checkout the epoch measures was modified (" + "; ".join(problems)
            + "). Target code changed the tree it is measured in; the measurements "
            "since the last check describe a different system. Start a new campaign.")


def build_preconditions(campaign: dict, run_id: str | None = None) -> list[str]:
    """What a build campaign needs BEFORE any token is spent (round 3, D3, E3):
    a git repo, every tracked file committed, and a work_dir outside the repo.
    Returns human-readable problems (empty when ready, or when no build)."""
    from orchestrator.optimize.build_scope import build_declared

    try:
        if not build_declared(campaign):
            return []
    except (TypeError, ValueError, AttributeError):
        return []
    repo = (campaign.get("target_system") or {}).get("repo_path")
    if not repo:
        return ["a build stage needs target_system.repo_path: the mechanism is authored "
                "in that repository and verified in a clean checkout of its commit."]
    repo_p = Path(str(repo)).expanduser()
    if not repo_p.is_dir():
        return [f"target_system.repo_path {repo} does not exist"]
    out: list[str] = []
    try:
        require_clean_base(repo_p)
    except CleanTreeError as exc:
        msg = str(exc)
        if "not a git repository" in msg:
            out.append(f"a build stage needs target_system.repo_path to be a git "
                       f"repository; {repo} is not one. `git init && git add -A && "
                       f"git commit` it first.")
        elif "Dirty:" in msg:
            head, dirty = msg.split("Dirty:", 1)
            out.append(head.strip() + " Commit them (`git commit -am ...`) before "
                       "running. Dirty:" + dirty)
        else:
            out.append(msg)
    try:
        from orchestrator.work_dir_resolver import resolve_work_dir

        wd = resolve_work_dir(run_id or campaign.get("run_id") or "run", repo_p)
        Path(wd).resolve().relative_to(repo_p.resolve())
        out.append(
            f"the campaign work_dir would be {wd}, INSIDE the target repo: a build "
            f"stage's agent and every target command run there, so its gate records "
            f"would be in their reach. Export NOUS_CAMPAIGN_PARENT to a directory "
            f"outside the repo (e.g. `export NOUS_CAMPAIGN_PARENT=~/nous-campaigns`).")
    except ValueError:
        pass
    except Exception:  # noqa: BLE001 -- resolution problems are reported elsewhere
        pass
    return out
