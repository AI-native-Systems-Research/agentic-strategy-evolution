"""``optimization.max_parallel``: concurrency where the design can absorb it.

The epoch executed strictly sequentially and offered the author no way to say
otherwise. On a live campaign that is an 18-row screen at 5-90 minutes a row --
2 to 5+ hours of wall clock on a machine that is mostly idle. But the fix is not
"parallelize the sweep", because run-order randomization is what protects a
factorial design against DRIFT CONFOUNDING (a warming cache, a thermally
throttling machine, a background job), and co-scheduled rows contend for machine
resources, so a row's measured response would depend on WHICH OTHER ROWS
happened to run beside it. For an objective that measures where a system
saturates, that is a first-order confound, not a rounding error.

So the field is scoped to the one axis where contention is HARMLESS BY
CONSTRUCTION: a ``confirm`` REPLICATE BLOCK. Within one block each finalist is
measured exactly once, so whatever contention exists is symmetric across exactly
the things being compared -- the same argument that makes ``_confirm_rows``
shuffle INSIDE a block rather than across the whole matrix. The spending stages
(screen / foldover / refine) stay strictly sequential, and these tests are the
oracle for that exclusion rather than for the speedup.

The correctness-critical claim here is POSITIONAL ORDER. ``_finish_confirm``
appends each finalist's measurements in row order and
``certificate.terminal_regret_bound`` ZIPS them, so position *i* must be
replicate *i* for every finalist. A concurrent block that returned results in
completion order would silently mispair the paired-differences bound -- a wrong
number, not a crash. The overlap tests therefore all script a runner whose
completion order is deliberately the REVERSE of its submission order.

Nothing here asserts that a thread pool was constructed or which method was
called on a fake. The oracles are observable: wall clock (did the calls really
overlap?), returned ``row_index`` sequence (did order survive?), the recorded
concurrency in ``design_matrix.json``, and a peak-in-flight counter the fake
runner maintains itself.

No test in this file makes a live LLM call; the "target" is an in-process
callable that sleeps.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.runner import execute_design

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml"
DM_SCHEMA_PATH = (
    REPO_ROOT / "orchestrator" / "schemas" / "design_matrix.schema.json"
)


# --- fixtures ---------------------------------------------------------------

def _row(row_index: int, level: str = "off", *, replicate: int = 0) -> ConfigRow:
    return ConfigRow(
        row_index=row_index, levels={"L1": level}, role="corner",
        replicate=replicate,
        apply={"cli_args": [], "env": {}, "patches": []},
    )


def _factor(fid: str = "L1") -> list:
    return parse_factors([{
        "id": fid, "name": fid, "type": "choice", "levels": ["off", "on"],
        "apply": f"--{fid}={{level}}",
        "manipulation": {"observable": f"telemetry.{fid}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"{fid}-R1", "kind": "correctness",
                       "statement": "noop at baseline",
                       "native_test": f"tests/{fid}.py::test_noop"}],
    }])


def _response_spec() -> dict:
    return {"primary": {"metric": "throughput", "direction": "maximize"}}


class _SleepingRunner:
    """A fake target that sleeps, and reports its own PEAK CONCURRENCY.

    Two observables, both independent of how the loop is implemented:

    * ``peak`` -- the greatest number of calls simultaneously in flight. A
      sequential loop can never exceed 1, so this distinguishes "bounded at
      N" from "not concurrent at all" without inspecting a pool.
    * ``completion_order`` -- the row indices in the order calls RETURNED.
      ``per_row_delay`` lets a test make that order the reverse of submission,
      which is what turns the positional-order assertions into a real test
      rather than a coincidence.
    """

    def __init__(self, delay: float = 0.05,
                 per_row_delay: dict[int, float] | None = None):
        self._delay = delay
        self._per_row = per_row_delay or {}
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.completion_order: list[int] = []
        self.submission_order: list[int] = []

    def __call__(self, row: ConfigRow) -> dict:
        with self._lock:
            self.submission_order.append(row.row_index)
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        time.sleep(self._per_row.get(row.row_index, self._delay))
        with self._lock:
            self.in_flight -= 1
            self.completion_order.append(row.row_index)
        return {
            "throughput": float(10 + row.row_index),
            "telemetry": {"L1": row.levels["L1"]},
        }


def _campaign(repo: Path, **opt_over) -> dict:
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [{
            "id": "F", "name": "flag", "type": "choice", "levels": ["0", "1"],
            "apply": "--flag={level}",
            "manipulation": {"observable": "applied.flag", "op": "==",
                             "value": "{level}"},
            "relations": [{"id": "R1", "kind": "correctness", "statement": "s",
                           "native_test": "t.py::test_present"}],
        }],
        "stages": ["verify", "screen", "confirm"],
        "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
        "run_command": "./bench",
    }
    opt.update(opt_over)
    return {
        "kind": "optimization", "run_id": "mp",
        "research_question": "does the bound hold?",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "T", "description": "a slow target",
                          "repo_path": str(repo)},
        "optimization": opt,
    }


# --- 1. the calls genuinely overlap ----------------------------------------

def test_max_parallel_makes_replicate_block_runs_actually_overlap():
    """(a) Wall clock, not a mock assertion.

    Six rows at 0.25s each is 1.5s serial. At ``max_parallel=6`` the block
    should finish in roughly one row's time, so a ceiling well under the serial
    sum is proof the calls really were in flight together -- and the runner's
    own ``peak`` counter says how many. Both are observable outcomes of the
    loop; neither inspects it.
    """
    rows = [_row(i, replicate=0) for i in range(6)]
    runner = _SleepingRunner(delay=0.25)

    t0 = time.monotonic()
    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=_factor(), max_parallel=6,
    )
    elapsed = time.monotonic() - t0

    assert [o.row_index for o in outcomes] == list(range(6))
    assert all(o.status == "complete" for o in outcomes)
    serial = 6 * 0.25
    assert elapsed < serial / 2, (
        f"6 rows x 0.25s took {elapsed:.2f}s; a serial loop would take "
        f"{serial:.2f}s, so the calls did not overlap"
    )
    assert runner.peak > 1, (
        f"peak in-flight was {runner.peak}: the runs never overlapped"
    )


def test_max_parallel_is_an_upper_bound_not_a_target():
    """The bound is a CEILING on simultaneous in-flight runner calls.

    Oversubscription is exactly the contention the design is trying to keep
    symmetric, so a bound of 2 must never put 3 rows on the machine at once
    however many rows are queued.
    """
    rows = [_row(i) for i in range(8)]
    runner = _SleepingRunner(delay=0.05)

    execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=_factor(), max_parallel=2,
    )

    assert runner.peak == 2, f"peak in-flight {runner.peak}, bound was 2"


# --- 2. positional order survives completion order ------------------------

def test_outcomes_stay_in_positional_order_when_completion_order_is_reversed():
    """(b) THE correctness-critical claim.

    ``_finish_confirm`` appends each finalist's measurements in row order and
    ``terminal_regret_bound`` zips them, so position *i* must be replicate *i*
    for every finalist. Here row 0 is the SLOWEST and row 5 the fastest, so
    completion order is the exact reverse of submission order -- a loop that
    returned results as they landed would hand back a reversed list and the
    paired-differences bound would silently pair finalist A's replicate 1 with
    finalist B's replicate 3.

    The test asserts BOTH that completion order really was reversed (otherwise
    it proves nothing) and that the returned outcomes are nevertheless in row
    order, checked through the response VALUES as well as the indices so a
    reordering that fixed up indices alone would still fail.
    """
    delays = {0: 0.30, 1: 0.25, 2: 0.20, 3: 0.15, 4: 0.10, 5: 0.05}
    rows = [_row(i) for i in range(6)]
    runner = _SleepingRunner(per_row_delay=delays)

    outcomes = execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=_factor(), max_parallel=6,
    )

    assert runner.completion_order == [5, 4, 3, 2, 1, 0], (
        f"the fake did not complete in reverse order ({runner.completion_order}); "
        f"the ordering claim is untested without that"
    )
    assert [o.row_index for o in outcomes] == [0, 1, 2, 3, 4, 5]
    assert [o.response["throughput"] for o in outcomes] == [
        10.0, 11.0, 12.0, 13.0, 14.0, 15.0,
    ], "a response landed against the wrong row_index"


def test_on_row_fires_once_per_row_under_concurrency():
    """``runs.jsonl`` is appended through ``on_row``, which must stay
    exactly-once per row even when several rows are in flight.

    Order is deliberately NOT asserted here: ``on_row`` records the true
    execution sequence (that is its documented contract at the sequential
    seam too), so under concurrency it legitimately fires in completion order.
    What must hold is the multiset -- one call per row, no duplicates, no
    drops, and no torn writes from two threads appending at once.
    """
    rows = [_row(i) for i in range(6)]
    runner = _SleepingRunner(per_row_delay={0: 0.2, 1: 0.15, 2: 0.1})
    seen: list[int] = []
    lock = threading.Lock()

    def _on_row(outcome):
        with lock:
            seen.append(outcome.row_index)

    execute_design(
        rows, runner=runner, response_spec=_response_spec(), invariants=[],
        factors=_factor(), max_parallel=4, on_row=_on_row,
    )

    assert sorted(seen) == list(range(6)), seen


def test_a_crashed_row_under_concurrency_fails_only_itself_in_position():
    """The failure taxonomy is unchanged by the bound.

    A runner exception fails ONE row without aborting the sweep (spec §6.4),
    and the failed row must still land in its own position -- a concurrent loop
    that dropped a raised call would shorten the list and shift every later
    finalist's replicate by one.
    """
    rows = [_row(i) for i in range(4)]

    class _Boom(_SleepingRunner):
        def __call__(self, row: ConfigRow) -> dict:
            if row.row_index == 1:
                raise RuntimeError("target crashed")
            return super().__call__(row)

    outcomes = execute_design(
        rows, runner=_Boom(delay=0.05), response_spec=_response_spec(),
        invariants=[], factors=_factor(), max_parallel=4,
    )

    assert [o.row_index for o in outcomes] == [0, 1, 2, 3]
    assert outcomes[1].status == "failed"
    assert "target crashed" in outcomes[1].error
    assert [o.status for o in outcomes] == [
        "complete", "failed", "complete", "complete",
    ]


# --- 3. the default is byte-identical to today -----------------------------

def test_default_max_parallel_is_sequential_and_identical_to_today():
    """(c) Default 1 must be exactly today's behaviour.

    ``design_matrix.json`` is a pre-registration; execution conditions that
    changed underneath an already-registered design would mean the artifact no
    longer describes the runs it registered. So an omitted field, an explicit
    1, and the pre-field call signature must all produce the same outcomes AND
    the same strictly-sequential execution -- peak in-flight 1, submission
    order equal to row order, completion order equal to submission order.
    """
    rows = [_row(i) for i in range(5)]

    def _run(**kw):
        runner = _SleepingRunner(delay=0.01)
        outcomes = execute_design(
            rows, runner=runner, response_spec=_response_spec(),
            invariants=[], factors=_factor(), **kw,
        )
        return runner, outcomes

    omitted_runner, omitted = _run()
    explicit_runner, explicit = _run(max_parallel=1)

    for runner in (omitted_runner, explicit_runner):
        assert runner.peak == 1, f"peak {runner.peak}: default is not sequential"
        assert runner.submission_order == list(range(5))
        assert runner.completion_order == list(range(5))

    def _shape(outs):
        return [(o.row_index, o.status, o.response, o.error) for o in outs]

    assert _shape(omitted) == _shape(explicit)


# --- 4. the spending stages stay sequential --------------------------------

class _PeakTracker:
    """Wraps the synthetic surface runner and records peak concurrency PER
    DESIGN KIND, read off the matrix each stage wrote.

    Keying on the artifact's own ``kind`` rather than on an iteration number is
    deliberate: which iteration index a stage lands on depends on the policy's
    schedule (a foldover branch, a second confirm round), so a test that hardcodes
    "iteration 3 is confirm" is asserting the schedule, not the concurrency. The
    matrix says ``shortlist_replicate`` for a confirm round and ``full`` /
    ``fractional`` for a spending stage, which is exactly the distinction under
    test.
    """

    def __init__(self, surface, *, seed: int, delay: float = 0.03, **inner_kw):
        from orchestrator.optimize.synthetic import make_synthetic_runner

        # Delegates to the REAL factory with whatever the harness would have
        # passed (notably ``seed_env``, which is what makes the synthetic target
        # a model of a seeded one and the common-random-numbers pairing real
        # rather than decorative). A tracker that dropped it would silently turn
        # the confirm round it measures into an unpaired one.
        self._inner = make_synthetic_runner(surface, seed=seed, **inner_kw)
        self._delay = delay
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak = 0
        self.calls = 0

    def __call__(self, row):
        with self._lock:
            self._in_flight += 1
            self.calls += 1
            self.peak = max(self.peak, self._in_flight)
        try:
            time.sleep(self._delay)
            return self._inner(row)
        finally:
            with self._lock:
                self._in_flight -= 1


def _run_tracked(surface, *, seed: int, parent_dir: Path, overrides: dict,
                 monkeypatch):
    """``run_synthetic_campaign``, unchanged, with its runner wrapped.

    The harness is driven AS IS rather than reimplemented: its own docstring
    records that omitting the engine's ``DONE -> DESIGN`` advance between
    iterations makes ``_enter_phase("DESIGN")`` return False from iteration 2
    onward, which silently skips ``write_design_matrix`` for every later stage --
    measured, on four iteration directories with no matrix in any of them. A test
    that reproduced the loop by hand would reproduce that bug, and this test reads
    exactly the artifact that would go missing. So the tracker is injected by
    wrapping the runner factory the harness calls, leaving the harness's control
    flow the production one.
    """
    from orchestrator.optimize import harness as harness_mod

    holder: dict = {}

    def _factory(surf, *, seed: int, **kw):
        holder["tracker"] = _PeakTracker(surf, seed=seed, **kw)
        return holder["tracker"]

    monkeypatch.setattr(harness_mod, "make_synthetic_runner", _factory)
    res = harness_mod.run_synthetic_campaign(
        surface, seed=seed, parent_dir=parent_dir, campaign_overrides=overrides,
    )
    return res.work_dir, holder["tracker"]


def _matrices_by_kind(work_dir: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in (work_dir / "runs").glob("iter-*/design_matrix.json"):
        dm = json.loads(path.read_text())
        out.setdefault(dm["kind"], []).append(dm)
    return out


def test_screen_rows_stay_sequential_even_at_high_max_parallel(
    tmp_path: Path, monkeypatch,
):
    """(d) The exclusion, which is the whole statistical point.

    Screen / foldover / refine FIT A SURFACE over distinct configurations, so a
    row's measured response must not depend on which other rows were beside it
    on the machine -- co-scheduling would load contention asymmetrically onto
    whichever configurations happened to be paired, and the fitted coefficients
    would absorb it as a factor effect. So a campaign declaring
    ``max_parallel: 4`` must still record 1 on every spending matrix.

    Driven through the REAL stage runner rather than ``execute_design``
    directly: the claim is about which stage the bound reaches, and only the
    stage runner decides that.
    """
    from orchestrator.optimize.synthetic import SURFACES

    work_dir, tracker = _run_tracked(
        SURFACES["additive"](), seed=31, parent_dir=tmp_path,
        monkeypatch=monkeypatch,
        overrides={
            "max_parallel": 4,
            "stages": ["verify", "screen"],
            "design": {"screen": {"resolution": 5, "center_points": 4}},
        },
    )

    by_kind = _matrices_by_kind(work_dir)
    spending = [
        dm for kind, ms in by_kind.items()
        if kind != "shortlist_replicate" for dm in ms
    ]
    assert spending, f"no spending matrix was written: {sorted(by_kind)}"
    for dm in spending:
        assert dm["max_parallel"] == 1, (
            f"a {dm['kind']} matrix recorded max_parallel={dm['max_parallel']}; "
            f"a spending stage must record the concurrency it ACTUALLY ran at, "
            f"not the campaign's declared ceiling"
        )
    assert "shortlist_replicate" not in by_kind, (
        "this campaign declared no confirm stage, so any observed concurrency "
        "must have come from a spending stage"
    )
    assert tracker.calls > 1, "the screen sweep ran no rows"
    assert tracker.peak == 1, (
        f"a spending stage ran {tracker.peak} rows concurrently; screen / "
        f"foldover / refine must stay strictly sequential regardless of "
        f"max_parallel, because contention distributed unevenly across a design "
        f"is absorbed by the fitted coefficients as a factor effect"
    )


def test_confirm_records_and_uses_the_declared_concurrency(
    tmp_path: Path, monkeypatch,
):
    """The counterpart: at confirm the declared bound is the effective one.

    Confirm-only stage list, so any concurrency the tracker sees is confirm's.
    """
    from orchestrator.optimize.synthetic import SURFACES

    work_dir, tracker = _run_tracked(
        SURFACES["additive"](), seed=32, parent_dir=tmp_path,
        monkeypatch=monkeypatch,
        overrides={
            "max_parallel": 3,
            "stages": ["verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "confirm": {"replicates": 3, "shortlist_size": 3}},
        },
    )

    by_kind = _matrices_by_kind(work_dir)
    confirms = by_kind.get("shortlist_replicate") or []
    assert confirms, f"no confirm matrix was written: {sorted(by_kind)}"
    for dm in confirms:
        assert dm["max_parallel"] == 3, dm.get("max_parallel")
    for kind, ms in by_kind.items():
        if kind != "shortlist_replicate":
            for dm in ms:
                assert dm["max_parallel"] == 1, (kind, dm["max_parallel"])

    assert tracker.peak > 1, (
        f"peak in-flight was {tracker.peak}: the declared bound never took "
        f"effect at confirm"
    )
    assert tracker.peak <= 3, (
        f"peak in-flight {tracker.peak} exceeded the declared bound of 3"
    )

    # The paired-differences bound is what the ordering guarantee protects; it
    # must still be computable from a concurrently measured round.
    conf = None
    for path in (work_dir / "runs").glob("iter-*/confirmation.json"):
        conf = json.loads(path.read_text())
    assert conf and conf["finalists"], conf


def test_concurrency_is_bounded_within_a_replicate_block_not_across_blocks():
    """Blocks are a barrier: every finalist is measured once before any twice.

    That is the property ``_confirm_rows``' per-block shuffle exists to
    preserve -- a drifting machine then shifts all the finalists together
    instead of loading the drift onto whichever one was scheduled late. A
    concurrent implementation that dissolved the block boundary and kept the
    pool full across it would let replicate 2 of finalist A start before
    replicate 1 of finalist C, restoring exactly that confound. Note the bound
    here (8) is deliberately WIDER than a block (3), so a pool that ignored the
    boundary would have room to pull the next block forward and would be caught.

    Observable: record the replicate index at CALL and RETURN time, then walk
    the log asserting no call from block *i+1* started before every call from
    block *i* had returned. The last row of each block is the slowest, so a
    boundary-crossing pool would have visibly started block *i+1* early.
    """
    rows = []
    for rep in range(3):
        for finalist in range(3):
            rows.append(_row(len(rows), replicate=rep))

    events: list[tuple[str, int]] = []
    lock = threading.Lock()
    by_pos = {r.row_index: r.replicate for r in rows}

    def _blocky(row: ConfigRow) -> dict:
        rep = by_pos[row.row_index]
        with lock:
            events.append(("start", rep))
        # Make the LAST row of each block the slowest, so a pool that kept
        # itself full across the boundary would demonstrably pull the next
        # block's work forward while this one was still running.
        time.sleep(0.12 if row.row_index % 3 == 2 else 0.02)
        with lock:
            events.append(("end", rep))
        return {"throughput": float(10 + row.row_index),
                "telemetry": {"L1": row.levels["L1"]}}

    outcomes = execute_design(
        rows, runner=_blocky, response_spec=_response_spec(), invariants=[],
        factors=_factor(), max_parallel=8,
    )

    assert [o.row_index for o in outcomes] == list(range(9))

    # Walk the event log: at any "start" of replicate r, no OTHER replicate may
    # still be in flight, and no later replicate may have started yet.
    in_flight: dict[int, int] = {}
    started: set[int] = set()
    for kind, rep in events:
        if kind == "start":
            live = {r for r, n in in_flight.items() if n > 0}
            assert live <= {rep}, (
                f"replicate {rep} started while block(s) {sorted(live)} were "
                f"still in flight: the block barrier was dissolved"
            )
            assert not {r for r in started if r > rep}, (
                f"replicate {rep} started after a LATER block {sorted(started)}"
            )
            started.add(rep)
            in_flight[rep] = in_flight.get(rep, 0) + 1
        else:
            in_flight[rep] -= 1
    assert started == {0, 1, 2}, started
    # And the blocks really were internally concurrent, or the barrier claim is
    # vacuous: 9 rows with three 0.12s tails is ~0.36s concurrent vs ~0.48s
    # serial, so assert the observed overlap directly instead.
    assert max(
        len([1 for k, _ in events[:i] if k == "start"])
        - len([1 for k, _ in events[:i] if k == "end"])
        for i in range(len(events) + 1)
    ) > 1, "no two rows inside a block ever overlapped"


# --- 5. the effective value is on the pre-registration --------------------

def test_the_effective_concurrency_is_recorded_in_the_design_matrix(
    tmp_path: Path,
):
    """(e) Beside ``run_order_seed``, and for the same reason.

    A pre-registration that claims randomized run order while executing
    concurrently is asserting a guarantee it did not provide -- the same defect
    class as the run-order bug at ``stage_runner.py:2063``, where the artifact
    recorded a randomization that never happened. Recording the EFFECTIVE value
    (1 at a spending stage even when the campaign declared 4) is what makes the
    two readable together.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=21, parent_dir=tmp_path,
        campaign_overrides={
            "max_parallel": 2,
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    matrices = sorted(
        (res.work_dir / "runs").glob("iter-*/design_matrix.json"),
        key=lambda p: int(p.parent.name.split("-")[1]),
    )
    assert matrices, "no design matrix was written"
    for path in matrices:
        dm = json.loads(path.read_text())
        assert "max_parallel" in dm, f"{path} omits max_parallel"
        expected = 2 if dm["kind"] == "shortlist_replicate" else 1
        assert dm["max_parallel"] == expected, (
            f"{path.parent.name} ({dm['kind']}) recorded "
            f"{dm['max_parallel']}, expected {expected}"
        )


def test_the_default_concurrency_is_recorded_too(tmp_path: Path):
    """Recorded even when the campaign said nothing, on the ``run_timeout_sec``
    convention: "the author did not choose" and "the author chose 1" produce
    the same runs, and a reader should not need to know which release wrote it.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=22, parent_dir=tmp_path,
        campaign_overrides={
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    for path in (res.work_dir / "runs").glob("iter-*/design_matrix.json"):
        dm = json.loads(path.read_text())
        assert dm["max_parallel"] == 1, path


def test_an_enriched_design_matrix_still_validates_against_its_schema(
    tmp_path: Path,
):
    """``additionalProperties: false`` is what makes the artifact a record
    rather than a bag, so a field added to it has to be declared there.

    Scoped to the SPENDING matrices. A confirm round's matrix has never
    validated against this schema on any revision -- it carries ``finalists``,
    ``round`` and ``kind: "shortlist_replicate"``, none of which the schema
    declares (verified against a clean tree: iter-N/design_matrix.json for a
    confirm round fails with "Additional properties are not allowed
    ('finalists', 'round' were unexpected)"). That drift predates
    ``max_parallel`` and fixing it is a separate change; asserting on it here
    would make this file fail for a reason it is not about. What this test DOES
    establish is the claim that matters for the new field: it is declared, so
    adding it did not turn a previously valid matrix invalid.
    """
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=23, parent_dir=tmp_path,
        campaign_overrides={
            "max_parallel": 2,
            "workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite",
                                  "center_points": 4},
                       "confirm": {"replicates": 3}},
        },
    )
    schema = json.loads(DM_SCHEMA_PATH.read_text())
    checked = 0
    for path in (res.work_dir / "runs").glob("iter-*/design_matrix.json"):
        dm = json.loads(path.read_text())
        if dm["kind"] == "shortlist_replicate":
            # Still assert the FIELD is schema-legal in isolation, since that is
            # the part this change is responsible for.
            jsonschema.validate(
                dm["max_parallel"], schema["properties"]["max_parallel"],
            )
            continue
        jsonschema.validate(dm, schema)
        checked += 1
    assert checked, "no spending matrix was written"


# --- 6. the schema's own guard rails --------------------------------------

@pytest.mark.parametrize("bad", [0, -1, -4, 1.5, "4", None, True])
def test_schema_rejects_a_non_positive_integer_bound(tmp_path: Path, bad):
    """(f) 0 and negatives are not a schedule, they are a stall; a float or a
    string is a type error at the semaphore, i.e. after the pre-registration
    was already hashed. ``True`` is rejected because ``isinstance(True, int)``
    would otherwise smuggle a boolean in as a bound of 1.
    """
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    campaign = _campaign(tmp_path, max_parallel=bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(campaign, schema)


def test_schema_accepts_a_positive_integer_bound(tmp_path: Path):
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    jsonschema.validate(_campaign(tmp_path, max_parallel=4), schema)
    jsonschema.validate(_campaign(tmp_path, max_parallel=1), schema)
    jsonschema.validate(_campaign(tmp_path), schema)  # absent is legal


def test_execute_design_rejects_a_bound_below_one():
    """The runtime seam refuses what the schema would have caught, because a
    hand-edited campaign or an internal caller can reach here without one.
    """
    rows = [_row(0)]
    with pytest.raises(ValueError):
        execute_design(
            rows, runner=_SleepingRunner(delay=0.0),
            response_spec=_response_spec(), invariants=[], factors=_factor(),
            max_parallel=0,
        )


# --- 7. the oversubscription warning --------------------------------------

def test_oversubscribing_the_cpus_warns_and_does_not_error(tmp_path: Path):
    """(g) A WARNING, never an error.

    Oversubscription reintroduces exactly the contention the block structure
    exists to keep symmetric: more in-flight runs than cores means the runs
    time-slice against each other, and a finalist's measured response starts
    depending on the scheduler. But the author may legitimately know their
    target is I/O-bound (a run that mostly waits on a remote service uses no
    core while it waits), so refusing the value would be wrong -- and the
    validator cannot see which.
    """
    import os as _os

    from orchestrator.validate import validate_optimization_campaign

    cpus = _os.cpu_count() or 1
    campaign = _campaign(tmp_path, max_parallel=cpus * 4)
    issues = validate_optimization_campaign(campaign)
    warns = [i for i in issues if "max_parallel" in i]
    assert warns, issues
    assert all(w.startswith("WARN:") for w in warns), warns
    assert any(str(cpus) in w for w in warns), (
        "the warning must name the CPU count it compared against"
    )

    errors = [i for i in issues if not i.startswith("WARN:")]
    assert not errors, errors


def test_a_bound_within_the_cpu_count_does_not_warn(tmp_path: Path):
    import os as _os

    from orchestrator.validate import validate_optimization_campaign

    cpus = _os.cpu_count() or 1
    for value in {1, max(1, cpus // 2), cpus}:
        campaign = _campaign(tmp_path, max_parallel=value)
        assert not [i for i in validate_optimization_campaign(campaign)
                    if "max_parallel" in i], value
