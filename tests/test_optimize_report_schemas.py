"""Schema governance for the compiled epoch's decision artifacts.

``policy.json`` is the pre-registration and was schema-governed from the start.
The artifacts that carry the epoch's ANSWER — ``report.json``,
``recommendation.json``, ``confirmation.json`` and its ``shortlist.json``
pointer — were not, which left design spec §3.5's obligation ("the two regret
bounds must never be collapsed into one number") resting on a single equality
assertion in ``test_optimize_iteration.py``. That test proves the two numbers
came out DIFFERENT on one campaign; it cannot prove a future refactor could not
drop one of the fields entirely, or merge them, and still ship.

The schemas close that structurally: ``residual_regret_model`` and
``residual_regret_terminal`` are independently ``required`` and independently
``["number", "null"]`` in ``report.schema.json``, with no ``oneOf`` making one
imply the other and no combined field to collapse into. Enforcement is wired at
``stage_runner._write_json``, the one function every artifact write goes through,
so a report that violates the separation cannot reach disk at all.

Every test here drives a REAL campaign (the synthetic oracle, or ``run_stage``
against a fake config runner) and validates what actually landed on disk. A
schema validated only against a hand-built dict proves the dict, not the code.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.stage_runner import (
    GOVERNED_ARTIFACTS,
    SCHEMA_DIR,
    OptimizationAborted,
    _write_json,
)
from orchestrator.optimize.synthetic import SURFACES


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


# ─── the schemas describe REALITY, not an idealized shape ─────────────────


def test_every_synthetic_surfaces_artifacts_validate_against_their_schemas(tmp_path):
    """Drive the WHOLE oracle and validate every governed artifact each run left.

    All nine surfaces rather than a sample, because they take different paths
    through the compiled epoch and the artifacts differ in which optional keys
    are present: ``choice_x_numeric`` reaches terminal discrimination straight
    from ``screen``, others go through ``refine``, ``sla`` exercises the
    constrained case where finalists are excluded on measurement, and
    ``nan_at_corner`` / ``bowl_out_of_hull`` end on a semantic exception (so
    their reports carry ``epoch_ended`` and no terminal record at all).

    Coverage is accumulated ACROSS surfaces and asserted once: which artifacts a
    single campaign writes depends on the path it took, so a per-surface
    completeness assertion would be a claim about that path rather than about the
    schemas.
    """
    validated: set[str] = set()
    for i, name in enumerate(sorted(SURFACES)):
        res = run_synthetic_campaign(
            SURFACES[name](), seed=71 + i, parent_dir=tmp_path / name,
        )
        wd = res.work_dir
        jsonschema.validate(
            json.loads((wd / "report.json").read_text()),
            _schema("report.schema.json"),
        )
        validated.add("report.json")
        for artifact, schema_name in GOVERNED_ARTIFACTS.items():
            for path in sorted(wd.glob(f"runs/iter-*/{artifact}")):
                jsonschema.validate(
                    json.loads(path.read_text()), _schema(schema_name),
                )
                validated.add(artifact)

    # The whole governed set was actually exercised, not silently skipped.
    assert validated == set(GOVERNED_ARTIFACTS), validated


def test_both_regret_bounds_survive_a_real_campaign_as_separate_fields(tmp_path):
    """§3.5, at the schema level: two required fields, two distinct numbers.

    ``test_optimize_iteration.test_the_terminal_bound_is_not_the_model_bound_
    under_another_name`` already asserts the two VALUES differ on one campaign.
    This asserts the structural guarantee instead — the schema requires both
    keys, so the report cannot be written with either absent — and then confirms
    the real report satisfies it.
    """
    schema = _schema("report.schema.json")
    assert "residual_regret_model" in schema["required"]
    assert "residual_regret_terminal" in schema["required"]
    # No shape in the schema relates them: no oneOf/anyOf/allOf/dependency that
    # could let one stand in for the other, and no combined field to collapse into.
    assert not {"oneOf", "anyOf", "allOf", "dependentRequired", "dependentSchemas"} & set(schema)
    assert not [k for k in schema["properties"] if "regret" in k and k not in (
        "residual_regret_model", "residual_regret_terminal",
    )]

    res = run_synthetic_campaign(SURFACES["additive"](), seed=72, parent_dir=tmp_path)
    jsonschema.validate(res.report, schema)
    assert res.report["residual_regret_model"] is not None
    assert res.report["residual_regret_terminal"] is not None


# ─── the schema REJECTS a collapsed or truncated certificate ──────────────


def _valid_report() -> dict:
    """A minimal report.json that validates, as the baseline for mutations."""
    return {
        "recommendation": {"levels": {"A": 16}, "basis": "certified", "value": 17.5},
        "residual_regret_model": 1.28,
        "residual_regret_terminal": 0.77,
        "epsilon": 0.35,
        "delta_screen": 0.05,
        "delta_terminal": 0.05,
        "certified": True,
        "finalists": [],
        "known_valid_baseline": None,
        "path": ["screen", "confirm", "report"],
        "epoch": 1,
        "policy_hash": "0" * 64,
        "iteration": 3,
    }


def test_the_baseline_report_used_for_mutations_is_itself_valid():
    """Otherwise every rejection below would pass for the wrong reason."""
    jsonschema.validate(_valid_report(), _schema("report.schema.json"))


@pytest.mark.parametrize("mutate,why", [
    (lambda r: r.pop("residual_regret_terminal"),
     "dropping the terminal bound"),
    (lambda r: r.pop("residual_regret_model"),
     "dropping the model bound"),
    (lambda r: (r.pop("residual_regret_model"), r.pop("residual_regret_terminal"),
                r.update({"residual_regret": 0.77})),
     "collapsing both into one residual_regret"),
    (lambda r: r["recommendation"].update({"basis": "confirmed"}),
     "a basis outside the fallback ladder's six rungs"),
    (lambda r: r.update({"epoch_ended": None}),
     "epoch_ended as null instead of absent"),
    (lambda r: r.update({"delta_terminal": 0.9}),
     "a delta above 0.5, which is not a risk level"),
])
def test_the_report_schema_rejects_a_broken_certificate(mutate, why):
    bad = _valid_report()
    mutate(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema("report.schema.json"))


def test_epoch_ended_is_optional_but_never_null():
    """Its PRESENCE is the signal, so a null would be a third, ambiguous state.

    ``_run_report`` includes the key only when a semantic exception ended the
    epoch. A reader must be able to distinguish "ordinary report" from "written
    on the way out of a failed epoch" by presence alone, which a nullable field
    would destroy.
    """
    ok = _valid_report()
    jsonschema.validate(ok, _schema("report.schema.json"))       # absent: fine
    ok["epoch_ended"] = "screen: {\"nan_response\": true}"
    jsonschema.validate(ok, _schema("report.schema.json"))       # present: fine
    ok["epoch_ended"] = ""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ok, _schema("report.schema.json"))


# ─── basis: "none" — reachable, and schema-valid when reached ─────────────


def test_basis_none_is_reachable_through_a_real_campaign_and_validates(
    tmp_path, monkeypatch,
):
    """The bottom of the fallback ladder (§3.6), which is NOT a rung.

    Reaching it needs every rung above to be genuinely unavailable at once, and
    exactly one real campaign shape does that: a screen in which every row runs
    to COMPLETION but reports a non-numeric objective. That is the policy's
    registered ``nan_response`` semantic exception, so

      * ``certified`` / ``terminal_best`` are out — no terminal state ran;
      * ``model`` is out — ``epoch_ended`` suppresses the one rung that rests on
        the fitted surface, and a NaN response is evidence against that surface;
      * ``measured`` is out — ``_best_observed`` skips NaN values, so no
        completed row names a best measured configuration;
      * ``baseline`` is out — the campaign declared no ``known_valid_baseline``.

    With nothing legal to return, the report says so rather than inventing an
    origin, and it still writes a schema-valid report: "uncertainty weakens the
    claim; it need not prevent a decision" cuts both ways — the decision here is
    the honest absence of one.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from tests.test_optimize_iteration import _all_tests_pass, _campaign

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    c = _campaign()
    assert "known_valid_baseline" not in c["optimization"]
    wd = setup_work_dir("opt-none", repo_path=None, campaign=c)

    def nan_runner(row):
        return {"cfg": {k.lower(): v for k, v in row.levels.items()},
                "m": float("nan")}

    run_stage(c, wd, iteration=2, stage="screen", config_runner=nan_runner,
              test_results=_all_tests_pass(c), auto_approve=True)

    rep = json.loads((Path(wd) / "report.json").read_text())
    assert rep["recommendation"]["basis"] == "none", rep["recommendation"]
    assert rep["recommendation"]["levels"] == {}
    assert "value" not in rep["recommendation"]
    assert rep["epoch_ended"] == 'screen: {"nan_response": true}'
    assert rep["known_valid_baseline"] is None
    # BOTH bounds are null here and that is correct: nothing was fitted and no
    # terminal round ran. Null is not "collapsed" — the two keys are still both
    # present, still separate, still stating their own (unknown) value.
    assert rep["residual_regret_model"] is None
    assert rep["residual_regret_terminal"] is None
    jsonschema.validate(rep, _schema("report.schema.json"))


