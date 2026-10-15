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
    "1 design call",     # was the verify row of the iteration table
    "1 analyze call",    # was the confirm row of the iteration table
    "Once the model proposes",
]


def test_docs_do_not_claim_verify_or_confirm_model_calls():
    for rel in ("CLAUDE.md", "docs/optimization-campaign-guide.md",
                "orchestrator/optimize/stage_runner.py"):
        text = (ROOT / rel).read_text()
        for phrase in RETIRED:
            assert phrase not in text, f"{rel} still says {phrase!r}"


def test_claude_md_states_the_true_call_count():
    text = (ROOT / "CLAUDE.md").read_text()
    assert ("the only model calls\nin the kind are the opt-in `plan` and `build` stages"
            in text)


SCHEMA_RETIRED = [
    "the model proposes",
    "model interprets the fitted",
    "when the model proposes factors",
    "~3 model calls",
]


def test_schema_does_not_claim_a_model_proposes_or_interprets():
    """Factors are author-declared and report/gate surfaces are rendered with
    zero tokens; the schema descriptions an authoring agent reads must say so."""
    text = (ROOT / "orchestrator/schemas/campaign.schema.yaml").read_text()
    for phrase in SCHEMA_RETIRED:
        assert phrase.lower() not in text.lower(), f"schema still says {phrase!r}"
