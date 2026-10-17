"""Item 1 of #321: the model that authored the mechanism is recorded as SERVED,
not only as requested.

``OPTIMIZATION_MODEL`` is an alias (``claude-opus-5``); no dated snapshot of it
is verifiable, so none is pinned. What closes the reproducibility gap instead is
recording, per call, the ID the SDK reports serving the turn. Zero LLM: the SDK
is a fake module at the import seam, and the build call uses ``sdk_runner=``.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import jsonschema

from orchestrator.sdk_dispatch import SDKResult

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "orchestrator"
                     / "schemas" / "report.schema.json").read_text())


def _fake_sdk(served: str, usage_keys=()):
    class _Opts:
        def __init__(self, **kw):
            self.kw = kw

    class AssistantMessage:
        content = []
        model = served

    class ResultMessage:
        is_error = False
        usage = {}
        total_cost_usd = 0.0
        duration_ms = 1
        num_turns = 1
        model_usage = {k: {} for k in usage_keys}

    async def query(*, prompt, options):  # noqa: ARG001
        yield AssistantMessage()
        yield ResultMessage()

    m = types.ModuleType("claude_agent_sdk")
    m.ClaudeAgentOptions = _Opts
    m.query = query
    return m


def test_the_default_runner_reports_the_model_the_sdk_served(monkeypatch, tmp_path):
    from orchestrator.sdk_dispatch import _default_sdk_runner_factory

    monkeypatch.setitem(sys.modules, "claude_agent_sdk",
                        _fake_sdk("claude-opus-5-20261001", ["claude-opus-5-20261001"]))
    res = _default_sdk_runner_factory()(prompt="x", model="claude-opus-5",
                                        cwd=tmp_path, max_turns=1)
    assert res.resolved_model == "claude-opus-5-20261001"


def _build(tmp_path, result: SDKResult) -> Path:
    from orchestrator.optimize import build as build_mod

    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    campaign = {
        "kind": "optimization", "run_id": "m",
        "target_system": {"repo_path": str(repo)},
        "optimization": {"factors": [], "stages": ["build", "verify", "screen"]},
    }
    build_mod.run_build(campaign, work, iteration=1, declared_tests=["t::T"],
                        sdk_runner=lambda **_k: result)
    return work


def test_llm_metrics_and_provenance_record_requested_and_served(tmp_path):
    from orchestrator.campaign import OPTIMIZATION_MODEL
    from orchestrator.optimize.provenance import model_record

    work = _build(tmp_path, SDKResult(text="ok", resolved_model="claude-opus-5-20261001"))
    row = json.loads((work / "llm_metrics.jsonl").read_text().splitlines()[0])
    assert row["model"] == OPTIMIZATION_MODEL
    assert row["model_resolved"] == "claude-opus-5-20261001"
    rec = model_record(work)
    assert rec["configured_default"] == OPTIMIZATION_MODEL
    assert rec["snapshot_pinned"] is False
    assert rec["calls"] == [{"phase": "build", "requested": OPTIMIZATION_MODEL,
                             "resolved": "claude-opus-5-20261001"}]


def test_an_unreported_served_model_is_recorded_as_unknown_not_as_the_alias(tmp_path):
    """A producer that reports no served model must not be read as having served
    the alias: ``resolved`` is null, which report.md renders 'not reported'."""
    from orchestrator.optimize.provenance import model_record

    work = _build(tmp_path, SDKResult(text="ok"))
    assert model_record(work)["calls"][0]["resolved"] is None


def test_a_synthetic_report_carries_the_model_block_and_validates(tmp_path):
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["bowl"](), seed=4, parent_dir=tmp_path)
    jsonschema.validate(res.report, SCHEMA)
    m = res.report["provenance"]["model"]
    assert m["calls"] == [] and m["snapshot_pinned"] is False
