"""The guide's examples are executable truth, not prose (Task 13).

``docs/optimization-campaign-guide.md`` is the authoring interface for
``kind: optimization`` campaigns -- these campaigns are authored by AI, so
ambiguity in the guide produces invalid campaigns rather than a human who
asks a clarifying question. This test extracts every ```yaml fenced block
in the guide and holds each complete campaign example to the same bar the
real validator applies at authoring time:

1. Every ```yaml block parses as YAML.
2. Every block that is a complete campaign (has ``research_question``)
   passes ``campaign.schema.yaml``.
3. Every such campaign passes ``validate_optimization_campaign`` with zero
   hard errors (``WARN:``-prefixed strings are advisory and expected --
   rules 7 and 10 are warnings by design).
4. Every factor in every example has >=1 ``correctness`` relation and a
   non-trivial ``manipulation`` predicate (``predicates.is_trivial``).
5. No example uses the retired ``ordinal`` / ``categorical`` / ``continuous``
   type vocabulary -- only ``numeric`` and ``choice``.
6. No example names a ``held_out`` metric anywhere in ``primary``,
   ``constraints``, or ``regimes``.

An example that fails its own validator is the single most damaging thing
a doc for AI authors can contain -- this exact check caught the design
spec's own worked example shipping a trivially-true predicate during
design review. When an example fails here, the fix is to the GUIDE, never
to this test.
"""
from __future__ import annotations

import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.optimize.predicates import is_trivial
from orchestrator.validate import validate_optimization_campaign

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = REPO_ROOT / "docs" / "optimization-campaign-guide.md"
SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml"

RETIRED_TYPES = {"ordinal", "categorical", "continuous"}


def _schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text())


def _guide_text() -> str:
    if not GUIDE_PATH.exists():
        pytest.fail(f"guide not found at {GUIDE_PATH}")
    return GUIDE_PATH.read_text()


def _extract_yaml_blocks(text: str) -> list[str]:
    """Every ```yaml ... ``` fenced block in the guide, in document order."""
    return re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)


def _yaml_blocks() -> list[str]:
    blocks = _extract_yaml_blocks(_guide_text())
    if not blocks:
        pytest.fail("no ```yaml blocks found in the guide")
    return blocks


def _parsed_blocks() -> list[object]:
    parsed = []
    for i, block in enumerate(_yaml_blocks()):
        try:
            parsed.append(yaml.safe_load(block))
        except yaml.YAMLError as exc:
            pytest.fail(f"yaml block #{i} failed to parse: {exc}\n---\n{block}")
    return parsed


def _complete_campaigns() -> list[dict]:
    """Blocks that are a full campaign (declare research_question)."""
    campaigns = []
    for obj in _parsed_blocks():
        if isinstance(obj, dict) and "research_question" in obj:
            campaigns.append(obj)
    if not campaigns:
        pytest.fail("no complete campaign examples (with research_question) found")
    return campaigns


# ---------------------------------------------------------------------------
# Check 1: every ```yaml block parses.
# ---------------------------------------------------------------------------


def test_every_yaml_block_parses():
    blocks = _yaml_blocks()
    for i, block in enumerate(blocks):
        try:
            yaml.safe_load(block)
        except yaml.YAMLError as exc:
            pytest.fail(f"yaml block #{i} failed to parse: {exc}\n---\n{block}")


# ---------------------------------------------------------------------------
# Check 2: every complete campaign passes the JSON Schema.
# ---------------------------------------------------------------------------


def test_every_complete_campaign_passes_schema():
    schema = _schema()
    for i, campaign in enumerate(_complete_campaigns()):
        try:
            jsonschema.validate(campaign, schema)
        except jsonschema.ValidationError as exc:
            name = campaign.get("run_id", f"<example #{i}>")
            pytest.fail(f"campaign {name!r} failed schema validation: {exc}")


# ---------------------------------------------------------------------------
# Check 3: every complete campaign passes validate_optimization_campaign
# with zero HARD errors. WARN:-prefixed strings are advisory (rules 7, 10).
# ---------------------------------------------------------------------------


