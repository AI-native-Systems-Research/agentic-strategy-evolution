"""Campaign-completion robustness: resume, circuit breaker, progress, reaping, budget.

Behavioral throughout: every assertion is about an artifact on disk, a returned
verdict, or an observable process outcome. Nothing asserts that a mock was
called.

The property tests are DERANDOMIZED (``derandomize=True``), so a failure here
reproduces from the test name alone rather than from a recorded example
database.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from orchestrator.optimize import progress, reaper, resume

pytestmark = pytest.mark.robustness

DET = settings(
    derandomize=True, deadline=None, max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture(autouse=True)
def _isolate_reaper_globals():
    """Leave ``reaper``'s module-level state exactly as it was found.

    ``reaper`` keeps two process-wide globals by design — ``_TRACKED`` (live
    child handles, so a terminating campaign can reap trees it would otherwise
    orphan) and ``_ATEXIT_REGISTERED`` (so the backstop is registered once).
    Both are correct for a campaign process and both are cross-test state in a
    test process: a tracked handle surviving a test would let a later test's
    ``reap_all`` signal a process it never spawned, and the ``atexit`` hook
    would run at interpreter shutdown against whatever was left.

    Autouse rather than opt-in because ``run_in_process_group`` registers the
    hook implicitly, so any test that measures a subprocess acquires the state
    without naming it. Nothing here changes what production does — the globals
    are restored, not disabled.
    """
    saved_tracked = set(reaper._TRACKED)
    saved_flag = reaper._ATEXIT_REGISTERED
    try:
        yield
    finally:
        reaper._TRACKED.clear()
        reaper._TRACKED.update(saved_tracked)
        reaper._ATEXIT_REGISTERED = saved_flag


# ───────────────────────────── helpers ──────────────────────────────────────

def _matrix(*, policy_hash="ph1", rows=3, seeds=True, epoch=None,
            contract=None, run_order_seed=1):
    payload = {
        "factor_ids": ["A", "B"],
        "kind": "full",
        "resolution": None,
        "generators": [],
        "aliases": [],
        "run_order": list(range(rows)),
        "run_order_seed": run_order_seed,
        "policy_hash": policy_hash,
        "rows": [
            {
                "row_index": i,
                "levels": {"A": float(i), "B": 1.0},
                "role": "corner",
                "replicate": 0,
                "apply": {"cli_args": [f"--a={i}"], "env": {}, "patches": []},
            }
            for i in range(rows)
        ],
    }
    if seeds:
        payload["workload_seeds"] = {str(i): 1000 + i for i in range(rows)}
        for row in payload["rows"]:
            row["apply"]["env"] = {"NOUS_WORKLOAD_SEED": 1000 + row["row_index"]}
    if epoch is not None:
        payload["epoch"] = epoch
    if contract is not None:
        payload["adapter_contract_hash"] = contract
    return payload


def _run_row(payload, idx, *, status="complete", duration_ms=1000, m=1.0):
    planned = next(r for r in payload["rows"] if r["row_index"] == idx)
    return {
        "row_index": idx,
        "levels": dict(planned["levels"]),
        "role": planned["role"],
        "replicate": planned["replicate"],
        "apply": dict(planned["apply"]),
        "status": status,
        "response": {"m": m},
        "duration_ms": duration_ms,
        "attempts": 1,
        "last_attempt_ms": duration_ms,
        "error": "",
        "failure_kind": "" if status == "complete" else "timeout",
    }


def _seed_iteration(work_dir: Path, n: int, payload: dict, rows: list[dict]):
    d = work_dir / "runs" / f"iter-{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_matrix.json").write_text(json.dumps(payload, indent=2))
    with (d / "runs.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return d


# ═══════════════════════ 1. RESUMABILITY ════════════════════════════════════

def test_a_retry_reuses_the_rows_the_prior_attempt_measured(tmp_path):
    """The headline case: 2 of 3 rows measured, 1 failed -> only the failed one is pending."""
    prior = _matrix()
    _seed_iteration(tmp_path, 4, prior, [
        _run_row(prior, 0), _run_row(prior, 1),
        _run_row(prior, 2, status="failed"),
    ])

    candidate = resume.carry_forward_payload(prior, _matrix(run_order_seed=1))
    assert candidate is not None
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-5",
        payload=candidate, policy_hash="ph1",
    )

    assert plan.reused_count == 2
    assert sorted(r["row_index"] for r in plan.rows) == [0, 1]
    assert plan.pending_indices == [2]
    assert plan.refused == ""


def test_a_reused_row_is_identifiable_as_reused_with_its_source_iteration(tmp_path):
    """Provenance: a reader must never mistake reuse for fresh measurement."""
    prior = _matrix(rows=2)
    _seed_iteration(tmp_path, 3, prior, [_run_row(prior, 0), _run_row(prior, 1)])

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-4",
        payload=resume.carry_forward_payload(prior, _matrix(rows=2)),
        policy_hash="ph1", epoch=1,
    )
    assert plan.reused_count == 2
    for row in plan.rows:
        assert row["reused_from"] == {"iteration": 3, "epoch": 1}


def test_a_failed_row_is_re_run_and_the_other_three_statuses_are_reused(tmp_path):
    """Status taxonomy, verified against runner.py's own documented meanings."""
    prior = _matrix(rows=4)
    _seed_iteration(tmp_path, 1, prior, [
        _run_row(prior, 0, status="complete"),
        _run_row(prior, 1, status="infeasible"),
        _run_row(prior, 2, status="rejected"),
        _run_row(prior, 3, status="failed"),
    ])
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=4)),
        policy_hash="ph1",
    )
    assert sorted(r["row_index"] for r in plan.rows) == [0, 1, 2]
    assert plan.pending_indices == [3]


@pytest.mark.mutation_sentinel
def test_reuse_is_refused_wholesale_across_a_differing_policy_hash(tmp_path):
    """A row scheduled by a different pre-registration is a different experiment."""
    prior = _matrix(policy_hash="OLD")
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, i) for i in range(3)])

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(policy_hash="NEW")),
        policy_hash="NEW",
    )
    assert plan.reused_count == 0
    assert plan.pending_indices == [0, 1, 2]
    assert "pre-registration" in plan.refused


@pytest.mark.mutation_sentinel
def test_reuse_is_refused_across_an_adapter_contract_change(tmp_path):
    """An apparatus change is an epoch boundary, not an edit."""
    from orchestrator.optimize import adapter_contract as ac

    # The epoch's live contract.
    ac.write_contract(tmp_path, ac.capture_contract(
        tmp_path, {"m": 1.0}, epoch=1, row_index=0, stage="screen",
    ))
    live = ac.contract_hash(ac.read_contract(tmp_path))

    prior = _matrix(contract="a-different-instrument-hash")
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, i) for i in range(3)])

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(
            prior, _matrix(contract="a-different-instrument-hash")),
        policy_hash="ph1",
    )
    assert plan.reused_count == 0
    assert "apparatus change is an epoch boundary" in plan.refused
    assert live  # the live contract really was recorded


