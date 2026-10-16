"""Oracle 2(d): the build's authored correctness tests must discriminate the
mechanism, not merely its existence (audit Q10).

Why 2(b) is not enough
----------------------
Oracle 2(b) rejects a declared correctness test that already PASSED before
the build. It accepts every test that failed before -- including a test that
failed only because the module or symbol it imports did not exist yet. Such a
test (``import mech; assert mech``) passes the "fails before, passes after"
oracle for every build that creates the name, whatever the mechanism does.
That is the trivially satisfiable case this oracle closes.

The rule
--------
Each declared ``correctness`` test of a factor the build is authoring (the
same factor set 2(b) binds, ``stage_runner.built_factor_ids``) needs ONE piece
of DISCRIMINATION EVIDENCE:

``pre_build_behavioral_failure``
    It ran before the build and failed for a reason other than a missing
    symbol (an assertion, a wrong value, a behavioural exception). The test
    exercised code that existed and behaved differently.

``mutant_behavioral_failure``
    Against a MECHANISM-REVERTED MUTANT it fails for a reason other than a
    missing symbol. The mutant is the post-build tree with every pre-existing
    non-test file the build edited restored to HEAD, while the build's tests and
    its NEW files are kept. New modules therefore still import, so an
    import-only test PASSES on the mutant (vacuous); a test that exercises the
    mechanism's wiring into the system fails on it behaviourally.

A test with neither -- it passes on the mutant, or fails there only with
``ImportError``/``ModuleNotFoundError``/``AttributeError``/``NameError`` on a
missing name (or a language's equivalent), or no mutant can be built (not a
git tree, no ``test_command``) -- fails verify, unless the campaign waives the
oracle with ``build_checks.allow_nondiscriminating_tests: "<reason>"``, which
is recorded in ``authored_tests.json`` and report.json ``provenance.waivers``.

What it does NOT prove
----------------------
That the test asserts the RIGHT behaviour. A test can still assert something
irrelevant that happens to differ between the mutant and the build. The
oracle removes the trivially satisfiable case (existence-only tests) and
forces the test to observe behaviour; it does not grade the assertion.
A mechanism that lives entirely in new files reached only by a new entry
point leaves no pre-existing file to revert, so its mutant equals the build
and every test reads as vacuous; such a campaign must restructure the test to
compare against the pre-existing path, or waive with a reason.

Classification is a text match on the failing test's own output
(``failure_kind``), with the signatures in ``ABSENCE`` below. A failure whose
text carries an absence signature and no assertion signature is ``absence``.
When verdicts were injected without any test output (the unit-test seam), the
kind is ``unknown`` and a pre-build failure is accepted as-is, exactly as 2(b)
accepts it today; production always runs the test command and records text.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: Failure signatures meaning "the name the test uses does not exist".
ABSENCE = [re.compile(p) for p in (
    r"\bModuleNotFoundError\b",
    r"\bImportError\b",
    r"cannot import name",
    r"\bAttributeError\b.*has no attribute",
    r"\bNameError\b.*is not defined",
    r"unexpected keyword argument",
    r"\bundefined: \w+",                     # go
    r"has no field or method",               # go
    r"cannot find symbol",                   # java
    r"cannot find (function|value|type|struct|module)",  # rust
    r"unresolved import",                    # rust
    r"has no exported member",               # typescript
    r"Cannot find module",                   # node
)]
#: Signatures of a behavioural (assertion-level) failure.
ASSERTION = [re.compile(p) for p in (
    r"\bAssertionError\b", r"^\s*(E\s+)?assert\b", r"\bassert .*(==|!=|<|>|is)",
    r"Error Trace:", r"expected .* (got|but was|actual)", r"\bassert_eq!",
    r"Expected:|Received:",
)]

TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec"})
TEST_FILE = re.compile(
    r"(^test_.*\.py$|_test\.py$|_test\.go$|Test\.java$|Tests\.java$|"
    r"\.(test|spec)\.[jt]sx?$|_spec\.rb$)")


def failure_kind(text: str | None) -> str:
    """``absence`` | ``behavioral`` | ``unknown`` for one failing test's text."""
    if not text or not text.strip():
        return "unknown"
    lines = text.splitlines()
    # pytest prints the failing SOURCE line too ("    assert mech.f(2) == 4"),
    # which would read as an assertion; its error lines start with "E ". When
    # they exist, classify on them and on the short-summary lines only.
    err = [ln for ln in lines if ln.startswith("E ") or ln.startswith(("FAILED ", "ERROR "))]
    lines = err or lines
    absent = any(p.search(ln) for p in ABSENCE for ln in lines)
    asserted = any(p.search(ln) for p in ASSERTION for ln in lines)
    if absent and not asserted:
        return "absence"
    return "behavioral"


