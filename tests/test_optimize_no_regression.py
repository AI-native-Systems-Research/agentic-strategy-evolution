"""Regression gate: the reflective path is unchanged by ``kind: optimization``.

Twelve tasks added a ``kind: optimization`` campaign type. The whole design
rests on one claim: a campaign with no ``kind`` field, or ``kind: reflective``,
behaves exactly as it did before any of this landed. This file makes that
claim mechanically checkable.

This file adds NO production code. Its only job is to prove the guarantee.
If any test here fails, the optimization work has leaked into the shared
reflective path -- fix the leak, never the test.

No live LLM calls: uses StubDispatcher / patched HumanGate throughout, per
tests/CLAUDE.md and the autouse ``block_live_llm_calls`` fixture in
tests/conftest.py.
"""
from __future__ import annotations

import ast
import inspect
import json
import shutil
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.campaign import run_campaign
from orchestrator.dispatch import StubDispatcher
from orchestrator.engine import Engine
from orchestrator.iteration import run_iteration, setup_work_dir
from orchestrator.complexity_tier import format_tier_summary
from orchestrator.validate import (
    campaign_kind,
    validate_design,
    validate_optimization_campaign,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMAS_DIR = REPO_ROOT / "orchestrator" / "schemas"
TEMPLATES_DIR = REPO_ROOT / "orchestrator" / "templates"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


def _example_campaign_paths() -> list[Path]:
    paths = sorted(EXAMPLES_DIR.glob("*.yaml")) + sorted(EXAMPLES_DIR.glob("*.yml"))
    assert paths, f"expected at least one campaign yaml under {EXAMPLES_DIR}"
    return paths


EXAMPLE_CAMPAIGN_PATHS = _example_campaign_paths()


# ─── Assertion 1: every examples/ campaign validates against the schema ────


class TestExamplesValidateAgainstSchema:
    @pytest.mark.parametrize("path", EXAMPLE_CAMPAIGN_PATHS, ids=lambda p: p.name)
    def test_example_validates(self, path: Path) -> None:
        campaign = yaml.safe_load(path.read_text())
        schema = _load_campaign_schema()
        jsonschema.validate(campaign, schema)


# ─── Assertion 2: campaign_kind defaults to "reflective" for every example ──


class TestExamplesAreReflectiveByDefault:
    @pytest.mark.parametrize("path", EXAMPLE_CAMPAIGN_PATHS, ids=lambda p: p.name)
    def test_campaign_kind_is_reflective(self, path: Path) -> None:
        campaign = yaml.safe_load(path.read_text())
        assert campaign_kind(campaign) == "reflective"


# ─── Assertion 3: validate_optimization_campaign is a no-op for reflective ──


class TestValidateOptimizationCampaignNoOpOnReflective:
    @pytest.mark.parametrize("path", EXAMPLE_CAMPAIGN_PATHS, ids=lambda p: p.name)
    def test_no_errors_for_examples(self, path: Path) -> None:
        campaign = yaml.safe_load(path.read_text())
        assert "optimization" not in campaign
        errors = validate_optimization_campaign(campaign)
        assert errors == []

    def test_no_errors_for_minimal_reflective_dict(self) -> None:
        """A reflective campaign built from scratch, no `optimization` block."""
        campaign = {
            "research_question": "does X affect Y?",
            "target_system": {"name": "sys"},
        }
        assert validate_optimization_campaign(campaign) == []

    def test_no_errors_for_explicit_kind_reflective(self) -> None:
        campaign = {
            "kind": "reflective",
            "research_question": "does X affect Y?",
        }
        assert validate_optimization_campaign(campaign) == []


# ─── Assertion 4: validate_design on a fixed fixture matches known-good ────
#
# The fixture and its expected result are pinned by hand -- NOT captured
# from a run of the current code -- so a change that silently alters
# validate_design's reflective-path behavior fails this test instead of
# being absorbed into a fresh snapshot.


def _reflective_fixture_bundle() -> dict:
    return {
        "metadata": {
            "iteration": 1,
            "family": "no-regression-fixture",
            "research_question": "does batch size affect latency?",
        },
        "arms": [
            {
                "type": "h-main",
                "prediction": "larger batch size increases latency",
                "mechanism": "queueing delay grows with batch size",
                "diagnostic": "measure p50 latency at each batch size",
            },
            {
                "type": "h-control-negative",
                "prediction": "no effect",
                "mechanism": "baseline",
                "diagnostic": "measure p50 latency at default batch size",
            },
        ],
    }


def _write_reflective_fixture(tmp_path: Path) -> Path:
    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "problem.md").write_text(
        "# Problem\n\nDoes batch size affect latency?\n"
    )
    (iter_dir / "handoff_snapshot.md").write_text(
        "## Handoff\n### Goal\nMeasure latency vs batch size.\n"
    )
    (iter_dir / "bundle.yaml").write_text(
        yaml.safe_dump(_reflective_fixture_bundle(), sort_keys=False)
    )
    return iter_dir


