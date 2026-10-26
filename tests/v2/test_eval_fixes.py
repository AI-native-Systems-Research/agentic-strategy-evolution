"""Fixes from the merge-bar deep analysis (dbg / pd / search vs Claude + prompt).

1. answered: a declared condition is covered by a claim whose condition contains it; the
   agent is told which requirements are still unmet.
2. validators: every schema error at once, with its path; formatting auto-fixed on disk.
3. noise: zero noise (deterministic) never blocks a CONFIRMED/REFUTED status.
4. principles: add/revise must state the scope they were tested in.
5. session: the user's own settings and CLAUDE.md do not leak into a campaign.
6. cost: the CLI's own session cost is the meter's authority.
"""

from __future__ import annotations

import json

from orchestrator.v2.cost import CostMeter
from orchestrator.v2.loop import Campaign, parse_campaign_config
from orchestrator.v2.session import Session
from orchestrator.v2.stop_rule import check_stop, unmet_requirements
from orchestrator.v2.validators import (
    ValidatorContext,
    validate_artifact,
    validate_phase_artifacts,
)
from tests.fakes.sdk_client import FakeAssistantMessage, FakeClient, FakeResultMessage
from tests.v2.test_loop import (
    _answer,
    _baseline,
    _bundle,
    _campaign_yaml,
    _findings,
    _plan,
    _principle_updates,
)


def _hyp(claims, **kw):
    return {"id": "h1", "status": "CONFIRMED", "error_type": "none", "evidence": [],
            "noise_unmeasured": True, "noise_reason": "n/a", "claims": claims, **kw}


def _claim(cond, cid="c1", **kw):
    return {"claim_id": cid, "metric": "m", "condition": cond, "value": 1, **kw}


def _stop(tmp_path, claims, need):
    f = {"hypotheses": [_hyp(claims)], "question_answered": True, "reason": "r"}
    return check_stop(iteration=1, findings=f, principle_updates=None, ledger=[], max_iterations=5,
                      stall_iterations=2, halt_path=tmp_path / "h", stop_sentinel_path=tmp_path / "s",
                      claims_needed=need)


# ── 1. answered ──────────────────────────────────────────────────────────


class TestConditionCoverage:
    def test_claim_condition_containing_declared_condition_counts(self):
        need = [{"id": "c1", "conditions": ["kv_blocks=600", "Rate 20"]}]
        f = {"hypotheses": [_hyp([_claim("small KV: kv_blocks=600, seed 42"), _claim("rate 20,  200 requests")])]}
        assert unmet_requirements(f, need) == []

    def test_uncovered_condition_is_advice_not_a_gate(self, tmp_path):
        # pd rep4: "rate in {10,30,...,150}" vs claims "rates [10,30,...]": free text never matches
        need = [{"id": "c1", "conditions": ["kv_blocks=600", "rate 20"]}]
        assert _stop(tmp_path, [_claim("kv_blocks=600")], need) == "answered"
        f = {"hypotheses": [_hyp([_claim("kv_blocks=600")])]}
        assert any("rate 20" in u for u in unmet_requirements(f, need))

    def test_unmet_requirements_name_what_is_missing(self):
        need = [{"id": "c1", "conditions": ["rate 20"]}, {"id": "c2", "min_seeds": 3},
                {"id": "c3", "needs_ci": True}, {"id": "c4"}]
        f = {"hypotheses": [_hyp([_claim("rate 10"), _claim("x", cid="c2", seeds=[1]),
                                  _claim("x", cid="c3")])]}
        unmet = unmet_requirements(f, need)
        text = "\n".join(unmet)
        assert len(unmet) == 4
        assert "c1" in text and "rate 20" in text
        assert "c2" in text and "3" in text
        assert "c3" in text and "ci" in text
        assert "c4" in text
        assert unmet_requirements(f, [{"id": "c2", "min_seeds": 1}]) == []


