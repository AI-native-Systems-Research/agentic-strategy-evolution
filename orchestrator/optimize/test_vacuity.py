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

Classification is a TEXT MATCH on the failing test's own output, and it fails
closed (``failure_kind``): any absence signature (``ABSENCE``, including
``hasattr``/``getattr`` probes and arity/fixture errors) makes a failure
``absence`` even beside an assertion; only an assertion signature makes it
``behavioral``; anything else -- a timeout, a crash, an unparsed framework,
an echoed source line -- is ``unknown``, and ``unknown`` is never evidence.
Per-test text is isolated EXACTLY (an id must match the summary line exactly;
a long-format section is used only when its name is unique) or not at all; the
whole log is never substituted. The one exception: when the pre-build verdicts
were INJECTED with no test output (``output_recorded: false``, the unit-test
seam), an unclassifiable pre-build failure is accepted as
``pre_build_failure_unclassified`` and listed in report.json's waivers.

Not implemented: a second mutant that keeps the new symbols but stubs their
bodies, which would also catch tests that assert on a value any stub returns.
A git failure while building the mutant is recorded as ``mutant.unavailable``
with git's error, and the test then lacks evidence -- it is not called vacuous.
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

#: Failure signatures meaning "the name the test uses does not exist" (or
#: exists with a different shape). ANY of these in the failure text makes it an
#: absence failure, even next to an assertion: `assert hasattr(m, "f")` fails by
#: assertion, but what it checks is existence.
ABSENCE = [re.compile(p) for p in (
    r"\bModuleNotFoundError\b",
    r"\bImportError\b",
    r"cannot import name",
    r"\bAttributeError\b.*has no attribute",
    r"\bNameError\b.*is not defined",
    r"unexpected keyword argument",
    r"takes \d+ positional arguments? but \d+ (was|were) given",   # python arity
    r"missing \d+ required (positional|keyword-only) argument",
    r"fixture '[^']+' not found",                                # pytest
    r"\bhasattr\(", r"\bgetattr\(",                              # existence probes
    r"\bundefined: \w+",                                          # go
    r"has no field or method",                                    # go
    r"cannot find symbol",                                        # java
    r"cannot find (function|value|type|struct|module|crate|trait|macro)",  # rust
    r"no (method|function or associated item|field) named",       # rust
    r"unresolved import",                                         # rust
    r"has no exported member",                                    # typescript
    r"does not exist on type",                                    # typescript
    r"Cannot find (module|name)",                                 # node / ts
    r"is not a function",                                         # js
)]
#: Signatures of a behavioural (assertion-level) failure. Only these make a
#: failure "behavioral"; a failure matching neither list is "unknown" and is
#: NOT evidence (a timeout, a crash, an unparsed framework).
ASSERTION = [re.compile(p) for p in (
    r"\bAssertionError\b", r"^\s*(E\s+)?assert\b", r"\bassert .*(==|!=|<|>|is)",
    r"Error Trace:", r"Not equal:", r"expected .* (got|but was|actual)",
    r"assertion `left == right` failed", r"assertion failed", r"Expected:|Received:",
    r"\bexpected:? .*\bactual\b", r"expect\(received\)",
    r"\bgot\b.*\bwant\b", r"\bwant\b.*\bgot\b",              # go t.Errorf idiom
    r"^\s*\S+_test\.go:\d+:",                                    # go t.Error/Fatal line
)]
#: Lines that ECHO source code rather than report the failure: pytest's ">"
#: source line and rustc/tsc code frames ("  12 |", "-->", "^^^"). NOT indented
#: lines in general: Go prints its failure messages indented.
ECHO = re.compile(r"^(>\s|\s*\d+\s*\|\s|\s*\|\s|\s*-->|\s*\^+\s*$)")
#: pytest's "+  where ..." explanation lines restate the asserted expression;
#: they count for absence only when they show an existence probe.
WHERE = re.compile(r"^E?\s+\+\s+where\b")
PROBES = [re.compile(r"\bhasattr\("), re.compile(r"\bgetattr\(")]

TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec"})
TEST_FILE = re.compile(
    r"(^test_.*\.py$|_test\.py$|_test\.go$|Test\.java$|Tests\.java$|"
    r"\.(test|spec)\.[jt]sx?$|_spec\.rb$)")


