"""Validation gates for Nous artifacts.

Usage:
    python -m orchestrator.validate design --dir runs/iter-1/
    python -m orchestrator.validate execution --dir runs/iter-1/
    python -m orchestrator.validate meta-findings --dir <work_dir>/
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import jsonschema
import yaml

from orchestrator.optimize.design import is_tabulated, min_runs_for
from orchestrator.optimize.factors import is_refinable
from orchestrator.optimize.predicates import is_trivial

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def _load_yaml_schema(name: str) -> dict:
    return yaml.safe_load((SCHEMAS_DIR / name).read_text())


def _load_json_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


# Files that the orchestrator or agents are expected to write at iter_dir root.
# If you add a new root-level artifact, add it here — otherwise validation
# will flag it as an unexpected file.
_KNOWN_ROOT_FILES = {
    ".experiment_id",
    "problem.md", "bundle.yaml", "handoff_snapshot.md",
    "experiment_plan.yaml", "findings.json", "principle_updates.json",
    "design_log.md", "executor_log.md", "design_raw.md",
    "execute_analyze_output.json",
    "gate_summary_design.json", "gate_summary_findings.json",
    "gate_summary_continue.json",
    "human_feedback.json",
    # #188: provenance for `nous run --bundle <path>` (pre-authored
    # bundle, skips DESIGN dispatch).
    "bundle_manifest.json",
}


def _check_unexpected_files(
    iter_dir: Path,
    extra_allowed: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """Flag files at iter root that aren't known protocol artifacts.

    #199: ``extra_allowed`` is a per-campaign extension to the global
    ``_KNOWN_ROOT_FILES`` whitelist. Campaigns that need additional
    iter-root artifacts (e.g. paper-* needing ``analysis_summary.json``
    + ``manifest.json``) declare them via ``campaign.validation.iter_root_extensions``
    in the campaign YAML.
    """
    if not iter_dir.is_dir():
        return []
    allowed = _KNOWN_ROOT_FILES | set(extra_allowed)
    errors = []
    for f in iter_dir.iterdir():
        if f.is_dir():
            continue
        if f.name not in allowed:
            errors.append(
                f"unexpected file at iter root: {f.name} "
                f"(should be in inputs/ or results/)"
            )
    return errors


def _campaign_iter_root_extensions(campaign: dict | None) -> frozenset[str]:
    """Read ``campaign.validation.iter_root_extensions`` (#199).

    Returns an empty frozenset for campaigns that don't declare it (the
    common case — most campaigns are fine with the global whitelist).
    """
    if not campaign:
        return frozenset()
    validation = campaign.get("validation") or {}
    extensions = validation.get("iter_root_extensions") or []
    return frozenset(str(x) for x in extensions if x)


def _campaign_required_iter_root(campaign: dict | None) -> frozenset[str]:
    """Read ``campaign.validation.required_iter_root`` (#199 v2).

    Files declared here are treated as MUST-EXIST at validate_execution
    time. Required ⊆ allowed: a required file is also implicitly an
    iter-root extension, so campaigns don't need to list it twice.
    """
    if not campaign:
        return frozenset()
    validation = campaign.get("validation") or {}
    required = validation.get("required_iter_root") or []
    return frozenset(str(x) for x in required if x)


def _check_required_iter_root(
    iter_dir: Path, required: set[str] | frozenset[str],
) -> list[str]:
    """Return one error per required iter-root file that's missing.

    #199 v2: campaign.validation.required_iter_root declares files the
    campaign promises to produce by EXECUTE_ANALYZE end. Missing entries
    are surfaced with a clear "required iter-root file missing: X"
    message so the operator (or a future incomplete-iteration diagnostic
    in the spirit of #187 / #200) sees what the campaign committed to.
    """
    errors: list[str] = []
    if not iter_dir.is_dir():
        return errors
    for name in sorted(required):
        if not (iter_dir / name).exists():
            errors.append(f"required iter-root file missing: {name}")
    return errors


def _validate_ground_truth_independence(bundle: dict) -> list[str]:
    """Cross-field check that the ground truth can disagree with the detector (issue #85).

    Returns a list of strings:
      * Plain strings are HARD ERRORS (validator fails).
      * Strings starting with "WARN:" are advisory (validator passes
        but surfaces the warning to the human gate).

    The four tautological-campaign failure mode (#84) is caught when an
    author either (a) self-declares ``shares_computation_with_detector: true``
    or (b) omits the ``ground_truth`` block entirely while testing a
    detector — the schema can't enforce (b) without breaking legacy
    bundles, so the absence of the block is silently allowed for now.
    """
    errors: list[str] = []
    gt = bundle.get("ground_truth")
    if not isinstance(gt, dict):
        return errors  # legacy bundles validate unchanged

    if gt.get("shares_computation_with_detector") is True:
        errors.append(
            "ground_truth.shares_computation_with_detector=true: the "
            "experiment is tautological by construction (the ground "
            "truth uses the same computation as the detector under test). "
            "Choose an independent ground truth — see issue #85."
        )
        return errors  # no point in further checks if the design is broken

    if not gt.get("independence_argument"):
        errors.append(
            "WARN: ground_truth.independence_argument is missing. Provide "
            "a plain-English justification that the ground truth can "
            "disagree with the detector — required to defend the "
            "experiment at the design gate."
        )

    mt = gt.get("measurement_type")
    dmt = gt.get("detector_measurement_type")
    if mt and dmt and mt == dmt:
        errors.append(
            f"WARN: ground_truth.measurement_type ({mt!r}) equals "
            f"detector_measurement_type ({dmt!r}); they may secretly "
            f"measure the same physical signal. Re-check the "
            f"independence_argument."
        )

    return errors


def validate_principles_have_empirical_content(
    principles: list[dict],
) -> list[str]:
    """Return WARN strings for category=domain principles missing #86 fields.

    Issue #179: even after the deterministic classifier
    (``orchestrator.principles_classifier``) runs, some principles
    will have a statement too neutral for the heuristic to classify.
    This validator surfaces those residuals so the human can act on
    them at the design gate or in the report.

    Meta-category principles (constraint principles emitted by
    ``orchestrator.refute_constraints`` per #169) are exempt — they're
    orchestrator-emitted facts, not LLM-extracted observations, and
    the empirical/algebraic distinction doesn't apply to them.

    Returned strings are advisory (``WARN:`` prefix); they don't fail
    validation. Callers may surface them via the design-gate summary
    or via a campaign-end report.
    """
    if not isinstance(principles, list):
        return []
    warnings: list[str] = []
    for i, p in enumerate(principles):
        if not isinstance(p, dict):
            continue
        if p.get("category") == "meta":
            continue
        if p.get("empirical_content") is None or p.get("derivation_type") is None:
            pid = p.get("id", f"principles[{i}]")
            warnings.append(
                f"WARN: principle {pid} has unset empirical_content / "
                f"derivation_type (issue #86). The classifier (#179) "
                f"could not infer the fields from the statement. Add "
                f"explicit empirical_content + derivation_type to the "
                f"principle, or refine the statement so it cites either "
                f"a concrete measurement (empirical) or an algebraic / "
                f"definitional marker (e.g. 'iff', 'theorem', "
                f"'by definition')."
            )
    return warnings


def campaign_kind(campaign: dict) -> str:
    """Return ``campaign.get("kind")`` normalized to its schema default.

    ``"reflective"`` is returned for both an absent ``kind`` and an
    explicit ``kind: reflective`` -- the schema default means the two
    are indistinguishable in behavior, so callers should treat them
    identically rather than branching on presence.
    """
    return campaign.get("kind") or "reflective"


def _rule1_kind_optimization_block(campaign: dict) -> list[str]:
    """Rule 1: kind: optimization requires an optimization block;
    kind: reflective (or absent) forbids one."""
    kind = campaign_kind(campaign)
    has_block = "optimization" in campaign
    if kind == "optimization" and not has_block:
        return [
            "kind: optimization requires a top-level 'optimization' block "
            "(response, factors, design). Add one -- see "
            "docs/optimization-campaign-guide.md -- or set kind: reflective "
            "if this campaign doesn't need a pre-registered design matrix."
        ]
    if kind == "reflective" and has_block:
        return [
            "an 'optimization' block is present but kind is reflective "
            "(or absent, which defaults to reflective). Either add "
            "'kind: optimization' to activate it, or remove the "
            "'optimization' block if this campaign is meant to run the "
            "reflective flow."
        ]
    return []


def _norm_metric(name: object) -> str | None:
    """Fold a metric/observable name for **comparison only**.

    Two spellings that differ only by leading/trailing whitespace or
    letter case are the same metric to a human author, even though the
    runtime resolves metric names by exact string match. Comparing the
    normalized forms lets rule 2 catch that intent; the declared strings
    themselves are never rewritten -- doing so would break the exact-match
    resolution the campaign runs under.
    """
    if not isinstance(name, str):
        return None
    return name.strip().lower()


def _rule2_held_out_leakage(opt: dict) -> list[str]:
    """Rule 2: a held_out metric must not equal response.primary.metric
    nor appear in constraints/regimes -- the leakage guard that prevents
    a campaign from optimizing against its own generalization check.

    Comparisons are case/whitespace-insensitive (see _norm_metric) so a
    held_out entry that differs from the colliding name only by spelling
    (" throughput_gbps" vs "throughput_gbps", "OOS" vs "oos") still trips
    the guard -- the author meant the same metric in both places, and a
    silent pass here would be worse than a false positive."""
    response = opt.get("response") or {}
    held_out = response.get("held_out") or []
    if not held_out:
        return []
    errors: list[str] = []
    primary_metric = (response.get("primary") or {}).get("metric")
    primary_norm = _norm_metric(primary_metric)
    for metric in held_out:
        metric_norm = _norm_metric(metric)
        if primary_norm and metric_norm == primary_norm:
            errors.append(
                f"response.held_out contains {metric!r}, which collides "
                f"with response.primary.metric {primary_metric!r} (same "
                f"metric name, ignoring case/whitespace) -- this is data "
                f"leakage (the holdout-selection failure class): a "
                f"held_out metric must never be an input the design matrix "
                f"fits against. Choose a different held_out metric, or fit "
                f"on a different primary metric. If the two spellings were "
                f"meant to be different metrics, make them unambiguously "
                f"distinct."
            )
        for constraint in response.get("constraints") or []:
            cmetric = constraint.get("metric") or constraint.get("observable")
            if _norm_metric(cmetric) == metric_norm:
                errors.append(
                    f"response.held_out contains {metric!r}, which collides "
                    f"with {cmetric!r} in response.constraints (same "
                    f"metric name, ignoring case/whitespace) -- this is "
                    f"data leakage: a held_out metric must never feed "
                    f"fitting (constraints exclude configs from fitting, "
                    f"but the metric itself must stay unobserved until "
                    f"confirm). Remove {cmetric!r} from constraints or "
                    f"{metric!r} from held_out."
                )
        for regime in response.get("regimes") or []:
            rmetric = regime.get("metric") or regime.get("observable")
            if _norm_metric(rmetric) == metric_norm:
                errors.append(
                    f"response.held_out contains {metric!r}, which collides "
                    f"with {rmetric!r} in response.regimes (same metric "
                    f"name, ignoring case/whitespace) -- this is data "
                    f"leakage: a held_out metric must never feed fitting. "
                    f"Remove {rmetric!r} from regimes or {metric!r} from "
                    f"held_out."
                )
    return errors


def _rule3_screen_levels_membership(factors: list[dict]) -> list[str]:
    """Rule 3: every screen_levels entry must be a member of that
    factor's levels."""
    errors: list[str] = []
    for factor in factors:
        fid = factor.get("id", "<unknown>")
        screen_levels = factor.get("screen_levels")
        if screen_levels is None:
            continue
        levels = factor.get("levels") or []
        missing = [lvl for lvl in screen_levels if lvl not in levels]
        if missing:
            errors.append(
                f"factor {fid!r}: screen_levels {missing!r} are not "
                f"members of levels {list(levels)!r}. screen_levels must "
                f"name two of the factor's own declared levels."
            )
    return errors


class _RawFactorView:
    """Minimal shim exposing ``.type`` / ``.levels`` so raw campaign-dict
    factors (pre-``parse_factors``) can be checked with the same
    ``is_refinable`` predicate ``orchestrator.optimize.factors`` uses for
    parsed ``Factor`` objects -- one definition of "refinable", not two."""

    __slots__ = ("type", "levels")

    def __init__(self, factor: dict):
        self.type = factor.get("type")
        self.levels = tuple(factor.get("levels") or ())


def _dict_is_refinable(factor: dict) -> bool:
    return is_refinable(_RawFactorView(factor))


def _rule4_refine_needs_two_refinable_factors(
    design: dict, factors: list[dict],
) -> list[str]:
    """Rule 4: refine.kind requires >=2 factors satisfying is_refinable
    (numeric with more than 2 levels)."""
    if not isinstance(design, dict) or "refine" not in design:
        return []
    refinable = sum(1 for factor in factors if _dict_is_refinable(factor))
    if refinable >= 2:
        return []
    return [
        f"design.refine is set but only {refinable} factor(s) are "
        f"refinable (numeric with > 2 levels); refine needs >= 2. Either "
        f"drop design.refine (skip straight to confirm at the winning "
        f"corner), or add levels to a second numeric factor so refine has "
        f"a surface with curvature to fit."
    ]


def _rule11_build_stage_position(opt: dict) -> list[str]:
    """Rule 11: ``build``, if present, must be the first stage and appear once.

    ``build`` authors the mechanism the other stages measure. Placing it after
    ``verify`` means verify gates code that does not exist yet and aborts the
    campaign; placing it after ``screen`` means the screen measured the OLD
    mechanism and its effect table describes a system the campaign then
    replaced. Both fail in ways that still produce schema-valid artifacts,
    which is exactly the class of error worth rejecting up front.
    """
    stages = opt.get("stages")
    if not isinstance(stages, list) or not stages:
        return []
    names = [str(getattr(s, "value", s)) for s in stages]
    count = names.count("build")
    if count == 0:
        return []
    errors: list[str] = []
    if count > 1:
        errors.append(
            f"optimization.stages lists 'build' {count} times. The build stage "
            f"spends an agent call authoring the mechanism; running it again "
            f"would re-author code that later stages already measured. Keep a "
            f"single 'build' as the first stage.",
        )
    if names[0] != "build":
        errors.append(
            f"optimization.stages has 'build' at position {names.index('build') + 1} "
            f"(stages: {names}). 'build' must come FIRST: it authors the "
            f"mechanism that every later stage measures. Behind 'verify' it "
            f"aborts the campaign (verify gates tests for code that does not "
            f"exist yet); behind 'screen' the screen measures the old mechanism "
            f"and reports an effect table for a system the campaign replaced. "
            f"Reorder to {['build'] + [n for n in names if n != 'build']}.",
        )
    return errors


#: Source extensions a declared ``native_test`` path may name. Used to tell a
#: path-style locator from a bare identifier -- not to restrict what a target
#: may be written in (an unrecognised extension falls through to the
#: "could not check" branch rather than being dropped).
_TEST_SOURCE_SUFFIXES = (".go", ".py", ".rs", ".ts", ".js", ".java", ".kt",
                         ".rb", ".cc", ".cpp", ".c", ".cs", ".scala", ".swift")

#: Flags by which a command-style locator selects one test. ``go test -run``
#: and ``pytest -k`` are the two the runner's own output parsers were built
#: against; the rest are the same idea in other runners.
_TEST_SELECTOR_FLAGS = ("-run", "-k", "--run", "--test", "-t", "--filter",
                        "--gtest_filter", "--name")

#: A bare test identifier: what `go test -v` prints after ``--- PASS:`` and
#: what pytest prints as a node's trailing name. This is the style the Go
#: result parser matches on, and the one rule 12 used to skip silently.
_BARE_TEST_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _native_test_identifier(declared: str) -> tuple[str, str | None]:
    """Classify a ``native_test`` locator into ``(kind, subject)``.

    ``kind`` is one of:

    ``path``
        ``a/b.py::test_foo`` or ``pkg/file_test.go`` -- ``subject`` is the
        repo-relative path, checked for existence.
    ``ident``
        ``TestFoo`` / ``test_foo``, possibly extracted from behind a
        command-style selector flag (``go test ./pkg -run TestFoo``,
        ``pytest -k test_foo``) -- ``subject`` is the identifier, checked for
        a definition anywhere in the tree.
    ``unknown``
        anything else -- ``subject`` is None, and the caller must say so out
        loud rather than skip it. The silence was the original defect: an
        author could not tell "checked and fine" from "could not check".

    A parametrization suffix is stripped before the identifier is matched
    (``test_x[0.95-1.05]``, ``TestX/case_name``), mirroring
    ``runner.match_declared_tests``, so the bare function name is what gets
    looked for -- the same aggregation rule the contract check applies.
    """
    head = declared.split("::", 1)[0].strip()
    # A path is a SINGLE token: whitespace means this is a command line, and
    # `make check && ./scripts/verify.sh --all` would otherwise be mistaken for
    # a path (its head contains both a '/' and a '.') and reported as a missing
    # file rather than as un-checkable.
    if not any(c.isspace() for c in head) and (
        head.endswith(_TEST_SOURCE_SUFFIXES) or ("/" in head and "." in head)
    ):
        return "path", head

    def _strip_cases(name: str) -> str:
        return name.split("[", 1)[0].split("/", 1)[0]

    if _BARE_TEST_IDENT.match(_strip_cases(declared.strip())):
        return "ident", _strip_cases(declared.strip())

    # Command-style: find a selector flag and take its argument. Both
    # `-run TestFoo` and `-run=TestFoo` spellings are accepted.
    import shlex

    try:
        tokens = shlex.split(declared)
    except ValueError:
        return "unknown", None
    for i, tok in enumerate(tokens):
        flag, _, inline = tok.partition("=")
        if flag not in _TEST_SELECTOR_FLAGS:
            continue
        arg = inline or (tokens[i + 1] if i + 1 < len(tokens) else "")
        # A selector is a regex in Go and a substring expression in pytest, so
        # strip the anchors an author may have typed before matching.
        arg = _strip_cases(arg.strip().strip("^$"))
        if _BARE_TEST_IDENT.match(arg):
            return "ident", arg
        return "unknown", None
    return "unknown", None


def _identifier_is_defined(repo: Path, ident: str) -> bool:
    """Is ``ident`` defined as a test somewhere under ``repo``?

    Grep-shaped on purpose: a bare identifier carries no path, so the only
    thing that can be checked is whether the tree defines it at all. Matching
    a DEFINITION (``func TestFoo``, ``def test_foo``) rather than a bare
    mention keeps a call site or a comment from vouching for a test that does
    not exist.
    """
    pattern = re.compile(
        r"(?:func|def|fn|it|test|describe)\s*\(?\s*['\"]?" + re.escape(ident)
        + r"\b",
    )
    skip = {".git", "node_modules", "vendor", "target", "__pycache__",
            ".venv", "venv", "build", "dist", ".nous", ".nous-experiments"}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.endswith(_TEST_SOURCE_SUFFIXES):
                continue
            try:
                text = (Path(root) / name).read_text(errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                return True
    return False


def _rule12_missing_native_tests_need_build(
    campaign: dict, opt: dict, factors: list[dict],
) -> list[str]:
    """Rule 12: warn when a declared ``native_test`` cannot be found and no
    ``build`` stage exists to author it.

    ``relations.reconcile`` is fail-closed: a declared test that did not
    execute is a FAILED correctness relation, which aborts at verify. So a
    campaign naming tests that do not exist yet, with no build stage, is
    guaranteed to abort -- but only after a real run. Checking the locators
    here turns that into an authoring-time message.

    The rule handles the locator styles the RUNNER actually supports, not just
    the pytest-style ``path::test`` one. Before this it extracted a path and
    skipped anything without a source extension, which meant a bare Go test
    name -- precisely what ``runner.match_declared_tests`` matches on, and what
    ``--- PASS: TestName`` output is parsed into -- was silently ignored. A real
    campaign declaring bare Go test names with no ``build`` stage validated at
    0 errors / 0 warnings and aborted at verify after a full run.

    An un-checkable locator gets its own WARNING saying so. The silence WAS the
    defect: an author must be able to tell "checked and fine" from "could not
    check" from the output alone.

    A WARNING rather than an error throughout: the check is heuristic (a test
    can legitimately live somewhere the declared locator does not literally
    name -- a helper file, a generated suite, a build-tagged file), and a false
    hard-fail is worse than a false warning.
    """
    repo = (campaign.get("target_system") or {}).get("repo_path")
    if not repo or not Path(repo).is_dir():
        return []
    stages = opt.get("stages")
    names = (
        [str(getattr(s, "value", s)) for s in stages]
        if isinstance(stages, list) else []
    )
    if "build" in names:
        return []  # the campaign intends to author them

    declared_all: list[str] = []
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        for rel in factor.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            declared = rel.get("native_test")
            if isinstance(declared, str) and declared:
                declared_all.append(declared)

    missing: list[str] = []
    unknown: list[str] = []
    # A command-style locator that RESOLVES here can still fail the contract
    # check: `runner.match_declared_tests` matches on trailing identifiers and
    # never parses a command line, so `go test ./pkg -run TestFoo` passes this
    # rule and is then reported as "declared but not executed" by the fail-closed
    # reconcile. Endorsing a locator that verify will reject is worse than the
    # silence this rule was fixed to remove, so it is called out explicitly.
    command_style: list[str] = []
    # Definitions are looked up once per distinct identifier: the walk is over
    # the whole target tree, and a campaign routinely declares the same test
    # against several factors.
    defined: dict[str, bool] = {}
    for declared in declared_all:
        kind, subject = _native_test_identifier(declared)
        if kind == "path":
            if not (Path(repo) / str(subject)).exists():
                missing.append(declared)
        elif kind == "ident":
            if subject not in defined:
                defined[str(subject)] = _identifier_is_defined(
                    Path(repo), str(subject),
                )
            if not defined[str(subject)]:
                missing.append(declared)
        else:
            unknown.append(declared)
        if kind == "ident" and any(c.isspace() for c in declared.strip()):
            command_style.append(declared)

    out: list[str] = []
    if missing:
        uniq = sorted(set(missing))
        shown = ", ".join(uniq[:4])
        more = "" if len(uniq) <= 4 else f" (+{len(uniq) - 4} more)"
        out.append(
            f"WARN: {len(uniq)} declared native_test(s) could not be found in "
            f"the target repo: {shown}{more}. A path-style locator was checked "
            f"for the file's existence; a bare or selector-style identifier was "
            f"checked for a definition (func/def) anywhere under the target. A "
            f"declared test that does not run counts as a FAILED correctness "
            f"relation, so this campaign will abort at verify. If the mechanism "
            f"and its tests still need to be written, add 'build' as the first "
            f"entry in optimization.stages so a single agent call authors them "
            f"before verify gates them. If the tests exist under a different "
            f"name, correct the native_test locator.",
        )
    if command_style:
        uniq = sorted(set(command_style))
        shown = ", ".join(uniq[:3])
        more = "" if len(uniq) <= 3 else f" (+{len(uniq) - 3} more)"
        out.append(
            f"WARN: {len(uniq)} native_test locator(s) are COMMAND-STYLE: "
            f"{shown}{more}. This rule can resolve them, but the contract check "
            f"(runner.match_declared_tests) matches on trailing test identifiers "
            f"and does not parse a command line — so the relation will be "
            f"reported as 'declared but not executed' and fail closed at verify. "
            f"Declare the bare test identifier instead (e.g. 'TestFoo' rather "
            f"than 'go test ./pkg -run TestFoo'); the test_command still selects "
            f"which tests run.",
        )
    if unknown:
        uniq = sorted(set(unknown))
        shown = ", ".join(repr(u) for u in uniq[:4])
        more = "" if len(uniq) <= 4 else f" (+{len(uniq) - 4} more)"
        out.append(
            f"WARN: {len(uniq)} declared native_test(s) could not be checked "
            f"for existence, because the locator is neither a path "
            f"(a/b_test.go, a/b.py::test_x), a bare test identifier (TestFoo, "
            f"test_foo), nor a command with a recognised selector flag "
            f"({', '.join(_TEST_SELECTOR_FLAGS[:3])}...): {shown}{more}. This is "
            f"reported rather than skipped so that silence here never reads as "
            f"'checked and fine'. Run `nous validate campaign FILE --smoke` to "
            f"execute test_command and see which declared identifiers it "
            f"actually reports, or restate the locator in one of the checkable "
            f"forms.",
        )
    return out


def _rule5_correctness_relation_required(factors: list[dict]) -> list[str]:
    """Rule 5: each factor needs >=1 correctness relation.

    parse_factors (orchestrator.optimize.factors) enforces this for
    already-parsed Factor objects; this checks the raw campaign dict so
    the campaign-authoring gate catches it before any parse is attempted.
    """
    errors: list[str] = []
    for factor in factors:
        fid = factor.get("id", "<unknown>")
        relations = factor.get("relations") or []
        if not any(
            isinstance(r, dict) and r.get("kind") == "correctness"
            for r in relations
        ):
            errors.append(
                f"factor {fid!r} has no relation with kind: correctness. "
                f"A 'behavioral' relation alone is not enough -- "
                f"behavioral violations are recorded as findings and "
                f"never fail the campaign, so nothing would catch a "
                f"broken lever. Add at least one correctness relation "
                f"(e.g. 'baseline level reproduces the recorded baseline "
                f"run within noise')."
            )
    return errors


def _rule6_no_trivial_predicates(opt: dict, factors: list[dict]) -> list[str]:
    """Rule 6: no manipulation or invariant predicate may be trivially
    true (predicates.is_trivial)."""
    errors: list[str] = []
    for factor in factors:
        fid = factor.get("id", "<unknown>")
        man = factor.get("manipulation")
        if isinstance(man, dict) and is_trivial(man):
            errors.append(
                f"factor {fid!r}: manipulation predicate "
                f"{{op: {man.get('op')!r}, value: {man.get('value')!r}}} "
                f"is trivially true -- it cannot meaningfully fail, so it "
                f"manufactures false confidence that the lever engaged. "
                f"Tighten it to a check that a broken lever would "
                f"actually fail (e.g. compare against the interpolated "
                f"'{{level}}' value rather than a bare > 0 / != null)."
            )
    design_space = opt.get("design_space") or {}
    for inv in design_space.get("invariants") or []:
        if isinstance(inv, dict) and is_trivial(inv):
            errors.append(
                f"design_space.invariants entry {inv.get('id', '<unknown>')!r}: "
                f"predicate {{op: {inv.get('op')!r}, value: {inv.get('value')!r}}} "
                f"is trivially true -- it cannot meaningfully fail, so it "
                f"manufactures false confidence that the campaign stayed "
                f"inside its declared design space. Tighten it to a check "
                f"a real violation would actually fail."
            )
    return errors


def _rule7_low_resolution_screen_warning(
    design: dict, factors: list[dict],
) -> list[str]:
    """Rule 7 (WARNING): design.screen.resolution < 5 with > 1 factor --
    main-effects-only screening is the OFAT failure mode in disguise.
    Does not block; names the aliased pairs so an author can consciously
    accept resolution IV/III."""
    screen = (design or {}).get("screen") or {}
    resolution = screen.get("resolution")
    if not isinstance(resolution, int) or resolution >= 5:
        return []
    if len(factors) <= 1:
        return []
    try:
        from orchestrator.optimize.design import fractional_factorial

        ids = tuple(f.get("id", f"F{i}") for i, f in enumerate(factors))
        design_obj = fractional_factorial(ids, resolution)
        pairs = design_obj.generators and _alias_pairs_safe(design_obj)
    except Exception:
        pairs = None
    if pairs:
        pair_text = ", ".join(f"{a}~{b}" for a, b in pairs)
        detail = f" Aliased pairs: {pair_text}."
    else:
        detail = ""
    return [
        f"WARN: design.screen.resolution={resolution} with "
        f"{len(factors)} factors aliases two-factor interactions onto "
        f"other effects.{detail} Main-effects-only (or partially-"
        f"confounded) screening is the one-factor-at-a-time failure mode "
        f"in disguise -- a real campaign's headline finding was an "
        f"interaction that a resolution-{resolution} screen would have "
        f"inverted. Consider resolution: 5 unless you have a specific "
        f"reason to accept this aliasing."
    ]


def _alias_pairs_safe(design_obj) -> list[tuple[str, str]]:
    from orchestrator.optimize.design import alias_pairs

    return alias_pairs(design_obj)


def _rule8_resolution_run_budget(design: dict, factors: list[dict]) -> list[str]:
    """Rule 8 (corrected, see task-10 brief): min_runs_for's fallback of
    2**k for an untabulated (k, resolution) pair is a conservative UPPER
    BOUND, not a true minimum -- comparing it against max_runs would
    falsely reject a run budget that a real (untabulated) design could
    satisfy. So:

      * tabulated (k, resolution): compare the exact minimum against
        max_runs, error with the two honest options if it's exceeded.
      * untabulated (k, resolution) where the 2**k full factorial FITS
        max_runs: feasible, no error. The full factorial aliases nothing,
        so it achieves any requested resolution, and stage_runner falls
        back to it -- erroring would reject a campaign the runner runs.
      * untabulated (k, resolution) where 2**k does NOT fit: a distinct
        error saying Nous cannot certify a design within the budget,
        offering the full factorial's cost or fewer factors -- and noting
        2**k is an upper bound on the minimum, so a smaller untabulated
        design may exist that Nous cannot name.
    """
    if not isinstance(design, dict):
        return []
    max_runs = design.get("max_runs")
    if max_runs is None:
        return []
    screen = design.get("screen") or {}
    resolution = screen.get("resolution")
    if not isinstance(resolution, int):
        return []
    k = len(factors)
    if k == 0:
        return []
    tabulated = is_tabulated(k, resolution)
    if tabulated:
        required = min_runs_for(k, resolution)
        if required <= max_runs:
            return []
        return [
            f"design.screen.resolution={resolution} over {k} factors "
            f"needs {required} runs, but design.max_runs={max_runs} is "
            f"lower. Two honest options: (1) raise max_runs to >= "
            f"{required}, or (2) accept a lower resolution and its named "
            f"aliasing (see the resolution-{resolution - 1} generator's "
            f"alias_pairs) that fits within {max_runs} runs. Nous will "
            f"not silently downgrade resolution to fit the budget."
        ]
    # Untabulated. The 2**k full factorial ALWAYS achieves the requested
    # resolution, because it aliases nothing at all -- verified: k=2,3,4
    # each give alias_pairs() == []. So when 2**k fits the budget the
    # campaign is feasible and needs no error: that is exactly what
    # stage_runner._build_design does, falling back to the full factorial
    # for an untabulated combination. Erroring here would reject a campaign
    # the runner executes correctly, which is why the small examples in
    # docs/optimization-campaign-guide.md initially could not declare
    # max_runs at all.
    #
    # What remains true, and is why this branch is still distinct from the
    # tabulated one: 2**k is an upper bound on the MINIMUM, so a smaller
    # untabulated fractional design may exist and Nous cannot name it. That
    # matters only when 2**k does NOT fit -- then the honest answer is that
    # Nous cannot certify a design within the budget, not that none exists.
    full_factorial_runs = 2 ** k
    if full_factorial_runs <= max_runs:
        return []
    return [
        f"design.screen.resolution={resolution} is not a tabulated "
        f"design for {k} factors -- Nous has no published generator for "
        f"this (factor count, resolution) combination, so it cannot "
        f"certify a design for it, and it cannot say how many runs it "
        f"actually needs -- do NOT assume the {full_factorial_runs}-run "
        f"full-factorial fallback is the true minimum. Options: (1) use "
        f"the full factorial at {full_factorial_runs} runs (guaranteed "
        f"correct, no aliasing), or (2) reduce the factor count to a "
        f"tabulated combination."
    ]


def _rule9_no_complexity_tier_under_optimization(
    campaign: dict, opt: dict,
) -> list[str]:
    """Rule 9: complexity_tier / tier_justification present under
    kind: optimization is an error -- the #159 tier ladder is scoped to
    the reflective kind, and a pre-registered design matrix already
    strengthens the anti-p-hacking property the ladder protects, so the
    two disciplines must not be half-adopted together.

    Checks every location orchestrator.complexity_tier._read_bundle_tier /
    _read_bundle_justification resolve tier fields from: ``metadata``
    (canonical since #206) and the legacy top level. ``optimization`` is
    also checked for symmetry with earlier drafts of this rule, though
    neither location's own schema currently permits these keys there.
    Checking only one location would leave the other as a silent bypass
    for an author following #206's own documented convention.
    """
    errors: list[str] = []
    metadata = campaign.get("metadata")
    locations: list[tuple[str, dict]] = [("optimization", opt)]
    if isinstance(metadata, dict):
        locations.append(("metadata", metadata))
    locations.append(("top level", campaign))
    for field in ("complexity_tier", "tier_justification"):
        for location_name, container in locations:
            if field in container:
                where = (
                    f"optimization.{field}" if location_name == "optimization"
                    else f"metadata.{field}" if location_name == "metadata"
                    else f"{field} (top level)"
                )
                errors.append(
                    f"{where} is set, but the #159 graded-complexity tier "
                    f"ladder is scoped to kind: reflective only (see design "
                    f"spec §7.2). A pre-registered design matrix already "
                    f"strengthens the anti-p-hacking property the ladder "
                    f"protects, so the two disciplines must not be "
                    f"half-adopted together. Remove {field!r} from "
                    f"{location_name} -- this campaign is kind: "
                    f"optimization, so no tier field belongs anywhere on it."
                )
    return errors


def _rule10_uncontrolled_knob_warning(campaign: dict, opt: dict) -> list[str]:
    """Rule 10 (WARNING): a knob in target_system.controllable_knobs
    appearing in neither factors nor locked_parameters -- the "what did
    you forget to control" check."""
    target_system = campaign.get("target_system") or {}
    knobs = target_system.get("controllable_knobs") or []
    if not knobs:
        return []
    factor_names = set()
    for factor in opt.get("factors") or []:
        if factor.get("id"):
            factor_names.add(factor["id"])
        if factor.get("name"):
            factor_names.add(factor["name"])
    locked = campaign.get("locked_parameters") or {}
    locked_keys = set(locked) if isinstance(locked, dict) else set()
    warnings: list[str] = []
    for knob in knobs:
        if knob in factor_names or knob in locked_keys:
            continue
        warnings.append(
            f"WARN: target_system.controllable_knobs includes {knob!r}, "
            f"which appears in neither optimization.factors nor "
            f"locked_parameters. Either declare it as a factor (if the "
            f"campaign should vary it), add it to locked_parameters (if "
            f"it must stay pinned), or remove it from controllable_knobs "
            f"if it's out of scope for this campaign."
        )
    return warnings


def _rule13_known_valid_baseline(opt: dict, factors: list[dict]) -> list[str]:
    """Rule 13: ``known_valid_baseline`` must be a configuration the campaign
    is allowed to run.

    It is the bottom rung of the report's fallback ladder (spec §3.6) and the
    shortlist's last-resort finalist, so it is reached exactly when nothing
    else survived — the worst possible moment to discover it names a factor
    that does not exist or a level the author never declared runnable. Both
    failures are silent at that point: ``matrix.render_apply`` skips ids it does
    not recognise, so an unknown id simply drops its flag from the command line,
    and an out-of-range level is a configuration the target was never promised
    would work.

    Numerics are compared with a tolerance, matching
    ``matrix.check_fidelity``: a baseline of ``2.0`` against a declared level of
    ``2`` is the same configuration, and rejecting it would fail a campaign for
    a YAML representation choice.
    """
    baseline = opt.get("known_valid_baseline")
    if baseline is None:
        return []
    if not isinstance(baseline, dict) or not baseline:
        return [
            "optimization.known_valid_baseline must be a non-empty mapping of "
            "factor id -> level (e.g. {QUEUES: 2, BATCHING: off}). It is the "
            "configuration report.json returns when nothing measured survives, "
            "so an empty one leaves the campaign with nothing legal to return."
        ]
    by_id = {f.get("id"): f for f in factors if f.get("id")}
    errors: list[str] = []
    for fid, level in baseline.items():
        factor = by_id.get(fid)
        if factor is None:
            errors.append(
                f"optimization.known_valid_baseline names factor {fid!r}, which "
                f"is not a declared factor (declared: {sorted(by_id)!r}). An "
                f"unrecognised id renders no flag at all, so the baseline would "
                f"silently run with that knob at whatever the target defaults "
                f"to. Fix the id, or drop the entry if the knob is not a factor."
            )
            continue
        levels = list(factor.get("levels") or [])
        if any(_levels_equal(level, declared) for declared in levels):
            continue
        errors.append(
            f"optimization.known_valid_baseline sets factor {fid!r} to "
            f"{level!r}, which is not one of its declared levels {levels!r}. The "
            f"baseline must be a configuration inside the declared design space "
            f"— it is what the campaign falls back to when nothing else is "
            f"valid, and a level the author never declared runnable is not a "
            f"safe answer. Either use a declared level, or add {level!r} to the "
            f"factor's levels if the target really supports it."
        )
    return errors


def _levels_equal(a, b) -> bool:
    """Level equality with numeric tolerance; exact for anything else."""
    import math

    if (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and not isinstance(a, bool) and not isinstance(b, bool)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _rule14_policy_ranges(opt: dict) -> list[str]:
    """Rule 14: the ``policy`` block's registered numbers must be usable.

    These are the decision parameters the compiled epoch runs on, and every
    failure below produces a campaign that executes without complaint while
    meaning something other than what the author wrote:

    * ``delta_* <= 0`` makes the t-quantile infinite, so no bound is ever below
      epsilon and nothing can certify;
    * ``delta_* > 0.5`` is a one-sided "bound" that is below the point estimate
      — it would certify a challenger that is measurably AHEAD;
    * an ``epsilon`` with both ``abs`` and ``pct`` silently ignores ``pct``
      (``resolve_epsilon`` prefers ``abs``), so a campaign declaring both has
      one of its two stated thresholds quietly discarded;
    * an ``epsilon`` with neither falls to the ``pct: 2.0`` default, which is
      probably right but is not what an author who wrote an empty block meant
      to say;
    * ``confirm_max_rounds < 1`` registers a self-looping state that may never
      run, and the compiled guard ``round >= max_rounds`` would then fire on
      the FIRST round of a stage the author asked to loop.
    """
    pol = opt.get("policy")
    if pol is None:
        return []
    if not isinstance(pol, dict):
        return ["optimization.policy must be a mapping (epsilon, delta_screen, "
                "delta_terminal, confirm_max_rounds)."]
    errors: list[str] = []
    for key in ("delta_screen", "delta_terminal"):
        if key not in pol:
            continue
        raw = pol[key]
        try:
            val = float(raw)
        except (TypeError, ValueError):
            errors.append(
                f"optimization.policy.{key} is {raw!r}, which is not a number. "
                f"It is an error budget in (0, 0.5]; 0.05 is the default."
            )
            continue
        if not (0.0 < val <= 0.5):
            errors.append(
                f"optimization.policy.{key}={val!r} is outside (0, 0.5]. At or "
                f"below 0 the one-sided t-quantile is infinite and nothing can "
                f"ever certify; above 0.5 the 'upper bound' falls below the "
                f"point estimate, so the campaign would certify a challenger it "
                f"measured as ahead. Use 0.05 (the default) or another value in "
                f"(0, 0.5]."
            )
    eps = pol.get("epsilon")
    if eps is not None:
        if not isinstance(eps, dict):
            errors.append(
                "optimization.policy.epsilon must be a mapping with exactly one "
                "of abs (metric units) or pct (percent of the recommendation's "
                "value), e.g. {pct: 2.0}."
            )
        else:
            has = [k for k in ("abs", "pct") if k in eps]
            if len(has) != 1:
                errors.append(
                    f"optimization.policy.epsilon declares {has or 'neither'} of "
                    f"abs/pct; it must declare EXACTLY ONE. With both, "
                    f"resolve_epsilon uses abs and silently discards pct — one "
                    f"of the two thresholds you wrote would never apply. With "
                    f"neither, the indifference width falls to the pct: 2.0 "
                    f"default rather than to anything you stated."
                )
    if "confirm_max_rounds" in pol:
        raw = pol["confirm_max_rounds"]
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
            errors.append(
                f"optimization.policy.confirm_max_rounds={raw!r} must be an "
                f"integer >= 1. The compiled guard is `round >= max_rounds` "
                f"against a 1-BASED round counter, so a value below 1 sends the "
                f"campaign to report before the first round of terminal "
                f"discrimination has produced anything."
            )
    return errors


def _rule15_build_requires_baseline(opt: dict) -> list[str]:
    """Rule 15: a declared ``build`` stage requires ``known_valid_baseline``.

    Rule 13 checks that a baseline, IF PRESENT, is a configuration the campaign
    may run. This is the complementary question — must one be present at all —
    and the answer changes when ``build`` is declared, for a reason rule 13 has
    nothing to do with.

    ``build`` writes a mechanism that every later number describes. Oracle 2(c)
    (spec §3.7) is what keeps that mechanism honest: the campaign's declared
    control is measured before the build and again at ``verify``, and a shift
    beyond tolerance hard-fails, because a mechanism that moves the metric at
    its OFF level has changed something outside its own scope and confounds
    every treatment effect while looking clean. The baseline IS that control.
    Without it there is nothing to measure, so the check silently does not run —
    and a silently absent oracle on the one stage that authors code is the worst
    place in this kind to have one.

    (The baseline is also the report's last-resort action, per spec §3.6. That
    matters on every campaign; it is the build stage that makes it mandatory.)
    """
    stages = opt.get("stages")
    if not isinstance(stages, list):
        return []
    names = [str(getattr(s, "value", s)) for s in stages]
    if "build" not in names or opt.get("known_valid_baseline"):
        return []
    return [
        "optimization.known_valid_baseline is required when the build stage is "
        "declared: it is the control the build must leave unchanged (baseline "
        "equivalence, spec §3.7 oracle 2(c) — the control is measured before "
        "the build and again at verify, and a shift beyond tolerance aborts) "
        "and the report's last-resort action. Add a mapping of factor id -> "
        "level naming a configuration that is known to work today, with the "
        "mechanism under study at its OFF/control level, e.g. "
        "{QUEUES: 2, NEW_MECHANISM: off}.",
    ]


def _rule16_workload_seed_env(opt: dict) -> list[str]:
    """Rule 16: ``workload.seed_env`` must be a legal environment identifier.

    The name is exported into the run subprocess's environment (``runner``
    merges ``row.apply["env"]`` over ``os.environ``) and the target reads it
    from there. ``os.environ`` will happily hold ``"bad name"`` — Python does
    not police the key — and ``subprocess`` will pass it along, but almost
    nothing on the far side can read it: ``$bad name`` is two words to every
    POSIX shell, and a lowercase name collides with the convention every
    benchmark script's own variables follow.

    So the failure is not an error anywhere. The seed is exported, recorded in
    ``design_matrix.json``, and never read; every replicate then draws a fresh
    workload; and ``confirm`` still computes a PAIRED bound over differences
    whose shared seed term never actually cancelled. That bound is arithmetic
    performed correctly on the wrong premise. It is NOT overconfident — the
    variance comes from the observed differences, so a cancellation that never
    happened simply never narrows them, and coverage stays nominal. What is lost
    is efficiency (the paired t spends fewer degrees of freedom for a common
    term that was not common) and, more importantly, provenance: the artifact
    records ``bonferroni_one_sided_t_paired`` for an experiment that paired
    nothing, with nothing on disk to indicate it. A regex at authoring time is
    the only place this is visible.

    ``^[A-Z_][A-Z0-9_]*$`` rather than something more permissive: uppercase is
    the universal convention for an externally-supplied variable, and requiring
    it means a reviewer reading the target's benchmark script can tell which
    names come from outside.
    """
    wl = opt.get("workload")
    if not isinstance(wl, dict):
        return []
    errors: list[str] = []
    raw = wl.get("seed_env")
    name = str(getattr(raw, "value", raw)) if raw is not None else ""
    if not name or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        errors.append(
            f"optimization.workload.seed_env={raw!r} is not a legal environment "
            f"variable name (must match ^[A-Z_][A-Z0-9_]*$, e.g. "
            f"NOUS_WORKLOAD_SEED). Nous exports the per-row seed under this "
            f"name and the target reads it from its environment; a name with a "
            f"space, a hyphen, a leading digit or a lowercase letter is "
            f"exported successfully and then unreadable from the target's own "
            f"shell — so every replicate draws a fresh workload while confirm "
            f"still reports a PAIRED bound. That bound stays valid (its variance "
            f"comes from the observed differences), but it is less efficient than "
            f"the unpaired form and its recorded method claims a pairing that "
            f"never happened — and nothing errors anywhere to say so."
        )
    seeds = wl.get("seeds")
    if seeds is not None:
        if not isinstance(seeds, list) or not seeds:
            errors.append(
                f"optimization.workload.seeds={seeds!r} must be a non-empty "
                f"list of integers, or absent. Seeds are taken modulo the row "
                f"index (or, at confirm, the replicate index), so an empty list "
                f"has no element to take and the campaign would fall back to "
                f"derived seeds while the file reads as if it had pinned them."
            )
        elif any(not isinstance(s, int) or isinstance(s, bool) for s in seeds):
            bad = [s for s in seeds if not isinstance(s, int) or isinstance(s, bool)]
            errors.append(
                f"optimization.workload.seeds contains non-integer entr(ies) "
                f"{bad!r}. A seed is exported as a string into the target's "
                f"environment, so a float or a bool would arrive as '1.5' or "
                f"'True' and whatever the target does with that is not a seed."
            )
    return errors


# An hour: the point at which a campaign stops being something an author waits
# on and becomes something they schedule. Nothing in a campaign declares how long
# its author is willing to wait, so a threshold derived from the campaign would be
# inventing the number it claimed to derive.
HIGH_RUN_TIMEOUT_SEC = 3600


def _rule18_high_run_timeout_warning(opt: dict, factors: list[dict]) -> list[str]:
    """Rule 18: warn when ``run_timeout_sec`` buys a week of wall clock.

    ``run_timeout_sec`` exists precisely so that a target whose single
    LEGITIMATE measurement is a compound one -- an objective evaluation that is
    itself a bisection or a sweep to saturation -- can declare the real ceiling
    instead of buying a shorter one with a noisier statistic. So a large value is
    not wrong, and this is a WARNING: erroring on it would re-close the gap the
    field was added to open.

    What it IS, and what the author is the only person positioned to judge, is a
    schedule commitment multiplied by the run budget. The ceiling is per ROW; a
    90-row screen at a two-hour ceiling is 180 hours of worst-case wall clock,
    and the ceiling's own failure mode makes that worst case reachable rather
    than hypothetical -- a target that hangs (a deadlock, a saturated queue that
    never drains, a simulator waiting on a resource) consumes the full ceiling on
    every affected row and then fails it. The number the author typed is the only
    place that exposure is visible before the campaign is launched.

    The warning quantifies the exposure with the run budget the campaign
    declares. ``design.max_runs`` when present is the author's own stated
    ceiling on rows; otherwise the ``2**k`` full factorial, which is what
    ``_build_design`` falls back to and therefore an honest upper bound on the
    rows a screen can spend (a fractional design spends fewer -- that direction
    is safe for a warning about too MUCH time). Replicates and confirm rounds
    push the true total higher still, so the figure quoted is a floor on the
    exposure, not an estimate of it.

    3600 as the threshold rather than something derived: an hour is the point at
    which a campaign stops being something an author waits on and becomes
    something they schedule, and no field in the campaign says how long the
    author is willing to wait, so a derived threshold would be inventing the
    number it claims to derive.
    """
    raw = opt.get("run_timeout_sec")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= HIGH_RUN_TIMEOUT_SEC:
        return []
    design = opt.get("design") if isinstance(opt.get("design"), dict) else {}
    max_runs = design.get("max_runs")
    if isinstance(max_runs, int) and not isinstance(max_runs, bool) and max_runs > 0:
        runs, basis = max_runs, "design.max_runs"
    else:
        k = len(factors)
        if k == 0:
            return []
        runs, basis = 2 ** k, f"the {k}-factor full factorial"
    hours = runs * raw / 3600.0
    return [
        f"WARN: optimization.run_timeout_sec={raw} is a per-ROW ceiling, so "
        f"{runs} run(s) ({basis}) commit up to {hours:.0f} hours "
        f"({hours / 24:.1f} days) of worst-case wall clock before replicates or "
        f"a second confirm round are counted. That worst case is reachable, not "
        f"hypothetical: a target that hangs burns the whole ceiling on every "
        f"affected row and then fails it. Keep the value if the target's single "
        f"measurement really is compound (a bisection, a sweep to saturation) -- "
        f"that is what the field is for, and shortening the measurement to fit a "
        f"smaller ceiling would buy the schedule with a noisier statistic. "
        f"Otherwise lower it to just above the slowest corner's expected "
        f"duration, so a hang fails fast instead of quietly consuming the "
        f"budget. Run --smoke first: it prints the probe's real duration "
        f"alongside this ceiling.",
    ]


def _rule19_max_parallel_oversubscription(opt: dict) -> list[str]:
    """Rule 19: warn when ``max_parallel`` exceeds the machine's CPU count.

    ``optimization.max_parallel`` exists to buy wall clock at the one place a
    factorial design can absorb it -- a ``confirm`` replicate block, where every
    finalist is measured exactly once so whatever contention the block creates is
    SYMMETRIC across exactly the things being compared, shifts all the finalists
    together, and cancels out of the finalist-to-finalist difference.

    That symmetry argument is what the bound rests on, and OVERSUBSCRIPTION is
    where it stops holding cleanly. More in-flight runs than the machine has
    cores means the runs time-slice against each other, so a finalist's measured
    response starts depending on the scheduler rather than on its configuration:
    the contention is no longer a level shift the comparison cancels, it is
    variance injected into the very differences the terminal bound is computed
    from. A wider bound then buys wall clock with a wider residual-regret bound,
    which is the opposite of what the field is for -- the campaign spends the same
    runs and certifies less.

    A WARNING rather than an error, and the reason is a case the validator cannot
    see: a run that mostly WAITS -- on a remote inference endpoint, a managed
    database, a cluster it only submits to -- holds no core while it waits, so a
    bound well above ``cpu_count()`` is correct there and refusing it would make
    the field useless for exactly the targets whose wall clock hurts most. Only
    the author knows whether their ``run_command`` is CPU-bound or I/O-bound.

    ``os.cpu_count()`` rather than a derived or configured threshold, because it
    is the same number the contention is actually against, and because nothing in
    the campaign says how many cores the campaign will run on -- a derived
    threshold would be inventing the number it claims to derive. It is measured on
    the VALIDATING machine, which is usually but not always the running one; that
    is a limitation of the check, not a reason to skip it, and the message names
    the count so a mismatch is visible rather than silent.
    """
    import os as _os

    raw = opt.get("max_parallel")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 1:
        return []
    cpus = _os.cpu_count() or 1
    if raw <= cpus:
        return []
    return [
        f"WARN: optimization.max_parallel={raw} exceeds this machine's "
        f"{cpus} CPU(s), so a confirm replicate block would put more runs on the "
        f"machine than it has cores to run them on. The bound is safe at all "
        f"because contention inside a block is SYMMETRIC across the finalists "
        f"being compared and therefore cancels out of their differences; "
        f"time-slicing breaks that by injecting scheduler-dependent variance "
        f"into those same differences, which widens the terminal "
        f"residual-regret bound the round exists to tighten. Lower it to at most "
        f"{cpus} unless the target's run_command is I/O-bound (it mostly waits on "
        f"a remote service or a cluster and holds no core while waiting), which "
        f"is the one case where a higher bound is correct and the only case this "
        f"check cannot see. Note the count is this machine's; if the campaign "
        f"runs elsewhere, compare against that host's cores instead.",
    ]


def _rule17_config_patch_path_reachable(campaign: dict, opt: dict,
                                         factors: list[dict]) -> list[str]:
    """Rule 17: a ``config_patch`` factor's file must be reachable from the run.

    ``apply.kind: config_patch`` is realized by materializing a patched COPY of
    the declared file per run and rewriting every reference to the original
    ``path`` in the assembled command to point at that copy
    (``orchestrator.optimize.config_patch``). That mechanism has exactly one
    precondition: the ``path`` has to appear in ``optimization.run_command``,
    because there is no other place in the schema that says how the target is
    told which config file to read.

    THE DEFECT THIS CLOSES, in its second form. The first form was that nothing
    consumed ``apply["patches"]`` at all, so every row of a config-patch design
    silently measured the target's BASELINE while the pre-registered matrix and
    the fitted surface looked real. The runtime now refuses that case loudly —
    but refusing it at RUN time costs whatever the campaign already spent to get
    there, and on the live campaign that surfaced this it was a full ``build``
    stage and ~50 minutes of wall clock before row 1 of 18 said anything. A
    ``path`` the command never mentions is knowable from the campaign file
    alone, so it is knowable before anything is spent.

    HARD ERROR for the ``run_command`` half, WARNING for the on-disk half. A
    command that never names the file cannot work, in every case, with no
    exception worth preserving. Whether the file EXISTS is a different question:
    a ``build`` stage may be about to author it, the target may generate it from
    a template, and the check is path-based against a repo the validator can only
    see as a directory — the same reasoning that makes rule 12 a warning. A false
    hard-fail there would be worse than a false warning.

    Silent about campaigns with no ``run_command`` at all: that campaign has a
    more fundamental problem, and a secondary message about a patch path would
    bury it.

    THE MATCH REUSES THE RUNTIME'S OWN MATCHER rather than a bare ``in``
    substring test. The runtime anchors a path to an argument boundary (a whole
    token, or the tail of a ``--config=...`` token) precisely so that a factor
    declaring ``engine.json`` cannot be satisfied by a command naming
    ``other/engine.json``. A validator using ``in`` would pass exactly that
    campaign and leave the runtime to reject it -- which is the same
    "validated clean, aborted later" gap this rule exists to close, reintroduced
    at the level of the check itself. One matcher, one semantics.
    """
    import shlex

    from orchestrator.optimize.config_patch import command_names_path

    run_command = opt.get("run_command")
    run_command = str(getattr(run_command, "value", run_command) or "")
    try:
        tokens = shlex.split(run_command)
    except ValueError:
        # An unbalanced quote is a different (and louder) authoring problem;
        # fall back to the whole string as one token rather than adding a second
        # report for it here.
        tokens = [run_command]
    repo = (campaign.get("target_system") or {}).get("repo_path")

    errors: list[str] = []
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        spec = factor.get("apply")
        if not isinstance(spec, dict) or spec.get("kind") != "config_patch":
            continue
        path = spec.get("path")
        path = str(getattr(path, "value", path) or "")
        fid = factor.get("id")
        if not path:
            errors.append(
                f"factor {fid!r} declares apply.kind: config_patch with no "
                f"'path'. A config_patch needs path + pointer + value: the file "
                f"to copy-and-patch, the RFC 6901 location inside it, and the "
                f"value (normally '{{level}}')."
            )
            continue
        if run_command and not command_names_path(tokens, path):
            errors.append(
                f"factor {fid!r} patches {path!r}, but that path does not appear "
                f"in optimization.run_command ({run_command!r}). The patch is "
                f"applied to a per-run COPY of the file and the copy's path is "
                f"substituted for the original in the command — so a command "
                f"that never names the file has nothing to substitute, and the "
                f"run would read the target's unpatched configuration while the "
                f"design matrix recorded the requested level. Name the file as "
                f"an argument value, e.g. "
                f"'... --config {path} ...'."
            )
        # ``is_file()`` rather than ``exists()``: a DIRECTORY at the patch path
        # passes an existence check and then aborts at the apply seam, and a
        # broken symlink fails ``exists()`` while plainly being present. Both
        # need saying here, because "does not exist" sends an author hunting for
        # a typo in a path that is spelled correctly.
        if repo and path and not (Path(repo) / path).is_file():
            target = Path(repo) / path
            what = (
                "is a directory, not a file" if target.is_dir()
                else "is a symlink that does not resolve to a file"
                if target.is_symlink()
                else "is not a regular file" if target.exists()
                else "does not exist"
            )
            errors.append(
                f"WARN: factor {fid!r} patches {path!r}, which {what} "
                f"under target_system.repo_path ({repo}). Every run of this "
                f"factor would abort at the apply seam. Legitimate if a 'build' "
                f"stage authors the file or the target generates it from a "
                f"template; otherwise correct the path."
            )
    return errors


#: Characters that make a ``mechanism_paths`` entry a glob for git's pathspec
#: but a literal (and therefore unmatchable) string for ``_in_allowlist``.
_MECHANISM_PATH_GLOB_CHARS = "*?[]"


def _normalized_mechanism_path(raw: str) -> str:
    """``raw`` as ``_in_allowlist`` would have to see it to match anything.

    ``posixpath.normpath`` collapses ``//``, drops ``.`` segments and resolves
    interior ``..``. The trailing slash is restored afterwards because it is
    MEANINGFUL to a reader of the campaign file (``"src/"`` says "the
    directory") and ``_in_allowlist`` strips it itself — so normalising
    ``"src/"`` to ``"src"`` and then reporting a difference would reject the
    documented directory form, making the field unusable while every rejection
    test still passed.
    """
    import posixpath

    s = raw.replace("\\", "/")
    trailing = "/" if s.endswith("/") and s.strip("/") else ""
    return posixpath.normpath(s) + trailing


def _check_mechanism_paths_are_literal(opt: dict) -> list[str]:
    """``build_checks.mechanism_paths`` entries must be literal paths, not globs.

    DELIBERATELY UN-NUMBERED. The ``_ruleN`` family is numbered in the order the
    spec introduced them, and rule 16 is already spoken for (``workload.seed_env``).
    More importantly, this check does not belong to rule 15's subject: rule 15 is
    scoped to campaigns that DECLARE ``build``, whereas ``mechanism_paths`` is
    armed by the mere presence of ``mechanism.sha256`` and so applies to every
    optimization campaign. Filing it under a function named
    ``_rule15_build_requires_baseline`` would misfile it.

    THE DEFECT THIS CLOSES. The mechanism hash has two halves, scoped by the
    same entries through two different matchers:

      * tracked edits, via ``git diff HEAD -- <entries>`` — git's pathspec, which
        DOES expand ``*``, ``?`` and ``[...]``;
      * untracked files, via ``orchestrator.optimize.build._in_allowlist`` — a
        literal path-component prefix, which does NOT.

    So ``mechanism_paths: ["src/*"]`` reads perfectly naturally, is honoured by
    the tracked half, and matches NOTHING in the untracked half — which is the
    half where a newly authored mechanism module lives, the common case. The
    result is an oracle that looks scoped and silently watches half of what the
    author asked for: the same failure family the allowlist exists to remove,
    reintroduced by a single character.

    Rejected rather than supported-by-globbing on purpose. Making
    ``_in_allowlist`` glob would put the two halves' agreement at the mercy of
    two independent glob dialects (git pathspec magic vs. ``fnmatch``: ``*``
    crossing ``/``, ``**``, ``:(icase)``), and a wrong allowlist entry silently
    WIDENS the oracle's blind spot. A rejection the author reads once is cheaper
    than a mismatch nobody ever sees.

    ``.`` and ``""`` are rejected for the neighbouring reason: git takes ``.``
    as "the whole tree", ``_in_allowlist`` normalises it to a literal component
    named ``.`` that matches nothing, and ``_mechanism_text`` drops blank
    entries outright — so an allowlist of only such entries degrades to the
    whole-tree hash while the campaign file reads as scoped.

    NORMALIZATION SHAPES (added in Task 14, from Task 14.5's own review). The
    same two-matcher asymmetry is reachable without a single glob character.
    ``"src//mech.py"``, ``"src/./mech.py"``, ``"./src/mech.py"``,
    ``"src/sub/../mech.py"``, and an entry with surrounding whitespace or a
    trailing newline are all ordinary literal paths that git's pathspec
    NORMALISES before matching (so the tracked half finds the file) while
    ``_in_allowlist`` compares path components verbatim (so the untracked half
    finds nothing). Every one of them also passes ``nous validate campaign
    --smoke``, whose check is ``(repo / entry).exists()`` — and the OS
    normalises too. Verified on all five shapes: git reports ``src/mech.py``,
    ``_in_allowlist`` reports False, the smoke check reports "resolves".

    Rejected rather than silently normalised, for the same reason the globs are:
    the runtime defines the semantics and the runtime does not normalise, so a
    validator that repaired the entry would leave the campaign file and the
    oracle disagreeing about what was declared.

    ``..`` IS ITS OWN CASE, and worse than a narrowed oracle. Git refuses a
    pathspec that leaves the work tree ("fatal: '..' is outside repository")
    with a NON-ZERO exit, so ``_mechanism_text`` takes its ``returncode != 0``
    branch and returns None; ``snapshot_mechanism`` then returns "" and writes
    no ``mechanism.patch`` and no ``mechanism.sha256`` at all. The drift check
    keys on that file's presence, so it never runs: the oracle is not scoped
    down, it is absent, with no error at any layer. Its message names the escape
    rather than reusing "matches nothing", because an author told "matches
    nothing" hunts for a typo in a filename.
    """
    checks = opt.get("build_checks")
    if not isinstance(checks, dict):
        return []
    paths = checks.get("mechanism_paths")
    if not isinstance(paths, list):
        return []
    errors: list[str] = []
    for entry in paths:
        raw = str(getattr(entry, "value", entry))
        bad = sorted({c for c in raw if c in _MECHANISM_PATH_GLOB_CHARS})
        norm = _normalized_mechanism_path(raw)
        if bad:
            errors.append(
                f"optimization.build_checks.mechanism_paths entry {raw!r} looks "
                f"like a glob ({', '.join(repr(c) for c in bad)}), and this "
                f"field does not support globs. It is matched as a plain "
                f"path-component prefix: use 'src/' for everything under a "
                f"directory and an exact relative path like 'src/mech.py' for a "
                f"single file. A glob here would be expanded by git for the "
                f"tracked half of the drift hash and match nothing in the "
                f"untracked half, leaving a new mechanism module unwatched."
            )
        elif raw.strip().strip("/") in ("", "."):
            errors.append(
                f"optimization.build_checks.mechanism_paths entry {raw!r} "
                f"matches nothing: an empty entry is dropped and '.' is read as "
                f"a literal path component, not as 'the whole tree'. Name the "
                f"mechanism's actual files/directories ('src/', "
                f"'src/mech.py'), or omit mechanism_paths entirely to keep the "
                f"whole-tree default."
            )
        elif raw != raw.strip():
            errors.append(
                f"optimization.build_checks.mechanism_paths entry {raw!r} has "
                f"leading or trailing whitespace (a trailing newline from a YAML "
                f"block scalar looks like this), and it is NOT stripped at "
                f"runtime. Git takes the padded string as a literal filename "
                f"containing spaces and matches nothing; the untracked half's "
                f"literal prefix matches nothing either — so the allowlist is "
                f"non-empty (which is what turns the scoping ON) and covers no "
                f"file, leaving the drift oracle watching an empty set. "
                f"'nous validate campaign --smoke' cannot catch it: its check "
                f"strips before testing existence, so it reports the entry as "
                f"resolving. Write {raw.strip()!r}."
            )
        elif norm == ".." or norm.startswith("../"):
            errors.append(
                f"optimization.build_checks.mechanism_paths entry {raw!r} "
                f"points OUTSIDE the target repository (it normalises to "
                f"{norm!r}), which disables the drift oracle ENTIRELY rather "
                f"than narrowing it: git refuses a pathspec that escapes the "
                f"work tree with a non-zero exit, so no mechanism text is "
                f"produced, no mechanism.sha256 is written, and the drift check "
                f"— which keys on that file's presence — never runs and reports "
                f"nothing. Entries are repo-relative paths UNDER the target: "
                f"'src/' for a directory, 'src/mech.py' for a file."
            )
        elif norm != raw:
            errors.append(
                f"optimization.build_checks.mechanism_paths entry {raw!r} is "
                f"not in normalised form ({norm!r} is): it carries a redundant "
                f"separator, a '.' or '..' segment, or surrounding whitespace. "
                f"Git's pathspec normalises the entry before matching, so the "
                f"TRACKED half of the drift hash would find the file while the "
                f"UNTRACKED half — a literal path-component prefix, and where a "
                f"newly authored mechanism module lives — matches nothing. That "
                f"leaves half the oracle silently disarmed, and 'nous validate "
                f"campaign --smoke' cannot catch it either, because the OS "
                f"normalises the path too and reports it as resolving. Write "
                f"{norm!r}."
            )
    return errors


def validate_optimization_campaign(campaign: dict) -> list[str]:
    """Cross-field rules for ``kind: optimization`` campaigns that JSON
    Schema cannot express (Task 10).

    Returns a list of strings: plain strings are HARD ERRORS, strings
    prefixed ``WARN:`` are advisory. Every message names the actionable
    repair -- these campaigns are authored by AI, so a bare rejection
    with no next step is a defect, not just an incomplete message.

    Safe to call on ANY campaign dict, including reflective ones with no
    ``optimization`` block (rule 1 covers that case and everything else
    is a no-op).
    """
    errors: list[str] = []
    errors.extend(_rule1_kind_optimization_block(campaign))

    opt = campaign.get("optimization")
    if not isinstance(opt, dict):
        return errors  # rule 1 already reported (or nothing to check)

    factors = opt.get("factors") or []
    design = opt.get("design") or {}

    errors.extend(_rule2_held_out_leakage(opt))
    errors.extend(_rule3_screen_levels_membership(factors))
    errors.extend(_rule4_refine_needs_two_refinable_factors(design, factors))
    errors.extend(_rule5_correctness_relation_required(factors))
    errors.extend(_rule6_no_trivial_predicates(opt, factors))
    errors.extend(_rule7_low_resolution_screen_warning(design, factors))
    errors.extend(_rule8_resolution_run_budget(design, factors))
    errors.extend(_rule9_no_complexity_tier_under_optimization(campaign, opt))
    errors.extend(_rule10_uncontrolled_knob_warning(campaign, opt))
    errors.extend(_rule11_build_stage_position(opt))
    errors.extend(_rule12_missing_native_tests_need_build(campaign, opt, factors))
    errors.extend(_rule13_known_valid_baseline(opt, factors))
    errors.extend(_rule14_policy_ranges(opt))
    errors.extend(_rule15_build_requires_baseline(opt))
    errors.extend(_rule16_workload_seed_env(opt))
    errors.extend(_rule17_config_patch_path_reachable(campaign, opt, factors))
    errors.extend(_rule18_high_run_timeout_warning(opt, factors))
    errors.extend(_rule19_max_parallel_oversubscription(opt))
    errors.extend(_rule20_self_check_is_a_real_invariant(opt))
    errors.extend(_check_mechanism_paths_are_literal(opt))
    return errors


def _rule20_self_check_is_a_real_invariant(opt: dict) -> list[str]:
    """Rule 20: a declared ``response.self_check`` must be able to fail a row.

    The guard is only as good as the predicate, and two ways of declaring one
    make it useless:

      * TRIVIALLY TRUE (same floor rule 6 applies to manipulation predicates and
        design-space invariants). A self-check that cannot fail manufactures
        exactly the false confidence the whole mechanism exists to remove -- and
        worse here than elsewhere, because an author who declares one reasonably
        stops looking for the self-contradiction by hand.
      * OVER THE PRIMARY METRIC ITSELF. ``{metric: <primary>, op: ...}`` is a
        bound on the objective, which is what ``response.constraints`` (a config
        is inadmissible: ``infeasible``, retained as real data about the space)
        or ``response.ceiling`` (the instrumentation is lying: ``rejected``)
        already express, with the status semantics an author actually wants. A
        self-check is a check on the DIAGNOSTIC that defines the objective, and
        pointing it at the objective turns a row that is merely poor into a row
        that "contradicts itself" and is thrown away.
    """
    response = (opt or {}).get("response") or {}
    self_check = response.get("self_check") or []
    if not self_check:
        return []
    primary = ((response.get("primary") or {}).get("metric")) or ""
    errors: list[str] = []
    for pred in self_check:
        if not isinstance(pred, dict):
            continue
        path = pred.get("observable") or pred.get("metric")
        if is_trivial(pred):
            errors.append(
                f"response.self_check entry over {path!r}: predicate "
                f"{{op: {pred.get('op')!r}, value: {pred.get('value')!r}}} is "
                f"trivially true -- it cannot fail, so it certifies nothing "
                f"while making the campaign look as though its objective is "
                f"checked against its own definition. State the real threshold "
                f"the objective's definition uses (e.g. {{metric: "
                f"backlog_slope, op: '<=', value: 0.060}} for an objective "
                f"defined as 'the largest rate whose backlog is not growing')."
            )
        if primary and str(path) == str(primary):
            errors.append(
                f"response.self_check entry is over {path!r}, which IS "
                f"response.primary.metric. A self-check asserts that the "
                f"reported objective satisfies the predicate that DEFINES it, "
                f"so it must read the DIAGNOSTIC, not the objective: a bound on "
                f"the objective itself belongs in response.constraints (a "
                f"violation marks the config infeasible -- excluded from "
                f"fitting, retained as real data about the space) or "
                f"response.ceiling (a violation means the instrumentation is "
                f"lying). As a self-check it would fail the row outright, "
                f"discarding a measurement that is merely unattractive."
            )
    return errors


def _validate_locked_parameters(
    bundle: dict, campaign: dict | None,
) -> list[str]:
    """Issue #246 (F1): hard-fail when bundle deviates from campaign.locked_parameters.

    Closes the spec-fidelity gap left by HUMAN_DESIGN_GATE bypass under
    --auto-approve. The bundle's ``experiment_spec.verified_parameters``
    is the canonical place where DESIGN pins concrete values; comparing
    each ``campaign.locked_parameters[k]`` against
    ``verified_parameters.get(k)`` catches the failure mode where
    DESIGN silently rewrites locked workload parameters to its own
    guess (paper-memorytime-mirage iter-1: ``model``, ``concurrency``,
    ``duration``, ``warmup`` all overwritten).

    The error message lists EVERY deviation in one shot, not just the
    first — so a single re-run of the gate sees the full diff.
    """
    if not campaign:
        return []
    locked = campaign.get("locked_parameters")
    if not isinstance(locked, dict) or not locked:
        return []
    spec = bundle.get("experiment_spec") or {}
    verified = spec.get("verified_parameters") or {}
    if not isinstance(verified, dict):
        return [
            "campaign.locked_parameters is set but "
            "bundle.experiment_spec.verified_parameters is missing or "
            "malformed; cannot verify spec-fidelity (#246)."
        ]
    deviations: list[str] = []
    for key, expected in locked.items():
        if key not in verified:
            deviations.append(
                f"  - {key}: campaign={expected!r}, bundle=<missing>"
            )
            continue
        actual = verified[key]
        if actual != expected:
            deviations.append(
                f"  - {key}: campaign={expected!r}, bundle={actual!r}"
            )
    if not deviations:
        return []
    return [
        "bundle.experiment_spec.verified_parameters deviates from "
        "campaign.locked_parameters (#246/F1). Each entry must match "
        "exactly:\n" + "\n".join(deviations)
    ]


def _validate_locked_workload(
    iter_dir: Path, bundle: dict, campaign: dict | None,
) -> list[str]:
    """Issue #265 (F20): hard-fail when bundle.inputs/*.yaml deviates
    from campaign.locked_workload, unless bundle.workload_changes_from_canonical
    explicitly declares the deviation.

    Workload distributions live in ``inputs/<workload>.yaml`` (referenced
    from the bundle), not in ``verified_parameters``, so #246's check
    misses them. This validator does the structural diff.

    Resolution: scan ``iter_dir/inputs/*.yaml``; for each top-level field
    that also appears in ``locked_workload``, compare. If the values
    differ, fail unless ``workload_changes_from_canonical.diff`` declares
    that field-tuple.
    """
    if not campaign:
        return []
    locked = campaign.get("locked_workload")
    if not isinstance(locked, dict) or not locked:
        return []
    declared = bundle.get("workload_changes_from_canonical") or {}
    declared_diffs = declared.get("diff") or [] if isinstance(declared, dict) else []
    declared_fields = {
        (entry.get("tenant"), entry.get("field"))
        for entry in declared_diffs
        if isinstance(entry, dict)
    }

    inputs_dir = iter_dir / "inputs"
    if not inputs_dir.is_dir():
        # Workload yaml may not exist yet; nothing to diff.
        return []
    deviations: list[str] = []
    workload_yamls = sorted(inputs_dir.glob("*.yaml")) + sorted(inputs_dir.glob("*.yml"))
    for workload_path in workload_yamls:
        try:
            data = yaml.safe_load(workload_path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        # Compare every top-level locked field.
        _walk_locked_workload(
            locked, data, declared_fields, deviations, workload_path.name,
        )
    if not deviations:
        return []
    return [
        f"workload yaml deviates from campaign.locked_workload "
        f"(#265/F20). Each must match exactly OR be declared in "
        f"bundle.workload_changes_from_canonical.diff:\n"
        + "\n".join(deviations)
    ]


def _walk_locked_workload(
    locked: dict, actual: dict, declared: set, errors: list[str], src: str,
    *, path: str = "", tenant: str | None = None,
) -> None:
    """Recursive walk for #265: compare locked dict against actual,
    report any mismatch not present in ``declared`` (set of (tenant, field)
    tuples from workload_changes_from_canonical.diff).
    """
    for key, expected in locked.items():
        sub_path = f"{path}.{key}" if path else key
        if isinstance(expected, dict) and isinstance(actual.get(key), dict):
            # Recurse — for ``tenants`` block, the key at this level is
            # the tenant id, threaded through to the deviation tuple.
            _walk_locked_workload(
                expected, actual[key], declared, errors, src,
                path=sub_path, tenant=tenant or (key if path == "tenants" else tenant),
            )
            continue
        actual_value = actual.get(key, "<missing>")
        if actual_value != expected:
            if (tenant, sub_path) in declared or (None, sub_path) in declared:
                continue  # explicitly declared deviation
            errors.append(
                f"  - {src}: {sub_path}: canonical={expected!r}, "
                f"actual={actual_value!r}"
                + (f" (tenant={tenant})" if tenant else "")
            )


def _validate_depth_overrides(bundle: dict) -> list[str]:
    """Issue #248 (F3): if rehearsal_subset.depth_overrides has any
    payload field set (i.e. anything besides ``invalidates_checks``),
    ``invalidates_checks`` must be populated — otherwise the rehearsal
    silently weakens scale-dependent apparatus checks.
    """
    spec = bundle.get("experiment_spec") or {}
    rehearsal = spec.get("rehearsal_subset") or {}
    overrides = rehearsal.get("depth_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return []
    payload_keys = [k for k in overrides if k != "invalidates_checks"]
    if not payload_keys:
        return []
    invalidates = overrides.get("invalidates_checks") or []
    if not invalidates:
        return [
            "rehearsal_subset.depth_overrides sets payload field(s) "
            f"{payload_keys} without declaring invalidates_checks. "
            "Depth shrinkage silently invalidates scale-dependent "
            "apparatus checks; the campaign author must list which "
            "checks they're surrendering (#248/F3)."
        ]
    return []


def _validate_physical_realism(bundle: dict) -> list[str]:
    """Issue #260 (F15): soft-warn when k_realism_ratio is far from 1
    and justification is missing/perfunctory. WARN-prefixed; never
    hard-fails the gate (the campaign author may legitimately choose
    a synthetic regime to demonstrate the mechanism).
    """
    spec = bundle.get("experiment_spec") or {}
    block = spec.get("physical_realism_check")
    if not isinstance(block, dict):
        return []
    ratio = block.get("k_realism_ratio")
    if not isinstance(ratio, (int, float)):
        return []
    if 0.5 <= ratio <= 2.0:
        return []
    justification = (block.get("justification") or "").strip()
    # Perfunctory = empty or under 30 chars.
    if len(justification) >= 30:
        return []
    return [
        f"WARN: physical_realism_check.k_realism_ratio={ratio:.3f} "
        f"is far from 1 (synthetic-regime risk: \"you constructed "
        f"your own contention\"), and justification is empty or "
        f"perfunctory. Add a substantive justification or raise K to "
        f"the realistic value (#260/F15)."
    ]


def _validate_typed_arm_fields(bundle: dict) -> list[str]:
    """Cross-field rules per arm type that JSON Schema can't easily express.

    H-dose-response (issue #157) requires knob, values (>=3 distinct),
    metric, and expected_shape. JSON Schema accepts these as optional
    so existing arm types stay valid; this function enforces them
    when the arm type asks for them.

    H-tradeoff (issue #158) requires metric, secondary_metric, and
    a tradeoff prediction with secondary_budget — see #158's
    extension to this function.
    """
    errors: list[str] = []
    arms = bundle.get("arms") or []
    if not isinstance(arms, list):
        return errors
    for i, arm in enumerate(arms):
        if not isinstance(arm, dict):
            continue
        arm_type = arm.get("type")
        if arm_type == "h-dose-response":
            for field in ("knob", "values", "metric", "expected_shape"):
                if field not in arm:
                    errors.append(
                        f"arms[{i}] (h-dose-response) missing required field {field!r}"
                    )
            values = arm.get("values")
            if isinstance(values, list):
                if len(values) < 3:
                    errors.append(
                        f"arms[{i}] (h-dose-response) has < 3 values "
                        f"({len(values)}); dose-response needs >= 3."
                    )
                if len(values) != len(set(map(repr, values))):
                    errors.append(
                        f"arms[{i}] (h-dose-response) has duplicate values; "
                        f"distinct knob settings required."
                    )
        elif arm_type == "h-tradeoff":
            for field in (
                "metric", "secondary_metric", "secondary_budget",
                "secondary_direction",
            ):
                if field not in arm:
                    errors.append(
                        f"arms[{i}] (h-tradeoff) missing required field {field!r}"
                    )
            if (
                arm.get("metric") is not None
                and arm.get("metric") == arm.get("secondary_metric")
            ):
                errors.append(
                    f"arms[{i}] (h-tradeoff): secondary_metric must differ "
                    f"from primary metric (both = {arm.get('metric')!r})."
                )
    return errors


def compute_campaign_spec_diff(
    iter_dir: Path, campaign: dict | None,
) -> dict:
    """Issue #249 (F4): structured campaign-vs-bundle deviation report.

    Used by ``_generate_gate_summary`` to populate the
    ``campaign_spec_diff`` block on every gate summary, regardless of
    --auto-approve. The diff is "soft" (informational) by default —
    F1's ``_validate_locked_parameters`` is the hard-fail layer.

    Returns a dict with three sub-keys:
      * ``locked_parameters_violations`` — list of {param, campaign,
        bundle} entries (these are also hard validation failures
        upstream; recorded here so an auditor sees them in one place).
      * ``locked_workload_violations`` — list of {field, canonical, actual,
        tenant?} entries (these are also hard validation failures upstream).
      * ``depth_overrides_present`` — bool.
      * ``invalidated_checks_declared`` — list of strings.
      * ``workload_changes_from_canonical_declared`` — bool.

    All keys are present so the consumer can grep for missing keys as
    a regression signal (PR #235 pattern).
    """
    diff: dict = {
        "locked_parameters_violations": [],
        "locked_workload_violations": [],
        "depth_overrides_present": False,
        "invalidated_checks_declared": [],
        "workload_changes_from_canonical_declared": False,
    }
    bundle_path = iter_dir / "bundle.yaml"
    if not bundle_path.exists():
        return diff
    try:
        bundle = yaml.safe_load(bundle_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return diff
    if not isinstance(bundle, dict):
        return diff
    spec = bundle.get("experiment_spec") or {}
    verified = (spec.get("verified_parameters") or {}) if isinstance(spec, dict) else {}

    locked = (campaign or {}).get("locked_parameters") or {}
    if isinstance(locked, dict) and isinstance(verified, dict):
        for k, expected in locked.items():
            actual = verified.get(k, "<missing>")
            if actual != expected:
                diff["locked_parameters_violations"].append(
                    {"param": k, "campaign": expected, "bundle": actual}
                )

    rehearsal = spec.get("rehearsal_subset") or {} if isinstance(spec, dict) else {}
    overrides = rehearsal.get("depth_overrides") if isinstance(rehearsal, dict) else None
    if isinstance(overrides, dict):
        payload_keys = [k for k in overrides if k != "invalidates_checks"]
        diff["depth_overrides_present"] = bool(payload_keys)
        invalidates = overrides.get("invalidates_checks") or []
        if isinstance(invalidates, list):
            diff["invalidated_checks_declared"] = [str(x) for x in invalidates]

    diff["workload_changes_from_canonical_declared"] = (
        isinstance(bundle.get("workload_changes_from_canonical"), dict)
    )
    return diff


def validate_design(iter_dir: Path, campaign: dict | None = None) -> dict:
    """Check design artifacts exist and conform to schemas.

    #199: ``campaign`` is optional but recommended — it enables the
    per-campaign iter-root whitelist extension via
    ``campaign.validation.iter_root_extensions``.
    """
    iter_dir = Path(iter_dir)
    errors = []
    # #279 review: WARN-prefixed advisory entries (ground-truth
    # independence #85, physical realism #260) were detected then dropped.
    # Collect them and return them so the caller can surface them at the
    # design gate instead of silently discarding tautology / synthetic-
    # regime warnings.
    warnings: list[str] = []

    # problem.md
    problem_path = iter_dir / "problem.md"
    if not problem_path.exists():
        errors.append("problem.md not found")
    elif problem_path.stat().st_size == 0:
        errors.append("problem.md is empty")

    # bundle.yaml
    bundle_path = iter_dir / "bundle.yaml"
    if not bundle_path.exists():
        errors.append("bundle.yaml not found")
    else:
        try:
            bundle = yaml.safe_load(bundle_path.read_text())
            schema = _load_yaml_schema("bundle.schema.yaml")
            jsonschema.validate(bundle, schema)
            errors.extend(_validate_typed_arm_fields(bundle))
            # #246 (F1): locked_parameters spec-fidelity. Hard-fail under
            # auto-approve too — that's the whole point.
            errors.extend(_validate_locked_parameters(bundle, campaign))
            # #265 (F20): locked_workload diff against bundle.inputs/*.yaml.
            errors.extend(_validate_locked_workload(iter_dir, bundle, campaign))
            # #248 (F3): depth_overrides without invalidates_checks.
            errors.extend(_validate_depth_overrides(bundle))
            # #260 (F15): physical-realism soft warning. WARN-prefixed.
            for entry in _validate_physical_realism(bundle):
                if entry.startswith("WARN:"):
                    warnings.append(entry)
                else:
                    errors.append(entry)
            # Issue #85: WARN-prefixed entries are advisory and don't fail
            # validation (the human gate sees them but the campaign continues).
            for entry in _validate_ground_truth_independence(bundle):
                if entry.startswith("WARN:"):
                    warnings.append(entry)
                else:
                    errors.append(entry)
        except yaml.YAMLError as exc:
            errors.append(f"bundle.yaml is not valid YAML: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"bundle.yaml schema error: {exc.message}")

    # handoff_snapshot.md
    handoff_path = iter_dir / "handoff_snapshot.md"
    if not handoff_path.exists():
        errors.append("handoff_snapshot.md not found")
    elif handoff_path.stat().st_size == 0:
        errors.append("handoff_snapshot.md is empty")

    # #199 v2: required ⊆ allowed at design time too. We don't enforce
    # required-presence here (most required files are written during
    # EXECUTE, not DESIGN), but if the campaign agent does write one
    # during DESIGN, the unexpected-file check must not reject it.
    extensions = _campaign_iter_root_extensions(campaign)
    required = _campaign_required_iter_root(campaign)
    errors.extend(_check_unexpected_files(iter_dir, extensions | required))

    if errors:
        return {"status": "fail", "errors": errors, "warnings": warnings}
    return {"status": "pass", "warnings": warnings}


def validate_execution(iter_dir: Path, campaign: dict | None = None) -> dict:
    """Check execution artifacts exist, conform to schemas, and patches are valid."""
    iter_dir = Path(iter_dir)
    errors = []

    # experiment_plan.yaml
    plan_path = iter_dir / "experiment_plan.yaml"
    if not plan_path.exists():
        errors.append("experiment_plan.yaml not found")
    else:
        try:
            plan = yaml.safe_load(plan_path.read_text())
            schema = _load_yaml_schema("experiment_plan.schema.yaml")
            jsonschema.validate(plan, schema)
        except yaml.YAMLError as exc:
            errors.append(f"experiment_plan.yaml is not valid YAML: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"experiment_plan.yaml schema error: {exc.message}")

    # findings.json
    findings_path = iter_dir / "findings.json"
    if not findings_path.exists():
        errors.append("findings.json not found")
    else:
        try:
            findings = json.loads(findings_path.read_text())
            schema = _load_json_schema("findings.schema.json")
            jsonschema.validate(findings, schema)
        except json.JSONDecodeError as exc:
            errors.append(f"findings.json is not valid JSON: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"findings.json schema error: {exc.message}")

    # principle_updates.json
    principles_path = iter_dir / "principle_updates.json"
    if not principles_path.exists():
        errors.append("principle_updates.json not found")
    else:
        try:
            updates = json.loads(principles_path.read_text())
            if not isinstance(updates, list):
                errors.append(
                    f"principle_updates.json should be a list, got {type(updates).__name__}"
                )
            else:
                for i, entry in enumerate(updates):
                    if not isinstance(entry, dict) or "id" not in entry:
                        errors.append(
                            f"principle_updates.json entry {i} missing 'id'"
                        )
        except json.JSONDecodeError as exc:
            errors.append(f"principle_updates.json is not valid JSON: {exc}")

    # file references — check that output and input files in plan conditions exist
    if plan_path.exists():
        try:
            plan = yaml.safe_load(plan_path.read_text())
            for arm in plan.get("arms", []):
                for cond in arm.get("conditions", []):
                    output = cond.get("output")
                    if output:
                        output_file = Path(output)
                        if not output_file.is_absolute():
                            output_file = iter_dir / output
                        if not output_file.exists():
                            errors.append(
                                f"output file {cond['output']} referenced in "
                                f"{arm['arm_id']}/{cond['name']} not found"
                            )
                    for input_path in cond.get("inputs", []):
                        input_file = Path(input_path)
                        if not input_file.is_absolute():
                            input_file = iter_dir / input_path
                        if not input_file.exists():
                            errors.append(
                                f"input file {input_path} referenced in "
                                f"{arm['arm_id']}/{cond['name']} not found"
                            )
        except yaml.YAMLError:
            pass  # plan parse issues already caught above
        except KeyError as exc:
            errors.append(f"experiment_plan.yaml arm/condition missing key: {exc}")

    # patches — only required when bundle has code_changes
    bundle_path = iter_dir / "bundle.yaml"
    if bundle_path.exists():
        try:
            bundle = yaml.safe_load(bundle_path.read_text())
            arms_with_code = [
                arm for arm in bundle.get("arms", [])
                if arm.get("code_changes")
            ]
            if arms_with_code:
                patches_dir = iter_dir / "patches"
                if not patches_dir.is_dir():
                    errors.append(
                        "patches/ directory not found but bundle has arms with code_changes"
                    )
                else:
                    for arm in arms_with_code:
                        arm_type = arm["type"]
                        patch_file = patches_dir / f"{arm_type}.patch"
                        if not patch_file.exists():
                            errors.append(f"patches/{arm_type}.patch not found")
                        elif patch_file.stat().st_size == 0:
                            errors.append(f"patches/{arm_type}.patch is empty")
        except yaml.YAMLError as exc:
            errors.append(f"bundle.yaml is not valid YAML (patches check skipped): {exc}")
        except KeyError as exc:
            errors.append(f"bundle.yaml arm missing required field: {exc}")

    # #199 v2: required ⊆ allowed (a required file is also implicitly
    # allowed at iter-root, so campaigns don't have to declare it
    # twice). Merge before the unexpected-file check.
    extensions = _campaign_iter_root_extensions(campaign)
    required = _campaign_required_iter_root(campaign)
    errors.extend(_check_unexpected_files(iter_dir, extensions | required))
    errors.extend(_check_required_iter_root(iter_dir, required))

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}


def validate_meta_findings(work_dir: Path) -> dict:
    """Check meta_findings.json conforms to schema and citation floor.

    The citation floor (``orchestrator.meta_findings.evidence_is_concrete``)
    rejects entries whose ``evidence`` is a vague platitude. Schema does
    minLength + enum; the floor catches anything that passes minLength
    but is still aspirational.
    """
    work_dir = Path(work_dir)
    errors: list[str] = []

    target = work_dir / "meta_findings.json"
    if not target.exists():
        return {"status": "fail", "errors": [f"{target.name} not found at {work_dir}"]}

    try:
        payload = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        return {"status": "fail", "errors": [f"meta_findings.json is not valid JSON: {exc}"]}

    try:
        schema = _load_json_schema("meta_findings.schema.json")
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"meta_findings.json schema error: {exc.message}")

    # Citation floor — applied to every evidence string in every stream.
    from orchestrator.meta_findings import validate_evidence

    for stream_name in ("campaign_design_lessons", "target_system_asks", "nous_asks"):
        items = payload.get(stream_name) or []
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence", "")
            err = validate_evidence(evidence)
            if err:
                errors.append(f"{stream_name}[{i}]: {err}")

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Nous artifacts for a given phase.",
    )
    parser.add_argument(
        "phase", choices=["design", "execution", "meta-findings"],
        help="Which phase to validate",
    )
    parser.add_argument(
        "--dir", required=True, type=Path,
        help="Path to the iteration directory (or work_dir for meta-findings)",
    )
    args = parser.parse_args()

    if args.phase == "design":
        result = validate_design(args.dir)
    elif args.phase == "execution":
        result = validate_execution(args.dir)
    else:
        result = validate_meta_findings(args.dir)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
