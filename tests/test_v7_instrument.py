"""v7 instrument checks: instrument.json written by the evaluator session, summarized for later sessions."""
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.instrument import HEADING, instrument_summary, validate_instrument
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.sdk_dispatch import SDKResult
from tests.test_v7_profile import SCORES, _Fake, _campaign, _run, _v7_setup

GOOD = {
    "max_cpu_s": 4.2, "time_limit_s": 2.0, "speed_first": True,
    "noise": {"runs": [74.1, 75.3, 74.6], "min": 74.1, "max": 75.3, "spread": 1.2},
    "knobs": [{"name": "beam_width", "low": 4, "high": 64, "delta": 3.5, "matters": True},
              {"name": "seed_count", "low": 1, "high": 8, "delta": 0.4, "matters": False}],
}


def _write(work, iteration, data):
    d = Path(work) / "runs" / f"iter-{iteration}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "instrument.json").write_text(json.dumps(data))


class TestArtifact:
    def test_good_artifact_validates(self):
        assert validate_instrument(GOOD) == []
        assert validate_instrument(dict(GOOD, time_limit_s=None, knobs=[])) == []

    @pytest.mark.parametrize("bad", [
        {k: v for k, v in GOOD.items() if k != "noise"},
        dict(GOOD, noise={"runs": [74.1, 75.3], "min": 74.1, "max": 75.3, "spread": 1.2}),
        dict(GOOD, speed_first="yes"),
        dict(GOOD, knobs=[{"name": "k", "low": 1, "high": 2}]),
    ])
    def test_bad_artifact_rejected(self, bad):
        assert validate_instrument(bad)

    def test_summary_lines(self, tmp_path):
        _write(tmp_path, 1, GOOD)
        s = instrument_summary(_campaign(design_profile="v7"), tmp_path, 2)
        assert s.startswith(HEADING) and "iter-1/instrument.json" in s
        assert "max CPU 4.2 s" in s and "time limit 2 s" in s and "faster before any tuning" in s
        assert "74.1 to 75.3" in s and "spread 1.2" in s
        assert "above noise beam_width" in s and "drop from sweeps seed_count" in s
        assert len(s.strip().splitlines()) <= 5

    def test_summary_unknown_limit_and_under_half(self, tmp_path):
        _write(tmp_path, 1, dict(GOOD, max_cpu_s=0.8, speed_first=True))
        assert "faster" not in instrument_summary(_campaign(design_profile="v7"), tmp_path, 2)
        _write(tmp_path, 1, dict(GOOD, time_limit_s=None, speed_first=False, knobs=[]))
        s = instrument_summary(_campaign(design_profile="v7"), tmp_path, 2)
        assert "time limit unknown" in s and "faster" not in s and "Knobs" not in s

    def test_invalid_or_missing_gives_no_summary(self, tmp_path):
        c = _campaign(design_profile="v7")
        assert instrument_summary(c, tmp_path, 2) == ""
        _write(tmp_path, 1, {"max_cpu_s": 1})
        assert instrument_summary(c, tmp_path, 2) == ""

    @pytest.mark.parametrize("profile", ["v4", "v5", "v6", None])
    def test_other_profiles_get_nothing(self, tmp_path, profile):
        _write(tmp_path, 1, GOOD)
        assert instrument_summary(_campaign(design_profile=profile), tmp_path, 2) == ""


def _design_prompt(work, campaign, iteration):
    prompts = []

    def fn(**kw):
        prompts.append(kw["messages"][0]["content"])
        r = MagicMock()
        r.choices = [MagicMock(message=MagicMock(content="x"))]
        r.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
        return r
    (work / "runs" / f"iter-{iteration}").mkdir(parents=True, exist_ok=True)
    LLMDispatcher(work_dir=work, campaign=campaign, completion_fn=fn).dispatch(
        "planner", "design", output_path=work / "runs" / f"iter-{iteration}" / "d.md", iteration=iteration)
    return prompts[0]


class TestDesignContext:
    def _evaluator(self, work):
        (work / "evaluator").mkdir(parents=True, exist_ok=True)
        (work / "evaluator" / "README.md").write_text("run: python eval.py\n")

    def test_iteration_2_design_prompt_has_summary_once(self, tmp_path):
        self._evaluator(tmp_path)
        _write(tmp_path, 1, GOOD)
        p = _design_prompt(tmp_path, _campaign(design_profile="v7"), 2)
        assert p.count(HEADING) == 1 and "spread 1.2" in p
        # a handoff that already carries the section is not repeated
        (tmp_path / "handoff.md").write_text("## Handoff\n\n" + instrument_summary(
            _campaign(design_profile="v7"), tmp_path, 2))
        assert _design_prompt(tmp_path, _campaign(design_profile="v7"), 2).count(HEADING) == 1

    def test_absent_artifact_tolerated(self, tmp_path):
        self._evaluator(tmp_path)
        p = _design_prompt(tmp_path, _campaign(design_profile="v7"), 2)
        assert "run: python eval.py" in p and HEADING not in p

    @pytest.mark.parametrize("profile", ["v4", "v5", "v6"])
    def test_other_profiles_design_prompt_unchanged(self, tmp_path, profile):
        self._evaluator(tmp_path)
        _write(tmp_path, 1, GOOD)
        p = _design_prompt(tmp_path, _campaign(design_profile=profile), 2)
        assert HEADING not in p and "instrument" not in p.lower()