def test_every_complete_campaign_passes_cross_field_validator():
    for campaign in _complete_campaigns():
        name = campaign.get("run_id", campaign.get("research_question", "<example>"))
        errors = validate_optimization_campaign(campaign)
        hard_errors = [e for e in errors if not e.startswith("WARN:")]
        assert hard_errors == [], (
            f"campaign {name!r} has hard validator errors: {hard_errors}"
        )


# ---------------------------------------------------------------------------
# Check 4: every factor has >=1 correctness relation and a non-trivial
# manipulation predicate.
# ---------------------------------------------------------------------------


def test_every_factor_has_correctness_relation_and_nontrivial_manipulation():
    for campaign in _complete_campaigns():
        name = campaign.get("run_id", "<example>")
        opt = campaign.get("optimization") or {}
        factors = opt.get("factors") or []
        assert factors, f"campaign {name!r} declares an optimization block with no factors"
        for factor in factors:
            fid = factor.get("id", "<unknown>")

            relations = factor.get("relations") or []
            has_correctness = any(
                isinstance(r, dict) and r.get("kind") == "correctness"
                for r in relations
            )
            assert has_correctness, (
                f"campaign {name!r} factor {fid!r} has no correctness relation"
            )

            man = factor.get("manipulation")
            assert isinstance(man, dict), (
                f"campaign {name!r} factor {fid!r} has no manipulation predicate"
            )
            assert not is_trivial(man), (
                f"campaign {name!r} factor {fid!r} has a trivial manipulation "
                f"predicate: {man!r}"
            )


# ---------------------------------------------------------------------------
# Check 5: no example uses the retired type vocabulary.
# ---------------------------------------------------------------------------


def test_no_example_uses_retired_type_vocabulary():
    for campaign in _complete_campaigns():
        name = campaign.get("run_id", "<example>")
        opt = campaign.get("optimization") or {}
        for factor in opt.get("factors") or []:
            ftype = factor.get("type")
            assert ftype not in RETIRED_TYPES, (
                f"campaign {name!r} factor {factor.get('id')!r} uses retired "
                f"type {ftype!r} -- only 'numeric' and 'choice' are accepted"
            )
            assert ftype in ("numeric", "choice"), (
                f"campaign {name!r} factor {factor.get('id')!r} has an "
                f"unrecognized type {ftype!r}"
            )


# ---------------------------------------------------------------------------
# Check 6: no example names a held_out metric anywhere in primary,
# constraints, or regimes. (This mirrors validator rule 2, but is asserted
# independently here since it is specifically called out as a guide
# obligation, not just a validator obligation.)
# ---------------------------------------------------------------------------


def test_no_held_out_metric_leaks_into_primary_constraints_or_regimes():
    for campaign in _complete_campaigns():
        name = campaign.get("run_id", "<example>")
        opt = campaign.get("optimization") or {}
        response = opt.get("response") or {}
        held_out = {m.strip().lower() for m in (response.get("held_out") or [])}
        if not held_out:
            continue

        primary_metric = (response.get("primary") or {}).get("metric")
        if primary_metric:
            assert primary_metric.strip().lower() not in held_out, (
                f"campaign {name!r}: held_out leaks into response.primary"
            )

        for constraint in response.get("constraints") or []:
            cmetric = constraint.get("metric") or constraint.get("observable")
            if cmetric:
                assert cmetric.strip().lower() not in held_out, (
                    f"campaign {name!r}: held_out metric {cmetric!r} leaks "
                    f"into response.constraints"
                )

        for regime in response.get("regimes") or []:
            rmetric = regime.get("metric") or regime.get("observable")
            if rmetric:
                assert rmetric.strip().lower() not in held_out, (
                    f"campaign {name!r}: held_out metric {rmetric!r} leaks "
                    f"into response.regimes"
                )


# ---------------------------------------------------------------------------
# Sanity: the guide actually contains the four worked examples the brief
# asks for, and the anti-pattern section pairs a wrong/right example.
# ---------------------------------------------------------------------------


def test_guide_has_at_least_four_complete_worked_examples():
    campaigns = _complete_campaigns()
    assert len(campaigns) >= 4, (
        f"expected >= 4 complete worked example campaigns, found "
        f"{len(campaigns)}"
    )