# ─── the wiring fires during a real run, not only in a unit test ──────────


def test_a_schema_violating_report_cannot_reach_disk_during_a_real_run(
    tmp_path, monkeypatch,
):
    """The check is at the write seam, so the campaign hard-fails instead.

    Patching ``certificate.resolve_epsilon`` to return a string is a stand-in for
    any refactor that changes a governed field's type: the point is that the
    campaign aborts at the WRITE rather than shipping an artifact whose epsilon a
    downstream reader cannot compare a bound against. Asserted on the observable
    outcome — the exception and the ABSENT file — not on whether validate() was
    called.
    """
    monkeypatch.setattr(
        "orchestrator.optimize.certificate.resolve_epsilon",
        lambda *a, **k: "not-a-number",
    )
    res = run_synthetic_campaign(
        SURFACES["choice_x_numeric"](), seed=73, parent_dir=tmp_path,
    )
    # The harness records an OptimizationAborted as the last leg of the path
    # rather than letting it escape, so that is where the campaign-level failure
    # is observable from.
    assert res.path[-1].startswith("aborted:"), res.path
    assert "recommendation.json does not conform to recommendation.schema.json" in (
        res.path[-1]
    ), res.path[-1]
    # Nothing partially written: the offending artifact is absent everywhere.
    assert not list(tmp_path.glob("**/recommendation.json"))
    # ...and the campaign produced no report either, rather than a report built
    # on an artifact that never validated.
    assert not list(tmp_path.glob("**/report.json"))