class _Recording(_Fake):
    """Records each prompt; the evaluator session writes ``instrument`` (or nothing when None)."""

    def __init__(self, *a, instrument=GOOD, **kw):
        super().__init__(*a, **kw)
        self.instrument, self.prompts = instrument, []

    def __call__(self, **kw):
        self.prompts.append(kw["prompt"])
        out = super().__call__(**kw)
        if "Build the local evaluator" in kw["prompt"] and self.instrument is not None:
            (self.iter_dir / "instrument.json").write_text(json.dumps(self.instrument))
        return out


def _setup(tmp_path, monkeypatch, instrument=GOOD):
    repo, work, it, campaign, fake, d = _v7_setup(tmp_path, monkeypatch, SCORES)
    rec = _Recording(work, it, SCORES, instrument=instrument)
    d._sdk_runner = rec
    (work / "handoff.md").write_text("## Handoff\n\n### Goal\nG\n")
    return repo, work, it, campaign, rec, d


class TestExecute:
    def test_evaluator_writes_instrument_and_later_sessions_see_it(self, tmp_path, monkeypatch):
        repo, work, it, campaign, rec, d = _setup(tmp_path, monkeypatch)
        _run(repo, work, it, campaign, d)
        evaluator_prompt = rec.prompts[0]
        assert str(it.resolve() / "instrument.json") in evaluator_prompt
        assert "3 times" in evaluator_prompt and "largest allowed inputs" in evaluator_prompt
        state = json.loads((it / "arms" / "state.json").read_text())
        assert state["sessions"]["evaluator"]["instrument"] == "valid"
        for p in rec.prompts[1:]:  # every screening session and the winner
            assert p.count(HEADING) == 1 and "spread 1.2" in p
        for f in (work / "handoff.md", it / "handoff_snapshot.md"):
            text = f.read_text()
            assert text.count(HEADING) == 1 and "faster before any tuning" in text

    def test_iteration_2_context_and_handoff_refresh(self, tmp_path, monkeypatch):
        from orchestrator.v7_execute import run_v7_execute
        repo, work, it, campaign, rec, d = _setup(tmp_path, monkeypatch)
        _write(work, 1, GOOD)
        (work / "evaluator").mkdir()
        (work / "evaluator" / "README.md").write_text("python eval.py\n")
        it2 = work / "runs" / "iter-2"
        for sub in ("patches", "inputs", "results"):
            (it2 / sub).mkdir(parents=True, exist_ok=True)
        for name in ("bundle.yaml", "problem.md", "handoff_snapshot.md"):
            (it2 / name).write_text((it / name).read_text())
        # the iteration 2 designer rewrote the handoff with an outdated copy of the section
        (work / "handoff.md").write_text("## Handoff\n\n" + HEADING + ", stale\n\n- old\n\n## Notes\nN\n")
        rec.iter_dir = it2
        run_v7_execute(d, campaign, work, it2, 2, repo, extras=[])
        assert "Build the local evaluator" not in "".join(rec.prompts)
        assert all(p.count(HEADING) == 1 and "iter-1/instrument.json" in p for p in rec.prompts)
        handoff = (work / "handoff.md").read_text()
        assert "stale" not in handoff and "## Notes\nN" in handoff and handoff.count(HEADING) == 1

    def test_missing_instrument_does_not_stop_the_run(self, tmp_path, monkeypatch, caplog):
        repo, work, it, campaign, rec, d = _setup(tmp_path, monkeypatch, instrument=None)
        with caplog.at_level(logging.WARNING):
            _run(repo, work, it, campaign, d)
        assert (it / "findings.json").exists()
        state = json.loads((it / "arms" / "state.json").read_text())
        assert state["sessions"]["evaluator"]["instrument"] == "missing"
        assert any("instrument.json is missing" in r.getMessage() for r in caplog.records)
        assert HEADING not in (work / "handoff.md").read_text()
        assert "No instrument checks recorded yet." in rec.prompts[1]

    def test_invalid_instrument_is_ignored_with_warning(self, tmp_path, monkeypatch):
        repo, work, it, campaign, rec, d = _setup(tmp_path, monkeypatch, instrument={"max_cpu_s": "fast"})
        _run(repo, work, it, campaign, d)
        state = json.loads((it / "arms" / "state.json").read_text())
        assert state["sessions"]["evaluator"]["instrument"].startswith("invalid")
        assert all(HEADING not in p for p in rec.prompts[1:])
