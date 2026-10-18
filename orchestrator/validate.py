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

from orchestrator.optimize.design import min_runs_for
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
            "`nous docs guide` -- or set kind: reflective "
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
    # Multi-objective: EVERY objective is fitted, so every one is a leakage
    # target. (A campaign declaring both forms is reported by rule 26; checking
    # both here keeps this rule honest on that shape too.)
    objective_metrics = [
        o.get("metric") for o in (response.get("objectives") or [])
        if isinstance(o, dict) and o.get("metric")
    ] if isinstance(response.get("objectives"), list) else []
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
        for omet in objective_metrics:
            if metric_norm and _norm_metric(omet) == metric_norm:
                errors.append(
                    f"response.held_out contains {metric!r}, which collides "
                    f"with the response.objectives metric {omet!r} (same "
                    f"metric name, ignoring case/whitespace) -- this is data "
                    f"leakage (the holdout-selection failure class): every "
                    f"objective is fitted and ranked on, and a held_out "
                    f"metric must never be an input the design matrix fits "
                    f"against. Choose a different held_out metric, or drop "
                    f"{omet!r} from objectives."
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
        if factor.get("type") == "choice" and len(levels) > 2:
            errors.append(
                f"factor {fid!r}: a choice factor with {len(levels)} levels is "
                f"screened at every level (method of replacement), so "
                f"screen_levels does not apply. Remove screen_levels; to screen "
                f"fewer levels, declare fewer levels.")
            continue
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


def _rule11a_plan_stage_position(opt: dict) -> list[str]:
    """Rule 11a: ``plan``, if present, must be first and immediately precede ``build``.

    ``plan`` designs the mechanism ``build`` then authors. Anywhere else it is
    schema-valid and useless in a specific way worth rejecting:

    * ``plan`` with no ``build`` is a design nothing implements — the call is
      spent and no code is written.
    * ``plan`` AFTER ``build`` specifies code that already exists. The artifact
      then reads as a pre-registered design while actually being a post-hoc
      rationalisation of what was already committed, which is worse than absent.
    * ``plan`` twice re-designs a mechanism a later stage already measured.
    """
    stages = opt.get("stages")
    if not isinstance(stages, list) or not stages:
        return []
    names = [str(getattr(s, "value", s)) for s in stages]
    count = names.count("plan")
    if count == 0:
        return []
    errors: list[str] = []
    if count > 1:
        errors.append(
            f"optimization.stages lists 'plan' {count} times. The plan stage "
            f"spends an agent call designing the mechanism; running it again "
            f"would re-design a mechanism the build already authored. Keep a "
            f"single 'plan' as the first stage.",
        )
    if "build" not in names:
        errors.append(
            "optimization.stages declares 'plan' with no 'build'. The plan is a "
            "specification for the build stage to implement — without 'build' the "
            "call is spent and no code is written. Either add 'build' after "
            "'plan', or drop 'plan'.",
        )
        return errors
    if names[0] != "plan" or names[1] != "build":
        errors.append(
            f"optimization.stages has 'plan' at position "
            f"{names.index('plan') + 1} (stages: {names}). 'plan' must come "
            f"FIRST, immediately before 'build': it designs the mechanism that "
            f"'build' authors. After 'build' it describes code that already "
            f"exists, which reads as a pre-registered design but is a post-hoc "
            f"rationalisation. Reorder to "
            f"{['plan', 'build'] + [n for n in names if n not in ('plan', 'build')]}.",
        )
    return errors


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
    # `plan` is the one stage allowed to precede `build`: it designs the mechanism
    # `build` authors, and rule 11a pins it to position 1. So build at position 2
    # behind `plan` is correct, and only that arrangement is.
    expected_pos = 1 if names[0] == "plan" else 0
    if names.index("build") != expected_pos:
        errors.append(
            f"optimization.stages has 'build' at position {names.index('build') + 1} "
            f"(stages: {names}). 'build' must come FIRST: it authors the "
            f"mechanism that every later stage measures. Behind 'verify' it "
            f"aborts the campaign (verify gates tests for code that does not "
            f"exist yet); behind 'screen' the screen measures the old mechanism "
            f"and reports an effect table for a system the campaign replaced. "
            f"(The sole exception is 'plan', which may precede it — see rule 11a.) "
            f"Reorder to {[n for n in ('plan',) if n in names] + ['build'] + [n for n in names if n not in ('plan', 'build')]}.",
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


def locate_native_tests(
    repo: Path, declared_all: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Classify each declared ``native_test`` against the target tree.

    Returns ``(present, missing, unknown, command_style)``: found now, not
    found (a path that does not exist / an identifier defined nowhere),
    un-checkable locator style, and command-style locators (which resolve
    here but fail the runner's contract check). The ONE locator logic shared
    by rule 12 and ``--smoke``'s pre-build partition, so the two cannot
    disagree about which tests ``build`` is expected to author.
    """
    present: list[str] = []
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
            else:
                present.append(declared)
        elif kind == "ident":
            if subject not in defined:
                defined[str(subject)] = _identifier_is_defined(
                    Path(repo), str(subject),
                )
            if not defined[str(subject)]:
                missing.append(declared)
            else:
                present.append(declared)
        else:
            unknown.append(declared)
        if kind == "ident" and any(c.isspace() for c in declared.strip()):
            command_style.append(declared)
    return present, missing, unknown, command_style


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

    _present, missing, unknown, command_style = locate_native_tests(
        Path(repo), declared_all,
    )

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
        if isinstance(man, dict) and man.get("evidence") == "target":
            from orchestrator.optimize.factors import ECHO_ROOTS, manipulation_evidence

            if manipulation_evidence(man) == "echo":
                errors.append(
                    f"factor {fid!r}: manipulation.evidence is 'target' but the "
                    f"predicate reads {man.get('observable') or man.get('metric')!r}, "
                    f"Nous's own record of what it set ({sorted(ECHO_ROOTS)}), not a "
                    f"field the target emitted: it can show the lever was sent, never "
                    f"that it was received. Point it at a target-reported field, or "
                    f"drop 'evidence: target' (the check is then flagged echo-only).")
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
        if _mixed_screen_runs(design, factors, resolution) is not None:
            # A multi-level categorical: name the aliasing of the MIXED screen
            # (generalized, contrast components) the epoch will actually run.
            from orchestrator.optimize.design import mixed_screen
            from orchestrator.optimize.factors import parse_factors

            pairs = _alias_pairs_safe(mixed_screen(
                parse_factors(factors), resolution=resolution, center_points=0))
        else:
            design_obj = fractional_factorial(ids, resolution)
            pairs = design_obj.generators and _alias_pairs_safe(design_obj)
    except ValueError:
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


_ROMAN = {3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}


def _screen_center_points(design: dict) -> int:
    """``design.screen.center_points`` as ``_build_design`` reads it (default 4)."""
    screen = (design or {}).get("screen") if isinstance(design, dict) else None
    cp = (screen or {}).get("center_points", 4) if isinstance(screen, dict) else 4
    return cp if isinstance(cp, int) and not isinstance(cp, bool) and cp >= 0 else 4


def _screen_rows(design: dict, k: int) -> tuple[int, str] | None:
    """``(rows, basis)`` of the screen ``_build_design`` will build: the
    resolution-R design's corners (``min_runs_for``; R defaults to 5) plus the
    centre points. ``None`` when no design can be built (the construction
    refuses the factor count -- rule 8 reports that)."""
    screen = (design or {}).get("screen") if isinstance(design, dict) else None
    res = (screen or {}).get("resolution", 5) if isinstance(screen, dict) else 5
    if not isinstance(res, int) or isinstance(res, bool) or res < 3:
        res = 5
    try:
        corners = min_runs_for(k, res)
    except ValueError:
        return None
    cp = _screen_center_points(design)
    return corners + cp, (f"the resolution-{_ROMAN.get(res, res)} screen of {k} "
                          f"factors: {corners} corners + {cp} centre points")


def _rule8_resolution_run_budget(design: dict, factors: list[dict]) -> list[str]:
    """Rule 8: the screen's design must exist and fit ``design.max_runs``.

    ``min_runs_for`` is EXACT for every ``(k, resolution)``: the tabulated or
    constructed fractional design's run count, or ``2**k`` where the full
    factorial is already the smallest design of that resolution
    (``design.generators_for``). The comparison COUNTS THE CENTRE POINTS:
    ``max_runs`` is a run budget, and the runtime budget
    (``policy``'s ``budget_remaining``) and the design preview both count
    every row, centre points included. Past the budget the error names the
    options -- only the lower resolutions that both fit and are strictly
    cheaper than every higher one (a lower resolution at the same cost buys
    more aliasing for nothing) -- and Nous never silently downgrades the
    resolution to fit.
    """
    if not isinstance(design, dict):
        return []
    screen = design.get("screen") or {}
    resolution = screen.get("resolution")
    if not isinstance(resolution, int) or resolution < 3:
        return []
    k = len(factors)
    if k == 0:
        return []
    max_runs = design.get("max_runs")
    mixed = _mixed_screen_runs(design, factors, resolution)
    if mixed is not None:
        if max_runs is None:
            return []
        corners, cols = mixed
        cp = _screen_center_points(design)
        required = corners + cp
        if required <= max_runs:
            return []
        return [
            f"design.screen.resolution={resolution} over {k} factors -- {cols} "
            f"two-level columns once each multi-level choice factor takes its "
            f"pseudo-factors (method of replacement) -- needs {required} runs "
            f"({corners} corners + {cp} centre points), but design.max_runs="
            f"{max_runs} is lower. Options: (1) raise max_runs to >= {required}; "
            f"(2) accept a lower resolution; (3) declare fewer levels on a "
            f"categorical (L levels use 2^ceil(log2 L) - 1 contrast df: 3 for L = "
            f"3 or 4, 7 for L = 5..8); (4) screen fewer "
            f"factors this epoch. Nous will not silently downgrade resolution to "
            f"fit the budget."]
    try:
        corners = min_runs_for(k, resolution)
    except ValueError as exc:
        # Reported with or without a budget: the screen cannot be built.
        return [f"design.screen.resolution={resolution} over {k} factors cannot be "
                f"built: {exc}"]
    if max_runs is None:
        return []
    cp = _screen_center_points(design)
    required = corners + cp
    if required <= max_runs:
        return []
    lower: list[tuple[int, int]] = []
    cheapest = corners
    for r in range(resolution - 1, 2, -1):
        n = min_runs_for(k, r)
        if n < cheapest:
            lower.append((r, n))
            cheapest = n
    fits = [f"resolution {r} at {n + cp} runs" for r, n in lower if n + cp <= max_runs]
    options = [f"raise max_runs to >= {required}"]
    if fits:
        options.append(f"accept a lower resolution and its named aliasing "
                       f"({'; '.join(fits)} fits)")
    options.append("screen fewer factors this epoch")
    return [
        f"design.screen.resolution={resolution} over {k} factors needs "
        f"{required} runs ({corners} corners + {cp} centre points), but "
        f"design.max_runs={max_runs} is lower. Options: "
        + "; ".join(f"({i}) {o}" for i, o in enumerate(options, 1))
        + ". Nous will not silently downgrade resolution to fit the budget."
    ]

def _mixed_screen_runs(design: dict, factors: list[dict], resolution: int):
    """``(corner runs, column count)`` of the mixed-level screen when some
    choice factor has more than two levels, else ``None`` (the two-level path
    and its exact ``min_runs_for`` apply)."""
    if not any(isinstance(f, dict) and f.get("type") == "choice"
               and len(f.get("levels") or []) > 2 for f in factors):
        return None
    try:
        from orchestrator.optimize.design import mixed_screen
        from orchestrator.optimize.factors import parse_factors

        d = mixed_screen(parse_factors(factors), resolution=int(resolution),
                         center_points=0)
    except ValueError:
        # Only an UNPARSEABLE factor block is another rule's job (stage-1
        # M10); any other failure of the construction propagates rather than
        # silently under-reporting the screen's run count.
        return None
    return len(d.points), len(d.factor_ids)


def _rule29_categorical_expansion(design: dict, factors: list[dict]) -> list[str]:
    """Rule 29 (WARNING, informational): what a multi-level choice factor costs.

    A choice factor with L > 2 levels is screened at EVERY level by the method
    of replacement (Addelman 1962; Wu & Hamada ch. 7): m = ceil(log2 L)
    pseudo-factor columns, L-1 df, and -- when L < 2^m -- collapsed
    combinations that run the first-declared levels twice as often. Stated so
    the author sees the expanded column count and the run cost before launch.
    """
    cats = [f for f in factors if isinstance(f, dict) and f.get("type") == "choice"
            and len(f.get("levels") or []) > 2]
    if not cats:
        return []
    res = int(((design or {}).get("screen") or {}).get("resolution", 5) or 5)
    mixed = _mixed_screen_runs(design, factors, res)
    if mixed is None:
        return []
    runs, cols = mixed
    from orchestrator.optimize.design import mixed_screen_options
    from orchestrator.optimize.factors import parse_factors

    opts = mixed_screen_options(parse_factors(factors), res)
    which = (f"the level-space full factorial ({opts['level_full']} runs; the "
             f"replacement fraction would need {opts['replacement']})"
             if opts["chosen"] == "level_full" else
             f"the replacement fraction ({opts['replacement']} runs; the "
             f"level-space full factorial would need {opts['level_full']})")
    out = []
    for f in cats:
        L = len(f["levels"])
        m = (L - 1).bit_length()
        coll = (f"; {2 ** m - L} surplus combination(s) collaps"
                f"e onto the first level(s) {f['levels'][:2 ** m - L]}, which run "
                f"twice as often" if L < 2 ** m else "; no collapsing")
        out.append(
            f"WARN: factor {f.get('id')!r} ({L} levels) is screened at every level "
            f"by the method of replacement: {m} pseudo-factor column(s), {L - 1} "
            f"df main effect{coll}. The screen has {cols} two-level column(s); "
            f"Nous builds {which} (plus centre points).")
    return out


def _rule32_confirm_replicate_floor(opt: dict) -> list[str]:
    """Rule 32 (#321 P3, A5): confirm replicates against the registered floor.

    The floor (``policy.replicate_floor``) is the smallest replicate count at
    which the robust terminal bound exists at the per-look, per-challenger
    level. Single-objective confirm withholds ``replicates_below_floor`` below
    it, so a declared count under the floor gets a WARN naming that. Separately,
    a ``design.max_runs`` too small for ONE confirm round at the replicate count
    the campaign will actually use is an ERROR: the campaign could never reach
    a certificate, and it must not silently run fewer replicates.
    """
    if (opt.get("response") or {}).get("objectives"):
        return []
    stages = opt.get("stages")
    if isinstance(stages, list) and "confirm" not in stages:
        return []
    from orchestrator.optimize.policy import replicate_floor

    try:
        floor = replicate_floor(opt)
    except (TypeError, ValueError, ZeroDivisionError):
        return []      # an invalid delta is rule 14's to report
    design = opt.get("design") or {}
    confirm = design.get("confirm") or {}
    declared = confirm.get("replicates")
    reps = declared if isinstance(declared, int) and not isinstance(declared, bool) \
        and declared > 0 else floor
    out: list[str] = []
    if reps < floor:
        out.append(
            f"WARN: design.confirm.replicates={reps} is below the replicate floor "
            f"{floor} (the smallest n at which the exact sign-flip terminal bound "
            f"exists at delta_terminal / (looks x challengers)). Confirm will "
            f"measure but withhold certification as replicates_below_floor. "
            f"Raise it to >= {floor}, or omit it (the default is the floor).")
    # A `chance:<a>` constraint is shown only when the one-sided
    # Clopper-Pearson bound at delta_feasibility / (S C L) can reach a even
    # with ZERO violations: n >= log(level) / log(1 - a).
    import math as _m
    pol_cfg = opt.get("policy") or {}
    _dt = pol_cfg.get("delta_feasibility", pol_cfg.get("delta_terminal", 0.05))
    _cons = (opt.get("response") or {}).get("constraints") or []
    _dist = [c for c in _cons if isinstance(c, dict)
             and c.get("semantics", "every_replicate") != "every_replicate"]
    _seats0 = int(confirm.get("shortlist_size", 3)) + (
        1 if opt.get("known_valid_baseline") else 0)
    from orchestrator.optimize.policy import _registered_looks
    for c in _dist:
        sem = str(c.get("semantics"))
        if not sem.startswith("chance:"):
            continue
        try:
            a = float(sem.split(":", 1)[1])
            level = float(_dt) / (_seats0 * len(_dist) * _registered_looks(opt))
            need = _m.ceil(_m.log(level) / _m.log(1.0 - a))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if reps < need:
            out.append(
                f"WARN: constraint {c.get('metric') or c.get('observable')!r} has "
                f"semantics {sem}: the one-sided Clopper-Pearson bound at "
                f"delta_feasibility / (finalists x constraints x looks) = {level:.3g} "
                f"cannot reach {a} with fewer than {need} replicates even with no "
                f"violation, so confirm with {reps} can never show it feasible. "
                f"Raise design.confirm.replicates to >= {need}, or use semantics: mean.")
    mr = design.get("max_runs")
    seats = int(confirm.get("shortlist_size", 3)) + (
        1 if opt.get("known_valid_baseline") else 0)
    if isinstance(mr, int) and not isinstance(mr, bool) and mr > 0 and mr < seats * reps:
        out.append(
            f"design.max_runs ({mr}) cannot cover one confirm round: {seats} seat(s) x "
            f"{reps} replicate(s) = {seats * reps} runs, before any screen run. "
            f"Raise max_runs, or reduce design.confirm.shortlist_size.")
    return out


def _rule33_reuse_screen_with_choice_factor(design: dict, factors: list[dict],
                                           stages=None) -> list[str]:
    """Rule 33 (#321 P4 item 4): ``design.refine.reuse_screen`` with a choice
    factor is an ERROR, and partial reuse across choice slices is REJECTED.

    Refine fits ONE slice of each choice factor (the held level). A screen row
    measured at another level of that factor carries (a) the factor's main
    effect and (b) every interaction of it with the refined numerics, and the
    per-slice second-order model has no column for either. Reusing such rows
    biases every coefficient they load on. A block indicator absorbs only a
    CONSTANT shift between the slices, never the slice-by-numeric interactions
    (Box & Draper 2007, §15.3: blocking is valid only when block effects are
    additive). That is the REJECTION.

    A narrower variant, reusing only screen rows measured AT the held level,
    would be unbiased under the no-drift assumption (same configuration), and
    is DECLINED rather than rejected: at most 1/L of the screen's corners lie
    on the slice, and the screen's centre rows cycle the choice levels
    (``matrix.centre_configurations``), so the slice gets only
    ``center_points / g`` block-1 centres to estimate the block effect from.
    The runtime refuses either way (``stage_runner._screen_reuse``); this rule
    stops an author from declaring an option that cannot take effect.
    """
    if not isinstance(design, dict):
        return []
    refine = design.get("refine")
    if not isinstance(refine, dict) or not refine.get("reuse_screen"):
        return []
    if isinstance(stages, list) and "refine" not in stages:
        return []      # refine never runs: the option is inert, nothing to reject
    choice = [f.get("id") for f in factors
              if isinstance(f, dict) and f.get("type") == "choice"]
    if not choice:
        return []
    return [
        f"design.refine.reuse_screen is true but choice factor(s) {choice} are "
        f"declared. Partial reuse across choice slices is rejected: screen rows "
        f"at another level of a choice factor carry that factor's effect AND its "
        f"interactions with the refined numerics, which the per-slice refine "
        f"model cannot estimate, so reusing them biases the slice fit; a block "
        f"term absorbs only a constant shift, not those interactions. Remove "
        f"reuse_screen (every refine row is then measured), or, if the choice "
        f"factor is not under study, remove it from factors and pin it in the "
        f"workload instead."
    ]


def _rule34_confirm_allocate(opt: dict) -> list[str]:
    """Rule 34 (WP-D D1 / P6b): the opt-in ``design.confirm.allocate`` round.

    ERRORS (a campaign that could never use the branch, or whose extra look
    makes every confirm round uncertifiable, is refused, never compiled):

    * ``allocate_seats_exceed_shortlist``: the allocate round seats within
      ``shortlist_size``, so ``seats`` above it can never be honoured;
    * ``allocate_without_confirm``: ``stages`` omits confirm;
    * ``allocate_look_below_replicate_floor``: the extra look is charged to
      every confirm divisor and so raises the P3 replicate floor
      (``policy.replicate_floor``). A DECLARED ``design.confirm.replicates``
      that met the floor without the branch and misses it with the branch
      would make every round withhold ``replicates_below_floor`` -- declaring
      allocation would make certification impossible. (Omitting replicates
      takes the raised floor, so the defaults always remain certifiable.)
    """
    design = opt.get("design") or {}
    confirm = design.get("confirm") or {}
    a = confirm.get("allocate")
    if a is None:
        return []
    if not isinstance(a, dict):
        return [f"optimization.design.confirm.allocate must be a mapping "
                f"{{seats: k}}, got {a!r}."]
    errs = []
    seats = a.get("seats")
    if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
        errs.append(f"optimization.design.confirm.allocate.seats={seats!r} must be "
                    f"an integer >= 1.")
        return errs
    mo = bool((opt.get("response") or {}).get("objectives"))
    k = confirm.get("shortlist_size")
    if not isinstance(k, int) or isinstance(k, bool):
        k = 2 * len((opt.get("response") or {}).get("objectives") or []) + 2 if mo else 3
    if seats > k:
        errs.append(f"allocate_seats_exceed_shortlist: design.confirm.allocate.seats="
                    f"{seats} exceeds shortlist_size={k}; the allocate round seats "
                    f"within the shortlist, so lower seats or raise shortlist_size.")
    stages = opt.get("stages")
    if isinstance(stages, list) and "confirm" not in stages:
        errs.append("allocate_without_confirm: design.confirm.allocate is declared "
                    "but stages omits confirm, so the round can never run.")
    reps = confirm.get("replicates")
    if not mo and isinstance(reps, int) and not isinstance(reps, bool):
        from orchestrator.optimize.policy import replicate_floor

        try:
            with_a = replicate_floor(opt)
            without = {**opt, "design": {**design, "confirm": {
                kk: v for kk, v in confirm.items() if kk != "allocate"}}}
            base = replicate_floor(without)
        except (TypeError, ValueError, ZeroDivisionError):
            return errs
        if base <= reps < with_a:
            errs.append(
                f"allocate_look_below_replicate_floor: the allocate branch adds one "
                f"confirm look, which raises the replicate floor from {base} to "
                f"{with_a}; design.confirm.replicates={reps} would then withhold "
                f"every round as replicates_below_floor. Raise replicates to >= "
                f"{with_a}, omit it (the default is the floor), or drop allocate.")
    return errs


def _rule30_mixed_resolution_three_foldover(opt: dict, design: dict,
                                            factors: list[dict]) -> list[str]:
    """Rule 30: no resolution-III screen with a multi-level categorical while
    the registered foldover is on (stage-1 M3).

    A foldover of a resolution-III TWO-level screen negates every column and
    clears every 2fi~main alias (odd-length words die). With a multi-level
    categorical it does not: its contrast components are products of
    pseudo-columns, so a word such as ``C[12]AE`` (four columns) survives the
    negation and the "resolved" campaign still carries 2fi~main aliasing.
    Screen at resolution IV (every main-effect component clear of every 2fi),
    or switch the foldover off with ``policy.foldover: false``.
    """
    res = ((design or {}).get("screen") or {}).get("resolution")
    if res != 3 or not any(isinstance(f, dict) and f.get("type") == "choice"
                           and len(f.get("levels") or []) > 2 for f in factors):
        return []
    if not bool(((opt or {}).get("policy") or {}).get("foldover", True)):
        return []
    try:
        from orchestrator.optimize.design import mixed_screen_options
        from orchestrator.optimize.factors import parse_factors

        if mixed_screen_options(parse_factors(factors), 3)["chosen"] == "level_full":
            # The screen Nous builds is the level-space full factorial, which
            # aliases nothing: there is no aliasing for a fold to clear (N10).
            return []
    except ValueError as exc:
        # Unparseable factors (other rules report them): say THAT, rather than
        # a foldover verdict that rests on a screen nobody could build (P9).
        return [f"rule 30 could not build the screen to check resolution-III "
                f"foldover aliasing, because the factors do not parse: {exc}"]
    return [
        "design.screen.resolution=3 with a multi-level choice factor and the "
        "registered foldover on: a full foldover of a mixed-level screen does "
        "not clear two-factor-interaction~main-effect aliasing (a categorical's "
        "contrast is a product of its pseudo-factor columns, so words through "
        "it survive the negation). Use resolution 4, or set policy.foldover: "
        "false to accept resolution-III aliasing without a fold."]


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
                "delta_terminal, confirm_max_rounds, out_of_hull)."]
    errors: list[str] = []
    for key in ("delta_screen", "delta_terminal", "delta_constraint"):
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
    cd = pol.get("campaign_delta")
    if cd is not None:
        # #321 item 7: the charged cross-epoch budget.
        if not isinstance(cd, dict) or not isinstance(cd.get("total"), (int, float)) \
                or isinstance(cd.get("total"), bool) or not 0.0 < float(cd["total"]) <= 0.5:
            errors.append("optimization.policy.campaign_delta must be {total: D, "
                          "schedule: geometric | [d_1, d_2, ...]} with D in (0, 0.5].")
        else:
            sched = cd.get("schedule", "geometric")
            if sched != "geometric":
                if (not isinstance(sched, list) or not sched or any(
                        not isinstance(x, (int, float)) or isinstance(x, bool)
                        or not x > 0 for x in sched)):
                    errors.append("optimization.policy.campaign_delta.schedule must be "
                                  "'geometric' or a non-empty list of positive shares.")
                elif sum(float(x) for x in sched) > float(cd["total"]) + 1e-12:
                    errors.append(
                        f"optimization.policy.campaign_delta.schedule sums to "
                        f"{sum(float(x) for x in sched):g}, above total "
                        f"{float(cd['total']):g}: the union bound over epochs would "
                        f"not hold.")
    eps = pol.get("epsilon")
    if eps is not None:
        from orchestrator.optimize.objectives import is_epsilon_map

        if not isinstance(eps, dict):
            errors.append(
                "optimization.policy.epsilon must be a mapping with exactly one "
                "of abs (metric units) or pct (percent of the recommendation's "
                "value), e.g. {pct: 2.0}."
            )
        else:
            # The map form (objective metric -> spec) is checked entry by
            # entry; whether its keys are objectives at all is rule 26's.
            specs = (sorted(eps.items()) if is_epsilon_map(eps)
                     else [(None, eps)])
            for key, spec in specs:
                where = ("optimization.policy.epsilon" if key is None
                         else f"optimization.policy.epsilon.{key}")
                has = [k for k in ("abs", "pct") if k in spec]
                if len(has) != 1:
                    errors.append(
                        f"{where} declares {has or 'neither'} of "
                        f"abs/pct; it must declare EXACTLY ONE. With both, "
                        f"resolve_epsilon uses abs and silently discards pct — one "
                        f"of the two thresholds you wrote would never apply. With "
                        f"neither, the indifference width falls to the pct: 2.0 "
                        f"default rather than to anything you stated."
                    )
    if "out_of_hull" in pol and pol["out_of_hull"] not in ("confirm", "end_epoch"):
        errors.append(
            f"optimization.policy.out_of_hull={pol['out_of_hull']!r} must be "
            f"'confirm' (confirm the best configuration inside the declared "
            f"ranges -- the default) or 'end_epoch' (end the epoch so the ranges "
            f"can be widened first)."
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


def _rule31_validate_block(opt: dict) -> list[str]:
    """Rule 31 (#321 item 2): ``design.validate`` needs a
    ``known_valid_baseline`` and a single-objective campaign -- the block
    measures the winner's gain OVER the baseline, and a front has no single
    winner. Refusing beats compiling a block that silently never runs."""
    v = ((opt.get("design") or {}).get("validate"))
    if v is None:
        return []
    errs = []
    if not opt.get("known_valid_baseline"):
        errs.append("optimization.design.validate needs optimization.known_valid_baseline: "
                    "the block measures the winner's gain over the baseline.")
    if (opt.get("response") or {}).get("objectives"):
        errs.append("optimization.design.validate is single-objective only: a "
                    "multi-objective campaign has a front, not one winner to validate.")
    r = (v or {}).get("replicates") if isinstance(v, dict) else None
    if not isinstance(r, int) or isinstance(r, bool) or r < 2:
        errs.append(f"optimization.design.validate.replicates={r!r} must be an integer "
                    f">= 2 (a variance estimate needs two).")
    return errs + _rule31_pinned_seeds_are_fresh(opt)


def _rule31_pinned_seeds_are_fresh(opt: dict) -> list[str]:
    """Pinned ``workload.seeds`` with a post-selection block (P2 review H1).

    ``validate`` and ``inertness`` report numbers that must not come from the
    draws that selected the winner. Pinned seeds are used as ``seeds[i % len]``,
    so they get fresh draws only when the list is long enough to hold every
    confirm replicate AND these blocks' replicates after it."""
    design = opt.get("design") or {}
    seeds = ((opt.get("workload") or {}).get("seeds")) or []
    if not seeds:
        return []

    def _reps(block):
        r = (block or {}).get("replicates") if isinstance(block, dict) else None
        return r if isinstance(r, int) and not isinstance(r, bool) and r > 0 else 0

    post = _reps(design.get("validate")) + _reps(design.get("inertness"))
    if not post:
        return []
    confirm = design.get("confirm") or {}   # the compile reads design.confirm
    conf_reps = _reps(confirm) or 3
    need = conf_reps + post
    if len(seeds) >= need:
        return []
    return [f"optimization.workload.seeds has {len(seeds)} seed(s), but design.validate / "
            f"design.inertness need fresh draws: {conf_reps} confirm replicate(s) plus "
            f"{post} post-selection replicate(s) = {need}. With fewer, those blocks would "
            f"re-measure the winner on the draws that selected it. Declare at least "
            f"{need} seeds, or omit workload.seeds so seeds are derived per iteration."]


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
    ho = wl.get("held_out_seeds")
    if ho is not None:
        if (not isinstance(ho, list) or not ho
                or any(not isinstance(x, int) or isinstance(x, bool) for x in ho)):
            errors.append(
                f"optimization.workload.held_out_seeds={ho!r} must be a non-empty "
                f"list of integers, or absent.")
        else:
            shared = sorted(set(ho) & set(s for s in (seeds or []) if isinstance(s, int)))
            if shared:
                errors.append(
                    f"optimization.workload.held_out_seeds {shared} also appear in "
                    f"workload.seeds, so the measured rows already ran those draws: "
                    f"they are not held out, and the gain on them is not a "
                    f"generalization check. Choose seeds outside workload.seeds.")
            if not opt.get("known_valid_baseline"):
                errors.append(
                    "WARN: optimization.workload.held_out_seeds is declared but there "
                    "is no known_valid_baseline to pair the winner with, so the "
                    "held-out block will decline (no_baseline) and spend nothing.")
            if (opt.get("response") or {}).get("objectives"):
                errors.append(
                    "WARN: optimization.workload.held_out_seeds is declared on a "
                    "multi-objective campaign; a front has no single winner, so the "
                    "held-out block will decline (multi_objective).")
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
    ceiling on rows; otherwise the rows of the screen ``_build_design`` will
    build -- the resolution-R design's corners (``min_runs_for``, R defaulting
    to 5) plus its centre points (``_screen_rows``). A foldover, refine and
    confirm rounds push the true total higher still, so the figure quoted is
    a floor on the exposure, not an estimate of it.

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
        rows = _screen_rows(design, k) if k else None
        if rows is None:
            return []
        runs, basis = rows
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


#: Interpreters whose ``-c`` argument IS a shell script. A command that starts
#: with one of these and passes ``-c`` asked for a shell on purpose, so its
#: script's metacharacters are the shell's to interpret, not ours to flag.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})

#: Unquoted operators that only a shell gives meaning to, longest first so
#: ``&&`` is reported as ``&&`` rather than as two ``&``.
_SHELL_OPERATORS = ("&&", "||", "$(", ">>", "|", ";", ">", "<", "`", "&")


def _unquoted_shell_syntax(command: str) -> list[str]:
    """Shell operators appearing OUTSIDE quotes in ``command``, in order.

    Scanned by hand rather than read off ``shlex.split``'s tokens, because the
    tokens lose exactly the distinction that matters: ``-run 'TestA|TestB'`` and
    ``a | b`` both yield a token containing ``|``, but only the second is a
    pipe, and ``\\;`` (``find -exec``'s terminator) splits to the same ``;`` a
    real separator does. Tracking quotes and backslashes keeps every
    deliberately quoted metacharacter -- a regex, a filter expression, a
    ``python -c`` one-liner -- out of the error.

    Double quotes are NOT a shelter for ``$(`` and backticks: a shell would
    still substitute inside them, so an author who wrote ``"$(date)"`` expected
    a substitution that ``shlex`` will never perform.
    """
    found: list[str] = []
    i, n = 0, len(command)
    single = double = False
    while i < n:
        c = command[i]
        if single:
            single = c != "'"
            i += 1
            continue
        if c == "\\":
            i += 2  # the escaped character is literal, in or out of quotes
            continue
        if c == "'" and not double:
            single = True
            i += 1
            continue
        if c == '"':
            double = not double
            i += 1
            continue
        for op in _SHELL_OPERATORS:
            if not command.startswith(op, i):
                continue
            if double and op not in ("$(", "`"):
                continue
            # `2>` / `2>&1`: report the redirect, not a stray background `&`.
            if op == "&" and i > 0 and command[i - 1] == ">":
                break
            if op not in found:
                found.append(op)
            i += len(op) - 1
            break
        i += 1
    return found


def _rule23_commands_are_argv_not_shell(opt: dict) -> list[str]:
    """Rule 23: ``test_command`` / ``run_command`` must not use shell syntax.

    Neither is run in a shell. ``runner.run_test_command`` and
    ``runner.make_config_runner`` both ``shlex.split`` the string and exec the
    argv with ``cwd=target_system.repo_path``. So shell syntax is not an error
    the target reports -- it is silently passed through as ARGUMENTS:
    ``cd /abs/r2 && python -m pytest tests/ -v`` runs the program ``cd`` (or, as
    a ``test_command`` prefixed by a runner, hands ``cd`` and ``&&`` to pytest
    as file names), and the campaign then reports every declared relation as
    unmatched with nothing pointing at the real cause. A real author rewrote a
    ``test_command`` into exactly that shape -- after the guide had described
    the field as a "shell command" -- and spent a full gate cycle learning it.

    HARD ERROR, because no reading of such a command is the one the author
    meant: a pipe, a redirect, a chain or a substitution cannot have its shell
    meaning under ``shlex``. Two prefix forms are flagged too, for the same
    reason: a leading ``cd`` (a shell builtin; there is no ``cd`` program to do
    what was intended, and ``cwd`` is already the repo) and a leading
    ``VAR=value`` (exec'd as the binary name -- ``env VAR=value ...`` is the
    argv spelling).

    Deliberately NOT flagged: globs (``*`` is a legitimate argument to ``go test
    -run`` and ``pytest -k``, so a glob check would refuse working commands),
    anything quoted or escaped, and an explicit ``sh -c '...'``, which is the
    supported way to ask for a shell. ``integrity_command`` is not checked
    because nothing in this branch executes it.
    """
    import shlex

    errors: list[str] = []
    for field in ("test_command", "run_command"):
        cmd = opt.get(field)
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        where = f"optimization.{field}"
        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            errors.append(
                f"{where} cannot be parsed by shlex.split ({exc}): {cmd!r}. It "
                f"is split into an argv exactly that way before it runs, so fix "
                f"the quoting.",
            )
            continue
        if not argv:
            continue
        if os.path.basename(argv[0]) in _SHELLS and "-c" in argv[1:]:
            continue
        found = _unquoted_shell_syntax(cmd)
        if argv[0] == "cd":
            found.insert(0, "a leading `cd`")
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            found.insert(0, f"a leading `{argv[0]}` assignment (use `env {argv[0]} ...`)")
        if not found:
            continue
        named = ", ".join(f if f.startswith("a leading") else f"`{f}`" for f in found)
        errors.append(
            f"{where} uses shell syntax ({named}) but is not run in a shell: it "
            f"is split into an argv by shlex.split and executed with "
            f"cwd=target_system.repo_path, so these reach the program as "
            f"literal arguments and the command does not do what it says: "
            f"{cmd!r}. Drop the shell syntax -- the working directory is "
            f"already the repo, so pass paths relative to it -- or, if a shell "
            f"is really needed, wrap the whole command: sh -c '...'.",
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
    errors.extend(_rule11a_plan_stage_position(opt))
    errors.extend(_rule12_missing_native_tests_need_build(campaign, opt, factors))
    errors.extend(_rule13_known_valid_baseline(opt, factors))
    errors.extend(_rule14_policy_ranges(opt))
    errors.extend(_rule15_build_requires_baseline(opt))
    errors.extend(_rule16_workload_seed_env(opt))
    errors.extend(_rule17_config_patch_path_reachable(campaign, opt, factors))
    errors.extend(_rule18_high_run_timeout_warning(opt, factors))
    errors.extend(_rule19_max_parallel_oversubscription(opt))
    errors.extend(_rule31_validate_block(opt))
    errors.extend(_rule20_self_check_is_a_real_invariant(opt))
    errors.extend(_rule21_concurrency_declaration(opt))
    errors.extend(_rule22_completion_budgets(opt, factors))
    errors.extend(_rule23_commands_are_argv_not_shell(opt))
    errors.extend(_rule24_integer_levels_without_grid(factors))
    errors.extend(_rule25_geometric_levels_without_log_scale(factors))
    errors.extend(_rule27_levels_only(factors))
    errors.extend(_rule28_centre_points_cover_choice_levels(design, factors))
    errors.extend(_rule29_categorical_expansion(design, factors))
    errors.extend(_rule30_mixed_resolution_three_foldover(opt, design, factors))
    errors.extend(_rule26_objectives(opt))
    errors.extend(_rule32_confirm_replicate_floor(opt))
    errors.extend(_rule33_reuse_screen_with_choice_factor(design, factors, opt.get("stages")))
    errors.extend(_rule34_confirm_allocate(opt))
    errors.extend(_check_mechanism_paths_are_literal(opt))
    # #246/F1 on the matrix path: locked-vs-factor collision, typo'd
    # locked_observables keys, and a WARN naming every unenforceable lock.
    from orchestrator.optimize.locked import validation_findings as _locked_rules
    errors.extend(_locked_rules(campaign))
    # A build stage must declare where it may write (build_scope.py).
    from orchestrator.optimize.build_scope import validation_findings as _scope_rules
    errors.extend(_scope_rules(campaign))
    return errors


def _rule26_objectives(opt: dict) -> list[str]:
    """Rule 26: a multi-objective ``response`` must be coherent.

    ``response.objectives`` (spec ``2026-10-15-pareto-front-design.md``) asks
    for the trade-off FRONT between two or more responses. Every check below
    is a declaration that would otherwise run while meaning something other
    than what was written:

    * ``primary`` AND ``objectives`` -- which one is fitted is then a guess;
      neither -- nothing is fitted at all.
    * fewer than two DISTINCT objective metrics (ignoring case/whitespace):
      a front over one metric is a ranking, and two spellings of one metric
      make every point trivially non-dominated on one of them.
    * an objective that is also a constraint: the constraint excludes the very
      configurations that trade it away, so the front is cut where the author
      asked for it to be explored. (held_out and self_check collisions are
      rules 2 and 20.)
    * ``preference.weights`` / ``order`` naming a non-objective, a weight that
      is not > 0, an ``order`` that is not a permutation of the objectives, or
      either key supplied under a method that ignores it -- a stated
      preference that would silently not apply.
    * map-form ``policy.epsilon`` / ``noise_estimate_pct`` keyed by a
      non-objective (a typo'd metric falls to the default unnoticed), or used
      without ``objectives`` (the single-objective path reads one spec, so the
      map would be ignored).
    """
    from orchestrator.optimize.objectives import is_epsilon_map

    response = (opt or {}).get("response")
    if not isinstance(response, dict):
        return []
    errors: list[str] = []
    has_primary = "primary" in response
    has_objectives = "objectives" in response
    pol = opt.get("policy") if isinstance(opt.get("policy"), dict) else {}
    eps = pol.get("epsilon")
    noise = response.get("noise_estimate_pct")

    if has_primary and has_objectives:
        errors.append(
            "optimization.response declares both primary and objectives; they "
            "are mutually exclusive. Keep primary for ONE objective (and "
            "express the other responses as constraints), or move primary into "
            "objectives (>= 2 entries) to measure the trade-off front."
        )
    elif not has_primary and not has_objectives:
        errors.append(
            "optimization.response declares neither primary nor objectives, so "
            "there is nothing to fit. Add primary: {metric, direction} for one "
            "objective, or objectives: [{metric, direction}, ...] (>= 2) for a "
            "trade-off front."
        )

    if not has_objectives:
        if response.get("preference") is not None:
            errors.append(
                "optimization.response.preference is declared without "
                "response.objectives. preference chooses one point of a "
                "multi-objective front; a single primary objective has no "
                "front to choose from. Remove it, or declare objectives."
            )
        if is_epsilon_map(eps):
            errors.append(
                f"optimization.policy.epsilon is a per-objective map "
                f"({sorted(eps)}) but the campaign has a single primary "
                f"objective, which reads ONE spec -- the map would be ignored "
                f"and the default {{pct: 2.0}} used instead. Write one spec, "
                f"e.g. {{pct: 2.0}} or {{abs: 0.5}}."
            )
        if isinstance(noise, dict):
            errors.append(
                "optimization.response.noise_estimate_pct is a per-objective "
                "map but the campaign has a single primary objective; write "
                "one number (percent of the primary metric)."
            )
        return errors

    raw = response.get("objectives")
    if not isinstance(raw, list):
        return errors + ["optimization.response.objectives must be a list of "
                         "{metric, direction} entries (>= 2)."]
    metrics: list[str] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or not isinstance(entry.get("metric"), str) \
                or not entry.get("metric"):
            errors.append(
                f"optimization.response.objectives[{i}] must be "
                f"{{metric: <name>, direction: maximize|minimize}}."
            )
            continue
        if entry.get("direction") not in ("maximize", "minimize"):
            errors.append(
                f"optimization.response.objectives[{i}] ({entry['metric']!r}) "
                f"has direction {entry.get('direction')!r}; it must be "
                f"maximize or minimize."
            )
        metrics.append(entry["metric"])
    seen: dict[str, str] = {}
    for m in metrics:
        n = _norm_metric(m)
        if n in seen:
            errors.append(
                f"optimization.response.objectives names {seen[n]!r} and {m!r}, "
                f"which are the same metric (ignoring case/whitespace). Each "
                f"objective must be a DISTINCT response; a front over one "
                f"metric twice is a ranking in disguise."
            )
        else:
            seen[n] = m
    if len(seen) < 2:
        errors.append(
            f"optimization.response.objectives needs >= 2 distinct metrics "
            f"(got {len(seen)}). For one objective use response.primary "
            f"instead; a trade-off front needs at least two things to trade."
        )
    norms = set(seen)

    for c in response.get("constraints") or []:
        if not isinstance(c, dict):
            continue
        cm = c.get("metric") or c.get("observable")
        if _norm_metric(cm) in norms:
            errors.append(
                f"optimization.response.constraints bounds {cm!r}, which is "
                f"also one of response.objectives. Declare it as ONE of the "
                f"two: a constraint when you already know the acceptable bound "
                f"(admissibility -- the configurations past it are excluded), "
                f"or an objective when you want to see what trading it buys "
                f"(the front). As both, the constraint cuts off the very part "
                f"of the front the objective asks to explore."
            )

    pref = response.get("preference")
    if isinstance(pref, dict):
        method = pref.get("method")
        weights = pref.get("weights")
        order = pref.get("order")
        if method == "weights":
            if not isinstance(weights, dict) or not weights:
                errors.append(
                    "optimization.response.preference.method is weights but no "
                    "weights are declared. Add weights: {<objective metric>: "
                    "<weight > 0>, ...}, or use method: knee (no weights needed)."
                )
        elif weights is not None:
            errors.append(
                f"optimization.response.preference.weights is declared but "
                f"method is {method!r}, which ignores it -- the weights you "
                f"wrote would never apply. Set method: weights, or remove "
                f"weights."
            )
        if isinstance(weights, dict):
            for k, w in sorted(weights.items(), key=lambda kv: str(kv[0])):
                if _norm_metric(k) not in norms:
                    errors.append(
                        f"optimization.response.preference.weights names "
                        f"{k!r}, which is not an objective metric "
                        f"({', '.join(metrics)})."
                    )
                if (not isinstance(w, (int, float)) or isinstance(w, bool)
                        or not w > 0):
                    errors.append(
                        f"optimization.response.preference.weights.{k} = {w!r} "
                        f"must be a number > 0. An objective that should not "
                        f"count does not belong in objectives."
                    )
            missing = [m for m in metrics
                       if _norm_metric(m) not in {_norm_metric(k) for k in weights}]
            if method == "weights" and missing:
                errors.append(
                    f"WARN: optimization.response.preference.weights omits "
                    f"objective(s) {', '.join(missing)}, so they carry weight 0 "
                    f"in choosing the recommendation (the front still reports "
                    f"them). Give each objective an explicit weight."
                )
        if method == "lexicographic":
            if not isinstance(order, list) or not order:
                errors.append(
                    "optimization.response.preference.method is lexicographic "
                    "but no order is declared. Add order: [<most important "
                    "objective>, ...], a permutation of the objective metrics."
                )
        elif order is not None:
            errors.append(
                f"optimization.response.preference.order is declared but "
                f"method is {method!r}, which ignores it. Set method: "
                f"lexicographic, or remove order."
            )
        if isinstance(order, list) and order:
            onorm = [_norm_metric(x) for x in order]
            if sorted(onorm, key=str) != sorted(norms, key=str) \
                    or len(set(onorm)) != len(onorm):
                errors.append(
                    f"optimization.response.preference.order {order} must be a "
                    f"permutation of the objective metrics ({', '.join(metrics)}): "
                    f"each exactly once."
                )

    if is_epsilon_map(eps):
        for k in sorted(eps):
            if _norm_metric(k) not in norms:
                errors.append(
                    f"optimization.policy.epsilon.{k}: {k!r} is not an "
                    f"objective metric ({', '.join(metrics)}). A per-objective "
                    f"epsilon map is keyed by objective metric; a typo here "
                    f"leaves the real objective at the {{pct: 2.0}} default."
                )
        omitted = [m for m in metrics
                   if _norm_metric(m) not in {_norm_metric(k) for k in eps}]
        if omitted:
            errors.append(
                f"WARN: optimization.policy.epsilon map omits objective(s) "
                f"{', '.join(omitted)}, which take the {{pct: 2.0}} default "
                f"indifference width. State each objective's width explicitly."
            )
    if isinstance(noise, dict):
        for k in sorted(noise):
            if _norm_metric(k) not in norms:
                errors.append(
                    f"optimization.response.noise_estimate_pct.{k}: {k!r} is "
                    f"not an objective metric ({', '.join(metrics)})."
                )
    # Two keys that fold to ONE objective: the runtime resolves keys to the
    # declared names, so one of the two values would silently win (or, with
    # no exact match, both would be dropped for the default).
    for where, mapping in (("optimization.response.preference.weights",
                            pref.get("weights") if isinstance(pref, dict) else None),
                           ("optimization.policy.epsilon", eps if is_epsilon_map(eps) else None),
                           ("optimization.response.noise_estimate_pct", noise)):
        if not isinstance(mapping, dict):
            continue
        groups: dict = {}
        for k in mapping:
            groups.setdefault(_norm_metric(k), []).append(k)
        for keys in groups.values():
            if len(keys) > 1:
                errors.append(
                    f"{where} names one objective more than once "
                    f"({', '.join(repr(k) for k in sorted(keys, key=str))}): keys "
                    f"are matched ignoring case and surrounding spaces, so only "
                    f"one value could apply. Keep exactly one."
                )
    return errors


def _rule27_levels_only(factors: list[dict]) -> list[str]:
    """Rule 27: ``levels_only`` must be coherent (spec 2026-10-16, feature 2).

    HARD ERRORS -- the same refusals ``factors.parse_factors`` makes, stated
    here so ``nous validate`` reports them with the rest instead of the epoch
    discovering them at compile:

    * with ``grid``: two declarations of the runnable set that disagree
      (``grid: 1`` admits 65 between 64 and 128; ``levels_only`` does not);
    * on ``type: choice``: a choice factor already runs only its levels;
    * non-numeric or duplicate levels: nearest-level snapping is undefined.

    WARNING: on a two-level factor it changes nothing (a two-level numeric
    already runs only its pair), which usually means the author meant to list
    the interior levels too.
    """
    out: list[str] = []
    for f in factors:
        if not isinstance(f, dict) or "levels_only" not in f:
            continue
        fid = f.get("id", "<unknown>")
        flag = f.get("levels_only")
        if flag is not True:
            continue
        levels = list(f.get("levels") or [])
        if f.get("type") != "numeric":
            out.append(
                f"factor {fid!r}: levels_only applies to numeric factors only -- "
                f"a choice factor already runs only its declared levels. Remove "
                f"levels_only.")
            continue
        if f.get("grid") is not None:
            out.append(
                f"factor {fid!r}: levels_only and grid both declare the runnable "
                f"set and they disagree (grid {f.get('grid')!r} admits values "
                f"between the levels {levels}). Keep levels_only for a knob that "
                f"takes only the listed values, or grid for one that takes every "
                f"multiple of the step -- not both.")
            continue
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in levels) or len({float(v) for v in levels}) != len(levels):
            out.append(
                f"factor {fid!r}: levels_only needs distinct numeric levels (got "
                f"{levels}); the nearest declared level must be unique.")
            continue
        sl = f.get("screen_levels")
        if isinstance(sl, list) and len(sl) == 2 and all(
                isinstance(v, (int, float)) for v in sl):
            lo, hi = min(sl), max(sl)
            outside = [v for v in levels if not lo <= v <= hi]
            if outside:
                out.append(
                    f"WARN: factor {fid!r}: levels_only levels {outside} lie outside "
                    f"screen_levels {sl}, so they are never run or recommended (the "
                    f"runnable set is the declared levels inside the screen pair). "
                    f"Widen screen_levels or drop those levels.")
        if len(levels) <= 2:
            out.append(
                f"WARN: factor {fid!r} declares levels_only over {len(levels)} "
                f"levels {levels}: it changes nothing, because a two-level "
                f"numeric already runs only its pair. List the interior runnable "
                f"levels (e.g. every power of two between them) so refine can "
                f"use them, or drop levels_only.")
    return out


def _rule28_centre_points_cover_choice_levels(design: dict, factors: list[dict]) -> list[str]:
    """Rule 28 (WARNING): a choice level the screen's centre points never run.

    Centre points cycle the choice factors through their levels in
    ``g = max(1, min(lcm(L_j), floor(center_points / 2)))`` configurations
    (``matrix.centre_configurations``; spec 2026-10-16, feature 3), each
    replicated at least twice so pure error keeps its df. A level outside the
    first ``g`` gets no centre point, so the lack-of-fit test cannot see
    curvature under it -- the defect that made a bowl under ``C=on`` invisible
    when every centre ran ``C=off``. Reported from the same record the
    pre-registered ``design_matrix.json`` carries, so the two cannot disagree.
    """
    if not isinstance(design, dict) or not factors:
        return []
    try:
        from orchestrator.optimize.factors import parse_factors
        from orchestrator.optimize.matrix import centre_points_record
        from orchestrator.optimize.stage import Stage
        from orchestrator.optimize.stage_runner import _build_design

        parsed = parse_factors(factors)
        screen = _build_design(parsed, design, Stage.SCREEN.value)
        rec = centre_points_record(screen, parsed)
    except ValueError:
        # Only an unparseable block (reported by other rules) is skipped
        # (stage-1 M10); a construction failure propagates.
        return []
    if rec is None:
        return []
    return [f"WARN: {w}" for w in rec["warnings"]]


def _rule25_geometric_levels_without_log_scale(factors: list[dict]) -> list[str]:
    """Rule 25 (WARNING): levels that look geometric, coded linearly.

    Every numeric knob in three real campaigns was geometric (batch 100..5000,
    cache 2,000..64,000, interval 1..64), and linear coding put each centre
    point at the arithmetic midpoint -- 32.5 for [1, 64] -- so the design
    probed one end of the range and barely touched the region where the
    answer was. "Geometric" here: all levels positive, the range spans at
    least 10x, and the interior levels sit closer to the geometric mean than
    to the arithmetic one (or there are only two levels). It is a warning
    because a genuinely additive knob can span 10x too; ``scale: linear``
    states that explicitly and silences it.
    """
    import math

    warnings: list[str] = []
    for f in factors:
        levels = f.get("levels") or []
        if f.get("type") != "numeric" or "scale" in f or len(levels) < 2:
            continue
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and v > 0 for v in levels):
            continue
        lo, hi = min(levels), max(levels)
        if hi / lo < 10:
            continue
        geo, ari = math.sqrt(lo * hi), (lo + hi) / 2
        interior = [v for v in levels if lo < v < hi]
        if interior and not all(abs(math.log(v / geo)) < abs(math.log(v / ari))
                                for v in interior):
            continue
        warnings.append(
            f"WARN: factor {f.get('id')!r} levels {levels} span {hi / lo:g}x and "
            f"look geometric, but are coded linearly: the centre point would be "
            f"{ari:g} (arithmetic), not {geo:.4g} (geometric), so the design "
            f"spends its interior on one end of the range. Declare `scale: log` "
            f"for a size / batch / interval knob, or `scale: linear` to keep "
            f"linear coding deliberately.",
        )
    return warnings


def _rule24_integer_levels_without_grid(factors: list[dict]) -> list[str]:
    """Rule 24 (WARNING): an all-integer refinable factor with no ``grid``.

    ``refine`` places interior and axial points by interpolation, so a factor
    declared ``[8, 20, 32]`` can be asked to run at 23.4. Whole numbers already
    render as integers (``factors._integral_as_int``), but a fractional point
    still reaches the command line as a float, and an integer-only target
    rejects it as a usage error -- one failed row per such point, discovered
    mid-epoch. Nous cannot know whether the knob accepts fractions (a threshold
    may), so this warns rather than guessing; ``grid: 1`` is the declaration
    that settles it.
    """
    warnings: list[str] = []
    for f in factors:
        levels = f.get("levels") or []
        if (f.get("type") != "numeric" or f.get("grid") is not None
                or f.get("levels_only") is True or len(levels) <= 2):
            # levels_only is the right declaration for an integer knob that
            # takes only the listed values: refine never interpolates it.
            continue
        if all(isinstance(lv, int) and not isinstance(lv, bool) for lv in levels):
            warnings.append(
                f"WARN: factor {f.get('id')!r} declares only integer levels "
                f"{levels} and no grid, so refine can run it at a fractional "
                f"value (e.g. {(levels[0] + levels[1]) / 2 + 0.4:g}), which an "
                f"integer-only target rejects as a usage error. Add `grid: 1` "
                f"if the knob takes integers; leave it out only if fractional "
                f"values are genuinely runnable.",
            )
    return warnings


def _rule21_concurrency_declaration(opt: dict) -> list[str]:
    """Rule 21: a spending-stage concurrency claim must be coherent.

    Delegates to ``orchestrator.optimize.concurrency.check_declaration`` so the
    refusal and the resolution read the same declaration through one function --
    a validator that accepted a block the resolver then ignored would be the
    worst of both.

    HARD ERRORS, unlike rule 19's advisory oversubscription warning for
    ``confirm``. Rule 19 is advisory because it cannot see whether a
    ``run_command`` mostly WAITS on a remote service and so holds no core, and
    only the author knows. Under this block the width applies to the SPENDING
    stages, where the confound is first-order rather than cancelling, so an
    incoherent declaration is refused instead of warned about.

    Refusing at validation time rather than resolving quietly is the point.
    Silently running at 1 when the author asked for 8 costs a day of wall clock
    and explains nothing; silently running 8 uncertified corrupts the surface.
    Every message names the edit or the command that fixes it.
    """
    from orchestrator.optimize import concurrency

    return concurrency.check_declaration(opt)


#: A wall-clock budget below this is more likely a units mistake (minutes typed
#: as hours) than an intent: no real systems campaign screens a factorial design
#: in six minutes. Warned about, not refused -- a synthetic or simulator target
#: legitimately can.
LOW_WALL_CLOCK_HOURS = 0.1


def _rule22_completion_budgets(opt: dict, factors: list) -> list[str]:
    """Rule 22: the completion budgets must be able to complete something.

    Both fields exist because a real campaign spent ~14 hours producing zero
    usable output, and both fail in the same direction if declared carelessly:
    a budget too small to finish a single screen, or a failure threshold of 1,
    turns a robustness feature into a campaign that stops before it starts.

    ``max_wall_clock_hours`` is checked against the campaign's own declared
    exposure, reusing rule 18's run-count basis (``design.max_runs`` when the
    author stated one, else the rows of the resolution-R screen
    ``_build_design`` will build, centre points included). The comparison is
    against the ONE-ROW ceiling rather than
    the whole design: a budget that cannot fit even a single row at
    ``run_timeout_sec`` is an ERROR, because no rung of the fallback ladder can
    be reached from zero measurements -- the report would rest on
    ``known_valid_baseline`` or nothing at all. A budget that fits some rows but
    not the declared design is a WARNING, because that is a legitimate choice:
    the epoch ends cleanly and the report names an action from what was
    measured.

    ``max_identical_failures: 1`` is a WARNING rather than an error. It halts on
    the FIRST failure of any kind, which forecloses the ordinary case this
    machinery is built around -- a transient timeout that a retry repairs, on
    exactly the noisy systems targets this kind exists for. It is not refused
    because an author debugging an apparatus may genuinely want it.
    """
    out: list[str] = []

    raw_budget = opt.get("max_wall_clock_hours")
    if isinstance(raw_budget, (int, float)) and not isinstance(raw_budget, bool):
        budget_h = float(raw_budget)
        ceiling_sec = opt.get("run_timeout_sec")
        if not (isinstance(ceiling_sec, int) and not isinstance(ceiling_sec, bool)
                and ceiling_sec > 0):
            ceiling_sec = 600  # the documented default
        one_row_h = ceiling_sec / 3600.0

        if budget_h < one_row_h:
            out.append(
                f"optimization.max_wall_clock_hours={budget_h:g} is smaller than "
                f"the time ONE row is allowed to take "
                f"(run_timeout_sec={ceiling_sec}s = {one_row_h:.2f}h), so the "
                f"budget can expire before the first measurement completes. A "
                f"campaign with zero measured rows cannot reach any rung of the "
                f"fallback ladder above `baseline`, so the report it still "
                f"writes would name an action nothing in this epoch supports. "
                f"Raise the budget to at least a few multiples of the per-row "
                f"ceiling, or lower run_timeout_sec.",
            )
        else:
            design = opt.get("design") if isinstance(opt.get("design"), dict) else {}
            max_runs = design.get("max_runs")
            if (isinstance(max_runs, int) and not isinstance(max_runs, bool)
                    and max_runs > 0):
                runs, basis = max_runs, "design.max_runs"
            else:
                k = len(factors)
                runs, basis = (_screen_rows(design, k) if k else None) or (0, "")
            if runs:
                worst_h = runs * one_row_h
                if budget_h < worst_h:
                    out.append(
                        f"WARN: optimization.max_wall_clock_hours={budget_h:g} is "
                        f"below this campaign's worst-case exposure of "
                        f"{worst_h:.1f}h ({runs} run(s) from {basis} at "
                        f"{ceiling_sec}s each), so the budget can expire "
                        f"mid-design. That is a legitimate cap -- the epoch ends "
                        f"cleanly and report.json still names an action from what "
                        f"was measured -- but the recommendation would then rest "
                        f"on a PARTIAL design, and recommendation.basis will say "
                        f"so. Run --smoke (and --liveness) first: the real "
                        f"per-row duration is usually far below the ceiling, so "
                        f"the worst case quoted here is a bound rather than an "
                        f"estimate.",
                    )
        if budget_h < LOW_WALL_CLOCK_HOURS:
            out.append(
                f"WARN: optimization.max_wall_clock_hours={budget_h:g} is under "
                f"{LOW_WALL_CLOCK_HOURS:g}h ({budget_h * 60:.0f} minutes). If "
                f"minutes were intended, the field is in HOURS.",
            )

    raw_thresh = opt.get("max_identical_failures")
    if (isinstance(raw_thresh, int) and not isinstance(raw_thresh, bool)
            and raw_thresh == 1):
        out.append(
            "WARN: optimization.max_identical_failures=1 halts the campaign on "
            "the FIRST failed iteration, before any retry. On the noisy systems "
            "targets this kind exists for, a single wall-clock timeout or "
            "adapter hiccup is routinely repaired by re-running the "
            "configuration -- and with row reuse, the retry re-measures only the "
            "rows that actually failed. Keep 1 only while deliberately debugging "
            "an apparatus; the default of 3 is what bounds a genuinely "
            "deterministic loop.",
        )
    return out


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
    objectives = {
        str(o.get("metric")) for o in (response.get("objectives") or [])
        if isinstance(o, dict) and o.get("metric")
    } if isinstance(response.get("objectives"), list) else set()
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
                f"that definition uses: whenever the objective is the extremum "
                f"of a feasible set, the adapter had to decide membership, and "
                f"the self-check is that decision restated where Nous can "
                f"check it -- {{metric: residual_norm, op: '<=', value: 1e-8}} "
                f"for 'the coarsest mesh that still converged', or {{metric: "
                f"queue_growth_slope, op: '<=', value: 0.060}} for 'the "
                f"largest arrival rate whose backlog is not growing'."
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
        if path is not None and str(path) in objectives:
            errors.append(
                f"response.self_check entry is over {path!r}, which is one of "
                f"response.objectives. A self-check must read the DIAGNOSTIC "
                f"that defines an objective, never an objective itself: a "
                f"bound on an objective belongs in response.constraints -- "
                f"and then it should not also be an objective (declare it as "
                f"one or the other) -- or in response.ceiling. As a "
                f"self-check it would fail every row on the unattractive end "
                f"of the trade-off, deleting exactly the part of the front the "
                f"campaign exists to measure."
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
