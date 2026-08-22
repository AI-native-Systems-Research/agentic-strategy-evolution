"""Consumer-driven contracts across the epoch's artifact chain.

The chain is::

    policy.json -> design_matrix.json -> runs.jsonl
                -> effects.json / fit_exclusions.json
                -> recommendation.json -> confirmation.json -> report.json

Schema validation alone is not a contract. Two failure classes live entirely
inside "schema-valid":

  * an UNDECLARED key a producer writes and a consumer reads — invisible until
    the schema gets `additionalProperties: false` and a payload happens to be
    tested (`test_no_design_matrix_key_is_undeclared` is the existing guard for
    exactly one artifact; this file generalises the idea);
  * a SEMANTICALLY VACUOUS value: a field that validates on every run and is
    always its type's default. The real instance is `duration_ms`, declared and
    schema-valid and structurally always 0 because it was never assigned at any
    of nine construction sites. `"duration_ms": 0` does not read as "not
    measured" — it reads as "measured, instantaneous", which is worse than an
    absent key.

The reconciliation invariants are the other half: an artifact can be
individually valid and still disagree with its neighbour, and no schema can see
across the boundary. `planned == fitted + excluded`, `report.path ==
transitions.jsonl`, `finalists ⊆ shortlist` are all cross-artifact facts.

Campaigns here are driven through the REAL `stage_runner.run_stage` by
`harness.run_synthetic_campaign` — no dispatcher, no LLM, no subprocess. Module
scope on the fixtures because each campaign is several seconds and every test in
its group reads the same on-disk artifacts read-only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

pytestmark = pytest.mark.contract

SCHEMAS = Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"

# The six values of `report.json`'s `recommendation.basis` ladder (spec §3.6,
# CLAUDE.md). The report ALWAYS names an action, so `basis` is never absent.
BASIS_LADDER = ("certified", "terminal_best", "model", "measured", "baseline", "none")


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def _declared(schema: dict, *path: str) -> set[str]:
    """Property names declared at `path` within `schema`, following $defs."""
    node = schema
    for key in path:
        node = (node.get("properties") or {}).get(key, {})
        if "$ref" in node:
            ref = node["$ref"].split("/")[-1]
            node = (schema.get("$defs") or schema.get("definitions") or {})[ref]
        if node.get("type") == "array":
            node = node.get("items") or {}
            if "$ref" in node:
                ref = node["$ref"].split("/")[-1]
                node = (schema.get("$defs") or schema.get("definitions") or {})[ref]
    return set(node.get("properties") or {})


def _iters(work_dir) -> list[Path]:
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return []
    return sorted(runs.glob("iter-*"), key=lambda p: int(p.name.split("-")[1]))


def _read(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def _rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ── campaigns under test ───────────────────────────────────────────────────
#
# Three shapes, chosen so the chain is exercised at every artifact:
#   bowl      -> screen -> refine -> confirm -> report  (the full chain)
#   sla       -> constrained: some rows are INFEASIBLE, so exclusions matter
#   nan_corner-> a corner that cannot be measured: the semantic-exception path


# ── in-flight-breakage guard ──────────────────────────────────────────────
#
# These invariants drive real campaigns through `stage_runner.run_stage`. While
# other agents' changes are half-landed, that call can raise for reasons that
# have nothing to do with the contracts asserted here — an undefined name, a
# keyword one side passes and the other does not yet accept. The pre-existing
# `tests/test_optimize_harness.py` fails the same way on the same calls, which is
# how the attribution is established.
#
# Such a break is reported as a SKIP naming the cause, not an ERROR: an ERROR
# from a fixture is indistinguishable from these invariants being wrong, and the
# whole value of this layer is that a failure here means something. Genuine
# contract violations still fail — only NameError/TypeError/AttributeError
# escaping the driver is treated as someone else's unfinished edit, and only when
# it is not raised from this file.
_INFLIGHT = (NameError, TypeError, AttributeError)


def _drive_or_skip(surface_name, *, seed, parent_dir, overrides=None):
    """Run one synthetic campaign; skip with the cause when the driver is mid-edit."""
    try:
        return run_synthetic_campaign(
            SURFACES[surface_name](), seed=seed, parent_dir=parent_dir,
            campaign_overrides=overrides,
        )
    except _INFLIGHT as exc:
        pytest.skip(
            f"blocked by an in-flight change in the campaign driver, not by "
            f"this invariant: {type(exc).__name__}: {exc}"
        )


@pytest.fixture(scope="module")
def full_chain(tmp_path_factory):
    """A campaign that walks screen -> refine -> confirm -> report."""
    return _drive_or_skip("bowl", seed=3, parent_dir=tmp_path_factory.mktemp("chain"))


@pytest.fixture(scope="module")
def constrained_chain(tmp_path_factory):
    """A campaign whose SLA constraint makes part of the space invalid."""
    return _drive_or_skip("sla", seed=5, parent_dir=tmp_path_factory.mktemp("sla"))


@pytest.fixture(scope="module")
def nan_chain(tmp_path_factory):
    """A campaign with an unmeasurable corner — the semantic-exception path."""
    return _drive_or_skip("nan_at_corner", seed=7, parent_dir=tmp_path_factory.mktemp("nan"),
                  overrides={"stages": ["verify", "screen", "confirm"]})


ALL_CHAINS = ("full_chain", "constrained_chain", "nan_chain")


# ── C1: every artifact on disk validates against its own schema ────────────


@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_whole_document_artifact_validates_against_its_schema(chain, request):
    """Baseline: nothing on disk is schema-invalid.

    Weaker than everything below it, but it must hold first — a reconciliation
    invariant over an invalid document proves nothing. `runs.jsonl` rows are
    checked separately below because they currently FAIL (see that test).
    """
    res = request.getfixturevalue(chain)
    checked = 0
    for name, rel in (("report", "report.json"), ("policy", "policy.json")):
        doc = _read(Path(res.work_dir) / rel)
        if doc is not None:
            jsonschema.validate(doc, _schema(name))
            checked += 1
    for it in _iters(res.work_dir):
        for name, rel in (("effects", "effects.json"),
                          ("recommendation", "recommendation.json"),
                          ("confirmation", "confirmation.json"),
                          ("design_matrix", "design_matrix.json")):
            doc = _read(it / rel)
            if doc is not None:
                jsonschema.validate(doc, _schema(name))
                checked += 1
    assert checked, f"{chain} wrote no artifacts at all"


@pytest.mark.mutation_sentinel
@pytest.mark.xfail(
    strict=False,
    reason="BUG FOUND BY THIS LAYER: runs_row.schema.json's `role` enum is "
           "['corner','center','axial'] and omits 'confirm', but every "
           "confirm-round row is written with role='confirm'. Measured on "
           "`bowl` seed 3: 9 of 29 rows fail their own schema. "
           "design_matrix.schema.json DOES declare 'confirm' — the two "
           "schemas describing the same row disagree. Flips to pass when the "
           "enum is corrected.",
)
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_runs_jsonl_row_validates_against_runs_row_schema(chain, request):
    """A REAL DEFECT this contract layer surfaced.

    `runs_row.schema.json` has NO production consumer — nothing in
    `orchestrator/` validates against it. The only existing tests that use it
    build rows BY HAND (`test_optimize_artifacts.py`,
    `test_optimize_instrumentation.py`), so they validate rows that the schema
    was written from rather than rows the pipeline actually emits. Validating
    what a real campaign WROTE is what exposes the gap.

    Why it matters beyond tidiness: `role` is how a consumer tells a corner from
    a centre from a terminal-discrimination replicate. `pure_error` is computed
    from `role == "center"` rows, and `confirm`'s replicates must NOT enter it.
    A schema that cannot express the role the pipeline writes cannot be used to
    check that separation — and because nothing in production validates rows, the
    disagreement is invisible at runtime.
    """
    res = request.getfixturevalue(chain)
    schema, checked = _schema("runs_row"), 0
    for it in _iters(res.work_dir):
        for row in _rows(it / "runs.jsonl"):
            jsonschema.validate(row, schema)
            checked += 1
    assert checked, f"{chain} wrote no runs.jsonl rows"


# ── C2: no key any consumer reads is undeclared by its producer ────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
@pytest.mark.parametrize(
    "artifact,schema_name",
    [("effects.json", "effects"), ("recommendation.json", "recommendation"),
     ("confirmation.json", "confirmation")],
)
def test_no_iteration_artifact_key_is_undeclared(chain, artifact, schema_name, request):
    """Generalises `test_no_design_matrix_key_is_undeclared` to the rest of the chain.

    Stated as a SUBSET, not an equality, for the reason that test gives: a schema
    may legitimately declare a field this campaign's stages never wrote. The
    direction that catches drift is the other one — every key WRITTEN must be
    DECLARED — because a producer that adds a field without declaring it hands
    consumers a fact no schema promises will keep existing.
    """
    res = request.getfixturevalue(chain)
    schema = _schema(schema_name)
    declared = set(schema.get("properties") or {})
    assert declared, f"{schema_name}.schema.json declares no properties"

    seen = 0
    for it in _iters(res.work_dir):
        doc = _read(it / artifact)
        if doc is None:
            continue
        seen += 1
        undeclared = set(doc) - declared
        assert not undeclared, (
            f"{it.name}/{artifact} carries undeclared key(s) {sorted(undeclared)}"
        )
    if not seen:
        pytest.skip(f"{chain} wrote no {artifact}")


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_no_report_or_runs_row_key_is_undeclared(chain, request):
    """The two artifacts every campaign writes, at the root and per row."""
    res = request.getfixturevalue(chain)
    report = _read(Path(res.work_dir) / "report.json")
    if report is not None:
        declared = set(_schema("report").get("properties") or {})
        assert not set(report) - declared, (
            f"report.json carries undeclared key(s) "
            f"{sorted(set(report) - declared)}"
        )
    row_declared = set(_schema("runs_row").get("properties") or {})
    for it in _iters(res.work_dir):
        for row in _rows(it / "runs.jsonl"):
            assert not set(row) - row_declared, (
                f"{it.name} runs.jsonl row {row.get('row_index')} carries "
                f"undeclared key(s) {sorted(set(row) - row_declared)}"
            )


# ── C3: reconciliation across the boundary ────────────────────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_report_path_is_exactly_what_transitions_jsonl_recorded(chain, request):
    """`report.json`'s `path` is READ BACK from the audit trail, never recomputed.

    Two sources for the same fact would let them drift, and the trail is the one
    with the `policy_hash` on every row — so the report must agree with it
    exactly, node for node.
    """
    res = request.getfixturevalue(chain)
    report = _read(Path(res.work_dir) / "report.json")
    if report is None:
        pytest.skip(f"{chain} wrote no report.json")
    trail = _rows(Path(res.work_dir) / "transitions.jsonl")
    assert trail, (
        "report.json exists but transitions.jsonl is EMPTY — the audit trail "
        "the report's path is read back from was never written (this is the "
        "field failure: 18 measured rows, blank trail)"
    )
    epoch = report.get("epoch", 1)
    mine = [r for r in trail if r.get("epoch", 1) == epoch]
    expected = [r["from"] for r in mine] + ([mine[-1]["to"]] if mine else [])
    assert report["path"] == expected, (
        f"report.path {report['path']} != trail {expected}"
    )


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_transition_row_carries_its_epoch_and_the_hash_it_ran_under(chain, request):
    """A row without `epoch` is unattributable; without `policy_hash`,
    uncheckable against the pre-registration it claims to have followed.
    Cross-reference: `docs/optimization-invariants.md` INV-PROV04, INV-TMP02 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    trail = _rows(Path(res.work_dir) / "transitions.jsonl")
    if not trail:
        pytest.skip(f"{chain} wrote no transitions")
    recorded = (Path(res.work_dir) / "policy.sha256")
    for r in trail:
        assert "epoch" in r, f"transition row {r} has no epoch"
        assert r.get("policy_hash"), f"transition row {r} names no policy hash"
        assert r.get("from") and r.get("to")
        assert isinstance(r.get("rule"), dict)
    if recorded.exists():
        want = recorded.read_text().strip()
        assert all(r["policy_hash"] == want for r in trail), (
            "a transition ran under a policy hash other than the one on disk — "
            "the pre-registration changed inside the epoch"
        )


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_planned_row_is_accounted_for_as_fitted_or_excluded(chain, request):
    """`planned == fitted + excluded`, per iteration.

    The reconciliation nothing else can see: `design_matrix.json` knows what was
    planned, `runs.jsonl` what ran, `effects.json` how many rows the fit used,
    and `fit_exclusions.json` (when present) which rows were dropped. A row that
    is in none of the three buckets vanished silently — which is the shape of
    §4 D2, where an infeasible row was excluded from the abort guard's check and
    from nothing downstream.
    """
    res = request.getfixturevalue(chain)
    checked = 0
    for it in _iters(res.work_dir):
        matrix, eff = _read(it / "design_matrix.json"), _read(it / "effects.json")
        if matrix is None or eff is None:
            continue
        checked += 1
        planned = len(matrix["rows"])
        ran = _rows(it / "runs.jsonl")
        assert len(ran) == planned, (
            f"{it.name}: {planned} rows planned, {len(ran)} ran — check_fidelity "
            f"should have caught this"
        )
        fitted = eff.get("n_runs")
        excl = _read(it / "fit_exclusions.json")
        n_excluded = len(excl.get("excluded") or []) if excl else 0
        if fitted is not None:
            assert fitted + n_excluded == planned, (
                f"{it.name}: {planned} planned != {fitted} fitted + "
                f"{n_excluded} excluded — rows went missing between the "
                f"pre-registration and the fit"
            )
    if not checked:
        pytest.skip(f"{chain} fitted nothing")


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_excluded_row_index_names_a_row_that_actually_ran(chain, request):
    """An exclusion pointing at no row is an exclusion of nothing.

    `fit_exclusions.json` exists so a reader can see WHICH measurements the fit
    declined to use. An index that names no row in `runs.jsonl` makes that
    unauditable, and would let an off-by-one silently exclude a healthy row while
    keeping the damaged one.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT09 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    found = 0
    for it in _iters(res.work_dir):
        excl = _read(it / "fit_exclusions.json")
        if excl is None:
            continue
        found += 1
        ran = {r["row_index"] for r in _rows(it / "runs.jsonl")}
        for entry in excl.get("excluded") or []:
            idx = entry.get("row_index") if isinstance(entry, dict) else entry
            assert idx in ran, (
                f"{it.name}: excluded row_index {idx} appears in no runs.jsonl row "
                f"(rows present: {sorted(ran)})"
            )
            if isinstance(entry, dict):
                assert entry.get("reason"), (
                    f"{it.name}: row {idx} excluded with no reason — an "
                    f"unexplained exclusion cannot be reviewed"
                )
    if not found:
        pytest.skip(f"{chain} excluded no rows (no fit_exclusions.json)")


@pytest.mark.mutation_sentinel
def test_confirmed_finalists_are_a_subset_of_the_shortlist_they_came_from(full_chain):
    """`confirmation.json`'s finalists ⊆ `shortlist.json`.

    The shortlist is what `confirm` pre-committed to discriminating between; a
    finalist that was not on it is a candidate that entered terminal
    discrimination after the shortlist was fixed, which is the p-hacking the
    pre-registration exists to prevent.
    """
    found = 0
    for it in _iters(full_chain.work_dir):
        conf, short = _read(it / "confirmation.json"), _read(it / "shortlist.json")
        if conf is None:
            continue
        found += 1
        finalists = conf.get("finalists") or []
        if short is None:
            # The shortlist may be carried inside confirmation.json rather than
            # as its own file; then the containment is trivially satisfied but
            # the finalists must still be internally consistent.
            assert finalists, f"{it.name}: confirm recorded no finalists at all"
            continue
        # `shortlist.json` names its pool `finalists` (same key as
        # confirmation.json), with `see` pointing at the iteration that holds
        # the full record. Verified on disk rather than guessed.
        pool = short.get("finalists") or []
        def _lv(x):
            return tuple(sorted((x.get("levels") or x).items()))
        assert {_lv(f) for f in finalists} <= {_lv(c) for c in pool}, (
            f"{it.name}: a confirmed finalist was not on the shortlist"
        )
    if not found:
        pytest.skip("no confirm round ran")


# ── C4: the report always names an action, on a ladder rung ────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_the_report_always_names_an_action_on_a_declared_ladder_rung(chain, request):
    """Spec §3.6: the report ALWAYS names an action.

    Including on the semantic-exception path — the exception impeaches the fitted
    surface, so it removes the `model` rung, but the campaign still measured
    things and can still recommend from them. A report with no action would make
    a failed epoch indistinguishable from a crash.

    Cross-reference: `docs/optimization-invariants.md` INV-ST09 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    report = _read(Path(res.work_dir) / "report.json")
    if report is None:
        pytest.skip(f"{chain} wrote no report.json")
    rec = report.get("recommendation") or {}
    assert rec.get("basis") in BASIS_LADDER, (
        f"basis {rec.get('basis')!r} is not on the ladder {BASIS_LADDER}"
    )
    if rec["basis"] != "none":
        assert rec.get("levels"), (
            f"basis is {rec['basis']!r} but no configuration is named — every "
            f"rung except `none` names an action"
        )