def failure_texts(output: str, tests: list[str]) -> dict[str, str]:
    """Best-effort per-test failure text from a test runner's output.

    pytest: the ``FAILED <id> - <msg>`` / ``ERROR <id> - <msg>`` summary lines
    and the ``____ <name> ____`` long-format section; go: the lines between
    ``=== RUN <Name>`` and ``--- FAIL: <Name>``, or ``-json`` ``Output``
    records. A test whose text cannot be isolated gets the whole output when
    the whole output carries a failure signature (a collection-time
    ImportError names no single test)."""
    out: dict[str, str] = {}
    lines = output.splitlines()
    for t in tests:
        name = t.split("::")[-1]
        short = name.split("[")[0]
        chunks: list[str] = []
        for ln in lines:
            if (ln.startswith(("FAILED ", "ERROR ")) and t in ln):
                chunks.append(ln)
        # pytest long format: "____ test_name ____" until the next "____" header.
        sec = re.compile(r"^_{3,} (\S+\.)?" + re.escape(short) + r"(\[.*\])? _{3,}$")
        for i, ln in enumerate(lines):
            if sec.match(ln):
                j = i + 1
                while j < len(lines) and not re.match(r"^_{3,} \S.* _{3,}$|^={3,}", lines[j]):
                    j += 1
                chunks.append("\n".join(lines[i:j]))
        # go -v
        run = f"=== RUN   {short}"
        for i, ln in enumerate(lines):
            if ln.strip() == run.strip():
                j = i + 1
                while j < len(lines) and not lines[j].lstrip().startswith(
                        (f"--- FAIL: {short}", f"--- PASS: {short}")):
                    j += 1
                chunks.append("\n".join(lines[i:j + 1]))
        # go -json
        for ln in lines:
            if ln.startswith("{") and f'"Test":"{short}"' in ln.replace(" ", ""):
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if rec.get("Output"):
                    chunks.append(rec["Output"])
        if chunks:
            out[t] = "\n".join(chunks)
        elif any(p.search(output) for p in ABSENCE + ASSERTION):
            out[t] = output
    return out


def kinds_for(verdicts: dict[str, bool], output: str | None) -> dict[str, str]:
    """Failure kind of every failing (or absent) test in ``verdicts``."""
    failing = [t for t, ok in (verdicts or {}).items() if not ok]
    if output is None:
        return {t: "unknown" for t in failing}
    texts = failure_texts(output, failing)
    return {t: failure_kind(texts.get(t)) for t in failing}


def read_log(test_run) -> str | None:
    p = getattr(test_run, "log_path", None)
    if p is None or not Path(p).exists():
        return None
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return None


def is_test_path(rel: str, declared: list[str]) -> bool:
    files = {str(t).split("::", 1)[0] for t in declared}
    if rel in files:
        return True
    parts = rel.split("/")
    return bool(TEST_DIRS & set(parts[:-1])) or bool(TEST_FILE.search(parts[-1]))


