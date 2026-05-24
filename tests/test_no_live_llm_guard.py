"""Meta-tests: verify the conftest's no-live-LLM guard actually fires.

If these tests stop passing, the guard is broken — and a real test could
silently make a live API call. CI should fail loudly.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

from tests.conftest import LiveLLMCallBlocked


class TestEnvKeysStripped:
    """The guard removes LLM API key env vars so any code that reads them
    sees ``None`` and falls back to the disabled-mode path."""

    def test_openai_api_key_unset(self):
        assert os.environ.get("OPENAI_API_KEY") is None

    def test_anthropic_api_key_unset(self):
        assert os.environ.get("ANTHROPIC_API_KEY") is None


class TestUrlopenGuard:
    """Direct urllib.request.urlopen calls to LLM hosts must raise."""

    @pytest.mark.parametrize("host", [
        "https://api.anthropic.com/v1/messages",
        "https://api.openai.com/v1/chat/completions",
    ])
    def test_blocked_host_raises(self, host):
        with pytest.raises(LiveLLMCallBlocked):
            urllib.request.urlopen(host)

    def test_non_blocked_host_passes_through_signature(self):
        """The guard is a substring check on known LLM hosts; calls to
        other URLs are NOT blocked by this fixture (so tests that legitimately
        post to e.g. a Slack webhook still go through their own injection)."""
        # We don't actually call out to the network — just assert the guard
        # has correct shape for a non-blocked URL.
        # (The guard delegates to the original urlopen for non-blocked URLs.)
        try:
            urllib.request.urlopen("http://localhost:1/", timeout=0.01)
        except LiveLLMCallBlocked:
            pytest.fail("guard wrongly blocked a non-LLM host")
        except (urllib.error.URLError, OSError, TimeoutError):
            pass  # expected — connection refused / no listener


class TestSDKQueryGuard:
    """When claude_agent_sdk is installed, the guard replaces query() with
    a hard-fail. SDKDispatcher tests inject a fake sdk_runner instead."""

    def test_sdk_query_blocked_when_installed(self):
        try:
            import claude_agent_sdk  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("claude-agent-sdk not installed; nothing to guard")

        async def _drive():
            async for _ in claude_agent_sdk.query(prompt="x", options=None):
                pass

        import anyio
        with pytest.raises(LiveLLMCallBlocked):
            anyio.run(_drive)