async def test_next_design_message_lists_unmet_requirements(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    i1, i2 = work / "runs" / "iter-1", work / "runs" / "iter-2"
    problem = {"task_type": "debug", "claims_needed": [
        {"id": "c1", "description": "d", "test_method": "t", "conditions": ["kv_blocks=600"]}]}
    findings = _findings(answered=False)  # claim c1 under condition "default"
    iteration = lambda d: [
        {str(d / "problem.json"): json.dumps(problem), str(d / "bundle.json"): json.dumps(_bundle()),
         str(d / "plan.json"): json.dumps(_plan())},
        {str(d / "findings.json"): json.dumps(findings),
         str(d / "principle_updates.json"): json.dumps(_principle_updates())},
    ]
    per_turn = [{str(work / "baseline.json"): json.dumps(_baseline())}, *iteration(i1), *iteration(i2),
                {str(i1 / "results.json"): json.dumps({"pass_rate": 1.0}),
                 str(work / "answer.json"): json.dumps(_answer())}]
    client = FakeClient(script=[FakeResultMessage(session_id="s")] * 6, per_turn_files=per_turn)
    cfg = parse_campaign_config({**_campaign_yaml(max_iterations=2), "stall_iterations": 5})
    await Campaign(cfg, work, client_factory=lambda _o: client).run()
    design2 = client.queries[3]
    assert "Iteration 2, DESIGN" in design2
    assert "c1" in design2 and "kv_blocks=600" in design2
    assert "c1" not in client.queries[1].split("DESIGN phase.")[1].split("Write")[0]


# ── 2. validators ────────────────────────────────────────────────────────


def _findings_doc(**hyp):
    return {"hypotheses": [{"id": "h1", "status": "INCONCLUSIVE", "error_type": "none",
                            "evidence": [], **hyp}], "question_answered": False, "reason": "r"}


class TestAllSchemaErrors:
    def test_every_schema_error_reported_with_its_path(self, tmp_path):
        doc = _findings_doc(effect={"value": "big drop", "evidence": "results.json"})
        errs = validate_artifact("findings", doc, ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path))
        joined = "\n".join(errs)
        assert len(errs) >= 2
        assert "hypotheses/0/effect/value" in joined and "hypotheses/0/effect/evidence" in joined

    def test_formatting_fixed_on_disk(self, tmp_path):
        idir = tmp_path / "runs" / "iter-1"
        idir.mkdir(parents=True)
        doc = _findings_doc(status="PARTIALLY_CONFIRMED", partial_note="held at low load",
                            effect={"value": " 5.5 "}, noise_sd="0.1", noise_unmeasured=False,
                            noise_reason=None)
        (idir / "findings.json").write_text(json.dumps(doc))
        assert validate_phase_artifacts(tmp_path, idir, ["findings"]) == []
        h = json.loads((idir / "findings.json").read_text())["hypotheses"][0]
        assert h["effect"]["value"] == 5.5 and h["noise_sd"] == 0.1
        assert "noise_unmeasured" not in h and "noise_reason" not in h
        assert h["partial_note"] == "held at low load"

    def test_prose_is_not_coerced(self, tmp_path):
        idir = tmp_path / "runs" / "iter-1"
        idir.mkdir(parents=True)
        (idir / "findings.json").write_text(json.dumps(_findings_doc(effect={"value": "30% loss"})))
        errs = validate_phase_artifacts(tmp_path, idir, ["findings"])
        assert any("effect/value" in e for e in errs)


# ── 3. zero noise ────────────────────────────────────────────────────────


class TestZeroNoise:
    def _doc(self, **kw):
        return _findings_doc(status="REFUTED", effect={"value": 0}, **kw)

    def test_explicit_zero_noise_sd_accepts_zero_effect(self, tmp_path):
        ctx = ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path)
        assert validate_artifact("findings", self._doc(noise_sd=0), ctx) == []

    def test_deterministic_baseline_accepts_zero_effect(self, tmp_path):
        (tmp_path / "baseline.json").write_text(json.dumps(_baseline()))  # noise deterministic
        ctx = ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path)
        assert validate_artifact("findings", self._doc(), ctx) == []

    def test_nonzero_noise_still_enforced(self, tmp_path):
        ctx = ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path)
        errs = validate_artifact("findings", self._doc(noise_sd=0.5), ctx)
        assert any("noise_sd" in e for e in errs)


# ── 4. principle scope ───────────────────────────────────────────────────


