"""The pre-registration record must validate against its own schema, on disk.

``design_matrix.json`` is the artifact that attests WHAT WAS REGISTERED before
any result was seen. A record that fails its own schema cannot be relied on to
prove that: a reader who cannot validate the document has no mechanical way to
tell a faithful pre-registration from one whose fields drifted, and the whole
point of hashing a policy before the first benchmark run is that the resulting
paper trail is checkable rather than merely asserted.

WHY THIS MODULE EXISTS SEPARATELY FROM ``test_optimize_artifacts.py``. That
module's ``test_write_design_matrix_output_validates`` validates a FRESHLY
BUILT ``matrix.matrix_payload`` -- the design-provenance skeleton and nothing
else. Every stage then ENRICHES that payload before ``write_design_matrix``
sees it: ``confirm`` replaces ``kind`` and adds ``round`` / ``finalists``,
``foldover`` adds ``folded_on`` / ``screen_iteration`` /
``alias_consequential``, and the shared tail adds ``policy_hash`` /
``run_timeout_sec`` / ``max_parallel`` / ``workload_seeds`` / ``paired`` /
``held_fixed``. Validating the skeleton therefore proved nothing about the
document that actually lands on disk, which is why the drift survived: a
confirm-round matrix had never once been validated against the schema it
claims to satisfy. Tests here read the REAL on-disk artifact a real campaign
wrote, and the guard test below closes the class rather than the instance.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "orchestrator" / "schemas" / "design_matrix.schema.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _matrices(work_dir: Path) -> list[tuple[Path, dict]]:
    """Every design_matrix.json a campaign wrote, in iteration order."""
    out: list[tuple[Path, dict]] = []
    runs = Path(work_dir) / "runs"
    for it in sorted(runs.glob("iter-*"), key=lambda p: int(p.name.split("-")[1])):
        p = it / "design_matrix.json"
        if p.exists():
            out.append((p, json.loads(p.read_text())))
    return out


# A resolution-IV screen is what routes a campaign through `foldover`: the
# aliased two-factor interactions are what the registered foldover branch
# exists to resolve, so this is the override that makes the foldover matrix
# reachable at all. Mirrors `_RES4_OVERRIDES` in test_optimize_foldover.py.
_RES4 = {
    "design": {
        "screen": {"kind": "fractional", "resolution": 4},
        "refine": {"kind": "central_composite", "center_points": 3},
    },
}


@pytest.fixture(scope="module")
def _confirm_campaign(tmp_path_factory):
    """A campaign driven far enough to write a confirm-round matrix.

    ``bowl`` at this seed routes ``screen -> refine -> confirm -> report``, so
    one campaign supplies three of the four stages that write a matrix: a
    fractional/full screen, a central-composite refine, and the
    ``shortlist_replicate`` confirm round this module exists for.
    """
    res = run_synthetic_campaign(
        SURFACES["bowl"](), seed=16,
        parent_dir=tmp_path_factory.mktemp("confirm"),
    )
    assert res.path == ["screen", "refine", "confirm", "report"], res.path
    return res


@pytest.fixture(scope="module")
def _foldover_campaign(tmp_path_factory):
    """A campaign whose registered foldover branch fired."""
    return run_synthetic_campaign(
        SURFACES["interaction_only"](), seed=21,
        parent_dir=tmp_path_factory.mktemp("foldover"),
        campaign_overrides=dict(_RES4),
    )


# ─── 1. the confirm round's matrix validates ON DISK ───────────────────────


def test_confirm_round_design_matrix_validates_on_disk(_confirm_campaign):
    """The defect this module was written for.

    A `shortlist_replicate` matrix carries `round` and `finalists`, and its
    rows carry `role: "confirm"` and an `apply.finalist` index. None of the
    four was declared, so this artifact -- the pre-registration of terminal
    discrimination -- had never validated.
    """
    res = _confirm_campaign
    assert "confirm" in res.path, res.path

    confirm_matrices = [
        (p, m) for p, m in _matrices(res.work_dir)
        if m.get("kind") == "shortlist_replicate"
    ]
    assert confirm_matrices, "no confirm-round design_matrix.json was written"

    for path, matrix in confirm_matrices:
        jsonschema.validate(matrix, _schema())
        # The fields whose absence from the schema was the defect: present in
        # the artifact, and now describable by it.
        assert matrix["round"] >= 1
        assert matrix["finalists"], path
        assert all(r["role"] == "confirm" for r in matrix["rows"])
        assert all("finalist" in r["apply"] for r in matrix["rows"])


# ─── 2. the screen matrix validates ON DISK ────────────────────────────────


def test_screen_design_matrix_validates_on_disk(_confirm_campaign):
    """The shared enrichment tail (policy_hash / run_timeout_sec /
    max_parallel) rides on every stage's matrix, screen included."""
    res = _confirm_campaign
    screen = [
        (p, m) for p, m in _matrices(res.work_dir)
        if m.get("kind") in {"full", "fractional"}
    ]
    assert screen, "no screen design_matrix.json was written"
    for _path, matrix in screen:
        jsonschema.validate(matrix, _schema())
        assert matrix["policy_hash"]
        assert matrix["max_parallel"] >= 1