def _git(repo: Path, *args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                              text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None


def build_mutant(repo: Path, work_dir: Path, written: list[str],
                 declared: list[str], dest: Path) -> list[str] | None:
    """Create the mechanism-reverted mutant at ``dest``; return the reverted
    paths (None when ``repo`` is not a git tree). See the module docstring."""
    from orchestrator.optimize.build import _nous_owned_prefixes, _in_allowlist

    p = _git(repo, "worktree", "add", "--detach", "--force", str(dest), "HEAD")
    if p is None or p.returncode != 0:
        return None
    tracked = set((_git(repo, "ls-files").stdout or "").splitlines())
    st = _git(repo, "status", "--porcelain=v1", "-z", "-uall", "--no-renames")
    owned = _nous_owned_prefixes(repo, work_dir)
    reverted = []
    for entry in (st.stdout if st else "").split("\0"):
        if len(entry) < 4:
            continue
        rel = entry[3:]
        if _in_allowlist(rel, owned):
            continue
        if rel in written and rel in tracked and not is_test_path(rel, declared):
            reverted.append(rel)          # keep HEAD's version: the mechanism edit is undone
            continue
        src, dst = repo / rel, dest / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif not src.exists() and dst.exists():
            dst.unlink()
    return sorted(reverted)


def remove_mutant(repo: Path, dest: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(dest))
    shutil.rmtree(dest, ignore_errors=True)
    _git(repo, "worktree", "prune")


def check(campaign: dict, work_dir: Path, factors, *, repo: Path | None,
          run_tests: Callable[[Path], tuple[dict, str | None]] | None,
          built_ids: set[str]) -> dict:
    """Evaluate oracle 2(d); write ``authored_tests.json``; return the record.
    Raises ``ValueError`` (the caller converts it to a gate failure) when a
    test lacks evidence and the oracle is not waived."""
    wd = Path(work_dir)
    pre = json.loads((wd / "pre_build_tests.json").read_text())
    ran, passed = set(pre.get("ran") or ()), set(pre.get("passed") or ())
    kinds = dict(pre.get("failure_kinds") or {})
    tests = sorted({r["native_test"] for f in factors
                    if not built_ids or f.id in built_ids
                    for r in (f.relations or ())
                    if isinstance(r, dict) and r.get("kind") == "correctness"
                    and r.get("native_test")})
    evidence: dict[str, dict] = {}
    need_mutant = []
    for t in tests:
        if t in ran and t not in passed and kinds.get(t, "unknown") in ("behavioral", "unknown"):
            evidence[t] = {"evidence": "pre_build_behavioral_failure"
                           if kinds.get(t) == "behavioral" else "pre_build_failure_unclassified"}
        else:
            need_mutant.append(t)
    mutant_info: dict = {}
    if need_mutant:
        scope = wd / "build_scope.json"
        written = (json.loads(scope.read_text()).get("written") or []) if scope.exists() else None
        if repo is None or run_tests is None or written is None:
            mutant_info["unavailable"] = (
                "no git target, no test_command, or no record of what the build wrote")
        else:
            dest = Path(tempfile.mkdtemp(prefix="nous-mutant-")) / "tree"
            try:
                declared = [r["native_test"] for f in factors for r in (f.relations or ())
                            if isinstance(r, dict) and r.get("native_test")]
                reverted = build_mutant(Path(repo), wd, written, declared, dest)
                if reverted is None:
                    mutant_info["unavailable"] = "could not create a git worktree"
                else:
                    mutant_info["reverted"] = reverted
                    verdicts, text = run_tests(dest)
                    mk = kinds_for(verdicts, text)
                    for t in need_mutant:
                        if t not in verdicts:
                            mk.setdefault(t, "absence" if text is not None else "unknown")
                    mutant_info["verdicts"] = {t: verdicts.get(t) for t in need_mutant}
                    mutant_info["kinds"] = {t: mk.get(t) for t in need_mutant}
            finally:
                if repo is not None:
                    remove_mutant(Path(repo), dest)
                shutil.rmtree(dest.parent, ignore_errors=True)
    for t in need_mutant:
        why_pre = ("did not exist before the build" if t not in ran
                   else "failed before the build only on a missing symbol")
        if "unavailable" in mutant_info:
            evidence[t] = {"evidence": None,
                           "why": f"{why_pre}, and no mutant could be run "
                                  f"({mutant_info['unavailable']})"}
            continue
        v, k = mutant_info["verdicts"].get(t), mutant_info["kinds"].get(t)
        if v:
            evidence[t] = {"evidence": None,
                           "why": f"{why_pre}, and it PASSES with the build's edits to "
                                  f"existing code reverted: it does not observe the mechanism"}
        elif k == "behavioral":
            evidence[t] = {"evidence": "mutant_behavioral_failure"}
        else:
            evidence[t] = {"evidence": None,
                           "why": f"{why_pre}, and against the mechanism-reverted "
                                  f"mutant it fails only on a missing symbol ({k}): it "
                                  f"checks that a name exists, not what it does"}
    bad = {t: e for t, e in evidence.items() if e["evidence"] is None}
    waiver = ((campaign.get("optimization") or {}).get("build_checks") or {}).get(
        "allow_nondiscriminating_tests")
    record = {"tests": evidence, "mutant": mutant_info,
              "ok": not bad or bool(isinstance(waiver, str) and waiver.strip())}
    if bad and isinstance(waiver, str) and waiver.strip():
        record["waived"] = waiver.strip()
    (wd / "authored_tests.json").write_text(json.dumps(record, indent=2, default=str))
    if bad and "waived" not in record:
        raise ValueError(
            "oracle 2(d): declared correctness test(s) do not discriminate the "
            "mechanism:\n  " + "\n  ".join(f"{t}: {e['why']}" for t, e in sorted(bad.items()))
            + "\nA test that passes as soon as a name exists proves nothing about "
            "what the mechanism does. Make each test exercise the mechanism through "
            "code that existed before the build and assert on its behaviour (so it "
            "fails, by assertion, when the build's edits are reverted), or waive in "
            "writing: optimization.build_checks.allow_nondiscriminating_tests: "
            "\"<why>\" (recorded in report.json). See authored_tests.json."
        )
    return record