def failure_kind(text: str | None) -> str:
    """``absence`` | ``behavioral`` | ``unknown`` for one failing test's text.

    A TEXT MATCH, and it fails closed: absence wins whenever an absence
    signature appears; ``behavioral`` needs an assertion signature; anything
    else is ``unknown``, which no path accepts as discrimination evidence."""
    if not text or not text.strip():
        return "unknown"
    lines = [ln for ln in text.splitlines() if not ECHO.match(ln)]
    # pytest prints error lines with "E ": when they exist, classify on them
    # and on the short-summary lines only.
    err = [ln for ln in lines if ln.startswith("E ") or ln.startswith(("FAILED ", "ERROR "))]
    lines = err or lines
    for ln in lines:
        pats = PROBES if WHERE.match(ln) else ABSENCE
        if any(p.search(ln) for p in pats):
            return "absence"
    if any(p.search(ln) for p in ASSERTION for ln in lines):
        return "behavioral"
    return "unknown"


def failure_texts(output: str, tests: list[str]) -> dict[str, str]:
    """Per-test failure text, isolated EXACTLY or not at all.

    pytest: the ``FAILED <id>`` / ``ERROR <id>`` summary line for exactly that
    id, plus the ``____ <name> ____`` long-format section when that name is
    unique in the output (two files with the same test name would mix); go:
    the lines between ``=== RUN <Name>`` and ``--- FAIL: <Name>`` and ``-json``
    ``Output`` records for exactly that name. A test whose text cannot be
    isolated gets NO text -- its kind is ``unknown``, never the whole log."""
    out: dict[str, str] = {}
    lines = output.splitlines()
    header = re.compile(r"^_{3,} (.+?) _{3,}$")
    headers = [m.group(1) for ln in lines if (m := header.match(ln))]
    for t in tests:
        name = t.split("::")[-1]
        short = name.split("[")[0]
        chunks: list[str] = []
        summ = re.compile(r"^(FAILED|ERROR) " + re.escape(t) + r"(\s|$)")
        chunks += [ln for ln in lines if summ.match(ln)]
        hits = [h for h in headers if h in (name, short) or h.endswith("." + name)]
        if len(hits) == 1:
            for i, ln in enumerate(lines):
                m = header.match(ln)
                if m and m.group(1) == hits[0]:
                    j = i + 1
                    while j < len(lines) and not (header.match(lines[j])
                                                  or lines[j].startswith("====")):
                        j += 1
                    chunks.append("\n".join(lines[i:j]))
        for i, ln in enumerate(lines):
            if ln.strip() == f"=== RUN   {short}".strip() or ln.strip() == f"=== RUN {short}":
                j = i + 1
                while j < len(lines) and not re.match(
                        r"^\s*--- (FAIL|PASS|SKIP): " + re.escape(short) + r"(\s|$)", lines[j]):
                    j += 1
                chunks.append("\n".join(lines[i:j + 1]))
        for ln in lines:
            if ln.startswith("{"):
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if rec.get("Test") == short and rec.get("Output"):
                    chunks.append(rec["Output"])
        # Jest: "  ● Suite › name" headers, each block running to the next one.
        jest = [i for i, ln in enumerate(lines) if ln.strip().startswith("● ")]
        jhits = [i for i in jest if lines[i].strip()[2:] == name
                 or lines[i].strip().endswith("› " + name)]
        if len(jhits) == 1:
            i = jhits[0]
            nxt = [j for j in jest if j > i]
            end = nxt[0] if nxt else len(lines)
            chunks.append("\n".join(lines[i:end]))
        if chunks:
            out[t] = "\n".join(chunks)
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


def build_mutant(repo: Path, work_dir: Path, written: list[str],
                 declared: list[str], dest: Path) -> list[str]:
    """Create the mechanism-reverted mutant at ``dest``; return the reverted
    paths. Any git failure raises ``build_scope.GitError`` with git's stderr,
    which the caller records as "mutant unavailable" -- never as a verdict on
    the test."""
    from orchestrator.optimize.build import _in_allowlist, _nous_owned_prefixes
    from orchestrator.optimize.build_scope import _git

    _git(repo, "worktree", "add", "--detach", "--force", str(dest), "HEAD")
    tracked = set(_git(repo, "ls-files").splitlines())
    st = _git(repo, "status", "--porcelain=v1", "-z", "-uall", "--no-renames")
    owned = _nous_owned_prefixes(repo, work_dir)
    reverted = []
    for entry in st.split("\0"):
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


def build_mutant_clean(repo: Path, work_dir: Path, rec: dict, declared: list[str],
                       dest: Path) -> list[str]:
    """The mechanism-reverted mutant in the clean-checkout model: a worktree of
    the pre-build commit with ONLY the patch's test files and NEW files applied.
    Every pre-existing non-test file the patch edits stays at the base commit."""
    from orchestrator.optimize.build_scope import _git
    from orchestrator.optimize.clean_tree import PATCH

    base = rec["base_sha"]
    _git(repo, "worktree", "add", "--detach", "--force", str(dest), base)
    in_base = set(_git(repo, "ls-tree", "-r", "--name-only", base).splitlines())
    keep = [p for p in rec.get("touched") or [] if is_test_path(p, declared) or p not in in_base]
    reverted = sorted(p for p in rec.get("touched") or [] if p not in keep)
    patch = (Path(work_dir) / PATCH).resolve()
    if keep and patch.stat().st_size:
        _git(dest, "apply", "--binary", "--whitespace=nowarn",
             *[f"--include={p}" for p in keep], str(patch))
    return reverted


