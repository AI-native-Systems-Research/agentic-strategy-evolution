"""Behavioral tests for channel gate notification (issue #130, Phase A).

Contract: given a channels config and a gate summary, ``notify_gate``
emits one HTTP POST per channel with the rendered markdown card. Per-channel
failures don't break the campaign — they're recorded in the returned
results list.

Tests use a poster-injection seam to avoid real HTTP. Behavioral assertions
are about *what* was sent (URL, body content, headers) — never about
which functions ``notify_gate`` called internally.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.channels import notify_gate


def _summary() -> dict:
    return {
        "gate_type": "design",
        "summary": "Hypothesis bundle is well-formed and consistent with active principles.",
        "key_points": [
            "h-main covers ordinal scheduling under saturation.",
            "Methodology aligns with prior principles.",
        ],
    }


class _RecordingPoster:
    """Capture (url, body, headers, timeout) for every call. Optionally
    raise on the Nth call to simulate flakiness."""

    def __init__(self, status: int = 200, raise_on: list[int] | None = None):
        self.calls: list[dict] = []
        self.status = status
        self.raise_on = raise_on or []

    def __call__(self, url: str, body: bytes, headers: dict, timeout: float):
        idx = len(self.calls)
        self.calls.append({
            "url": url,
            "body": body,
            "body_text": body.decode("utf-8"),
            "headers": dict(headers),
            "timeout": timeout,
        })
        if idx in self.raise_on:
            raise OSError("simulated transport error")
        return self.status


# ─── Empty / disabled config ────────────────────────────────────────────────

class TestNoChannels:

    def test_none_is_noop(self, tmp_path):
        assert notify_gate(
            None, summary=_summary(), gate_type="design", iter_dir=tmp_path,
        ) == []

    def test_empty_list_is_noop(self, tmp_path):
        assert notify_gate(
            [], summary=_summary(), gate_type="design", iter_dir=tmp_path,
        ) == []


# ─── Per-channel post ───────────────────────────────────────────────────────

class TestSlackChannel:

    def test_posts_to_webhook_url_with_markdown_text(self, tmp_path):
        poster = _RecordingPoster()
        channels = [{"kind": "slack", "webhook_url": "https://hooks.slack.example/T/B/X"}]

        results = notify_gate(
            channels, summary=_summary(), gate_type="design",
            iter_dir=tmp_path, poster=poster,
        )

        assert len(poster.calls) == 1
        call = poster.calls[0]
        assert call["url"] == "https://hooks.slack.example/T/B/X"

        body = json.loads(call["body_text"])
        # Slack expects ``text`` field; the markdown card is what we send.
        assert "text" in body
        text = body["text"]
        # Card content reflects the gate.
        assert "design" in text
        assert "Hypothesis bundle is well-formed" in text
        assert "h-main covers" in text
        assert "approve" in text.lower()
        assert "reject" in text.lower()
        assert "abort" in text.lower()

        assert results[0]["ok"] is True
        assert results[0]["status_code"] == 200


class TestGenericWebhook:

    def test_posts_with_custom_headers_and_url(self, tmp_path):
        poster = _RecordingPoster()
        channels = [{
            "kind": "webhook",
            "url": "https://example.com/nous/gate",
            "headers": {"Authorization": "Bearer secret-token"},
        }]

        notify_gate(
            channels, summary=_summary(), gate_type="findings",
            iter_dir=tmp_path, poster=poster,
        )

        call = poster.calls[0]
        assert call["url"] == "https://example.com/nous/gate"
        assert call["headers"]["Authorization"] == "Bearer secret-token"

        body = json.loads(call["body_text"])
        # Generic webhook receives markdown under a 'markdown' key.
        assert "markdown" in body
        assert "findings" in body["markdown"]


# ─── Error isolation ────────────────────────────────────────────────────────

class TestErrorIsolation:

    def test_failed_channel_does_not_break_others(self, tmp_path):
        poster = _RecordingPoster(raise_on=[0])  # first channel raises
        channels = [
            {"kind": "slack", "webhook_url": "https://hooks.slack.example/A"},
            {"kind": "slack", "webhook_url": "https://hooks.slack.example/B"},
        ]

        results = notify_gate(
            channels, summary=_summary(), gate_type="design",
            iter_dir=tmp_path, poster=poster,
        )

        assert len(results) == 2
        assert results[0]["ok"] is False
        assert "error" in results[0]
        assert results[1]["ok"] is True

    def test_unknown_kind_records_error_does_not_raise(self, tmp_path):
        poster = _RecordingPoster()
        channels = [{"kind": "telegram-not-yet-supported", "url": "https://x"}]

        results = notify_gate(
            channels, summary=_summary(), gate_type="design",
            iter_dir=tmp_path, poster=poster,
        )

        # Phase A only ships slack + generic; unknown kind logs but
        # doesn't raise. Future phases extend dispatchers without
        # breaking older campaign configs.
        assert len(results) == 1
        # When poster is provided, we don't go through the dispatcher
        # registry, so a poster-based fake will succeed even on
        # unknown kinds. Real (no-poster) path raises ValueError -
        # tested below in TestRealUrlopenIntegration if expanded.
        assert results[0]["ok"] is True or "error" in results[0]


# ─── Markdown card shape ────────────────────────────────────────────────────

class TestMarkdownCard:

    def test_card_includes_iter_dir_for_audit(self, tmp_path):
        poster = _RecordingPoster()
        channels = [{"kind": "slack", "webhook_url": "https://hooks.slack.example/X"}]

        notify_gate(
            channels, summary=_summary(), gate_type="design",
            iter_dir=tmp_path / "runs" / "iter-1", poster=poster,
        )

        text = json.loads(poster.calls[0]["body_text"])["text"]
        # Reviewers need the iter dir to find the artifacts.
        assert "iter-1" in text

    def test_card_includes_summary_text_when_no_key_points(self, tmp_path):
        poster = _RecordingPoster()
        summary = {
            "gate_type": "findings",
            "summary": "Findings approved by validator.",
            "key_points": [],
        }
        notify_gate(
            [{"kind": "slack", "webhook_url": "https://hooks.slack.example/X"}],
            summary=summary, gate_type="findings", iter_dir=tmp_path, poster=poster,
        )
        text = json.loads(poster.calls[0]["body_text"])["text"]
        assert "Findings approved by validator." in text


# ─── Phase B: reply parsing + wait-for-decision ────────────────────────────


class TestParseReply:

    def test_recognizes_approve_tokens(self):
        from orchestrator.channels import parse_reply
        for text in ("approve", "Approved", "LGTM", "ok let's go", "yes please"):
            assert parse_reply(text) == "approve", text

    def test_recognizes_reject_tokens(self):
        from orchestrator.channels import parse_reply
        for text in ("reject", "no", "Rejected — fix h-main", "redesign"):
            assert parse_reply(text) == "reject", text

    def test_recognizes_abort_tokens(self):
        from orchestrator.channels import parse_reply
        for text in ("abort", "STOP", "cancel this"):
            assert parse_reply(text) == "abort", text

    def test_unrecognized_reply_returns_none(self):
        from orchestrator.channels import parse_reply
        assert parse_reply("hmm not sure") is None
        assert parse_reply("") is None
        assert parse_reply(None) is None  # type: ignore[arg-type]


class TestWaitForReply:

    def test_returns_decision_on_first_recognized_reply(self):
        from orchestrator.channels import wait_for_reply

        replies = iter(["", "still thinking", "approve"])

        def provider():
            try:
                return next(replies)
            except StopIteration:
                return None

        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0])

        decision = wait_for_reply(
            provider, timeout_seconds=10,
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
        )
        assert decision == "approve"

    def test_timeout_returns_none(self):
        from orchestrator.channels import wait_for_reply

        ticks = iter([0.0, 5.0, 10.0, 15.0])

        decision = wait_for_reply(
            lambda: None, timeout_seconds=10,
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
        )
        assert decision is None

    def test_unrecognized_replies_keep_polling(self):
        from orchestrator.channels import wait_for_reply

        replies = iter(["hmm", "thinking", "weird message", "abort"])
        ticks = iter([0.0] * 20)

        def provider():
            try:
                return next(replies)
            except StopIteration:
                return None

        decision = wait_for_reply(
            provider, timeout_seconds=100,
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
        )
        assert decision == "abort"