def test_the_write_seam_validates_every_governed_artifact(tmp_path):
    """Not just report.json — each name in the table binds to its own schema.

    Driven through ``_write_json`` directly with a payload that is nonsense for
    the artifact in question, because arranging four independent real-campaign
    corruptions would test the corruptions rather than the table.
    """
    for name in GOVERNED_ARTIFACTS:
        with pytest.raises(OptimizationAborted, match=f"{name} does not conform"):
            _write_json(tmp_path / name, {"unexpected": "shape"})
        assert not (tmp_path / name).exists()

    # An UNGOVERNED artifact is untouched by the seam — the table is the scope.
    _write_json(tmp_path / "epoch_end-1.json", {"anything": True})
    assert (tmp_path / "epoch_end-1.json").exists()


def test_every_governed_name_has_a_schema_file_that_exists():
    """A typo in the table would silently disable a gate, which is the exact
    class of defect the ``relations.json`` schema calls out for native tests."""
    for name, schema_name in GOVERNED_ARTIFACTS.items():
        path = SCHEMA_DIR / schema_name
        assert path.exists(), f"{name} -> missing {schema_name}"
        jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_the_data_model_inventory_names_each_governed_artifacts_schema():
    """``docs/data-model.md``'s inventory used to say `none` for all four.

    The inventory calls itself "the complete list of what the code writes", so a
    row still claiming a governed artifact is unschema'd would send a reader
    looking for a check that exists — the same drift the schemas themselves are
    here to prevent, one level up.
    """
    doc = (Path(__file__).resolve().parents[1] / "docs" / "data-model.md").read_text()
    for name, schema_name in GOVERNED_ARTIFACTS.items():
        assert f"`{name}` |" in doc, f"{name} missing from the inventory"
        assert f"`schemas/{schema_name}`" in doc, (
            f"the inventory does not name {schema_name} for {name}"
        )
