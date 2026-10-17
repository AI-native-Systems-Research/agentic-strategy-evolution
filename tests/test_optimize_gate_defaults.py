"""Tests for kind-scoped gate-default resolution (spec §7.1, task 11a).

``resolve_gate_mode(args, campaign)`` decides the effective
``auto_approve`` bool for ``nous run`` / ``nous resume``:

  1. ``--interactive`` forces prompting (``False``) for either kind.
  2. An explicit ``--auto-approve`` on the command line wins over the
     kind default, in either direction.
  3. Otherwise, the kind default applies: ``True`` for
     ``kind: optimization``, ``False`` for ``kind: reflective`` (or a
     campaign with no ``kind`` field at all).

These are behavioral tests against the return value of
``resolve_gate_mode`` only. No LLM calls; no campaign execution.
"""

from orchestrator.cli import build_parser, resolve_gate_mode


def _parse(argv):
    """Parse argv with the real ``nous`` parser (tests flag wiring too)."""
    return build_parser().parse_args(argv)


def test_optimization_kind_no_flags_defaults_to_auto_approve():
    campaign = {"kind": "optimization"}
    args = _parse(["run", "campaign.yaml"])
    assert resolve_gate_mode(args, campaign) is True


def test_reflective_kind_no_flags_defaults_to_prompting():
    campaign = {"kind": "reflective"}
    args = _parse(["run", "campaign.yaml"])
    assert resolve_gate_mode(args, campaign) is False


def test_interactive_forces_prompting_for_optimization():
    campaign = {"kind": "optimization"}
    args = _parse(["run", "campaign.yaml", "--interactive"])
    assert resolve_gate_mode(args, campaign) is False


def test_explicit_auto_approve_wins_for_reflective():
    campaign = {"kind": "reflective"}
    args = _parse(["run", "campaign.yaml", "--auto-approve"])
    assert resolve_gate_mode(args, campaign) is True


def test_interactive_beats_auto_approve_for_both_kinds():
    for kind in ("optimization", "reflective"):
        campaign = {"kind": kind}
        args = _parse(["run", "campaign.yaml", "--auto-approve", "--interactive"])
        assert resolve_gate_mode(args, campaign) is False


def test_no_kind_field_behaves_exactly_as_reflective():
    campaign = {}
    args = _parse(["run", "campaign.yaml"])
    assert resolve_gate_mode(args, campaign) is False


class TestResumeSubparserSameSemantics:
    """The plan calls out that p_resume must get identical treatment."""

    def test_optimization_kind_no_flags_defaults_to_auto_approve(self):
        campaign = {"kind": "optimization"}
        args = _parse(["resume", "campaign.yaml"])
        assert resolve_gate_mode(args, campaign) is True

    def test_reflective_kind_no_flags_defaults_to_prompting(self):
        campaign = {"kind": "reflective"}
        args = _parse(["resume", "campaign.yaml"])
        assert resolve_gate_mode(args, campaign) is False

    def test_interactive_forces_prompting_for_optimization(self):
        campaign = {"kind": "optimization"}
        args = _parse(["resume", "campaign.yaml", "--interactive"])
        assert resolve_gate_mode(args, campaign) is False

    def test_explicit_auto_approve_wins_for_reflective(self):
        campaign = {"kind": "reflective"}
        args = _parse(["resume", "campaign.yaml", "--auto-approve"])
        assert resolve_gate_mode(args, campaign) is True