@pytest.mark.mutation_sentinel
def test_a_row_whose_workload_seed_differs_is_not_reused(tmp_path):
    """The seed is part of the row's identity: a different draw is a different measurement.

    This is the failure mode that makes naive reuse UNSOUND in this codebase:
    `_assign_workload_seeds` derives the seed from `run_order_seed=iteration`,
    so a retry at iteration i+1 registers different draws. Reuse must notice.
    """
    prior = _matrix(rows=2)
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, 0), _run_row(prior, 1)])

    # A candidate that did NOT carry the prior draws forward: it registers its
    # own, different seeds (what the real code would derive at iteration 2).
    candidate = _matrix(rows=2)
    candidate["workload_seeds"] = {"0": 9999, "1": 8888}
    for row in candidate["rows"]:
        row["apply"]["env"] = {"NOUS_WORKLOAD_SEED": candidate["workload_seeds"][
            str(row["row_index"])]}

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=candidate, policy_hash="ph1",
    )
    assert plan.reused_count == 0, (
        "a row measured under a different workload draw must not be reused"
    )
    assert plan.pending_indices == [0, 1]


def test_carry_forward_refuses_a_design_that_is_not_the_same_registration():
    """Continuing one pre-registration is only meaningful while it IS the same design."""
    prior = _matrix(rows=3)
    assert resume.carry_forward_payload(prior, _matrix(rows=4)) is None

    other_kind = _matrix(rows=3)
    other_kind["kind"] = "central_composite"
    assert resume.carry_forward_payload(prior, other_kind) is None

    other_factors = _matrix(rows=3)
    other_factors["factor_ids"] = ["A", "B", "C"]
    assert resume.carry_forward_payload(prior, other_factors) is None


def test_carry_forward_replaces_the_candidates_seeds_with_the_priors():
    """The mechanism that makes reuse legitimate rather than merely fast."""
    prior = _matrix(rows=2)
    candidate = _matrix(rows=2)
    candidate["workload_seeds"] = {"0": 7, "1": 8}
    for row in candidate["rows"]:
        row["apply"]["env"] = {"NOUS_WORKLOAD_SEED": candidate[
            "workload_seeds"][str(row["row_index"])]}

    out = resume.carry_forward_payload(prior, candidate)
    assert out["workload_seeds"] == prior["workload_seeds"]
    for row in out["rows"]:
        assert row["apply"]["env"]["NOUS_WORKLOAD_SEED"] == prior[
            "workload_seeds"][str(row["row_index"])]


def test_carry_forward_does_not_copy_the_policy_hash():
    """Copying it would forge the agreement plan_reuse is supposed to CHECK."""
    prior = _matrix(policy_hash="OLD")
    candidate = _matrix(policy_hash="NEW")
    out = resume.carry_forward_payload(prior, candidate)
    assert out["policy_hash"] == "NEW"


@pytest.mark.mutation_sentinel
def test_an_applied_config_difference_blocks_reuse_even_when_levels_match(tmp_path):
    """Levels alone are not the configuration: a changed patch/flag/env matters."""
    prior = _matrix(rows=1, seeds=False)
    row = _run_row(prior, 0)
    row["apply"] = {"cli_args": ["--a=SOMETHING-ELSE"], "env": {}, "patches": []}
    _seed_iteration(tmp_path, 1, prior, [row])

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=1, seeds=False)),
        policy_hash="ph1",
    )
    assert plan.reused_count == 0
    assert plan.pending_indices == [0]


def test_reuse_from_an_earlier_epoch_is_refused(tmp_path):
    prior = _matrix(rows=2, epoch=1)
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, 0), _run_row(prior, 1)])
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=2, epoch=1)),
        policy_hash="ph1", epoch=2,
    )
    assert plan.reused_count == 0
    assert "epoch" in plan.refused


def test_the_manifest_records_the_refusal_not_only_the_success(tmp_path):
    """"Everything was re-measured, and here is why" is the fact a reader needs."""
    prior = _matrix(policy_hash="OLD")
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, i) for i in range(3)])
    iter_dir = tmp_path / "runs" / "iter-2"
    iter_dir.mkdir(parents=True, exist_ok=True)

    plan = resume.plan_reuse(
        tmp_path, iter_dir=iter_dir,
        payload=resume.carry_forward_payload(prior, _matrix(policy_hash="NEW")),
        policy_hash="NEW",
    )
    resume.write_manifest(iter_dir, plan.manifest(
        iteration=2, epoch=1, policy_hash="NEW"))

    doc = json.loads((iter_dir / resume.MANIFEST_FILE).read_text())
    assert doc["reused_count"] == 0
    assert doc["pending_count"] == 3
    assert "pre-registration" in doc["refused"]


def test_disabled_reuse_re_measures_everything(tmp_path):
    prior = _matrix()
    _seed_iteration(tmp_path, 1, prior, [_run_row(prior, i) for i in range(3)])
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2", payload=prior,
        policy_hash="ph1", enabled=False,
    )
    assert plan.reused_count == 0
    assert plan.pending_indices == [0, 1, 2]


def test_saved_ms_sums_the_reused_rows_original_durations(tmp_path):
    prior = _matrix(rows=2)
    _seed_iteration(tmp_path, 1, prior, [
        _run_row(prior, 0, duration_ms=5000),
        _run_row(prior, 1, duration_ms=7000),
    ])
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=2)),
        policy_hash="ph1",
    )
    assert plan.saved_ms == 12000


# ── property: reuse never changes a row's identity ───────────────────────────

@DET
@given(statuses=st.lists(
    st.sampled_from(["complete", "failed", "infeasible", "rejected"]),
    min_size=1, max_size=6))
def test_property_reuse_never_changes_a_rows_identity(statuses, tmp_path_factory):
    """A carried-forward row's identity fields are byte-identical to the source."""
    tmp_path = tmp_path_factory.mktemp("identity")
    n = len(statuses)
    prior = _matrix(rows=n)
    source_rows = [_run_row(prior, i, status=s) for i, s in enumerate(statuses)]
    _seed_iteration(tmp_path, 1, prior, source_rows)

    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=n)),
        policy_hash="ph1",
    )
    by_index = {r["row_index"]: r for r in source_rows}
    for reused in plan.rows:
        src = by_index[reused["row_index"]]
        for field in ("row_index", "levels", "role", "replicate", "status",
                      "response", "apply", "duration_ms"):
            assert reused[field] == src[field], field
        # ...and the ONLY added key is the provenance marker.
        assert set(reused) - set(src) == {"reused_from"}


@DET
@given(statuses=st.lists(
    st.sampled_from(["complete", "failed", "infeasible", "rejected"]),
    min_size=1, max_size=6))
def test_property_reused_and_pending_partition_the_planned_rows(statuses,
                                                                tmp_path_factory):
    """Every planned row is either reused or pending — never both, never neither."""
    tmp_path = tmp_path_factory.mktemp("partition")
    n = len(statuses)
    prior = _matrix(rows=n)
    _seed_iteration(tmp_path, 1, prior,
                    [_run_row(prior, i, status=s) for i, s in enumerate(statuses)])
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-2",
        payload=resume.carry_forward_payload(prior, _matrix(rows=n)),
        policy_hash="ph1",
    )
    reused = {r["row_index"] for r in plan.rows}
    pending = set(plan.pending_indices)
    assert reused | pending == set(range(n))
    assert reused & pending == set()
    # Exactly the failed rows are pending.
    assert pending == {i for i, s in enumerate(statuses) if s == "failed"}


