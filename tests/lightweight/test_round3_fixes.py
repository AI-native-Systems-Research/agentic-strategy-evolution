"""Evidence roots, numeric strings, the repro check and evidence export."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.lightweight.final_check import check_answer
from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.loop import REPRO_MSG, Campaign
from orchestrator.lightweight.validators import ValidatorContext, check_evidence_item, validate_answer
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _answer() -> dict:
    return {"answer": "fixed", "deliverable": "patch", "repro": "pytest test_bug.py", "claims": []}


def _campaign_yaml(repo_path: str) -> dict:
    return {"research_question": "Is the bug fixable?", "run_id": "test-run", "max_iterations": 3,
            "target_system": {"name": "t", "repo_path": repo_path}}


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
    assert validate_answer(ans, ValidatorContext(work_dir=tmp_path)) == []


# ── 3. repro must have run as written ────────────────────────────────────


def _no_gap(_opts):
    msg = FakeResultMessage(session_id="rev")
    msg.result = '{"gap": false, "why": "x"}'
    return FakeClient(script=[msg])


async def test_one_repro_message_when_repro_never_ran(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    work.mkdir(); repo.mkdir()
    _w(work / "runs.jsonl", json.dumps({"command": "pytest other.py", "exit_code": 0}) + "\n")
    client = FakeClient(script=[FakeResultMessage()] * 3,
                        per_turn_files=[{str(work / "answer.json"): json.dumps(_answer())}])
    cfg = parse_campaign_config(_campaign_yaml(str(repo)))
    await Campaign(cfg, work, client_factory=lambda _o: client, challenger_factory=_no_gap).run()
    assert client.queries.count(REPRO_MSG) == 1 and len(client.queries) == 2
    assert json.loads((work / "ledger.json").read_text())[-1]["repro_recorded"] is False


async def test_no_repro_message_when_repro_ran(tmp_path):
    work, repo = tmp_path / "work", tmp_path / "repo"
    work.mkdir(); repo.mkdir()
    _w(work / "runs.jsonl", json.dumps({"command": "pytest test_bug.py", "exit_code": 0}) + "\n")
    client = FakeClient(script=[FakeResultMessage()],
                        per_turn_files=[{str(work / "answer.json"): json.dumps(_answer())}])
    cfg = parse_campaign_config(_campaign_yaml(str(repo)))
    await Campaign(cfg, work, client_factory=lambda _o: client, challenger_factory=_no_gap).run()
    assert REPRO_MSG not in client.queries
    assert json.loads((work / "ledger.json").read_text())[-1]["repro_recorded"] is True


# ── 4. evidence export of absolute and in-repo paths ─────────────────────


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
    cfg = parse_campaign_config(_campaign_yaml(str(repo)))
    Campaign(cfg, work, client_factory=None)._export_evidence()
    claims = json.loads((work / "answer.json").read_text())["claims"]
    assert [c["evidence"] for c in claims] == ["nous_evidence/runs/iter-1/r.json", "results/b.json"]
    assert (repo / "nous_evidence" / "runs" / "iter-1" / "r.json").is_file()
    assert not (repo / "nous_evidence" / "results").exists()
    assert check_answer(work, {"repo_dir": repo})["evidence_errors"] == []
