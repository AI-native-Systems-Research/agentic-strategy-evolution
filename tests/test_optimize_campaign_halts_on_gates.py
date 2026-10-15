"""A failed gate, or a failed pre-epoch stage, STOPS a kind: optimization campaign.

Found by a real plan+build campaign driven through `nous run`: verify raised
"build changed the baseline" (a hard gate), the campaign loop recorded it as
one failed iteration and advanced -- and iteration 4 screened, then refined, the
mechanism verify had just refused, until the circuit breaker stopped it three
failures later. Earlier the same loop had skipped a rejected `plan` straight to
`build`. These tests drive the REAL `run_campaign` against a real subprocess
target and a real pytest suite; no model call is involved (no plan/build stage).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orchestrator.campaign import run_campaign
from orchestrator.iteration import setup_work_dir


def _target(tmp_path: Path, *, relation_passes: bool) -> Path:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    (repo / "bench.py").write_text(
        "import json, sys\n"
        "a = dict(x.lstrip('-').split('=') for x in sys.argv[1:])\n"
        "k = int(a['k'])\n"
        "print(json.dumps({'m': 10.0 - (k - 3) ** 2, 'cfg': {'k': k}}))\n")
    (repo / "tests" / "test_rel.py").write_text(
        f"def test_k_moves_m():\n    assert {relation_passes!r}\n")
    return repo


def _campaign(repo: Path) -> dict:
    py = sys.executable
    return {
        "kind": "optimization", "run_id": "halt-gate", "research_question": "q?",
        "target_system": {"name": "t", "repo_path": str(repo), "description": "toy"},
        "optimization": {
            "stages": ["verify", "screen", "confirm"],
            "run_command": f"{py} bench.py",
            "test_command": f"{py} -m pytest tests/test_rel.py -v -p no:cacheprovider",
            "known_valid_baseline": {"K": 1},
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "design": {"screen": {"resolution": 3, "center_points": 2},
                       "confirm": {"replicates": 2}},
            "factors": [{
                "id": "K", "name": "k", "type": "numeric", "levels": [1, 5],
                "grid": 1, "apply": "--k={level}",
                "manipulation": {"observable": "cfg.k", "op": "==", "value": "{level}"},
                "relations": [{"id": "K-R1", "kind": "correctness",
                               "statement": "k moves m",
                               "native_test": "tests/test_rel.py::test_k_moves_m"}],
            }],
        },
    }


def _run(tmp_path, monkeypatch, *, relation_passes: bool) -> Path:
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "runs"))
    repo = _target(tmp_path, relation_passes=relation_passes)
    campaign = _campaign(repo)
    wd = setup_work_dir("halt-gate", repo_path=str(repo), campaign=campaign)
    run_campaign(campaign, wd, max_iterations=6, auto_approve=True)
    return Path(wd)


def test_a_failed_verify_gate_halts_before_any_measurement(tmp_path, monkeypatch):
    wd = _run(tmp_path, monkeypatch, relation_passes=False)
    halt = json.loads((wd / "halt.json").read_text())
    assert halt["kind"] == "gate_failed" and halt["stage"] == "verify"
    assert "nous resume" in halt["reason"]
    # Nothing after verify ran: no design was measured at all.
    assert not list(wd.glob("runs/iter-*/runs.jsonl"))
    failed = [r for r in json.loads((wd / "ledger.json").read_text())["iterations"]
              if r.get("status") == "FAILED"]
    assert len(failed) == 1, "a gate must stop the loop, not be retried into the breaker"
    assert (wd / "report.md").exists()


def test_a_passing_gate_does_not_halt(tmp_path, monkeypatch):
    wd = _run(tmp_path, monkeypatch, relation_passes=True)
    assert not (wd / "halt.json").exists()
    assert (wd / "report.json").exists()


# ── resume after a mid-epoch halt (found resuming a real Go campaign) ───────
#
# Re-entering the halted iteration re-ran its stage into the same runs/iter-N/
# and APPENDED to its runs.jsonl; the design-fidelity gate then refused the
# duplicate rows, so the campaign could never be resumed.

def _drifting_target(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    (repo / "bench.py").write_text(
        "import json, os, sys\n"
        "a = dict(x.lstrip('-').split('=') for x in sys.argv[1:])\n"
        "k = int(a['k'])\n"
        "n = len(os.listdir(os.environ['COUNT_DIR']))\n"
        "open(os.path.join(os.environ['COUNT_DIR'], str(n)), 'w').close()\n"
        "bad = os.path.exists(os.environ['DRIFT_FLAG']) and n >= 2\n"
        "m = 'oops' if bad else 10.0 - (k - 3) ** 2\n"
        "print(json.dumps({'m': m, 'cfg': {'k': k}}))\n")
    (repo / "tests" / "test_rel.py").write_text("def test_k_moves_m():\n    assert True\n")
    return repo


def test_a_campaign_halted_mid_epoch_resumes_and_reuses_its_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "runs"))
    repo = _drifting_target(tmp_path)
    flag, counts = tmp_path / "drift.flag", tmp_path / "counts"
    flag.write_text("x")
    counts.mkdir()
    monkeypatch.setenv("DRIFT_FLAG", str(flag))
    monkeypatch.setenv("COUNT_DIR", str(counts))
    campaign = _campaign(repo)
    wd = Path(setup_work_dir("halt-gate", repo_path=str(repo), campaign=campaign))
    run_campaign(campaign, wd, max_iterations=6, auto_approve=True)
    assert json.loads((wd / "halt.json").read_text())["kind"] == "gate_failed"

    flag.unlink()                                   # the author fixes the cause
    run_campaign(campaign, wd, max_iterations=6, auto_approve=True)   # = nous resume
    assert (wd / "report.json").exists(), "resume never reached the report"
    for rj in wd.glob("runs/iter-*/runs.jsonl"):
        idx = [json.loads(l)["row_index"] for l in rj.read_text().splitlines() if l.strip()]
        assert len(idx) == len(set(idx)), f"{rj}: duplicate rows {idx}"
    reused = [json.loads(l) for rj in wd.glob("runs/iter-*/runs.jsonl")
              for l in rj.read_text().splitlines() if l.strip() and "reused_from" in l]
    assert reused, "the rows measured before the halt were re-measured, not reused"
    # The earlier halt is history now: a completed resume must not still read
    # HALTED in every progress line, and why it once stopped stays on record.
    from orchestrator.optimize.progress import read_progress_snapshot

    assert not (wd / "halt.json").exists()
    assert not read_progress_snapshot(wd).halted
    history = [json.loads(l) for l in (wd / "halt_history.jsonl").read_text().splitlines()]
    assert [h["kind"] for h in history] == ["gate_failed"]