# ═══════════════════════ 2. CIRCUIT BREAKER ═════════════════════════════════

def _fail(it, err, stage="screen", exc="OptimizationAborted"):
    return progress.FailureRecord(iteration=it, stage=stage, error=err, exc_type=exc)


@pytest.mark.mutation_sentinel
def test_the_breaker_trips_on_n_identical_failures(tmp_path):
    msg = "3 of 18 rows unusable; refusing to fit"
    failures = [_fail(2, msg), _fail(3, msg), _fail(4, msg)]
    verdict = progress.check_breaker(failures, threshold=3)
    assert verdict.tripped
    assert verdict.count == 3
    assert verdict.iterations == (2, 3, 4)
    assert "same failure mode" in verdict.reason


@pytest.mark.mutation_sentinel
def test_the_breaker_never_trips_on_distinct_failures():
    failures = [
        _fail(2, "build gate check failed for factor A"),
        _fail(3, "cannot coerce None to float in effects fit"),
        _fail(4, "adapter emitted no parseable JSON"),
    ]
    assert not progress.check_breaker(failures, threshold=3).tripped


def test_the_breaker_does_not_trip_below_the_threshold():
    msg = "same thing"
    assert not progress.check_breaker([_fail(2, msg), _fail(3, msg)], threshold=3).tripped


def test_an_intervening_different_failure_resets_the_run():
    """Consecutive, not cumulative: a campaign still learning is not stopped.

    Four failures of one kind in total, but a different one in the middle, so
    the longest consecutive run is 2 — below the threshold. Cumulative counting
    would stop this campaign; consecutive counting correctly lets it continue.
    """
    msg = "flaky timeout"
    failures = [_fail(2, msg), _fail(3, msg), _fail(4, "something else entirely"),
                _fail(5, msg), _fail(6, msg)]
    verdict = progress.check_breaker(failures, threshold=3)
    assert not verdict.tripped
    assert verdict.count == 2, "only the trailing consecutive run is counted"


def test_a_successful_iteration_between_failures_is_not_a_repeat(tmp_path):
    """Read through the ledger: a clean iteration between two identical failures.

    ledger.json is the real source, so this exercises the path production uses
    rather than a hand-built list. Iterations 2 and 4 failed identically and 3
    succeeded — but the ledger records only FAILED rows for the breaker, so the
    caller must not see a run of 2. The reset is expressed by the caller
    passing the failures it observed since the last success; this test pins the
    ledger reader's contract that a non-FAILED row is not a failure.
    """
    (tmp_path / "ledger.json").write_text(json.dumps({"iterations": [
        {"iteration": 2, "status": "FAILED", "error": "flaky timeout"},
        {"iteration": 3},  # clean
        {"iteration": 4, "status": "FAILED", "error": "flaky timeout"},
    ]}))
    recs = progress.failures_from_ledger(tmp_path)
    assert [r.iteration for r in recs] == [2, 4]
    assert not progress.check_breaker(recs, threshold=3).tripped


def test_the_same_message_at_two_different_stages_is_two_failures():
    msg = "identical text"
    failures = [_fail(2, msg, stage="screen"), _fail(3, msg, stage="confirm"),
                _fail(4, msg, stage="screen")]
    assert not progress.check_breaker(failures, threshold=3).tripped


def test_incidental_per_iteration_text_does_not_defeat_the_fingerprint():
    """Different iter-N paths and row counts are the SAME defect."""
    a = "screen aborted: see runs/iter-2/runs.jsonl row_index 3 for the levels"
    b = "screen aborted: see runs/iter-3/runs.jsonl row_index 7 for the levels"
    assert (progress.failure_fingerprint(stage="screen", error=a)
            == progress.failure_fingerprint(stage="screen", error=b))


def test_genuinely_different_messages_keep_different_fingerprints():
    a = "design matrix is singular"
    b = "adapter emitted no parseable JSON object"
    assert (progress.failure_fingerprint(stage="screen", error=a)
            != progress.failure_fingerprint(stage="screen", error=b))


def test_the_exception_type_separates_two_failures_with_alike_messages():
    assert (progress.failure_fingerprint(stage="screen", error="boom",
                                         exc_type="OptimizationAborted")
            != progress.failure_fingerprint(stage="screen", error="boom",
                                            exc_type="KeyError"))


def test_the_breaker_verdict_lands_on_disk_as_its_own_artifact(tmp_path):
    """halt.json, not epoch_end-N.json: nothing semantic was discovered."""
    msg = "the same crash"
    verdict = progress.check_breaker([_fail(2, msg), _fail(3, msg), _fail(4, msg)],
                                     threshold=3)
    progress.write_halt(tmp_path, {
        "kind": "repeated_failure", "reason": verdict.reason,
        "breaker": verdict.as_dict(),
    })
    doc = json.loads((tmp_path / progress.HALT_FILE).read_text())
    assert doc["kind"] == "repeated_failure"
    assert doc["breaker"]["count"] == 3
    assert doc["breaker"]["iterations"] == [2, 3, 4]
    # The verbatim messages are kept so a human can see any fingerprint merge.
    assert doc["breaker"]["messages"] == [msg, msg, msg]
    # And it is NOT filed as an epoch end.
    assert not list(tmp_path.glob("epoch_end*.json"))


def test_failures_are_read_back_from_the_ledger(tmp_path):
    """ledger.json is the durable source, so the breaker survives a restart."""
    (tmp_path / "ledger.json").write_text(json.dumps({"iterations": [
        {"iteration": 1},
        {"iteration": 2, "status": "FAILED", "error": "boom"},
        {"iteration": 3, "status": "FAILED", "error": "boom"},
    ]}))
    recs = progress.failures_from_ledger(tmp_path)
    assert [r.iteration for r in recs] == [2, 3]
    assert all(r.error == "boom" for r in recs)


@DET
@given(n=st.integers(min_value=1, max_value=8),
       threshold=st.integers(min_value=1, max_value=5))
def test_property_identical_failures_trip_iff_count_reaches_threshold(n, threshold):
    failures = [_fail(i, "one deterministic defect") for i in range(n)]
    verdict = progress.check_breaker(failures, threshold=threshold)
    assert verdict.tripped == (n >= threshold)


@DET
@given(n=st.integers(min_value=1, max_value=8),
       threshold=st.integers(min_value=2, max_value=5))
def test_property_all_distinct_failures_never_trip(n, threshold):
    failures = [_fail(i, f"distinct failure number {i}") for i in range(n)]
    assert not progress.check_breaker(failures, threshold=threshold).tripped


# ═══════════════════════ 3. PROGRESS SURFACE ════════════════════════════════

def test_progress_reports_stage_iteration_and_row_counts(tmp_path):
    payload = _matrix(rows=4)
    _seed_iteration(tmp_path, 2, payload, [
        _run_row(payload, 0), _run_row(payload, 1),
        _run_row(payload, 2, status="failed"),
    ])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "demo", "iteration": 2, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    (tmp_path / "ledger.json").write_text(json.dumps({"iterations": [
        {"iteration": 1}, {"iteration": 2, "status": "FAILED", "error": "boom"},
    ]}))

    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.run_id == "demo"
    assert snap.iteration == 2
    assert snap.rows_planned == 4
    assert snap.rows_done == 2
    assert snap.rows_failed == 1
    assert snap.rows_pending == 1
    assert snap.completed_iterations == 1
    assert snap.failed_iterations == 1
    assert snap.phase == "EXECUTE_ANALYZE"