def remove_mutant(repo: Path, dest: Path) -> None:
    from orchestrator.optimize.build_scope import _git

    _git(repo, "worktree", "remove", "--force", str(dest), check=False)
    shutil.rmtree(dest, ignore_errors=True)
    _git(repo, "worktree", "prune", check=False)


def check(campaign: dict, work_dir: Path, factors, *, repo: Path | None,
          run_tests: Callable[[Path], tuple[dict, str | None]] | None,
          built_ids: set[str], records: dict | None = None) -> dict:
    """Evaluate oracle 2(d); write ``authored_tests.json``; return the record.
    Raises ``ValueError`` (the caller converts it to a gate failure) when a
    test lacks evidence and the oracle is not waived."""
    wd = Path(work_dir)
    pre = (records["pre_build_tests.json"] if records is not None
           else json.loads((wd / "pre_build_tests.json").read_text()))
    ran, passed = set(pre.get("ran") or ()), set(pre.get("passed") or ())
    kinds = dict(pre.get("failure_kinds") or {})
    tests = sorted({r["native_test"] for f in factors
                    if not built_ids or f.id in built_ids
                    for r in (f.relations or ())
                    if isinstance(r, dict) and r.get("kind") == "correctness"
                    and r.get("native_test")})
    evidence: dict[str, dict] = {}
    need_mutant = []
    preexisting_ok = bool(((campaign.get("optimization") or {}).get("build_checks")
                           or {}).get("allow_preexisting_tests"))
    for t in tests:
        if t in passed and preexisting_ok:
            # The author declared (build_checks.allow_preexisting_tests) that
            # these relations cover PRE-EXISTING behaviour; 2(b) honours that and
            # so does 2(d). Recorded, and listed in provenance.waivers.
            evidence[t] = {"evidence": "declared_preexisting_behaviour"}
        elif t in ran and t not in passed and kinds.get(t) == "behavioral":
            evidence[t] = {"evidence": "pre_build_behavioral_failure"}
        elif (t in ran and t not in passed and kinds.get(t, "unknown") == "unknown"
              and not pre.get("output_recorded")):
            # No test output exists to classify: the verdicts were INJECTED
            # (the unit-test seam), not produced by running the test command.
            # Accepted as 2(b) accepts it, and listed in provenance.waivers so
            # it never reads as classified.
            evidence[t] = {"evidence": "pre_build_failure_unclassified"}
        else:
            need_mutant.append(t)
    mutant_info: dict = {}
    if need_mutant:
        scope = wd / "build_scope.json"
        if records is not None:
            written = (records.get("build_scope.json") or {}).get("written")
        else:
            written = (json.loads(scope.read_text()).get("written") or []) if scope.exists() else None
        if repo is None or run_tests is None or written is None:
            mutant_info["unavailable"] = (
                "no git target, no test_command, or no record of what the build wrote")
        else:
            from orchestrator.optimize.build_scope import GitError

            scratch = wd / ".mutant-tmp"
            scratch.mkdir(exist_ok=True)
            dest = Path(tempfile.mkdtemp(prefix="nous-mutant-", dir=scratch)) / "tree"
            try:
                declared = [r["native_test"] for f in factors for r in (f.relations or ())
                            if isinstance(r, dict) and r.get("native_test")]
                try:
                    clean_rec = (records or {}).get("clean_tree.json")
                    reverted = (build_mutant_clean(Path(repo), wd, clean_rec, declared, dest)
                                if clean_rec else
                                build_mutant(Path(repo), wd, written, declared, dest))
                except GitError as exc:
                    reverted = None
                    mutant_info["unavailable"] = f"could not build the mutant: {exc}"
                if reverted is not None:
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
                shutil.rmtree(scratch, ignore_errors=True)
    for t in need_mutant:
        why_pre = ("did not exist before the build" if t not in ran
                   else "passed before the build" if t in passed
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
        elif k == "unknown":
            evidence[t] = {"evidence": None,
                           "why": f"{why_pre}, and against the mechanism-reverted "
                                  f"mutant it fails for a reason the classifier "
                                  f"cannot read as an assertion (no isolatable "
                                  f"failure text, a timeout, a crash): unclassifiable "
                                  f"is not evidence"}
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
