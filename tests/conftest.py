import urllib.request

import pytest


# ─── No-live-LLM enforcement (project principle, see CLAUDE.md) ────────────


_BLOCKED_HOSTS = (
    "api.anthropic.com",
    "api.openai.com",
    "api.litellm.ai",
)


class LiveLLMCallBlocked(RuntimeError):
    """A test triggered something that would call a real LLM provider.

    The fix is to inject a fake (tests.fakes.sdk_client.FakeClient,
    monkeypatch subprocess.run, etc.) — NEVER to disable this guard.
    See CLAUDE.md.
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

    # #239: NOUS_CAMPAIGN_PARENT relocates campaign work_dirs. Strip it
    # from every test's environment so that tests asserting on legacy
    # paths (<repo>/.nous/<run>) don't fail when a contributor follows
    # the README's recommendation to export the var in their shell rc.
    # Tests that legitimately need the var set use monkeypatch.setenv
    # to opt back in.
    monkeypatch.delenv("NOUS_CAMPAIGN_PARENT", raising=False)

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
    # one-shot SDK calls.
    try:
        import claude_agent_sdk  # type: ignore[import-not-found]

        async def _blocked_query(*args, **kwargs):
            raise LiveLLMCallBlocked(
                "Test invoked claude_agent_sdk.query — use "
                "tests.fakes.sdk_client.FakeClient instead. See CLAUDE.md."
            )
            yield  # pragma: no cover  (makes the function an async generator)

        monkeypatch.setattr(claude_agent_sdk, "query", _blocked_query)
    except ImportError:
        pass

    # Block ClaudeSDKClient.connect — tests must use FakeClient instead.
    try:
        from claude_agent_sdk import ClaudeSDKClient

        def _blocked_connect(self, *args, **kwargs):
            raise LiveLLMCallBlocked(
                "Test invoked ClaudeSDKClient.connect — use "
                "tests.fakes.sdk_client.FakeClient instead. See CLAUDE.md."
            )

        monkeypatch.setattr(ClaudeSDKClient, "connect", _blocked_connect)
    except ImportError:
        pass