@pytest.mark.mutation_sentinel
def test_no_eta_is_reported_when_every_duration_is_zero(tmp_path):
    """A confident ETA from zeros is the plausible-looking-signal failure itself.

    duration_ms reserves 0 for "never executed", and it was structurally always
    0 for most of this project's history.
    """
    payload = _matrix(rows=4)
    _seed_iteration(tmp_path, 1, payload, [
        _run_row(payload, 0, duration_ms=0), _run_row(payload, 1, duration_ms=0),
    ])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 1, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.rows_pending == 2
    assert snap.eta_seconds is None
    assert snap.mean_row_seconds is None
    assert "no completed row has a usable duration" in snap.eta_basis
    assert "unavailable" in progress.format_progress(snap)


def test_an_eta_is_reported_when_durations_are_real(tmp_path):
    payload = _matrix(rows=4)
    _seed_iteration(tmp_path, 1, payload, [
        _run_row(payload, 0, duration_ms=10_000),
        _run_row(payload, 1, duration_ms=20_000),
    ])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 1, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    snap = progress.read_progress_snapshot(tmp_path)
    # mean 15s, 2 rows pending -> 30s
    assert snap.eta_seconds == pytest.approx(30.0)
    assert snap.mean_row_seconds == pytest.approx(15.0)


def test_a_reused_rows_duration_does_not_inform_the_eta(tmp_path):
    """It was paid in a previous iteration and predicts nothing about what remains."""
    payload = _matrix(rows=3)
    reused = _run_row(payload, 0, duration_ms=1)
    reused["reused_from"] = {"iteration": 1, "epoch": 1}
    _seed_iteration(tmp_path, 2, payload, [reused,
                                           _run_row(payload, 1, duration_ms=10_000)])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 2, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.rows_reused == 1
    # mean over the FRESH row only (10s), 1 pending -> 10s, not ~5s.
    assert snap.eta_seconds == pytest.approx(10.0)


def test_progress_json_is_written_atomically_and_is_valid_while_running(tmp_path):
    payload = _matrix(rows=2)
    _seed_iteration(tmp_path, 1, payload, [_run_row(payload, 0)])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 1, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    progress.write_progress(tmp_path)
    doc = json.loads((tmp_path / progress.PROGRESS_FILE).read_text())
    assert doc["rows"]["planned"] == 2
    assert doc["rows"]["done"] == 1
    assert doc["run_id"] == "z"
    # No stray temp files left behind.
    assert not list(tmp_path.glob("*.tmp"))


def test_a_rewrite_never_leaves_a_partial_document(tmp_path):
    """Repeated rewrites always leave parseable JSON — the atomic-write guarantee."""
    payload = _matrix(rows=2)
    _seed_iteration(tmp_path, 1, payload, [_run_row(payload, 0)])
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 1, "last_entered_phase": "DESIGN",
        "family": None, "timestamp": "x",
    }))
    for _ in range(20):
        progress.write_progress(tmp_path)
        json.loads((tmp_path / progress.PROGRESS_FILE).read_text())


def test_progress_on_an_empty_work_dir_says_unknown_rather_than_raising(tmp_path):
    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.eta_seconds is None
    assert snap.rows_planned == 0
    text = progress.format_progress(snap)
    assert "unknown" in text


def test_progress_surfaces_the_halt_verdict(tmp_path):
    progress.write_halt(tmp_path, {"kind": "repeated_failure", "reason": "because"})
    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.halted["kind"] == "repeated_failure"
    assert "HALTED" in progress.format_progress(snap)
    assert "HALTED" in progress.format_progress_line(snap)


@DET
@given(done=st.integers(0, 8), failed=st.integers(0, 8), extra=st.integers(0, 5))
def test_property_progress_counts_always_reconcile(done, failed, extra,
                                                   tmp_path_factory):
    """done + failed + pending == planned, for every combination."""
    tmp_path = tmp_path_factory.mktemp("reconcile")
    planned = done + failed + extra
    if planned == 0:
        planned = 1
        extra = 1
    payload = _matrix(rows=planned)
    rows = ([_run_row(payload, i) for i in range(min(done, planned))]
            + [_run_row(payload, i, status="failed")
               for i in range(min(done, planned),
                              min(done + failed, planned))])
    _seed_iteration(tmp_path, 1, payload, rows)
    (tmp_path / "state.json").write_text(json.dumps({
        "run_id": "z", "iteration": 1, "last_entered_phase": "EXECUTE_ANALYZE",
        "family": None, "timestamp": "x",
    }))
    snap = progress.read_progress_snapshot(tmp_path)
    assert snap.rows_done + snap.rows_failed + snap.rows_pending == snap.rows_planned


@DET
@given(durations=st.lists(st.integers(min_value=-5, max_value=0), max_size=6),
       pending=st.integers(min_value=1, max_value=10))
def test_property_eta_is_absent_rather_than_wrong_without_usable_durations(
        durations, pending):
    eta, basis, mean = progress._estimate_eta(pending=pending, durations=durations)
    assert eta is None
    assert mean is None
    assert "usable duration" in basis


# ═══════════════════════ 4. ORPHAN REAPING ══════════════════════════════════

def _spawner_script(tmp_path: Path) -> Path:
    """A script shaped like a real benchmark adapter: backgrounds a server, prints JSON."""
    marker = tmp_path / "grandchild_alive"
    script = tmp_path / "adapter.sh"
    script.write_text(
        "#!/bin/bash\n"
        f"( while true; do touch {marker}; sleep 0.1; done ) &\n"
        'echo \'{"m": 1.0}\'\n'
        "sleep 300\n",
    )
    script.chmod(0o755)
    return script


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
@pytest.mark.mutation_sentinel
def test_a_timed_out_adapter_leaves_no_surviving_grandchild(tmp_path):
    """The measured defect: subprocess.run(timeout=) orphans grandchildren to PID 1."""
    script = _spawner_script(tmp_path)
    marker = tmp_path / "grandchild_alive"

    with pytest.raises(subprocess.TimeoutExpired):
        reaper.run_in_process_group([str(script)], timeout=1.5)

    # Give any survivor a chance to prove it is alive, then check the marker
    # stops advancing.
    if marker.exists():
        marker.unlink()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if marker.exists():
            pytest.fail(
                "a grandchild of the timed-out adapter survived: it kept "
                "touching its marker after the process group was killed",
            )
        time.sleep(0.1)


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_a_killed_parent_process_leaves_no_children(tmp_path):
    """End to end: SIGTERM the parent, and the whole tree goes with it."""
    script = _spawner_script(tmp_path)
    marker = tmp_path / "grandchild_alive"
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from orchestrator.optimize import reaper\n"
        "reaper.install_signal_handlers()\n"
        "import subprocess\n"
        f"p = subprocess.Popen([{str(script)!r}], start_new_session=True,\n"
        "                     stdout=subprocess.PIPE)\n"
        "reaper.track(p)\n"
        "time.sleep(60)\n",
    )
    parent = subprocess.Popen([sys.executable, str(driver)])
    try:
        # Wait for the grandchild to exist.
        deadline = time.time() + 10
        while time.time() < deadline and not marker.exists():
            time.sleep(0.1)
        assert marker.exists(), "grandchild never started; test cannot conclude"

        parent.terminate()
        parent.wait(timeout=15)

        marker.unlink()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if marker.exists():
                pytest.fail(
                    "killing the parent left a billing grandchild running — "
                    "this is the reported 18-hour orphan",
                )
            time.sleep(0.1)
    finally:
        if parent.poll() is None:  # pragma: no cover - cleanup
            parent.kill()


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_a_clean_adapter_run_returns_its_output_unchanged(tmp_path):
    """The reaper is a drop-in: normal runs behave exactly as subprocess.run did."""
    script = tmp_path / "ok.sh"
    script.write_text('#!/bin/bash\necho \'{"m": 42.0}\'\nexit 0\n')
    script.chmod(0o755)
    done = reaper.run_in_process_group([str(script)], timeout=30)
    assert done.returncode == 0
    assert json.loads(done.stdout.strip())["m"] == 42.0


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_a_nonzero_exit_is_reported_not_swallowed(tmp_path):
    script = tmp_path / "bad.sh"
    script.write_text('#!/bin/bash\necho oops >&2\nexit 3\n')
    script.chmod(0o755)
    done = reaper.run_in_process_group([str(script)], timeout=30)
    assert done.returncode == 3
    assert "oops" in done.stderr


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_reap_all_reports_how_many_trees_it_terminated(tmp_path):
    script = _spawner_script(tmp_path)
    procs = [subprocess.Popen([str(script)], start_new_session=True,
                              stdout=subprocess.PIPE) for _ in range(2)]
    for p in procs:
        reaper.track(p)
    try:
        assert reaper.reap_all(grace=2.0) == 2
        for p in procs:
            assert p.poll() is not None
    finally:
        for p in procs:  # pragma: no cover - cleanup
            if p.poll() is None:
                p.kill()


