"""The guide's security claims, each pinned to the behaviour that makes it true
(round 5). If the guide is reworded so a claim no longer matches, or the code
changes so a claim is false, one of these fails."""
from __future__ import annotations

from pathlib import Path

GUIDE = (Path(__file__).resolve().parents[1] / "docs" / "optimization-campaign-guide.md").read_text()


def _norm(s: str) -> str:
    return " ".join(s.split())


def test_setsid_claim_is_stated_and_backed():
    text = _norm(GUIDE)
    assert "a `setsid()` before or after the first poll does not escape" in text
    from tests import test_optimize_build_scope as t
    assert hasattr(t, "test_a_child_that_calls_setsid_after_the_first_poll_is_reaped")
    assert hasattr(t, "test_a_target_child_that_calls_setsid_is_still_reaped_and_recorded")


def test_not_probed_claim_lists_wrappers_and_scripts_and_is_backed():
    text = _norm(GUIDE)
    for w in ("`timeout`", "`nice`", "`time`", "`env A=B`", "`./bench.sh`", "`env -i`",
              "`-W ignore`"):
        assert w in text, w
    from tests import test_optimize_private_tree as t
    for name in ("test_a_wrapped_interpreter_with_a_path_into_the_repo_is_refused",
                 "test_a_non_python_or_unparseable_wrapper_is_recorded_as_not_probed",
                 "test_interpreter_flags_with_arguments_are_kept_together",
                 "test_a_launcher_command_is_recorded_as_not_probed"):
        assert hasattr(t, name), name


def test_deleted_key_claim_is_stated_and_backed():
    text = _norm(GUIDE)
    assert "including a re-run build stage. A new key is never minted" in text
    from tests import test_optimize_private_tree as t
    assert hasattr(t, "test_ensure_key_never_mints_a_replacement_for_a_deleted_key")
    assert hasattr(t, "test_a_rerun_build_stage_after_the_key_was_deleted_fails")
    assert hasattr(t, "test_a_deleted_key_is_never_replaced_by_a_new_one")


def test_copy_back_claim_is_stated_and_backed():
    text = _norm(GUIDE)
    assert "never written through" in text and "`row-K.attempt-N`" in text
    from tests import test_optimize_target_env as t
    assert hasattr(t, "test_a_symlink_planted_by_one_attempt_cannot_steer_the_next_attempts_copy")
