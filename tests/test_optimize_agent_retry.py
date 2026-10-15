"""Behavioral tests: the ``plan`` / ``build`` agent calls survive infra hiccups.

``build`` is THE agent call of ``kind: optimization``; a single network blip,
silence-watchdog trip, or context exhaustion there must not kill the campaign.
But one real build attempt costs ~$20 and ~30 minutes, so the retry budget is
small and bounded (``optimization.agent_retries``, default 2), and every
attempt's tokens land in ``llm_metrics.jsonl`` so the cost of retrying is
visible.

No live LLM calls: each test injects a scripted ``sdk_runner=`` fake and asserts
on what lands on disk (``build_summary.md``, ``mechanism_plan.json``,
``llm_metrics.jsonl``, ``retry_log.jsonl``), the return value, or the raised
exception. Backoff is zeroed via ``retry_sleep=`` so nothing sleeps for real.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import build as build_mod
from orchestrator.optimize import plan as plan_mod
from orchestrator.sdk_dispatch import SDKResult, SDKTransientError
from tests.test_optimize_build import _campaign as _build_campaign
from tests.test_optimize_plan import _campaign as _plan_campaign
from tests.test_optimize_plan import _valid_plan

RESUME_MARKER = "continue from where you left off"


def _no_sleep(_s: float) -> None:
    return None


def _scripted(*steps):
    """A fake agent that plays ``steps`` in order, one per attempt.

    Each step is an exception instance (raised), an ``SDKResult`` (returned),
    or a callable ``(kwargs) -> SDKResult`` for steps that react to the prompt
    or watchdog threshold the way a real agent session would.
    """
    queue = list(steps)

    def _run(**kwargs):
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(kwargs)
        return step

    return _run


def _continuing_agent(kwargs) -> SDKResult:
    """Succeeds, and says whether it was told to continue rather than restart."""
    told = RESUME_MARKER in kwargs["prompt"]
    return SDKResult(
        text=f"authored mechanism (continued={told})",
        input_tokens=10, output_tokens=20,
    )


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def test_build_retries_a_transient_failure_and_continues(tmp_path: Path):
    work = tmp_path / "work"
    build_mod.run_build(
        _build_campaign(_repo(tmp_path)), work,
        iteration=1, declared_tests=[],
        sdk_runner=_scripted(SDKTransientError("stream dropped"),
                             _continuing_agent),
        retry_sleep=_no_sleep,
    )
    summary = (work / "runs" / "iter-1" / "build_summary.md").read_text()
    assert "continued=True" in summary  # a retry continues, never restarts
    retries = _rows(work / "retry_log.jsonl")
    assert len(retries) == 1
    assert retries[0]["phase"] == "build"
    assert retries[0]["failure_type"] == "transient"
    assert "stream dropped" in retries[0]["error"]
    assert len(_rows(work / "llm_metrics.jsonl")) == 1


def test_build_context_exhaustion_is_retried_in_a_fresh_session(tmp_path: Path):
    work = tmp_path / "work"
    build_mod.run_build(
        _build_campaign(_repo(tmp_path)), work,
        iteration=1, declared_tests=[],
        sdk_runner=_scripted(
            SDKResult(text="", is_error=True, error_message="Prompt is too long",
                      input_tokens=900_000, output_tokens=40_000, cost_usd=20.0),
            _continuing_agent,
        ),
        retry_sleep=_no_sleep,
    )
    summary = (work / "runs" / "iter-1" / "build_summary.md").read_text()
    assert "continued=True" in summary
    metrics = _rows(work / "llm_metrics.jsonl")
    assert len(metrics) == 2  # the failed attempt's $20 is on the cost axis
    assert metrics[0]["cost_usd"] == 20.0
    assert all(m["phase"] == "build" for m in metrics)
    retries = _rows(work / "retry_log.jsonl")
    assert len(retries) == 1
    assert retries[0]["phase"] == "build"
    assert "Prompt is too long" in retries[0]["error"]


@pytest.mark.parametrize("msg", [
    "authentication_error: invalid x-api-key",
    "invalid_request_error: model not found",
    "quota exhausted",
])
def test_build_fails_fast_on_a_non_retryable_error(tmp_path: Path, msg: str):
    work = tmp_path / "work"
    with pytest.raises(build_mod.BuildFailed, match=msg.split(":")[0]):
        build_mod.run_build(
            _build_campaign(_repo(tmp_path)), work,
            iteration=1, declared_tests=[],
            sdk_runner=_scripted(
                SDKResult(text="", is_error=True, error_message=msg),
                _continuing_agent,  # would succeed — must never be reached
            ),
            retry_sleep=_no_sleep,
        )
    assert len(_rows(work / "llm_metrics.jsonl")) == 1
    assert not (work / "runs" / "iter-1" / "build_summary.md").exists()


def test_build_exhaustion_names_attempts_and_last_error(tmp_path: Path):
    work = tmp_path / "work"
    with pytest.raises(build_mod.BuildFailed) as exc:
        build_mod.run_build(
            _build_campaign(_repo(tmp_path)), work,
            iteration=1, declared_tests=[],
            sdk_runner=_scripted(SDKTransientError("watchdog: 600s silence")),
            retry_sleep=_no_sleep,
        )
    # Default budget: 2 retries = 3 attempts.
    assert "3 attempt" in str(exc.value)
    assert "watchdog: 600s silence" in str(exc.value)
    assert len(_rows(work / "retry_log.jsonl")) == 3


def test_build_retry_budget_is_configurable(tmp_path: Path):
    work = tmp_path / "work"
    campaign = _build_campaign(_repo(tmp_path))
    campaign["optimization"]["agent_retries"] = 0
    with pytest.raises(build_mod.BuildFailed, match="1 attempt"):
        build_mod.run_build(
            campaign, work, iteration=1, declared_tests=[],
            sdk_runner=_scripted(SDKTransientError("blip"), _continuing_agent),
            retry_sleep=_no_sleep,
        )
    assert len(_rows(work / "retry_log.jsonl")) == 1


def test_build_retry_budget_rejects_nonsense(tmp_path: Path):
    campaign = _build_campaign(_repo(tmp_path))
    campaign["optimization"]["agent_retries"] = -1
    with pytest.raises(build_mod.BuildFailed, match="agent_retries"):
        build_mod.run_build(
            campaign, tmp_path / "work", iteration=1, declared_tests=[],
            sdk_runner=_scripted(_continuing_agent), retry_sleep=_no_sleep,
        )


def _threshold_agent(kwargs) -> SDKResult:
    return SDKResult(text=f"threshold={kwargs.get('turn_silence_threshold')}")


@pytest.mark.parametrize("timeouts, expected", [
    (None, "600.0"),                                            # DESIGN default
    ({"turn_silence_threshold_seconds": 300}, "300.0"),         # scalar
    ({"turn_silence_threshold_seconds": {"build": 900}}, "900.0"),
    ({"turn_silence_threshold_seconds": {"design": 50}}, "600.0"),
])
def test_build_runs_under_a_live_silence_watchdog(tmp_path: Path, timeouts, expected):
    work = tmp_path / "work"
    campaign = _build_campaign(_repo(tmp_path))
    if timeouts is not None:
        campaign["sdk_timeouts"] = timeouts
    build_mod.run_build(
        campaign, work, iteration=1, declared_tests=[],
        sdk_runner=_scripted(_threshold_agent), retry_sleep=_no_sleep,
    )
    summary = (work / "runs" / "iter-1" / "build_summary.md").read_text()
    assert summary == f"threshold={expected}"


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def _plan_ok(**kw) -> SDKResult:
    return SDKResult(text=json.dumps(_valid_plan()),
                     input_tokens=100, output_tokens=200, **kw)


def test_plan_retries_a_transient_failure(tmp_path: Path):
    work = tmp_path / "work"
    plan_mod.run_plan(
        _plan_campaign(_repo(tmp_path)), work, iteration=1,
        sdk_runner=_scripted(SDKTransientError("connection reset"), _plan_ok()),
        retry_sleep=_no_sleep,
    )
    assert (work / plan_mod.PLAN_FILENAME).exists()
    retries = _rows(work / "retry_log.jsonl")
    assert [r["phase"] for r in retries] == ["plan"]
    assert len(_rows(work / "llm_metrics.jsonl")) == 1


def test_plan_exhaustion_fails_closed_and_logs_every_attempt(tmp_path: Path):
    work = tmp_path / "work"
    with pytest.raises(plan_mod.PlanRejected) as exc:
        plan_mod.run_plan(
            _plan_campaign(_repo(tmp_path)), work, iteration=1,
            sdk_runner=_scripted(SDKResult(
                text="", is_error=True, error_message="overloaded_error",
                input_tokens=7,
            )),
            retry_sleep=_no_sleep,
        )
    assert "3 attempt" in str(exc.value)
    assert "overloaded_error" in str(exc.value)
    assert not (work / plan_mod.PLAN_FILENAME).exists()
    metrics = _rows(work / "llm_metrics.jsonl")
    assert len(metrics) == 3 and all(m["phase"] == "plan" for m in metrics)
    assert len(_rows(work / "retry_log.jsonl")) == 3


def test_plan_non_retryable_error_fails_closed_immediately(tmp_path: Path):
    work = tmp_path / "work"
    with pytest.raises(plan_mod.PlanRejected, match="authentication"):
        plan_mod.run_plan(
            _plan_campaign(_repo(tmp_path)), work, iteration=1,
            sdk_runner=_scripted(
                SDKResult(text="", is_error=True,
                          error_message="authentication_error: bad key"),
                _plan_ok(),
            ),
            retry_sleep=_no_sleep,
        )
    assert not (work / plan_mod.PLAN_FILENAME).exists()
    assert len(_rows(work / "llm_metrics.jsonl")) == 1


def test_plan_watchdog_threshold_has_its_own_key(tmp_path: Path):
    work = tmp_path / "work"
    campaign = _plan_campaign(_repo(tmp_path))
    campaign["sdk_timeouts"] = {"turn_silence_threshold_seconds": {"plan": 450}}

    def agent(kwargs):
        plan = _valid_plan()
        plan["approach"]["summary"] += f" threshold={kwargs.get('turn_silence_threshold')}"
        return SDKResult(text=json.dumps(plan))

    plan_mod.run_plan(campaign, work, iteration=1,
                      sdk_runner=_scripted(agent), retry_sleep=_no_sleep)
    written = json.loads((work / plan_mod.PLAN_FILENAME).read_text())
    assert written["approach"]["summary"].endswith("threshold=450.0")


def test_campaign_schema_accepts_plan_and_build_watchdog_keys_and_agent_retries():
    import jsonschema
    import yaml

    schema = yaml.safe_load(
        (Path(__file__).parent.parent / "orchestrator" / "schemas"
         / "campaign.schema.yaml").read_text()
    )
    tst = schema["properties"]["sdk_timeouts"]["properties"][
        "turn_silence_threshold_seconds"]
    jsonschema.validate({"plan": 600, "build": 900}, tst)
    retries = schema["properties"]["optimization"]["properties"]["agent_retries"]
    jsonschema.validate(2, retries)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(-1, retries)