# ═══════════════════════ 5. WALL-CLOCK BUDGET ═══════════════════════════════

def test_an_undeclared_budget_is_unbounded():
    v = progress.check_budget(budget_hours=None, started_at=0.0, now=10 ** 9)
    assert not v.exhausted


def test_a_declared_budget_is_exhausted_once_it_is_spent():
    start = 1000.0
    v = progress.check_budget(budget_hours=2.0, started_at=start,
                              now=start + 2 * 3600 + 1)
    assert v.exhausted
    assert v.elapsed_hours == pytest.approx(2.0, abs=1e-3)
    assert "wall-clock budget" in v.reason
    # The message must say a recommendation is still produced.
    assert "recommendation" in v.reason


def test_a_budget_not_yet_spent_allows_another_iteration():
    start = 1000.0
    v = progress.check_budget(budget_hours=2.0, started_at=start,
                              now=start + 3600)
    assert not v.exhausted
    assert v.elapsed_hours == pytest.approx(1.0, abs=1e-3)


def test_a_nonsensical_budget_is_treated_as_undeclared():
    assert not progress.check_budget(budget_hours=0, started_at=0, now=10 ** 9).exhausted
    assert not progress.check_budget(budget_hours=-1, started_at=0, now=10 ** 9).exhausted
    assert not progress.check_budget(budget_hours="nope", started_at=0,
                                     now=10 ** 9).exhausted


def test_the_budget_verdict_lands_on_disk_with_its_elapsed_time(tmp_path):
    start = 1000.0
    v = progress.check_budget(budget_hours=1.0, started_at=start,
                              now=start + 7200)
    progress.write_halt(tmp_path, {
        "kind": "wall_clock_budget", "reason": v.reason, "budget": v.as_dict(),
    })
    doc = json.loads((tmp_path / progress.HALT_FILE).read_text())
    assert doc["kind"] == "wall_clock_budget"
    assert doc["budget"]["exhausted"] is True
    assert doc["budget"]["budget_hours"] == 1.0
    assert doc["budget"]["elapsed_hours"] == pytest.approx(2.0, abs=1e-3)


# ═══════════════ 6. END TO END through the real run_stage ═══════════════════
#
# These drive `stage_runner.run_stage` in process over a synthetic surface via
# `orchestrator.optimize.harness` — no dispatcher, no LLM, no subprocess.

def _drive(surface, *, seed, parent_dir, overrides=None, max_iterations=6):
    from orchestrator.optimize.harness import run_synthetic_campaign
    return run_synthetic_campaign(
        surface, seed=seed, parent_dir=parent_dir,
        campaign_overrides=overrides, max_iterations=max_iterations,
    )


def _flaky_runner(base_runner, *, fail_rows, fail_on_attempt):
    """A runner that fails a chosen row set on the FIRST attempt only.

    Models the real incident: a row times out once (a transient wall-clock
    overrun on a loaded machine) and succeeds when re-run. `attempts` counts
    per row_index, so the second attempt at the same row measures cleanly —
    which is exactly the case where reuse of the OTHER rows must not
    re-measure them.
    """
    attempts: dict = {}

    def run(row):
        n = attempts.get(row.row_index, 0) + 1
        attempts[row.row_index] = n
        if row.row_index in fail_rows and n <= fail_on_attempt:
            raise RuntimeError(
                f"config run failed: simulated wall-clock timeout on row "
                f"{row.row_index}",
            )
        return base_runner(row)

    run.attempts = attempts
    return run


def _run_one_stage(campaign, work_dir, *, iteration, runner, stage="screen"):
    from orchestrator.optimize.harness import _all_pass
    from orchestrator.optimize.stage_runner import run_stage
    return run_stage(
        campaign, work_dir, iteration=iteration, stage=stage,
        config_runner=runner, test_results=_all_pass(campaign),
        auto_approve=True,
    )


def _setup(campaign, parent_dir, run_id):
    import os
    from orchestrator.iteration import setup_work_dir
    prior = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(parent_dir)
    try:
        return setup_work_dir(run_id, repo_path=None, campaign=campaign)
    finally:
        if prior is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior


SEED_ENV = "NOUS_WORKLOAD_SEED"


def _screen_campaign(surface, **extra):
    """A verify->screen->confirm campaign that declares a workload seed.

    ``workload.seed_env`` is declared because reuse identity INCLUDES the
    workload draw, and nearly every real campaign declares it (5 of the 6
    examples in examples/optimization/ do). A campaign without it is the
    weaker case for reuse, not the representative one.
    """
    from orchestrator.optimize.harness import synthetic_campaign
    return synthetic_campaign(
        surface, stages=["verify", "screen", "confirm"],
        workload={"seed_env": SEED_ENV}, **extra,
    )


