"""Nous Lightweight: free session + notebook + final gate + one challenger. No live LLM calls (FakeClient only)."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.loop import Campaign, parse_verdict
from orchestrator.lightweight.notebook import check_notebook, summary
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


def _cfg(**kw):
    return parse_campaign_config({"research_question": "Is the cache worth it?", "max_iterations": 2,
                                  "target_system": {"name": "t", "repo_path": "/tmp/none-repo"}, **kw})


def _nb(work: Path, *entries):
    (work / "notebook.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


H = {"kind": "hypothesis", "id": "H1", "claim": "cache lowers p99", "predict": "p99 drops by >10 ms"}
R = {"kind": "result", "id": "H1", "status": "confirmed",
     "evidence": [{"path": "r.json", "key": "/p99", "value": 40}]}


def _answer(work: Path):
    (work / "r.json").write_text('{"p99": 40}')
    return json.dumps({"answer": "Yes.", "deliverable": "cache.patch", "repro": "python bench.py",
                       "claims": [{"id": "C1", "metric": "p99", "value": 40, "condition": "cache=256",
                                   "evidence": {"path": "r.json", "key": "/p99", "value": 40}}]})


# ── notebook ─────────────────────────────────────────────────────────────


class TestNotebook:
    def test_valid_notebook(self, tmp_path):
        (tmp_path / "r.json").write_text('{"p99": 40}')
        _nb(tmp_path, H, R, {"kind": "note", "text": "changed my mind"})
        assert check_notebook(tmp_path) == []
        assert summary(tmp_path) == {"hypotheses": 1, "confirmed": 1, "refuted": 0, "inconclusive": 0, "notes": 1}

    def test_result_needs_an_earlier_hypothesis(self, tmp_path):
        (tmp_path / "r.json").write_text('{"p99": 40}')
        _nb(tmp_path, R, H)
        assert any("no earlier hypothesis" in e for e in check_notebook(tmp_path))

    def test_result_evidence_is_checked(self, tmp_path):
        (tmp_path / "r.json").write_text('{"p99": 55}')
        _nb(tmp_path, H, R)
        assert any("mismatch" in e for e in check_notebook(tmp_path))

    def test_confirmed_needs_evidence_inconclusive_does_not(self, tmp_path):
        _nb(tmp_path, H, {"kind": "result", "id": "H1", "status": "confirmed"})
        assert any("needs `evidence`" in e for e in check_notebook(tmp_path))
        _nb(tmp_path, H, {"kind": "result", "id": "H1", "status": "inconclusive"})
        assert check_notebook(tmp_path) == []

    def test_bad_lines_reported(self, tmp_path):
        (tmp_path / "notebook.jsonl").write_text('not json\n{"kind": "guess"}\n')
        errs = check_notebook(tmp_path)
        assert any("not JSON" in e for e in errs) and any("kind must be" in e for e in errs)


def test_parse_verdict():
    assert parse_verdict('thinking... {"gap": true, "test": "fit at low rate", "why": "w"}') == \
        {"gap": True, "test": "fit at low rate", "why": "w"}
    assert parse_verdict('{"gap": false, "why": "ok"}')["gap"] is False
    assert parse_verdict("no json here") is None


# ── campaign ─────────────────────────────────────────────────────────────


def _challenger(reply: str):
    from tests.fakes.sdk_client import FakeResultMessage as R_
    msg = R_(session_id="rev")
    msg.result = reply
    return lambda _o: FakeClient(script=[msg])


async def test_one_free_session_no_phases(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    per_turn = [{str(work / "notebook.jsonl"): json.dumps(H) + "\n" + json.dumps(R) + "\n",
                 str(work / "answer.json"): _answer(work)}]
    client = FakeClient(script=[FakeResultMessage(session_id="s")], per_turn_files=per_turn)
    c = Campaign(_cfg(), work, client_factory=lambda _o: client,
                 challenger_factory=_challenger('{"gap": false, "why": "settled"}'))
    out = await c.run()
    assert out["stop_reason"] == "answered"
    assert len(client.queries) == 1  # one task message; no phase messages
    assert "Is the cache worth it?" in client.queries[0]
    fc = json.loads((work / "final_check.json").read_text())
    assert fc["answer_valid"] and fc["notebook"]["confirmed"] == 1 and fc["challenger"]["gap"] is False
    assert json.loads((work / "ledger.json").read_text())[0]["nous_version"] == 3  # kept for ledger readers


async def test_challenger_gap_gets_one_follow_up_turn(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    per_turn = [{str(work / "notebook.jsonl"): json.dumps(H) + "\n" + json.dumps(R) + "\n",
                 str(work / "answer.json"): _answer(work)}, {}]
    client = FakeClient(script=[FakeResultMessage(session_id="s")] * 2, per_turn_files=per_turn)
    c = Campaign(_cfg(), work, client_factory=lambda _o: client,
                 challenger_factory=_challenger('{"gap": true, "test": "repeat at cache=16", "why": "one size only"}'))
    await c.run()
    assert len(client.queries) == 2
    assert "repeat at cache=16" in client.queries[1]


async def test_no_answer_gets_continue_then_partial(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    client = FakeClient(script=[FakeResultMessage(session_id="s")] * 6)
    c = Campaign(_cfg(), work, client_factory=lambda _o: client,
                 challenger_factory=_challenger('{"gap": false, "why": "x"}'))
    out = await c.run()
    assert out["stop_reason"] == "partial"
    assert any("Continue the investigation" in q for q in client.queries)
    assert json.loads((work / "final_check.json").read_text())["challenger"] is None  # not run on a failed answer


async def test_invalid_answer_blocked_and_repaired(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    bad = json.loads(_answer(work))
    bad["claims"][0]["value"] = 99  # does not match the evidence
    per_turn = [{str(work / "answer.json"): json.dumps(bad)},
                {str(work / "answer.json"): _answer(work)}]
    holder = {}

    def factory(opts):  # the session's own hooks, so the Stop gate fires as in the CLI
        holder["c"] = FakeClient(script=[FakeResultMessage(session_id="s")] * 3, per_turn_files=per_turn,
                                 hooks=opts.hooks)
        return holder["c"]

    c = Campaign(_cfg(), work, client_factory=factory,
                 challenger_factory=_challenger('{"gap": false, "why": "x"}'))
    assert (await c.run())["stop_reason"] == "answered"
    assert holder["c"].stop_decisions[0] == "block"


async def test_challenger_failure_never_stops_the_campaign(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    per_turn = [{str(work / "answer.json"): _answer(work)}]
    client = FakeClient(script=[FakeResultMessage(session_id="s")], per_turn_files=per_turn)

    def broken(_o):
        raise RuntimeError("reviewer down")

    c = Campaign(_cfg(), work, client_factory=lambda _o: client, challenger_factory=broken)
    assert (await c.run())["stop_reason"] == "answered"


def test_cli_runs_lightweight(tmp_path, monkeypatch):
    import argparse

    from orchestrator import cli
    seen = {}

    class Fake:
        def __init__(self, cfg, work_dir, client_factory):
            seen["cls"] = type(self).__module__

        async def run(self):
            return {"stop_reason": "answered", "iterations": 1}

    import orchestrator.lightweight.loop as lw
    monkeypatch.setattr(lw, "Campaign", type("Campaign", (Fake,), {"__module__": "orchestrator.lightweight.loop"}))
    for raw_extra in ({}, {"nous_version": 2}, {"nous_version": 3}):
        seen.clear()
        raw = {"research_question": "q", "target_system": {"name": "t", "repo_path": str(tmp_path)}, **raw_extra}
        args = argparse.Namespace(max_iterations=None, model=None, verbose=False, note=None)
        cli._drive_campaign(raw, tmp_path, args)
        assert seen["cls"] == "orchestrator.lightweight.loop"


def test_repro_must_run_in_any_copy(tmp_path):
    from orchestrator.lightweight.validators import ValidatorContext, validate_answer
    base = {"answer": "a", "deliverable": "d", "claims": []}
    ctx = ValidatorContext(work_dir=tmp_path / "w", repo_dir=tmp_path / "repo")
    for bad in ["export P=x && cd /somewhere && make", f"{tmp_path / 'repo'}/blis run --x", "make; cd sub; ls"]:
        assert any("repro" in e for e in validate_answer({**base, "repro": bad}, ctx)), bad
    assert validate_answer({**base, "repro": "go build -o blis main.go && ./blis run --x"}, ctx) == []


def test_evidence_path_naming_the_work_dir_resolves(tmp_path):
    from orchestrator.lightweight.validators import check_evidence_item
    work = tmp_path / "work"
    work.mkdir()
    (work / "e.json").write_text('{"v": 3}')
    assert check_evidence_item({"path": "work/e.json", "key": "/v", "value": 3}, work) == []
    assert check_evidence_item({"path": "other/e.json", "key": "/v", "value": 3}, work) != []


# ── review fixes ─────────────────────────────────────────────────────────


class _HangingClient(FakeClient):
    async def receive_response(self):
        import asyncio
        await asyncio.sleep(30)
        yield FakeResultMessage(session_id="rev")


async def test_hung_challenger_times_out_and_never_stops_the_campaign(tmp_path, monkeypatch):
    import orchestrator.lightweight.loop as lw
    monkeypatch.setattr(lw, "CHALLENGER_TIMEOUT_S", 0.05)
    work = tmp_path / "work"
    work.mkdir()
    client = FakeClient(script=[FakeResultMessage(session_id="s")],
                        per_turn_files=[{str(work / "answer.json"): _answer(work)}])
    c = Campaign(_cfg(), work, client_factory=lambda _o: client, challenger_factory=lambda _o: _HangingClient())
    assert (await c.run())["stop_reason"] == "answered"
    ch = json.loads((work / "final_check.json").read_text())["challenger"]
    assert ch["gap"] is None and ch["error"]


async def test_resume_of_a_stale_session_starts_fresh_with_the_task(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({"phase": "INVESTIGATE", "session_id": "gone"}))
    fresh = FakeClient(script=[FakeResultMessage(session_id="s2")],
                       per_turn_files=[{str(work / "answer.json"): _answer(work)}])

    class Stale(FakeClient):
        async def query(self, prompt):
            raise RuntimeError("No conversation found with session ID: gone")

    c = Campaign(_cfg(), work, client_factory=lambda o: Stale() if o.resume else fresh,
                 challenger_factory=_challenger('{"gap": false, "why": "x"}'))
    assert (await c.resume())["stop_reason"] == "answered"
    assert "Is the cache worth it?" in fresh.queries[0]


async def test_fresh_resume_says_continue_from_the_notebook(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({"phase": "INVESTIGATE"}))
    client = FakeClient(script=[FakeResultMessage(session_id="s")],
                        per_turn_files=[{str(work / "answer.json"): _answer(work)}])
    c = Campaign(_cfg(), work, client_factory=lambda _o: client,
                 challenger_factory=_challenger('{"gap": false, "why": "x"}'))
    await c.resume()
    assert "Is the cache worth it?" in client.queries[0]
    assert "continue" in client.queries[0].lower() and str(work / "notebook.jsonl") in client.queries[0]


async def test_resume_of_a_finished_campaign_runs_nothing(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "state.json").write_text(json.dumps({"phase": "DONE", "session_id": "s"}))
    (work / "ledger.json").write_text(json.dumps([{"iteration": 1, "stop_reason": "partial", "cost_meter_usd": 2.0}]))

    def no_client(_o):
        raise AssertionError("a finished campaign must not start a session")

    out = await Campaign(_cfg(), work, client_factory=no_client).resume()
    assert out == {"stop_reason": "partial", "iterations": 1}
    assert json.loads((work / "ledger.json").read_text())[0]["cost_meter_usd"] == 2.0


async def test_resume_after_a_crash_in_challenge_keeps_the_earlier_cost(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    per_turn = [{str(work / "answer.json"): _answer(work)}]

    class Crash(FakeClient):  # the challenge turn dies with the process
        async def query(self, prompt):
            if "independent reviewer" in prompt:
                raise KeyboardInterrupt
            await super().query(prompt)

    first = Crash(script=[FakeResultMessage(session_id="s1", total_cost_usd=1.0)], per_turn_files=per_turn)
    gap = '{"gap": true, "test": "repeat at cache=16", "why": "w"}'
    c = Campaign(_cfg(), work, client_factory=lambda _o: first, challenger_factory=_challenger(gap))
    try:
        await c.run()
    except KeyboardInterrupt:
        pass
    assert json.loads((work / "state.json").read_text())["phase"] == "CHALLENGE"
    second = FakeClient(script=[FakeResultMessage(session_id="s2", total_cost_usd=0.5)] * 2)
    c2 = Campaign(_cfg(), work, client_factory=lambda _o: second,
                  challenger_factory=_challenger('{"gap": false, "why": "x"}'))
    await c2.resume()
    cost = json.loads((work / "ledger.json").read_text())[0]["cost_meter_usd"]
    assert abs(cost - (1.0 + 0.01 + 0.5)) < 1e-9  # first process (agent + challenger) + this one


class TestNotebookRobustness:
    def test_unhashable_id_is_an_error_not_a_crash(self, tmp_path):
        _nb(tmp_path, {**H, "id": ["H1"]}, {**R, "id": ["H1"]})
        assert any("id" in e for e in check_notebook(tmp_path))

    def test_bad_evidence_items_are_errors_not_crashes(self, tmp_path):
        for ev in ([{"path": 5, "key": "/p99", "value": 40}], ["r.json"]):
            _nb(tmp_path, H, {**R, "evidence": ev})
            assert check_notebook(tmp_path) != []

    def test_only_the_latest_result_per_hypothesis_is_checked(self, tmp_path):
        (tmp_path / "r.json").write_text('{"p99": 31}')  # the rerun rewrote the file
        new = {**R, "evidence": [{"path": "r.json", "key": "/p99", "value": 31}]}
        _nb(tmp_path, H, R, new)
        assert check_notebook(tmp_path) == []
        _nb(tmp_path, H, new, R)
        assert any("mismatch" in e for e in check_notebook(tmp_path))


def test_repro_absolute_path_and_cd_checks(tmp_path):
    from orchestrator.lightweight.validators import ValidatorContext, validate_answer
    base = {"answer": "a", "deliverable": "d", "claims": []}
    repo = tmp_path / "proj"
    ctx = ValidatorContext(work_dir=tmp_path / "w", repo_dir=repo)
    errs = lambda r: [e for e in validate_answer({**base, "repro": r}, ctx) if "repro" in e]  # noqa: E731
    root = str(repo.resolve())
    assert errs(f"python run.py --data {root}-data/x.csv") == []
    assert errs(f"python run.py --out '{root}-data'") == []
    for bad in [f"{root}/run.sh", f"python x.py --root {root}", f"python x.py --root '{root}'",
                "(cd sub && make)", "make\ncd sub\nls"]:
        assert errs(bad), bad
    assert errs("make abcd") == [] and errs("./scd run") == []