def test_guide_mentions_anti_patterns_section():
    text = _guide_text()
    assert re.search(r"anti-pattern", text, re.IGNORECASE), (
        "guide has no anti-patterns section"
    )


# ---------------------------------------------------------------------------
# Task 16: the compiled policy is documented, and the section's own example
# exercises the fields the epoch reads. The needles below are the vocabulary a
# reader has to be able to search for -- an artifact name they will find on
# disk, a campaign field they have to declare, and the two bounds they must not
# confuse. Checked as SUBSTRINGS of the guide rather than by re-parsing the
# section, because the extraction tests above already hold every campaign block
# in the section to the real validator: this test only asserts the section
# exists and names what it must name.
# ---------------------------------------------------------------------------


GUIDE_POLICY_NEEDLES = (
    "## The compiled policy",
    "policy.json",
    "policy.sha256",
    "known_valid_baseline",
    "shortlist_size",
    "residual_regret",
    # The REAL on-disk name. Spec §3.9's artifact table calls this `epoch.json`;
    # `stage_runner._close_iteration` writes `epoch_end-<epoch>.json`, one per
    # epoch, at the work_dir root. The guide documents the name a reader will
    # actually find, and says so where it transcribes the spec's table.
    "epoch_end",
    "transitions.jsonl",
    "semantic exception",
    "terminal discrimination",
)


def test_guide_documents_the_compiled_policy():
    text = _guide_text()
    for needle in GUIDE_POLICY_NEEDLES:
        assert needle in text, needle


def test_guide_compiled_policy_example_declares_the_epoch_fields():
    """At least one complete example declares `policy`, `workload`, and a
    `known_valid_baseline` -- the three blocks the compiled epoch reads that
    the pre-Task-16 examples did not exercise.

    Asserted over the extracted campaigns rather than as prose needles so the
    example stays a VALID campaign (checks 1-6 above run over the same list),
    not just a plausible-looking YAML block.
    """
    campaigns = _complete_campaigns()
    matching = [
        c for c in campaigns
        if all(k in (c.get("optimization") or {})
               for k in ("policy", "workload", "known_valid_baseline"))
    ]
    assert matching, (
        "no complete example declares all of optimization.policy, "
        "optimization.workload, and optimization.known_valid_baseline; the "
        "compiled-policy section must ship one so the extraction tests "
        "validate the fields it documents"
    )
    for c in matching:
        opt = c["optimization"]
        assert "shortlist_size" in (opt["design"].get("confirm") or {}), (
            f"example {c.get('run_id')!r} documents the terminal stage but "
            f"leaves design.confirm.shortlist_size implicit"
        )
        assert "seed_env" in opt["workload"], (
            f"example {c.get('run_id')!r} declares workload without seed_env"
        )


# ---------------------------------------------------------------------------
# The artifact names the guide and docs/data-model.md promise must be the ones
# the code actually writes. A doc naming an artifact that does not exist is
# the same class of defect as the "phantom claims" Phase 0 of the compiled-
# policy plan removed (spec §1) -- it sends a reader looking for a file that
# was never written.
# ---------------------------------------------------------------------------


def test_data_model_documents_the_real_epoch_artifact_names():
    text = (REPO_ROOT / "docs" / "data-model.md").read_text()
    for needle in ("policy.json", "policy.sha256", "transitions.jsonl",
                   "recommendation.json", "confirmation.json", "shortlist.json",
                   "report.json", "epoch_end-", "fit_exclusions.json",
                   "mechanism.patch", "mechanism.sha256",
                   "pre_build_tests.json", "baseline_equivalence.json"):
        assert needle in text, needle


def test_docs_reference_the_target_adapter_contract():
    """`docs/targets.md` is reachable from the guide and from CLAUDE.md.

    It shipped in Task 15 with zero inbound links, which makes an adapter
    contract that a target author must satisfy findable only by knowing it
    exists.
    """
    for path in ("docs/optimization-campaign-guide.md", "CLAUDE.md"):
        text = (REPO_ROOT / path).read_text()
        assert "docs/targets.md" in text or "targets.md" in text, (
            f"{path} does not link docs/targets.md"
        )