def test_e2e_a_retried_iteration_reuses_the_rows_that_measured_fine(tmp_path):
    """THE REAL FAILURE, reproduced and repaired.

    Attempt 1 fails: some rows never measure and the iteration aborts. Attempt 2
    (a fresh iteration, same registered state — which is what production does)
    must re-measure ONLY the rows that failed, and must reuse the rest.
    """
    from orchestrator.engine import Engine
    from orchestrator.optimize.stage_runner import OptimizationAborted
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = _screen_campaign(surface)
    work_dir = _setup(campaign, tmp_path, "e2e-reuse")

    base = make_synthetic_runner(surface, seed=11, seed_env=SEED_ENV)
    # Fail rows 2 and 5 on the first attempt only.
    flaky = _flaky_runner(base, fail_rows={2, 5}, fail_on_attempt=1)

    # iter-1 = verify (pre-epoch), iter-2 = screen (attempt 1).
    _run_one_stage(campaign, work_dir, iteration=1, runner=flaky, stage="verify")
    eng = Engine(work_dir)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")

    try:
        _run_one_stage(campaign, work_dir, iteration=2, runner=flaky, stage="screen")
    except OptimizationAborted:
        pass

    first = json.loads(
        (work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    n_planned = len(first["rows"])
    rows_1 = [json.loads(l) for l in
              (work_dir / "runs" / "iter-2" / "runs.jsonl").read_text().splitlines()
              if l.strip()]
    measured_ok = {r["row_index"] for r in rows_1 if r["status"] == "complete"}
    assert len(measured_ok) >= n_planned - 2, "attempt 1 should measure most rows"

    # Attempt 2: the retry, as run_campaign does it.
    eng = Engine(work_dir)
    eng.force_phase("DESIGN")
    fresh_calls_before = dict(flaky.attempts)
    _run_one_stage(campaign, work_dir, iteration=3, runner=flaky, stage="screen")

    iter3 = work_dir / "runs" / "iter-3"
    rows_3 = [json.loads(l) for l in
              (iter3 / "runs.jsonl").read_text().splitlines() if l.strip()]

    # Every planned row is present exactly once.
    assert len(rows_3) == n_planned
    assert len({r["row_index"] for r in rows_3}) == n_planned

    reused = [r for r in rows_3 if r.get("reused_from")]
    assert reused, "the retry must reuse the rows attempt 1 measured"
    for r in reused:
        assert r["reused_from"]["iteration"] == 2

    # The rows that FAILED in attempt 1 were re-measured, not reused.
    reused_idx = {r["row_index"] for r in reused}
    assert 2 not in reused_idx and 5 not in reused_idx

    # And the reused rows were NOT re-run: their attempt counters did not move.
    for idx in reused_idx:
        assert flaky.attempts[idx] == fresh_calls_before[idx], (
            f"row {idx} was reused but the runner was invoked again"
        )

    manifest = json.loads((iter3 / "reuse_manifest.json").read_text())
    assert manifest["reused_count"] == len(reused)
    assert manifest["source_iteration"] == 2
    assert manifest["saved_ms"] >= 0


def test_e2e_a_resumed_fit_equals_the_unresumed_fit(tmp_path):
    """THE key correctness property of resumability.

    If a campaign that reused rows reaches a different fitted answer than one
    that measured the same configurations fresh, resumability is a CORRECTNESS
    BUG, not a speedup.

    WHAT "THE SAME MEASUREMENTS" MEANS HERE, because getting the control wrong
    makes the test meaningless in either direction. A retried iteration derives
    its OWN workload seeds (`run_order_seed` is the iteration number), and reuse
    deliberately carries the PRIOR attempt's seeds forward instead — so a
    control arm that simply re-measured at iteration 3 would be measuring
    different workload draws, and would differ for a legitimate reason that has
    nothing to do with reuse. Verified while writing this test: the resumed arm
    registered seeds 15838.. and a naive control 23757...

    So the control re-measures the REUSED ROWS' OWN configurations — same
    levels, same seeds — through the same seed-honouring synthetic runner, and
    the property asserted is that the value reuse carried forward is bit-equal
    to the value a fresh measurement of that identical configuration produces.
    That is exactly the claim reuse makes, and it is falsifiable: change the
    carried seed and this test fails.
    """
    from orchestrator.engine import Engine
    from orchestrator.optimize.stage_runner import OptimizationAborted
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = _screen_campaign(surface)
    work_dir = _setup(campaign, tmp_path, "resumed")

    base = make_synthetic_runner(surface, seed=21, seed_env=SEED_ENV)
    flaky = _flaky_runner(base, fail_rows={1, 4}, fail_on_attempt=1)

    _run_one_stage(campaign, work_dir, iteration=1, runner=flaky, stage="verify")
    e = Engine(work_dir)
    if e.phase != "DONE":
        e.transition("DONE")
    e.transition("DESIGN")
    try:
        _run_one_stage(campaign, work_dir, iteration=2, runner=flaky, stage="screen")
    except OptimizationAborted:
        pass
    Engine(work_dir).force_phase("DESIGN")
    _run_one_stage(campaign, work_dir, iteration=3, runner=flaky, stage="screen")

    iter3 = work_dir / "runs" / "iter-3"
    matrix = json.loads((iter3 / "design_matrix.json").read_text())
    rows = [json.loads(l) for l in
            (iter3 / "runs.jsonl").read_text().splitlines() if l.strip()]
    reused = [r for r in rows if r.get("reused_from")]
    assert reused, "the retry must have reused rows for this test to mean anything"

    # A FRESH, independent instrument over the same surface and campaign seed.
    # Seed-honouring, so an identical (levels, seed) pair must reproduce the
    # identical number.
    control = make_synthetic_runner(surface, seed=21, seed_env=SEED_ENV)
    planned = {r["row_index"]: r for r in matrix["rows"]}

    class _Row:
        def __init__(self, spec):
            self.row_index = spec["row_index"]
            self.levels = spec["levels"]
            self.role = spec["role"]
            self.replicate = spec["replicate"]
            self.apply = spec["apply"]

    for row in reused:
        idx = row["row_index"]
        fresh = control(_Row(planned[idx]))
        assert fresh["m"] == pytest.approx(row["response"]["m"], rel=1e-12), (
            f"row {idx}: the carried-forward measurement differs from a fresh "
            f"measurement of the identical registered configuration — reuse "
            f"resurrected a stale value"
        )

    # And the registered seed really is the PRIOR attempt's, not this one's:
    # that is the mechanism the equality above depends on.
    prior_matrix = json.loads(
        (work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    assert matrix["workload_seeds"] == prior_matrix["workload_seeds"], (
        "the retry must register the prior attempt's draws for the reused rows "
        "to be measurements of what it registered"
    )

    # The fit is over the full 12 rows, so nothing was lost to the failure.
    fit = json.loads((iter3 / "effects.json").read_text())
    assert fit["effects"], "the resumed iteration must produce a fit"
    assert len(rows) == len(matrix["rows"])


def test_e2e_reuse_saves_measurable_wall_clock(tmp_path):
    """A real number, not an estimate: the reused rows' measurement time.

    The synthetic runner is instant, so a synthetic campaign cannot show a wall
    clock saving by simply running faster. It is made honest here by giving each
    measurement a real, known cost and measuring the two arms with a clock.
    """
    from orchestrator.engine import Engine
    from orchestrator.optimize.stage_runner import OptimizationAborted
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    from orchestrator.optimize.harness import synthetic_campaign

    surface = SURFACES["additive"]()
    # Large enough that the reused rows dominate interpreter/IO noise: at
    # 0.05s the two arms were within 40ms of each other and the sign of the
    # difference was not stable across runs, which would make this test a
    # coin flip rather than a measurement.
    COST_S = 0.25  # per measurement

    def costly(base):
        def run(row):
            time.sleep(COST_S)
            return base(row)
        return run

    # ── arm A: retry WITH reuse ──
    c = _screen_campaign(surface)
    wd = _setup(c, tmp_path, "saving-reuse")
    base = make_synthetic_runner(surface, seed=31, seed_env=SEED_ENV)
    flaky = _flaky_runner(costly(base), fail_rows={0, 7}, fail_on_attempt=1)
    _run_one_stage(c, wd, iteration=1, runner=flaky, stage="verify")
    e = Engine(wd)
    if e.phase != "DONE":
        e.transition("DONE")
    e.transition("DESIGN")
    try:
        _run_one_stage(c, wd, iteration=2, runner=flaky, stage="screen")
    except OptimizationAborted:
        pass
    Engine(wd).force_phase("DESIGN")
    t0 = time.monotonic()
    _run_one_stage(c, wd, iteration=3, runner=flaky, stage="screen")
    with_reuse_s = time.monotonic() - t0

    rows = [json.loads(l) for l in
            (wd / "runs" / "iter-3" / "runs.jsonl").read_text().splitlines()
            if l.strip()]
    n_reused = sum(1 for r in rows if r.get("reused_from"))
    n_total = len(rows)
    assert n_reused > 0

    # ── arm B: the same retry with reuse DISABLED ──
    c2 = _screen_campaign(surface, reuse_measured_rows=False)
    wd2 = _setup(c2, tmp_path, "saving-noreuse")
    base2 = make_synthetic_runner(surface, seed=31, seed_env=SEED_ENV)
    flaky2 = _flaky_runner(costly(base2), fail_rows={0, 7}, fail_on_attempt=1)
    _run_one_stage(c2, wd2, iteration=1, runner=flaky2, stage="verify")
    e2 = Engine(wd2)
    if e2.phase != "DONE":
        e2.transition("DONE")
    e2.transition("DESIGN")
    try:
        _run_one_stage(c2, wd2, iteration=2, runner=flaky2, stage="screen")
    except OptimizationAborted:
        pass
    Engine(wd2).force_phase("DESIGN")
    t1 = time.monotonic()
    _run_one_stage(c2, wd2, iteration=3, runner=flaky2, stage="screen")
    without_reuse_s = time.monotonic() - t1

    rows2 = [json.loads(l) for l in
             (wd2 / "runs" / "iter-3" / "runs.jsonl").read_text().splitlines()
             if l.strip()]
    assert not any(r.get("reused_from") for r in rows2)

    print(f"\n  MEASURED WALL CLOCK ({n_total} rows, {n_reused} reused, "
          f"{COST_S}s per measurement):")
    print(f"    with reuse:    {with_reuse_s:.3f}s")
    print(f"    without reuse: {without_reuse_s:.3f}s")
    print(f"    saved:         {without_reuse_s - with_reuse_s:.3f}s "
          f"({100 * (1 - with_reuse_s / without_reuse_s):.0f}%)")

    # The saving must be real and must be roughly the reused rows' cost.
    assert with_reuse_s < without_reuse_s
    assert (without_reuse_s - with_reuse_s) > 0.5 * n_reused * COST_S


def test_e2e_a_campaign_failing_identically_trips_the_breaker(tmp_path):
    """The loop stops with an actionable artifact instead of burning the budget."""
    from orchestrator.optimize.synthetic import SURFACES

    surface = SURFACES["additive"]()
    campaign = _screen_campaign(surface)
    work_dir = _setup(campaign, tmp_path, "e2e-breaker")

    # A DETERMINISTIC defect: every attempt fails the same way, at every row.
    msg = "config run failed: adapter is not executable"

    def always_broken(row):
        raise RuntimeError(msg)

    from orchestrator.ledger import append_failed_row
    from orchestrator.optimize.stage_runner import OptimizationAborted

    # Four attempts, as the real campaign made.
    for i in (2, 3, 4, 5):
        try:
            _run_one_stage(campaign, work_dir, iteration=i,
                           runner=always_broken, stage="screen")
        except OptimizationAborted as exc:
            append_failed_row(work_dir, i, f"{type(exc).__name__}: {exc}")

    failures = progress.failures_from_ledger(work_dir)
    assert len(failures) >= 3, "the attempts must have been recorded as failures"

    verdict = progress.check_breaker(failures, threshold=3)
    assert verdict.tripped, (
        f"four identical failures must trip the breaker; got {verdict}"
    )
    # The exception type was recovered from the ledger's error text.
    assert failures[0].exc_type == "OptimizationAborted"

    progress.write_halt(work_dir, {
        "kind": "repeated_failure", "reason": verdict.reason,
        "breaker": verdict.as_dict(),
    })
    doc = json.loads((work_dir / progress.HALT_FILE).read_text())
    assert doc["breaker"]["tripped"] is True
    # A human can read WHY without opening a log.
    assert "Fix the cause and resume" in doc["reason"]

    snap = progress.read_progress_snapshot(work_dir)
    assert snap.halted is not None
    assert snap.failed_iterations >= 3


def test_e2e_progress_reports_the_stage_a_status_call_cannot(tmp_path):
    """`nous status` reads state.json only; the stage lives in transitions.jsonl."""
    from orchestrator.engine import Engine
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = _screen_campaign(surface)
    work_dir = _setup(campaign, tmp_path, "e2e-progress")
    runner = make_synthetic_runner(surface, seed=41, seed_env=SEED_ENV)

    _run_one_stage(campaign, work_dir, iteration=1, runner=runner, stage="verify")
    e = Engine(work_dir)
    if e.phase != "DONE":
        e.transition("DONE")
    e.transition("DESIGN")
    _run_one_stage(campaign, work_dir, iteration=2, runner=runner, stage="screen")

    progress.write_progress(work_dir)
    doc = json.loads((work_dir / progress.PROGRESS_FILE).read_text())
    assert doc["stage"], "progress must name the compiled epoch's current state"
    assert doc["rows"]["planned"] > 0
    assert doc["rows"]["done"] + doc["rows"]["failed"] + doc["rows"]["pending"] \
        == doc["rows"]["planned"]


# ═══════════ 7. TERMINAL DISCRIMINATION IS NEVER REUSED ═════════════════════
#
# Raised in review: `confirm` REQUIRES fresh samples, so a reused replicate
# would defeat the one guarantee the stage exists to provide. Two confirm
# ROUNDS also share `kind: shortlist_replicate`, so the structural comparison
# alone could have matched round 1 against round 2 — and a second round is spent
# exactly when the shortlist is unchanged, i.e. exactly when that match fires.

def _confirm_matrix(*, policy_hash="ph1", rnd=1, replicates=2):
    finalists = [
        {"key": "f0", "levels": {"A": 2.0}, "why": "the fitted recommendation"},
        {"key": "f1", "levels": {"A": 16.0}, "why": "best observed"},
    ]
    rows, idx = [], 0
    for rep in range(replicates):
        for fi, f in enumerate(finalists):
            rows.append({
                "row_index": idx, "levels": dict(f["levels"]), "role": "confirm",
                "replicate": rep,
                "apply": {"cli_args": [], "env": {"NOUS_WORKLOAD_SEED": 500 + rep},
                          "patches": [], "finalist": fi},
            })
            idx += 1
    return {
        "factor_ids": ["A"], "kind": "shortlist_replicate", "resolution": None,
        "generators": [], "aliases": [], "run_order": list(range(idx)),
        "run_order_seed": rnd, "policy_hash": policy_hash, "paired": True,
        "round": rnd, "finalists": finalists, "rows": rows,
        "workload_seeds": {str(r["row_index"]): 500 + r["replicate"] for r in rows},
    }


@pytest.mark.mutation_sentinel
def test_a_confirm_round_never_donates_or_receives_a_reused_row():
    """`shortlist_replicate` is refused on BOTH sides of the carry-forward."""
    r1 = _confirm_matrix(rnd=1)
    r2 = _confirm_matrix(rnd=2)
    assert resume.carry_forward_payload(r1, r2) is None, (
        "a second confirm round must not reuse round 1's replicates: the round "
        "exists because round 1 did not discriminate"
    )
    # Even byte-identical shortlists (the case a second round actually hits).
    assert resume.carry_forward_payload(r1, _confirm_matrix(rnd=1)) is None
    # And a confirm matrix cannot receive rows from a screen block either.
    assert resume.carry_forward_payload(_matrix(rows=4), r1) is None
    assert resume.carry_forward_payload(r1, _matrix(rows=4)) is None


@pytest.mark.mutation_sentinel
def test_reuse_is_refused_even_when_a_confirm_round_would_otherwise_match(tmp_path):
    """Through plan_reuse, not just the payload comparison."""
    r1 = _confirm_matrix(rnd=1)
    rows = []
    for spec in r1["rows"]:
        rows.append({
            "row_index": spec["row_index"], "levels": dict(spec["levels"]),
            "role": "confirm", "replicate": spec["replicate"],
            "apply": dict(spec["apply"]), "status": "complete",
            "response": {"m": 1.0}, "duration_ms": 4000, "attempts": 1,
            "last_attempt_ms": 4000, "error": "", "failure_kind": "",
        })
    _seed_iteration(tmp_path, 3, r1, rows)

    # A caller that (wrongly) hands plan_reuse a confirm payload directly must
    # still not receive reused replicates.
    plan = resume.plan_reuse(
        tmp_path, iter_dir=tmp_path / "runs" / "iter-4",
        payload=_confirm_matrix(rnd=2), policy_hash="ph1",
    )
    assert plan.reused_count == 0, (
        "terminal discrimination must measure its finalists freshly"
    )


def test_e2e_confirm_measures_every_finalist_freshly_after_a_retry(tmp_path):
    """The end-to-end version: every finalist gets its full sample count.

    The review found a confirm finalist with `n: 0` — no samples at all —
    alongside two with `n: 2`. A finalist the campaign never measured cannot
    take part in terminal discrimination, so this pins that every finalist is
    measured the declared number of times even on a work_dir that already holds
    a completed screen.

    HONEST LIMIT OF THIS TEST, disclosed rather than implied. It does NOT
    isolate the `kind`-based confirm guard. The only prior iteration here is a
    12-row `kind: full` screen while confirm registers a 6-row
    `shortlist_replicate`, so `carry_forward_payload` already refuses on
    `factor_ids` / row-set / design-family grounds independently — verified by
    mutation: removing ALL THREE confirm guards leaves this test passing (M17
    survives, see the mutation matrix). What it does prove is the OUTCOME the
    review asked about: no confirm row is reused and every finalist that takes
    part has samples.

    The guard's real exposure is confirm round 1 -> round 2, where both matrices
    share `kind`, `factor_ids` and (when the shortlist is unchanged, which is
    exactly when a second round is spent) the row set. That case is covered by
    `test_a_confirm_round_never_donates_or_receives_a_reused_row` and
    `test_reuse_is_refused_even_when_a_confirm_round_would_otherwise_match`,
    which DO kill their mutants (M15, M16). Reaching a genuine second confirm
    round end to end needs a policy with `max_rounds > 1` plus a first round
    that fails to discriminate; that is left uncovered at the E2E layer and is
    the honest gap in this file.
    """
    from orchestrator.engine import Engine
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = _screen_campaign(surface)
    campaign["optimization"]["design"]["confirm"] = {
        "replicates": 2, "shortlist_size": 3,
    }
    work_dir = _setup(campaign, tmp_path, "e2e-confirm-fresh")
    runner = make_synthetic_runner(surface, seed=61, seed_env=SEED_ENV)

    _run_one_stage(campaign, work_dir, iteration=1, runner=runner, stage="verify")
    e = Engine(work_dir)
    if e.phase != "DONE":
        e.transition("DONE")
    e.transition("DESIGN")
    _run_one_stage(campaign, work_dir, iteration=2, runner=runner, stage="screen")
    Engine(work_dir).force_phase("DESIGN")
    _run_one_stage(campaign, work_dir, iteration=3, runner=runner, stage="confirm")

    iter3 = work_dir / "runs" / "iter-3"
    rows = [json.loads(l) for l in
            (iter3 / "runs.jsonl").read_text().splitlines() if l.strip()]
    # NOTHING in a confirm round may be reused.
    assert not any(r.get("reused_from") for r in rows), (
        "confirm rows must all be fresh measurements"
    )
    assert not (iter3 / resume.MANIFEST_FILE).exists(), (
        "reuse must not even be planned at confirm"
    )

    conf = json.loads((iter3 / "confirmation.json").read_text())
    measured = [f for f in conf["finalists"] if f.get("status") != "unmeasured"]
    assert measured, conf["finalists"]
    for f in measured:
        assert f.get("n", 0) > 0, (
            f"finalist {f.get('key')} took part in terminal discrimination with "
            f"n={f.get('n')} samples: {f}"
        )


def test_reuse_is_not_planned_on_an_iteration_already_past_its_design_phase(tmp_path):
    """A RESUMED iteration (vs a RETRIED one) must not re-append its own rows.

    The two look similar and behave oppositely. A RETRY is a fresh iteration
    number with an empty `runs/iter-N/`, which is where reuse belongs. A RESUME
    re-enters an iteration whose `design_matrix.json` is already written and
    whose `runs.jsonl` already holds some rows — planning reuse there would try
    to append rows that are already on disk, and `matrix.check_fidelity`
    correctly reports a repeated `row_index` as a duplicate-run violation.

    Pinned through the phase gate rather than through a full campaign, because
    the gate IS the mechanism: reuse is planned at or before DESIGN and never
    after.
    """
    from orchestrator.engine import Engine
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import _enter_phase_pending

    campaign = {
        "kind": "optimization", "run_id": "phase-gate",
        "research_question": "q",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "t", "description": "d"},
        "optimization": {"response": {"primary": {"metric": "m",
                                                  "direction": "maximize"}},
                         "factors": [], "design": {}},
    }
    import os
    prior = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(tmp_path)
    try:
        wd = setup_work_dir("phase-gate", repo_path=None, campaign=campaign)
    finally:
        if prior is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior

    eng = Engine(wd)
    eng.force_phase("DESIGN")
    assert _enter_phase_pending(eng, wd), "a retry at DESIGN may plan reuse"

    eng.transition("HUMAN_DESIGN_GATE")
    eng.transition("EXECUTE_ANALYZE")
    assert not _enter_phase_pending(Engine(wd), wd), (
        "an iteration already executing must NOT plan reuse: its rows are "
        "registered and partly written, so re-appending them would be a "
        "duplicate-row_index fidelity violation"
    )