class TestPrincipleScope:
    def _ctx(self, tmp_path):
        return ValidatorContext(work_dir=tmp_path, iter_dir=tmp_path)

    def test_add_without_scope_rejected(self, tmp_path):
        doc = {"updates": [{"id": "p1", "text": "block size does not matter", "finding_ref": "h1",
                            "action": "add"}]}
        assert any("scope" in e for e in validate_artifact("principle_updates", doc, self._ctx(tmp_path)))

    def test_add_with_scope_and_remove_without(self, tmp_path):
        doc = {"updates": [
            {"id": "p1", "text": "block size does not matter", "finding_ref": "h1", "action": "add",
             "scope": "tested at kv_blocks=5000 only (no memory pressure)"},
            {"id": "p0", "text": "old", "finding_ref": "h1", "action": "remove"}]}
        assert validate_artifact("principle_updates", doc, self._ctx(tmp_path)) == []

    async def test_scope_kept_and_shown_in_next_design(self, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        i1, i2 = work / "runs" / "iter-1", work / "runs" / "iter-2"
        pu = {"updates": [{"id": "p1", "text": "block size does not matter", "finding_ref": "h1",
                           "action": "add", "scope": "kv_blocks=5000 only"}]}
        it = lambda d, p: [
            {str(d / "problem.json"): json.dumps({"task_type": "debug", "claims_needed": [
                {"id": "c1", "description": "d", "test_method": "t"}]}),
             str(d / "bundle.json"): json.dumps(_bundle()), str(d / "plan.json"): json.dumps(_plan())},
            {str(d / "findings.json"): json.dumps(_findings(answered=False)),
             str(d / "principle_updates.json"): json.dumps(p)},
        ]
        per_turn = [{str(work / "baseline.json"): json.dumps(_baseline())}, *it(i1, pu),
                    *it(i2, _principle_updates()),
                    {str(i1 / "results.json"): json.dumps({"pass_rate": 1.0}),
                     str(work / "answer.json"): json.dumps(_answer())}]
        client = FakeClient(script=[FakeResultMessage(session_id="s")] * 6, per_turn_files=per_turn)
        cfg = parse_campaign_config({**_campaign_yaml(max_iterations=2), "stall_iterations": 5})
        await Campaign(cfg, work, client_factory=lambda _o: client).run()
        assert json.loads((work / "principles.json").read_text())[0]["scope"] == "kv_blocks=5000 only"
        assert "kv_blocks=5000 only" in client.queries[3]


# ── 5. clean session ─────────────────────────────────────────────────────


def test_session_does_not_load_user_settings():
    opts = Session(client_factory=None, options={"model": "claude-opus-4-6"}).build_agent_options()
    assert opts.setting_sources is not None
    assert "user" not in opts.setting_sources and "project" in opts.setting_sources


# ── 6. cost ──────────────────────────────────────────────────────────────


PRICES = {"claude-opus-4-6": {"input_tokens": 5.0, "output_tokens": 25.0}}


def _msg(mid, out=1000):
    return FakeAssistantMessage(message_id=mid, model="claude-opus-4-6",
                                usage={"input_tokens": 0, "output_tokens": out})


class TestCliCostAuthority:
    def test_cli_session_total_is_used(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))  # streamed usage undercounts: priced at $0.025
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.10))
        assert round(m.total()["cost_usd"], 6) == 0.10
        m.record(_msg("b"))
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.25))  # cumulative per session
        assert round(m.total()["cost_usd"], 6) == 0.25

    def test_fresh_session_adds_its_own_total(self):
        m = CostMeter(PRICES)
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.30))
        m.record(FakeResultMessage(session_id="s2", total_cost_usd=0.05))
        assert round(m.total()["cost_usd"], 6) == 0.35

    def test_iter_delta_uses_cli_cost(self):
        m = CostMeter(PRICES)
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.30))
        assert round(m.iter_delta()["cost_usd"], 6) == 0.30
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=0.45))
        assert round(m.iter_delta()["cost_usd"], 6) == 0.15

    def test_falls_back_to_priced_usage_without_cli_cost(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))
        m.record(FakeResultMessage(session_id="s1", total_cost_usd=None))
        assert round(m.total()["cost_usd"], 6) == 0.025

    def test_total_mid_turn_includes_estimate(self):
        m = CostMeter(PRICES)
        m.record(_msg("a"))
        assert round(m.total()["cost_usd"], 6) == 0.025
