import json
import urllib.request
from pathlib import Path

import pytest
import yaml


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"


# ─── No-live-LLM enforcement (project principle, see CLAUDE.md) ────────────


_BLOCKED_HOSTS = (
    "api.anthropic.com",
    "api.openai.com",
    "api.litellm.ai",
)


class LiveLLMCallBlocked(RuntimeError):
    """A test triggered something that would call a real LLM provider.

    The fix is to inject a fake at the dispatcher seam (sdk_runner=,
    completion_fn=, monkeypatch subprocess.run, etc.) — NEVER to
    disable this guard. See CLAUDE.md.
    """


@pytest.fixture(autouse=True)
def block_live_llm_calls(monkeypatch):
    """Auto-applied to every test: strip LLM API keys from env and refuse
    real network calls to known LLM hosts.

    Tests that legitimately need to construct an OpenAI client should pass
    api_key= explicitly (existing tests already do this). Tests that need
    to dispatch an agent should inject a fake — see tests/CLAUDE.md.
    """
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    original_urlopen = urllib.request.urlopen

    def _guarded_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if any(host in url for host in _BLOCKED_HOSTS):
            raise LiveLLMCallBlocked(
                f"Test attempted urlopen to {url!r} — live LLM calls are "
                "forbidden. Inject a fake at the dispatcher seam. See CLAUDE.md."
            )
        return original_urlopen(req, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", _guarded_urlopen)

    # Patch claude_agent_sdk.query if installed; this catches accidental
    # uses of the default sdk_runner path.
    try:
        import claude_agent_sdk  # type: ignore[import-not-found]

        async def _blocked_query(*args, **kwargs):
            raise LiveLLMCallBlocked(
                "Test invoked claude_agent_sdk.query — pass sdk_runner= "
                "to SDKDispatcher with a fake. See CLAUDE.md."
            )
            yield  # pragma: no cover  (makes the function an async generator)

        monkeypatch.setattr(claude_agent_sdk, "query", _blocked_query)
    except ImportError:
        pass

    # Block live PyMC NUTS sampling (issue #164). Importing pymc is
    # allowed; running pymc.sample() is not — it pulls in MCMC chains
    # that take seconds-to-minutes per call and inject randomness into
    # the test suite. The seam is principles_posterior.posterior(
    # posterior_fn=...) — inject a deterministic fake.
    try:
        import pymc  # type: ignore[import-not-found]

        def _blocked_sample(*args, **kwargs):
            raise RuntimeError(
                "Test invoked pymc.sample — live MCMC is forbidden in tests. "
                "Inject a deterministic posterior_fn= into "
                "orchestrator.principles_posterior.posterior(). See CLAUDE.md."
            )

        monkeypatch.setattr(pymc, "sample", _blocked_sample)
    except ImportError:
        pass

    # Block live Optuna trial execution (issue #165). Importing optuna
    # is allowed; running Study.optimize() is not — it triggers per-trial
    # function calls that the seam is meant to control. Inject a sampler=
    # callable into orchestrator.arm_sweep.run_sweep() instead.
    try:
        import optuna  # type: ignore[import-not-found]

        def _blocked_optimize(self, *args, **kwargs):
            raise RuntimeError(
                "Test invoked optuna Study.optimize — live trial execution "
                "is forbidden in tests. Inject a sampler= callable into "
                "orchestrator.arm_sweep.run_sweep(). See CLAUDE.md."
            )

        monkeypatch.setattr(optuna.study.Study, "optimize", _blocked_optimize)
    except ImportError:
        pass


@pytest.fixture
def schemas_dir():
    return SCHEMAS_DIR


@pytest.fixture
def templates_dir():
    return TEMPLATES_DIR


@pytest.fixture
def load_schema(schemas_dir):
    def _load(name: str) -> dict:
        path = schemas_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        return json.loads(path.read_text())
    return _load


@pytest.fixture
def load_template(templates_dir):
    def _load(name: str):
        path = templates_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        if path.suffix == ".json":
            return json.loads(path.read_text())
        return path.read_text()
    return _load
