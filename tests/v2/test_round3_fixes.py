"""Round-3 general fixes: evidence roots, numeric strings, append-only claims_needed,
repro repair at REPORT, evidence export of absolute paths."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.v2.final_check import check_answer
from orchestrator.v2.hooks import HookState, make_stop_hook
from orchestrator.v2.loop import REPRO_REPAIR_MSG, Campaign, parse_campaign_config
from orchestrator.v2.validators import (
    ValidatorContext, check_evidence_item, validate_artifact, validate_phase_artifacts,
)
from tests.fakes.sdk_client import FakeClient
from tests.v2.test_loop import (
    _answer, _baseline, _build_per_turn_files, _bundle, _campaign_yaml, _findings, _make_script,
    _plan, _principle_updates, _problem,
)


def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ── 1. evidence resolution ───────────────────────────────────────────────


def _roots(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    idir = work / "runs" / "iter-1"
    idir.mkdir(parents=True); repo.mkdir()
    return idir, work, repo


def test_relative_path_falls_back_to_work_dir_then_repo(tmp_path):
    idir, work, repo = _roots(tmp_path)
    _w(work / "out" / "a.json", '{"x": 1}')
    _w(repo / "results" / "b.json", '{"y": 2}')
    assert check_evidence_item({"path": "out/a.json", "key": "/x", "value": 1}, idir, work, repo) == []
    assert check_evidence_item({"path": "runs/iter-1/../../out/a.json", "key": "/x", "value": 1},
                               idir, work, repo) == []
    assert check_evidence_item({"path": "results/b.json", "key": "/y", "value": 2}, idir, work, repo) == []


def test_absolute_path_inside_a_root_is_accepted_outside_is_not(tmp_path):
    idir, work, repo = _roots(tmp_path)
    f = _w(work / "out" / "a.json", '{"x": 1}')
    assert check_evidence_item({"path": str(f), "key": "/x", "value": 1}, idir, work, repo) == []
    out = _w(tmp_path / "elsewhere.json", '{"x": 1}')
    errs = check_evidence_item({"path": str(out), "key": "/x", "value": 1}, idir, work, repo)
    assert len(errs) == 1 and str(repo) in errs[0]


def test_missing_path_error_names_the_roots(tmp_path):
    idir, work, repo = _roots(tmp_path)
    errs = check_evidence_item({"path": "nope.json", "key": "/x", "value": 1}, idir, work, repo)
    assert "does not exist" in errs[0] and str(idir) in errs[0] and str(repo) in errs[0]


def test_pointer_without_leading_slash_is_normalized(tmp_path):
    _w(tmp_path / "r.json", '{"a": {"b": 3}}')
    _w(tmp_path / "r.jsonl", '{"a": 4}\n')
    assert check_evidence_item({"path": "r.json", "key": "a/b", "value": 3}, tmp_path) == []
    assert check_evidence_item({"path": "r.jsonl", "key": "0@a", "value": 4}, tmp_path) == []


def test_non_json_dot_json_file_gets_a_clear_message(tmp_path):
    _w(tmp_path / "out.json", "throughput: 12\n")
    errs = check_evidence_item({"path": "out.json", "key": "/x", "value": 12}, tmp_path)
    assert len(errs) == 1 and "not JSON" in errs[0] and ".txt/.log" in errs[0]


def test_findings_evidence_resolves_against_work_dir_and_repo(tmp_path):
    idir, work, repo = _roots(tmp_path)
    _w(work / "runs" / "iter-1" / "r.json", '{"v": 1}')
    _w(repo / "bench.csv", "v\n5\n")
    findings = _findings()
    findings["hypotheses"][0]["evidence"] = [
        {"path": "runs/iter-1/r.json", "key": "/v", "value": 1},
        {"path": "bench.csv", "key": "v@0", "value": 5},
    ]
    _w(idir / "findings.json", json.dumps(findings))
    _w(idir / "principle_updates.json", json.dumps(_principle_updates()))
    assert validate_phase_artifacts(work, idir, ["findings"], repo_dir=repo) == []


# ── 2. numeric strings ───────────────────────────────────────────────────


def test_numeric_string_equals_number(tmp_path):
    _w(tmp_path / "r.json", '{"n": "105082", "f": 1.5}')
    _w(tmp_path / "log.txt", "rate=1.5000\n")
    assert check_evidence_item({"path": "r.json", "key": "/n", "value": 105082}, tmp_path) == []
    assert check_evidence_item({"path": "r.json", "key": "/f", "value": "1.5"}, tmp_path) == []
    assert check_evidence_item({"path": "log.txt", "key": r"rate=(\S+)", "value": 1.5}, tmp_path) == []
    assert check_evidence_item({"path": "log.txt", "key": r"rate=(\S+)", "value": "1.5"}, tmp_path) == []
    assert check_evidence_item({"path": "r.json", "key": "/n", "value": 105999}, tmp_path)


def test_answer_claim_value_string_vs_number(tmp_path):
    _w(tmp_path / "r.json", '{"n": 105082}')
    ans = {**_answer(), "claims": [{"id": "c1", "metric": "n", "value": "105082", "condition": "c",
                                    "evidence": {"path": "r.json", "key": "/n", "value": 105082}}]}
    assert validate_artifact("answer", ans, ValidatorContext(work_dir=tmp_path)) == []


# ── 3. key-format reminder only on evidence errors ───────────────────────


async def test_stop_hook_reminds_evidence_key_formats_only_on_evidence_error(tmp_path):
    work = tmp_path / "work"
    idir = work / "runs" / "iter-1"
    findings = _findings()
    findings["hypotheses"][0]["evidence"] = [{"path": "nope.json", "key": "/x", "value": 1}]
    _w(idir / "findings.json", json.dumps(findings))
    _w(idir / "principle_updates.json", json.dumps(_principle_updates()))
    state = HookState(work_dir=work, phase="EXECUTE", iteration=1)
    out = await make_stop_hook(state)({}, None, None)
    assert out["decision"] == "block" and "regex with one capture group" in out["reason"]
    (idir / "findings.json").write_text(json.dumps({"hypotheses": "bad"}))
    out = await make_stop_hook(state)({}, None, None)
    assert out["decision"] == "block" and "capture group" not in out["reason"]


# ── 4. claims_needed append-only ─────────────────────────────────────────


def _problem_ids(*ids):
    return {"task_type": "debug", "claims_needed": [
        {"id": i, "description": i, "test_method": "t"} for i in ids]}


def test_problem_may_add_but_not_drop_claim_ids(tmp_path):
    work = tmp_path
    _w(work / "runs" / "iter-1" / "problem.json", json.dumps(_problem_ids("c1", "c2")))
    i2 = work / "runs" / "iter-2"
    _w(i2 / "problem.json", json.dumps(_problem_ids("c1", "c3")))
    errs = validate_phase_artifacts(work, i2, ["problem"])
    assert len(errs) == 1 and "may be added, not removed" in errs[0] and "c2" in errs[0]
    _w(i2 / "problem.json", json.dumps(_problem_ids("c1", "c2", "c3")))
    assert validate_phase_artifacts(work, i2, ["problem"]) == []


def test_final_check_uses_union_of_claims_and_findings(tmp_path):
    work = tmp_path
    _w(work / "runs.jsonl", "")
    _w(work / "answer.json", json.dumps({**_answer(), "claims": []}))
    f1 = _findings(); f1["hypotheses"][0]["claims"][0]["claim_id"] = "c1"
    f2 = _findings(); f2["hypotheses"][0]["claims"][0]["claim_id"] = "c2"
    _w(work / "runs" / "iter-1" / "problem.json", json.dumps(_problem_ids("c1", "c2")))
    _w(work / "runs" / "iter-1" / "findings.json", json.dumps(f1))
    _w(work / "runs" / "iter-2" / "problem.json", json.dumps(_problem_ids("c2", "c3")))
    _w(work / "runs" / "iter-2" / "findings.json", json.dumps(f2))
    assert abs(check_answer(work)["claims_matched_fraction"] - 2 / 3) < 1e-9


async def test_stop_rule_answered_needs_union_of_claims(tmp_path):
    """Iter 2 drops its focus to c1 only (validator lets it keep c2 by id); answered needs c2 too,
    and c2 answered in iter 1 stays answered."""
    work = tmp_path / "work"
    i1, i2 = work / "runs" / "iter-1", work / "runs" / "iter-2"
    need2 = _problem_ids("c1", "c2")
    f_c2 = _findings(answered=False); f_c2["hypotheses"][0]["claims"][0]["claim_id"] = "c2"
    turns = [
        {str(work / "baseline.json"): json.dumps(_baseline())},
        {str(i1 / "problem.json"): json.dumps(need2), str(i1 / "bundle.json"): json.dumps(
            {**_bundle(), "hypotheses": [{**h, "claim_ids": ["c1", "c2"]} for h in _bundle()["hypotheses"]]}),
         str(i1 / "plan.json"): json.dumps(_plan())},
        {str(i1 / "findings.json"): json.dumps(f_c2),
         str(i1 / "principle_updates.json"): json.dumps(_principle_updates(count=1))},
        {str(i2 / "problem.json"): json.dumps(need2), str(i2 / "bundle.json"): json.dumps(_bundle()),
         str(i2 / "plan.json"): json.dumps(_plan())},
        {str(i2 / "findings.json"): json.dumps(_findings(answered=True)),
         str(i2 / "principle_updates.json"): json.dumps(_principle_updates()),
         str(i2 / "results.json"): "{}"},
        {str(work / "runs" / "iter-1" / "results.json"): json.dumps({"pass_rate": 1.0}),
         str(work / "answer.json"): json.dumps(_answer())},
    ]
    client = FakeClient(script=_make_script(6), per_turn_files=turns)
    cfg = parse_campaign_config(_campaign_yaml(max_iterations=3, repo_path=str(tmp_path / "repo")))
    out = await Campaign(cfg, work, client_factory=lambda _o: client).run()
    assert out == {"stop_reason": "answered", "iterations": 2}
    assert json.loads((work / "final_check.json").read_text())["claims_matched_fraction"] == 1.0


# ── 5. repro must have run as written ────────────────────────────────────


async def test_report_sends_one_repro_repair_when_repro_never_ran(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    work.mkdir(); repo.mkdir()
    _w(work / "runs.jsonl", json.dumps({"command": "pytest other.py", "exit_code": 0}) + "\n")
    per_turn = _build_per_turn_files(work)
    client = FakeClient(script=_make_script(6), per_turn_files=per_turn)
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    await Campaign(cfg, work, client_factory=lambda _o: client).run()
    assert client.queries.count(REPRO_REPAIR_MSG) == 1 and len(client.queries) == 5
    assert json.loads((work / "ledger.json").read_text())[-1]["repro_recorded"] is False


async def test_no_repro_repair_when_repro_ran(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    work.mkdir(); repo.mkdir()
    _w(work / "runs.jsonl", json.dumps({"command": "pytest test_bug.py", "exit_code": 0}) + "\n")
    client = FakeClient(script=_make_script(4), per_turn_files=_build_per_turn_files(work))
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    await Campaign(cfg, work, client_factory=lambda _o: client).run()
    assert REPRO_REPAIR_MSG not in client.queries
    assert json.loads((work / "ledger.json").read_text())[-1]["repro_recorded"] is True


# ── 6. evidence export of absolute and in-repo paths ─────────────────────


def test_export_maps_absolute_paths_and_cites_repo_files_in_place(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    work_file = _w(work / "runs" / "iter-1" / "r.json", '{"n": 5}')
    _w(repo / "results" / "b.json", '{"m": 7}')
    _w(work / "answer.json", json.dumps({**_answer(), "claims": [
        {"id": "C1", "metric": "n", "value": 5, "condition": "c",
         "evidence": {"path": str(work_file), "key": "/n", "value": 5}},
        {"id": "C2", "metric": "m", "value": 7, "condition": "c",
         "evidence": {"path": str(repo / "results" / "b.json"), "key": "/m", "value": 7}},
    ]}))
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    Campaign(cfg, work, client_factory=None)._export_evidence()
    claims = json.loads((work / "answer.json").read_text())["claims"]
    assert [c["evidence"] for c in claims] == ["nous_evidence/runs/iter-1/r.json", "results/b.json"]
    assert (repo / "nous_evidence" / "runs" / "iter-1" / "r.json").is_file()
    assert not (repo / "nous_evidence" / "results").exists()
    assert check_answer(work, {"repo_dir": repo})["evidence_errors"] == []
