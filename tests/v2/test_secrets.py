"""Tests for orchestrator.v2.secrets — secret masking (spec 3.14)."""

from orchestrator.v2.secrets import check_secrets, mask_secrets


# ── mask_secrets ─────────────────────────────────────────────────────────


class TestMaskSecrets:
    def test_single_secret_replaced(self):
        assert mask_secrets("key=abc123", {"API_KEY": "abc123"}) == "key=<secret:API_KEY>"

    def test_multiple_secrets_in_same_text(self):
        text = "host=db.internal port=5432 pass=hunter2"
        secrets = {"DB_HOST": "db.internal", "DB_PASS": "hunter2"}
        result = mask_secrets(text, secrets)
        assert result == "host=<secret:DB_HOST> port=5432 pass=<secret:DB_PASS>"

    def test_empty_secrets_dict_returns_text_unchanged(self):
        assert mask_secrets("some text", {}) == "some text"

    def test_secret_not_present_returns_text_unchanged(self):
        assert mask_secrets("nothing here", {"KEY": "missing"}) == "nothing here"

    def test_secret_appears_multiple_times(self):
        result = mask_secrets("tok tok tok", {"T": "tok"})
        assert result == "<secret:T> <secret:T> <secret:T>"

    def test_overlapping_secrets_longer_value_first(self):
        # "abc123def" should be replaced before "abc123" gets a chance
        text = "value=abc123def"
        secrets = {"LONG": "abc123def", "SHORT": "abc123"}
        result = mask_secrets(text, secrets)
        assert result == "value=<secret:LONG>"

    def test_empty_value_secret_skipped(self):
        text = "keep this"
        result = mask_secrets(text, {"EMPTY": ""})
        assert result == "keep this"

    def test_empty_text_returns_empty(self):
        assert mask_secrets("", {"KEY": "val"}) == ""

    def test_secret_at_start_and_end(self):
        result = mask_secrets("secretXsecret", {"S": "secret"})
        assert result == "<secret:S>X<secret:S>"

    def test_multiline_text(self):
        text = "line1: tok123\nline2: tok123\n"
        result = mask_secrets(text, {"TOKEN": "tok123"})
        assert result == "line1: <secret:TOKEN>\nline2: <secret:TOKEN>\n"


# ── check_secrets ────────────────────────────────────────────────────────


class TestCheckSecrets:
    def test_secret_present(self):
        assert check_secrets("key=abc123", {"API_KEY": "abc123"}) == ["API_KEY"]

    def test_multiple_secrets_present_sorted(self):
        text = "host=db.internal pass=hunter2"
        secrets = {"DB_PASS": "hunter2", "DB_HOST": "db.internal"}
        result = check_secrets(text, secrets)
        assert result == ["DB_HOST", "DB_PASS"]

    def test_no_secrets_present(self):
        assert check_secrets("clean text", {"KEY": "missing"}) == []

    def test_empty_secrets_dict(self):
        assert check_secrets("anything", {}) == []

    def test_empty_value_secret_not_flagged(self):
        assert check_secrets("anything", {"EMPTY": ""}) == []

    def test_substring_match_is_detected(self):
        # "abc" appears inside "xabcx" — substring match counts
        assert check_secrets("xabcx", {"SHORT": "abc"}) == ["SHORT"]

    def test_empty_text(self):
        assert check_secrets("", {"KEY": "val"}) == []

    def test_multiline_detection(self):
        text = "line1\nSECRET_VAL\nline3"
        assert check_secrets(text, {"S": "SECRET_VAL"}) == ["S"]