class TestValidateDesignKnownGoodFixture:
    def test_matches_pinned_expected_result(self, tmp_path: Path) -> None:
        iter_dir = _write_reflective_fixture(tmp_path)
        result = validate_design(iter_dir)
        # Pinned expectation: this reflective fixture has always been
        # designed to pass cleanly with no errors and no warnings. If
        # the optimization work changes this, that is a regression.
        assert result["status"] == "pass"
        assert result.get("errors", []) == []
        assert result.get("warnings", []) == []


# ─── Assertion 5: resolve_gate_mode with no flags on reflective is False ───


class _Args:
    """Minimal stand-in for argparse.Namespace with only the attributes
    resolve_gate_mode reads."""

    def __init__(self, auto_approve=None, interactive=False):
        self.auto_approve = auto_approve
        self.interactive = interactive


class TestResolveGateModeReflectiveDefault:
    def test_no_flags_reflective_campaign_is_false(self) -> None:
        from orchestrator.cli import resolve_gate_mode

        campaign = {"research_question": "q?"}  # no kind -> reflective
        args = _Args(auto_approve=None, interactive=False)
        assert resolve_gate_mode(args, campaign) is False

    def test_no_flags_explicit_kind_reflective_is_false(self) -> None:
        from orchestrator.cli import resolve_gate_mode

        campaign = {"kind": "reflective", "research_question": "q?"}
        args = _Args(auto_approve=None, interactive=False)
        assert resolve_gate_mode(args, campaign) is False

    def test_build_parser_default_auto_approve_is_none_not_false(self) -> None:
        """The historical CLI flag was `action="store_true"` (default
        False). Task 12's brief requires the NEW default to still resolve
        to False for reflective campaigns -- but the flag itself must be
        None when omitted (not True), so resolve_gate_mode can distinguish
        "omitted" from "explicitly False". This pins that wiring."""
        from orchestrator.cli import build_parser

        parser = build_parser()
        # Parse a representative subcommand invocation with no
        # --auto-approve / --interactive flags supplied.
        args = parser.parse_args(["run", "examples/campaign.yaml"])
        assert getattr(args, "auto_approve", "MISSING") is None


# ─── Assertion 6: end-to-end reflective iteration via StubDispatcher ───────


SAMPLE_CAMPAIGN = {
    "research_question": "Does batch size affect latency?",
    "target_system": {
        "name": "TestSystem",
        "description": "A test system.",
        "observable_metrics": ["latency_ms"],
        "controllable_knobs": ["batch_size"],
    },
    "prompts": {
        "methodology_layer": "prompts/methodology",
        "domain_adapter_layer": None,
    },
}


def _setup_work_dir(tmp_path: Path) -> Path:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    for t in ["state.json", "ledger.json", "principles.json"]:
        shutil.copy(TEMPLATES_DIR / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test-campaign-no-regression"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))
    return work_dir


def _patch_for_stub(monkeypatch):
    import orchestrator.campaign as rc
    import orchestrator.iteration as ri

    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)
    monkeypatch.setattr(rc, "LLMDispatcher", stub_factory)


def _patch_gates_approve(monkeypatch):
    import orchestrator.campaign as rc
    import orchestrator.iteration as ri

    gate = MagicMock(prompt=MagicMock(return_value=("approve", None)))
    monkeypatch.setattr(ri, "HumanGate", lambda *a, **k: gate)
    monkeypatch.setattr(rc, "HumanGate", lambda *a, **k: gate)
    return gate


class TestEndToEndReflectiveIterationViaStub:
    def test_writes_full_artifact_set_and_ledger_row(self, tmp_path, monkeypatch):
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)
        _patch_gates_approve(monkeypatch)

        run_campaign(SAMPLE_CAMPAIGN, work_dir, max_iterations=1)

        iter_dir = work_dir / "runs" / "iter-1"
        assert (iter_dir / "bundle.yaml").exists()
        assert (iter_dir / "findings.json").exists()
        assert (iter_dir / "principle_updates.json").exists()

        engine = Engine(work_dir)
        assert engine.phase == "DONE"

        ledger = json.loads((work_dir / "ledger.json").read_text())
        iter_rows = [r for r in ledger["iterations"] if r["iteration"] > 0]
        assert len(iter_rows) == 1
        jsonschema.validate(
            ledger,
            json.loads((SCHEMAS_DIR / "ledger.schema.json").read_text()),
        )