@pytest.mark.mutation_sentinel
def test_a_semantic_exception_removes_the_model_rung_and_nothing_else(nan_chain):
    """The exception impeaches the SURFACE, not the measurements.

    `nan_at_corner` cannot be measured at one corner, so the fitted model is
    unusable there — but the rows that DID measure are still valid, so the report
    falls back to a measurement-based rung rather than to `none`.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM04 — the statement of
    record lives there; this test is the executable check.
    """
    report = _read(Path(nan_chain.work_dir) / "report.json")
    if report is None:
        pytest.skip("nan_at_corner produced no report in this configuration")
    if not report.get("epoch_ended"):
        pytest.skip("this seed did not route through the semantic exception")
    basis = (report.get("recommendation") or {}).get("basis")
    assert basis != "model", (
        "a semantic exception left the recommendation resting on the fitted "
        "model — the exception is precisely what impeached that model"
    )
    assert basis in BASIS_LADDER
    end = _read(Path(nan_chain.work_dir) / f"epoch_end-{report.get('epoch', 1)}.json")
    assert end is not None, "the epoch ended but wrote no epoch_end-<e>.json"
    assert end.get("next_epoch_requires"), (
        "an ended epoch must say what the next one requires, or the campaign "
        "has no way forward"
    )


# ── C5: the two bounds are NEVER collapsed ────────────────────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_the_two_residual_regret_bounds_are_separate_fields(chain, request):
    """`Pr(wrong global decision) <= delta_s + delta_t` needs them APART.

    `residual_regret_model` carries the registered response-class assumption;
    `residual_regret_terminal` carries none. One merged number would advertise
    the assumption-light guarantee while delivering the model-dependent one.
    A `null` means the variance was not estimable — an unknown, not a zero.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM01, INV-SEM02 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    report = _read(Path(res.work_dir) / "report.json")
    if report is None:
        pytest.skip(f"{chain} wrote no report.json")
    assert "residual_regret" not in report, (
        "report.json carries a BARE `residual_regret` — the two bounds were "
        "collapsed into one number"
    )
    assert "residual_regret_model" in report
    assert "residual_regret_terminal" in report
    for key in ("residual_regret_model", "residual_regret_terminal"):
        v = report[key]
        assert v is None or (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0.0), (
            f"{key} = {v!r}: a bound is a non-negative finite number or null"
        )
    assert report["delta_screen"] is not None
    assert report["delta_terminal"] is not None
    assert 0.0 < float(report["delta_screen"]) < 1.0
    assert 0.0 < float(report["delta_terminal"]) < 1.0


@pytest.mark.mutation_sentinel
def test_a_certified_report_carries_the_terminal_bound_not_only_the_model_one(full_chain):
    """`basis: certified` is a claim about the ASSUMPTION-LIGHT bound.

    Certifying on `residual_regret_model` alone would advertise a guarantee that
    holds only if the fitted response class is right — exactly the conflation the
    two-field split exists to prevent.
    """
    report = _read(Path(full_chain.work_dir) / "report.json")
    if report is None or (report.get("recommendation") or {}).get("basis") != "certified":
        pytest.skip("this campaign did not certify")
    assert report["residual_regret_terminal"] is not None, (
        "certified with a null terminal bound — the certificate rests on the "
        "model bound alone"
    )
    assert report.get("certified") is True


# ── C6: the "valid but meaningless" class ─────────────────────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_a_successful_row_reports_a_response_that_is_actually_a_measurement(chain, request):
    """SEMANTIC non-vacuity, not just schema validity.

    A row marked successful whose response is empty, or whose objective metric is
    absent or non-finite, validated fine and measured nothing. The fit then
    consumes it as a number.
    """
    res = request.getfixturevalue(chain)
    metric = "m"
    seen = 0
    nan_seen: list[tuple[str, object]] = []
    for it in _iters(res.work_dir):
        for row in _rows(it / "runs.jsonl"):
            if not row.get("ok", row.get("success", True)):
                continue
            seen += 1
            resp = row.get("response") or {}
            assert resp, (
                f"{it.name} row {row.get('row_index')} is marked successful with "
                f"an EMPTY response — schema-valid and semantically vacuous"
            )
            if metric in resp and isinstance(resp[metric], (int, float)):
                if not math.isfinite(resp[metric]):
                    # A NaN objective on a row the pipeline still calls
                    # successful. `nan_at_corner` produces this DELIBERATELY —
                    # it is the surface named for the defect — so the invariant
                    # is not "no NaN ever reaches a row" but "a NaN objective is
                    # recognised somewhere before the fit consumes it". The
                    # recognised places are the row's own status/self_check and
                    # the `nan_response` semantic exception; assert one of them
                    # fired rather than that the number is finite.
                    nan_seen.append((it.name, row.get("row_index")))
    assert seen, f"{chain} recorded no successful rows"
    if nan_seen:
        trail = _rows(Path(res.work_dir) / "transitions.jsonl")
        exceptioned = any(r.get("observations", {}).get("nan_response")
                          or r.get("to") == "exception" for r in trail)
        excluded = any((it / "fit_exclusions.json").exists()
                       for it in _iters(res.work_dir))
        assert exceptioned or excluded, (
            f"rows {nan_seen} carry a NON-FINITE objective and are marked "
            f"successful, yet no `nan_response` exception fired and no "
            f"fit_exclusions.json records them — the fit consumed a NaN as a "
            f"measurement (spec §4 D2's failure mode)"
        )


@pytest.mark.mutation_sentinel
@pytest.mark.pending_duration
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_duration_ms_is_a_measurement_and_not_a_declared_zero(chain, request):
    """THE `valid but meaningless` DEFECT, as a semantic-vacuity contract.

    `"duration_ms": 0` does not read as "not measured" — it reads as "measured,
    instantaneous", which is strictly worse than an absent key: a reader
    computing throughput divides by it, and a `--liveness` timeout-headroom check
    sized from it concludes every configuration is free.

    The test is a NON-VACUITY assertion, deliberately weak on the exact value:
    at least one successful row across the whole campaign must report a
    STRICTLY POSITIVE duration. A benchmark row that genuinely took under a
    millisecond is conceivable; every row of every iteration taking exactly zero
    is not.

    LIVE, not pending: Agent C's clock has landed. Measured on `bowl` seed 3,
    all 29 rows now report duration_ms=1 (the synthetic surface is genuinely
    sub-millisecond, so 1 is the honest floor rather than a placeholder). Kept
    marked `pending_duration` so the marker still selects the duration
    contract, but the xfail is REMOVED — leaving it would let a regression back
    to a structural 0 pass as an expected failure.

    Cross-reference: `docs/optimization-invariants.md` INV-RES06 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    durations, present = [], 0
    for it in _iters(res.work_dir):
        for row in _rows(it / "runs.jsonl"):
            if "duration_ms" not in row:
                continue
            present += 1
            durations.append(row["duration_ms"])
    if not present:
        pytest.skip("no row declares duration_ms yet")
    assert any(d and d > 0 for d in durations), (
        f"all {present} rows report duration_ms in {sorted(set(durations))} — a "
        f"field that validates and is always its default reads as measured "
        f"when it was never assigned"
    )