# ─── 3. foldover and refine matrices validate ON DISK ──────────────────────


def test_foldover_design_matrix_validates_on_disk(_foldover_campaign):
    """`foldover` adds three provenance fields the combined fit rests on:
    which column was negated, which iteration supplies the other half of the
    response vector, and which alias pairs were consequential."""
    res = _foldover_campaign
    assert "foldover" in res.path, res.path

    # Identified by the fields only a fold block carries, not by indexing into
    # `res.path`: that list comes from `transitions.jsonl` and includes the
    # terminal `report`, so its positions are transitions rather than
    # iterations and `path[i]` is not iteration i+1's stage.
    fold = [
        (p, m) for p, m in _matrices(res.work_dir) if "screen_iteration" in m
    ]
    assert fold, "no foldover design_matrix.json was written"

    for path, matrix in fold:
        jsonschema.validate(matrix, _schema())
        # `folded_on` is null for a FULL foldover (every column negated, which
        # is what a resolution-III screen needs) and a factor id for the
        # one-column fold a resolution-IV screen needs, so presence of the key
        # is the assertion -- a null here is a fact, not a missing value.
        assert "folded_on" in matrix
        assert matrix["screen_iteration"] >= 1
        assert matrix["alias_consequential"], path


def test_refine_design_matrix_validates_on_disk(_confirm_campaign):
    """A central-composite refine matrix carries axial rows and `held_fixed`
    for factors the refine design does not span."""
    res = _confirm_campaign
    refine = [
        (p, m) for p, m in _matrices(res.work_dir)
        if m.get("kind") == "central_composite"
    ]
    if not refine:
        pytest.skip("this campaign did not route through refine")
    for _path, matrix in refine:
        jsonschema.validate(matrix, _schema())


# ─── 4. THE GUARD: no undeclared key may ever appear again ─────────────────


def _declared_top_level(schema: dict) -> set[str]:
    return set(schema.get("properties", {}))


def _declared_row(schema: dict) -> set[str]:
    return set(schema["$defs"]["row"]["properties"])


def _declared_apply(schema: dict) -> set[str]:
    return set(schema["$defs"]["row"]["properties"]["apply"]["properties"])


@pytest.mark.parametrize("fixture_name", ["_confirm_campaign", "_foldover_campaign"])
def test_no_design_matrix_key_is_undeclared(fixture_name, request):
    """The mechanism that stops this drift class from recurring.

    Schema validation alone catches an undeclared key only because
    ``additionalProperties: false`` is set -- but it catches it only on the
    payloads a test happens to build, and the enriched ones went untested for
    exactly that reason. This asserts the SUBSET RELATION directly, over every
    matrix on disk and at all three nesting levels (top level, row, row.apply),
    so a field added to ``stage_runner``'s payload without a matching schema
    declaration fails loudly here even if no other test exercises that stage.

    Stated as a subset rather than an equality on purpose: the schema may
    legitimately declare a field no stage in THIS campaign writes (``paired``
    only appears under common random numbers, ``held_fixed`` only when a
    factor is left out of the design), so requiring equality would fail on a
    correct schema. The direction that matters is the one that catches drift:
    every key that is WRITTEN must be DECLARED.
    """
    res = request.getfixturevalue(fixture_name)
    schema = _schema()
    matrices = _matrices(res.work_dir)
    assert matrices, "campaign wrote no design_matrix.json at all"

    for path, matrix in matrices:
        undeclared = set(matrix) - _declared_top_level(schema)
        assert not undeclared, (
            f"{path} carries top-level key(s) {sorted(undeclared)} that "
            f"design_matrix.schema.json does not declare"
        )
        for row in matrix["rows"]:
            undeclared_row = set(row) - _declared_row(schema)
            assert not undeclared_row, (
                f"{path} row {row.get('row_index')} carries undeclared "
                f"key(s) {sorted(undeclared_row)}"
            )
            undeclared_apply = set(row.get("apply") or {}) - _declared_apply(schema)
            assert not undeclared_apply, (
                f"{path} row {row.get('row_index')}'s apply carries "
                f"undeclared key(s) {sorted(undeclared_apply)}"
            )