# ─── Assertion 7: format_tier_summary still exercised on reflective path ───


class TestTierPanelStillRendersOnReflectivePath:
    def test_gate_panel_content_appears_for_reflective_campaign(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Drive a real reflective iteration (real HumanGate.prompt, which
        prints tier_panel) through the design gate and assert the tier
        panel text (issue #159) appears in stdout. This is the sister
        check to assertion 8: reflective keeps calling
        format_tier_summary; optimization must never reach that call site.
        """
        work_dir = _setup_work_dir(tmp_path)
        _patch_for_stub(monkeypatch)

        # Stub dispatcher writes a bundle without a tier by default; we
        # need the DESIGN-produced bundle.yaml to declare complexity_tier
        # so format_tier_summary has something to render. Patch the
        # StubDispatcher's dispatch to inject a complexity_tier into the
        # bundle it writes, then let the rest of the flow run for real
        # (including the *real* HumanGate, auto-approved via
        # auto_response="approve", so gate.prompt actually executes and
        # prints the tier panel).
        import orchestrator.dispatch as dispatch_mod

        original_dispatch = dispatch_mod.StubDispatcher.dispatch

        def dispatch_and_tag_tier(self, role, phase, *, output_path, iteration, **kw):
            original_dispatch(
                self, role, phase, output_path=output_path,
                iteration=iteration, **kw,
            )
            if phase == "design":
                iter_dir = output_path.parent if output_path.name != "" else output_path
                bundle_path = self.work_dir / "runs" / f"iter-{iteration}" / "bundle.yaml"
                if bundle_path.exists():
                    bundle = yaml.safe_load(bundle_path.read_text())
                    bundle.setdefault("metadata", {})["complexity_tier"] = 1
                    bundle["metadata"]["tier_justification"] = (
                        "single mechanism, single knob, treatment vs control"
                    )
                    bundle_path.write_text(yaml.safe_dump(bundle, sort_keys=False))

        monkeypatch.setattr(
            dispatch_mod.StubDispatcher, "dispatch", dispatch_and_tag_tier,
        )

        outcome = run_iteration(
            SAMPLE_CAMPAIGN, work_dir, iteration=1, final=True,
            auto_approve=True, agent="sdk",
        )
        from orchestrator.iteration import IterationOutcome
        assert outcome == IterationOutcome.COMPLETED

        captured = capsys.readouterr()
        assert "COMPLEXITY TIER" in captured.out
        assert "tier 1" in captured.out

        # Cross-check against format_tier_summary called directly, so the
        # test also pins the direct-call contract (not just the printed
        # side effect).
        direct = format_tier_summary(
            iteration=1,
            bundle_path=work_dir / "runs" / "iter-1" / "bundle.yaml",
            work_dir=work_dir,
        )
        assert "COMPLEXITY TIER" in direct
        assert direct != ""


# ─── Assertion 8: structural check -- delegation happens first, once ───────


class TestRunIterationDelegationIsStructural:
    """Deliberately structural (not behavioral): the property under test
    IS the source-level shape of run_iteration, not its runtime behavior.
    This is the single sanctioned exception to "behavioral tests only" in
    this repo's testing conventions -- see tests/CLAUDE.md and the task-12
    brief, which calls this out explicitly as assertion 8's justification.

    The property matters because it's what keeps an optimization campaign
    from ever touching reflective state machinery (Engine, HumanGate,
    LLMDispatcher construction, etc.): the delegation must be checked and
    returned from BEFORE any of that machinery is reached, and it must
    only be checked once.

    Uses ``ast`` rather than line-based text matching. A line-based check
    is fragile to reformatting: the real delegation's ``return run_stage(``
    call spans several lines, so a naive "does the last line start with
    'return '" check breaks on the closing paren alone. Parsing the AST
    and inspecting statement nodes is immune to line wrapping, comment
    placement, and other cosmetic changes that must not make this gate
    flap.
    """

    def _find_delegation_if(self, tree: ast.FunctionDef) -> list[ast.If]:
        matches = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "campaign_kind" in ast.unparse(node.test) \
                    and "optimization" in ast.unparse(node.test):
                matches.append(node)
        return matches

    def test_delegation_appears_in_prologue_and_returns_immediately(self) -> None:
        source = inspect.getsource(run_iteration)
        tree = ast.parse(source.lstrip()).body[0]
        assert isinstance(tree, ast.FunctionDef)

        # Exactly one `if campaign_kind(campaign) == "optimization":` in
        # the whole function body.
        matches = self._find_delegation_if(tree)
        assert len(matches) == 1, (
            f"expected exactly one optimization-kind delegation `if`, "
            f"found {len(matches)}"
        )
        delegation_if = matches[0]

        # Its body's LAST statement must be `return run_stage(...)` --
        # i.e. the branch returns immediately and does not fall through
        # into reflective-path code.
        last_stmt = delegation_if.body[-1]
        assert isinstance(last_stmt, ast.Return), (
            f"expected the optimization branch's last statement to be a "
            f"return, got {type(last_stmt).__name__}: "
            f"{ast.unparse(last_stmt)!r}"
        )
        assert isinstance(last_stmt.value, ast.Call), (
            "expected the return value to be a call expression, got "
            f"{ast.unparse(last_stmt.value)!r}"
        )
        called_name = ast.unparse(last_stmt.value.func)
        assert called_name == "run_stage", (
            f"expected the optimization branch to return run_stage(...), "
            f"got a call to {called_name!r}"
        )

        # Nothing in the branch body touches reflective engine state.
        branch_src = ast.unparse(delegation_if)
        assert "engine.phase" not in branch_src
        assert "engine.transition" not in branch_src

        # "Before any state inspection": the delegation `if` must appear
        # earlier in the function body (by statement position) than the
        # first reflective-only state machinery -- Engine(...),
        # HumanGate(...), or validate_campaign(...). Comparing top-level
        # statement order (not a nested walk) is the right granularity
        # here: we want "does the delegation run before these other
        # statements get a chance to run", which is a source-order
        # question, not a structural-shape question -- so line-position
        # comparison is appropriate for this half of the assertion.
        lines = source.splitlines()
        kind_check_lineno = delegation_if.lineno
        reflective_markers = ("Engine(", "HumanGate(", "validate_campaign(")
        first_marker_lineno = None
        for i, line in enumerate(lines, start=1):
            if any(marker in line for marker in reflective_markers):
                first_marker_lineno = i
                break
        assert first_marker_lineno is not None, (
            "expected to find reflective-path state machinery "
            "(Engine(...), HumanGate(...), or validate_campaign(...)) "
            "somewhere in run_iteration's source"
        )
        assert kind_check_lineno < first_marker_lineno, (
            "the kind: optimization delegation check must appear BEFORE "
            "any reflective-path state machinery is constructed/called -- "
            f"found delegation at source line {kind_check_lineno}, first "
            f"reflective marker at line {first_marker_lineno}"
        )


# ─── Assertion 9: complexity_tier remains legal on a reflective campaign ───


class TestComplexityTierRemainsLegalOnReflective:
    def test_reflective_campaign_with_complexity_tier_has_no_hard_errors(self) -> None:
        """The tier ladder (#159) is reflective-only. Forbidding
        complexity_tier outright on any campaign carrying it would have
        been an easy wrong fix when rule 9 (kind: optimization forbids
        tier fields) was added; this pins that a reflective campaign
        with complexity_tier metadata remains fully legal."""
        campaign = {
            "research_question": "does X affect Y?",
            "target_system": {"name": "sys"},
            "complexity_tier": 1,
            "tier_justification": (
                "single mechanism, single knob, treatment vs control"
            ),
        }
        assert campaign_kind(campaign) == "reflective"
        errors = validate_optimization_campaign(campaign)
        # No hard errors. (Any WARN-prefixed advisory would be acceptable,
        # but none is expected here either.)
        hard_errors = [e for e in errors if not e.startswith("WARN:")]
        assert hard_errors == []

    def test_reflective_campaign_with_metadata_complexity_tier_has_no_hard_errors(
        self,
    ) -> None:
        """Same guarantee when complexity_tier lives under bundle-style
        metadata nesting on the campaign dict (defensive: some campaigns
        may carry it there per #206's metadata-first convention)."""
        campaign = {
            "research_question": "does X affect Y?",
            "metadata": {
                "complexity_tier": 2,
                "tier_justification": "single mechanism + multi-knob",
            },
        }
        assert campaign_kind(campaign) == "reflective"
        errors = validate_optimization_campaign(campaign)
        hard_errors = [e for e in errors if not e.startswith("WARN:")]
        assert hard_errors == []