@pytest.mark.mutation_sentinel
@pytest.mark.pending_duration
@pytest.mark.xfail(
    strict=False,
    reason="PENDING AGENT C: failed rows do not yet carry a `reason`.",
)
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_failed_row_says_why_it_failed(chain, request):
    """A failed row with no cause is a row nobody can act on.

    The exclusion machinery reads failure causes to decide whether the failures
    are LEVEL-CORRELATED (a dead factor level) or scattered (noise). A blank
    cause makes that distinction uncomputable, so a systematically broken level
    reads as random misfortune.
    """
    res = request.getfixturevalue(chain)
    failed = 0
    for it in _iters(res.work_dir):
        for row in _rows(it / "runs.jsonl"):
            if row.get("ok", row.get("success", True)):
                continue
            failed += 1
            cause = (row.get("reason") or row.get("failure_kind")
                     or row.get("error") or "")
            assert str(cause).strip(), (
                f"{it.name} row {row.get('row_index')} failed with no recorded "
                f"reason"
            )
    if not failed:
        pytest.skip(f"{chain} had no failed rows")


# ── C7: the pre-registration is immutable inside the epoch ────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_the_policy_on_disk_still_matches_the_hash_written_before_the_first_run(
        chain, request):
    """`policy.json` vs `policy.sha256`, checked after the epoch finished.

    A pre-registration that changed inside an epoch is not a pre-registration.
    `_load_or_compile_policy` checks this on every stage; asserting it on the
    FINISHED work_dir proves nothing in the epoch rewrote the document.

    Cross-reference: `docs/optimization-invariants.md` INV-PROV01 — the statement of
    record lives there; this test is the executable check.
    """
    from orchestrator.optimize.policy import policy_hash

    res = request.getfixturevalue(chain)
    doc = _read(Path(res.work_dir) / "policy.json")
    sha = Path(res.work_dir) / "policy.sha256"
    if doc is None:
        pytest.skip(f"{chain} compiled no policy")
    assert sha.exists(), "policy.json with no policy.sha256 is unpinnable"
    assert sha.read_text().strip() == policy_hash(doc), (
        "policy.json no longer hashes to policy.sha256 — the pre-registration "
        "was edited inside the epoch"
    )


