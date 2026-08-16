"""The guide/CLAUDE.md must describe the model calls the kind actually makes.

Spec §1: the branch's docs claimed verify and confirm each make a model call;
neither does. This test greps for the retired claims so they cannot return.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED = [
    "one model call interprets the fitted surface",
    "one model call authors the mechanism + its native tests.",  # was attributed to verify
    "interpretation (at the end) | 1",
]


def test_docs_do_not_claim_verify_or_confirm_model_calls():
    for rel in ("CLAUDE.md", "docs/optimization-campaign-guide.md",
                "orchestrator/optimize/stage_runner.py"):
        text = (ROOT / rel).read_text()
        for phrase in RETIRED:
            assert phrase not in text, f"{rel} still says {phrase!r}"


def test_claude_md_states_the_true_call_count():
    text = (ROOT / "CLAUDE.md").read_text()
    assert "the only model call in the kind is `build`" in text