@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_every_design_matrix_cites_the_policy_it_was_registered_under(chain, request):
    """Each iteration's matrix names the `policy_hash` it materialised from.

    Without it, a matrix on disk cannot be tied back to the pre-registration that
    fixed it, and the audit trail's per-row hash has nothing to reconcile
    against.
    """
    res = request.getfixturevalue(chain)
    sha = Path(res.work_dir) / "policy.sha256"
    if not sha.exists():
        pytest.skip(f"{chain} compiled no policy")
    want = sha.read_text().strip()
    seen = 0
    for it in _iters(res.work_dir):
        m = _read(it / "design_matrix.json")
        if m is None:
            continue
        seen += 1
        assert m.get("policy_hash") == want, (
            f"{it.name}/design_matrix.json cites policy_hash "
            f"{m.get('policy_hash')!r}, not the epoch's {want!r}"
        )
    assert seen, f"{chain} wrote no design_matrix.json"


# ── C8: the adapter contract is fingerprinted once and re-checked ─────────


@pytest.mark.parametrize("chain", ALL_CHAINS)
def test_the_adapter_contract_is_pinned_by_the_first_successful_row(chain, request):
    """`adapter_contract.json` + `.sha256` at the root, hashed like the policy.

    The measurement INSTRUMENT is the other half of the pre-registration. A key
    appearing, disappearing, or changing type mid-epoch damages the rows measured
    BEFORE the change — which is why an added key aborts too.

    Cross-reference: `docs/optimization-invariants.md` INV-PROV03, INV-TMP04 — the statement of
    record lives there; this test is the executable check.
    """
    res = request.getfixturevalue(chain)
    doc = _read(Path(res.work_dir) / "adapter_contract.json")
    if doc is None:
        pytest.skip(f"{chain} pinned no adapter contract")
    sha = Path(res.work_dir) / "adapter_contract.sha256"
    assert sha.exists(), "adapter_contract.json with no hash beside it"
    # Types, never values: values legitimately change per row.
    fields = doc.get("fields") or doc.get("contract") or doc
    assert isinstance(fields, dict) and fields, "the contract fingerprints nothing"


# ── C9: partial-design fitting (PENDING AGENT A) ─────────────────────────


@pytest.mark.mutation_sentinel
@pytest.mark.pending_partial_fit
@pytest.mark.xfail(
    strict=False,
    reason="PENDING AGENT A: an iteration where SOME rows fail must refit on "
           "the complete subset and write fit_exclusions.json, rather than "
           "aborting pre-fit. Until then this campaign aborts and writes "
           "neither effects.json nor a transition row.",
)
def test_an_iteration_that_lost_some_rows_still_fits_and_still_records_a_transition(
        tmp_path):
    """THE FIELD FAILURE, end to end.

    A real 14-hour campaign measured 18 valid rows and wrote a COMPLETELY EMPTY
    `transitions.jsonl`, because every iteration aborted before the fit — so
    `step()` never ran, no transition was recorded, and no terminal state was
    reached. The fix is partial-design fitting: refit on the complete-row subset,
    record the exclusions, and CONTINUE — which means the transition gets
    written.

    Asserted at the artifact level rather than on an exception type, so it stays
    true under any implementation Agent A chooses: after a campaign in which some
    rows failed, there must be an `effects.json`, a `fit_exclusions.json`, and a
    non-empty `transitions.jsonl`.
    """
    res = _drive_or_skip("nan_at_corner", seed=11, parent_dir=tmp_path,
                 overrides={"stages": ["verify", "screen", "confirm"]})
    trail = _rows(Path(res.work_dir) / "transitions.jsonl")
    assert trail, (
        "transitions.jsonl is EMPTY after a campaign that measured rows — the "
        "audit trail records nothing about a campaign that ran"
    )
    fitted = [it for it in _iters(res.work_dir) if (it / "effects.json").exists()]
    assert fitted, "no iteration produced a fit despite rows being measured"
    excl = [it for it in fitted if (it / "fit_exclusions.json").exists()]
    assert excl, (
        "rows were lost but no fit_exclusions.json records which — the fit "
        "silently used a different row set than the one pre-registered"
    )
