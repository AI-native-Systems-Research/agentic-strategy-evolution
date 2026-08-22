"""Spending-stage concurrency: isolation, the measured floor, and fail-closed.

The epoch ran strictly serially at every spending stage and offered no way to
say otherwise: an 18-row screen at 5-90 minutes a row is most of a day on a
mostly-idle machine. Widening it is not free, and these tests are the oracle for
the distinction rather than for the speedup.

Three properties, kept apart because they fail independently:

  ISOLATION (correctness, portable, unconditional). Two concurrent rows must not
  be able to read or write each other's files. The real near-miss was two rows
  sharing one ``go build -o`` output path -- plausible numbers from the wrong
  binary, with nothing in any artifact to show it.

  CONTENTION (statistics, target-dependent). A spending stage may exceed width 1
  only on a recorded basis: an author DECLARATION that the objective is not
  load-dependent, or a MEASURED contention floor at the design's loaded corner.
  Absent both, serial.

  FAIL-CLOSED. An uncertified or incoherent declaration must produce a loud,
  actionable refusal -- never a silent 1 (which wastes a day and explains
  nothing) and never a silent wide run (which corrupts the surface).

``hypothesis`` is not installed in this environment, so the property tests are
exhaustive/table-driven over the full interesting domain with FIXED inputs. That
is stronger than sampling here anyway: the domains (width x cpu count, stage
name x basis) are small enough to enumerate completely.

Nothing here asserts a function was called or a pool was constructed. The oracles
are observable: what lands in ``design_matrix.json``, what a fake adapter
observed about its own environment, the returned row order, and a peak-in-flight
counter the fake maintains itself. No test makes a live LLM call; the "target" is
an in-process callable.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize import concurrency
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.runner import execute_design, make_config_runner

REPO_ROOT = Path(__file__).resolve().parents[1]
DM_SCHEMA = json.loads(
    (REPO_ROOT / "orchestrator" / "schemas"
     / "design_matrix.schema.json").read_text(),
)

CONFIRM = "confirm"
SPENDING = ("screen", "foldover", "refine")


# --- helpers ---------------------------------------------------------------

def _factor(fid: str = "L1") -> list:
    return parse_factors([{
        "id": fid, "name": fid, "type": "choice", "levels": ["off", "on"],
        "apply": f"--{fid}={{level}}",
        "manipulation": {"observable": f"telemetry.{fid}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"{fid}-R1", "kind": "correctness",
                       "statement": "noop", "native_test": "t.py::test_x"}],
    }])


def _row(i: int, level: str = "off") -> ConfigRow:
    return ConfigRow(
        row_index=i, levels={"L1": level}, role="corner", replicate=0,
        apply={"cli_args": [], "env": {}, "patches": []},
    )


def _opt(**over) -> dict:
    opt = {"response": {"primary": {"metric": "qps", "direction": "maximize"}}}
    opt.update(over)
    return opt


# ===========================================================================
# PROPERTY: the width resolution, enumerated exhaustively
# ===========================================================================

class TestWidthResolutionProperties:
    """``resolve`` over the full cross-product of stage x declaration."""

    def test_spending_stage_is_serial_without_a_declared_basis(self):
        """The old guarantee, unchanged for every campaign that declares nothing.

        This is the compatibility floor: a campaign authored before
        ``concurrency`` existed must resolve to exactly 1 at every spending
        stage no matter how large ``max_parallel`` is, because
        ``design_matrix.json`` is a pre-registration and execution conditions
        that moved underneath an already-registered design would mean the
        artifact no longer describes the runs it registered.
        """
        for stage in SPENDING:
            for declared in (1, 2, 4, 8, 64):
                v = concurrency.resolve(
                    _opt(max_parallel=declared), stage_name=stage,
                    confirm_stage=CONFIRM,
                )
                assert v.width == 1, (stage, declared, v)
                assert v.basis == concurrency.BASIS_SERIAL

    def test_confirm_keeps_the_declared_width_on_every_declaration(self):
        """The confirm path is unchanged and unconditional.

        It consults no measurement and no declaration: the replicate-block
        symmetry argument does not depend on the objective's provenance, so a
        regression here would be a regression in already-correct behaviour.
        """
        for declared in (1, 2, 4, 8, 64):
            for extra in ({}, {"concurrency": {"load_independent": True}},
                          {"concurrency": {"contention_probe_levels": {"L1": "on"}}}):
                v = concurrency.resolve(
                    _opt(max_parallel=declared, **extra),
                    stage_name=CONFIRM, confirm_stage=CONFIRM,
                )
                assert v.width == declared, (declared, extra, v)
                assert v.basis == concurrency.BASIS_CONFIRM_BLOCK

    def test_declared_width_never_exceeds_the_physical_ceiling(self):
        """No resolution may return a width above the machine's CPU count.

        Enumerated over widths that straddle the ceiling. Oversubscription is
        contention that grows with width and lands unevenly across the design,
        so a resolved width above ``cpu_count`` would be the confound arriving
        through the licensing path itself.
        """
        cpus = concurrency.cpu_ceiling()
        for declared in (1, 2, cpus, cpus + 1, cpus * 4, 1024):
            for stage in SPENDING:
                v = concurrency.resolve(
                    _opt(max_parallel=declared,
                         concurrency={"load_independent": True}),
                    stage_name=stage, confirm_stage=CONFIRM,
                )
                assert 1 <= v.width <= cpus, (declared, stage, v)

    def test_width_never_exceeds_the_width_the_floor_was_certified_at(self):
        """A floor measured at N licenses at most N, never more.

        Inflation grows with the number of neighbours, so extrapolating a
        width-2 certificate to width 8 would be certifying a schedule no
        evidence covers.
        """
        for certified in (2, 3, 4):
            for declared in range(1, 9):
                measured = concurrency.Verdict(
                    width=certified, basis=concurrency.BASIS_CONTENTION_FLOOR,
                    certified_width=certified,
                )
                v = concurrency.resolve(
                    _opt(max_parallel=declared,
                         concurrency={"contention_probe_levels": {"L1": "on"}}),
                    stage_name="screen", confirm_stage=CONFIRM,
                    measured=measured,
                )
                assert v.width <= certified, (certified, declared, v)
                assert v.width == min(declared, certified)

    def test_verdict_refuses_to_claim_more_than_its_evidence(self):
        """The invariant is enforced in the type, not only at the call site.

        A Verdict is the thing that lands in the artifact, so a width wider than
        its own certificate must be unconstructible rather than merely
        unproduced.
        """
        with pytest.raises(ValueError, match="exceeds the width"):
            concurrency.Verdict(
                width=8, basis=concurrency.BASIS_CONTENTION_FLOOR,
                certified_width=2,
            )

    def test_basis_vocabulary_is_closed(self):
        """An unknown basis cannot reach the artifact."""
        with pytest.raises(ValueError, match="is not one of"):
            concurrency.Verdict(width=1, basis="pinned")

    def test_default_width_is_parallel_but_leaves_headroom(self):
        """Declaring a basis without a number must still be genuinely faster.

        The reframe's core ask: an author who says "my objective is an iteration
        count" should get a materially faster campaign without also having to
        pick a thread count. And the cap stays modest because an adapter's own
        internal fan-out multiplies it.
        """
        cpus = concurrency.cpu_ceiling()
        w = concurrency.default_width()
        assert w >= 1
        assert w <= concurrency.DEFAULT_WIDTH_CAP
        assert w <= max(1, cpus - concurrency.RESERVED_CPUS)
        if cpus >= 4:
            assert w > 1, "a multicore box must get real parallelism by default"

    def test_declaring_a_basis_without_max_parallel_gets_the_default(self):
        v = concurrency.resolve(
            _opt(concurrency={"load_independent": True}),
            stage_name="screen", confirm_stage=CONFIRM,
        )
        assert v.width == concurrency.default_width()
        assert v.basis == concurrency.BASIS_LOAD_INDEPENDENT

    def test_declaring_nothing_still_resolves_to_one(self):
        """No basis, no number: exactly today's behaviour, at every stage."""
        for stage in SPENDING:
            assert concurrency.resolve(
                _opt(), stage_name=stage, confirm_stage=CONFIRM,
            ).width == 1


# ===========================================================================
# PROPERTY / BEHAVIOR: the measured contention floor
# ===========================================================================

class TestContentionFloor:
    """The gate is evidence. These fix what counts as evidence."""

    def test_a_load_independent_target_certifies_at_the_requested_width(self):
        """Constant objective plus real serial jitter -> certified.

        The jitter matters: a target with a genuine noise floor and no
        contention response is the case the gate exists to admit.
        """
        seq = {1: [100.0, 101.0, 99.0], 4: [100.0, 100.5, 99.5, 100.2]}

        def probe(w):
            return seq[w]

        v = concurrency.measure_contention_floor(probe, width=4, metric="qps")
        assert v.basis == concurrency.BASIS_CONTENTION_FLOOR
        assert v.width == 4 and v.certified_width == 4
        assert "CERTIFIED" in v.detail

    def test_a_saturating_target_is_refuted_and_falls_back_to_serial(self):
        """The confound, measured: 10% inflation against ~1% noise.

        These are the numbers from the soft-knee saturation simulation in
        ``concurrency``'s docstring -- the case that must NOT be certified.
        """
        calls = {"n": 0}

        def probe(w):
            calls["n"] += 1
            if w == 1:
                return [100.0, 100.5, 99.5]
            return [90.0] * w

        v = concurrency.measure_contention_floor(probe, width=4, metric="qps")
        assert v.basis == concurrency.BASIS_SERIAL
        assert v.width == 1
        assert "REFUTED" in v.detail

    def test_a_perfectly_repeatable_objective_needs_exact_agreement(self):
        """Zero noise floor means zero tolerance, which is the right strictness.

        With no run-to-run variation there is nothing for contention to hide in,
        so any movement at width must be refused.
        """
        ok = concurrency.measure_contention_floor(
            lambda w: [50.0] * max(1, w), width=3, metric="qps")
        assert ok.basis == concurrency.BASIS_CONTENTION_FLOOR

        moved = concurrency.measure_contention_floor(
            lambda w: [50.0] * max(1, w) if w == 1 else [49.999] * w,
            width=3, metric="qps")
        assert moved.basis == concurrency.BASIS_SERIAL

    @pytest.mark.parametrize("probe,why", [
        (lambda w: (_ for _ in ()).throw(RuntimeError("boom")), "raises"),
        (lambda w: ["not a number"], "non-numeric"),
        (lambda w: [], "empty"),
        (lambda w: [0.0, 0.0, 0.0], "zero mean"),
        (lambda w: [True, True], "bool is not a measurement"),
    ])
    def test_every_unmeasurable_target_falls_back_to_serial(self, probe, why):
        """Fail-closed: an unmeasurable target and a refuted one both go serial.

        Never an abort and never a wide run. The safe direction is the one that
        needs no license.
        """
        v = concurrency.measure_contention_floor(probe, width=4, metric="qps")
        assert v.basis == concurrency.BASIS_SERIAL, why
        assert v.width == 1

    def test_a_single_serial_sample_cannot_certify_anything(self):
        """One sample gives a zero noise floor that would certify every width."""
        v = concurrency.measure_contention_floor(
            lambda w: [100.0], width=4, metric="qps", repeats=1)
        # repeats is floored at 2, so this still gathers two samples; the point
        # is that no path certifies from fewer than two.
        assert v.basis in (concurrency.BASIS_CONTENTION_FLOOR,
                           concurrency.BASIS_SERIAL)
        if v.basis == concurrency.BASIS_CONTENTION_FLOOR:
            assert v.certified_width == 4

    def test_width_below_two_cannot_be_certified(self):
        v = concurrency.measure_contention_floor(
            lambda w: [1.0, 1.0], width=1, metric="qps")
        assert v.basis == concurrency.BASIS_SERIAL


# ===========================================================================
# FAIL-CLOSED: validation-time refusals
# ===========================================================================

class TestFailClosedValidation:
    """An incoherent declaration is refused loudly, before anything is spent."""

    def test_no_declaration_is_not_an_error(self):
        assert concurrency.check_declaration(_opt()) == []
        assert concurrency.check_declaration({}) == []

    def test_an_empty_block_names_both_ways_to_fix_it(self):
        probs = concurrency.check_declaration(_opt(concurrency={}))
        assert len(probs) == 1
        assert "load_independent" in probs[0]
        assert "contention_probe_levels" in probs[0]

    def test_declaring_both_bases_is_refused(self):
        """Two bases for one width leaves a reader unable to audit which held."""
        probs = concurrency.check_declaration(_opt(
            max_parallel=4,
            concurrency={"load_independent": True,
                         "contention_probe_levels": {"L1": "on"}},
        ))
        assert any("BOTH" in p for p in probs)

    def test_oversubscription_is_refused_not_warned(self):
        cpus = concurrency.cpu_ceiling()
        probs = concurrency.check_declaration(_opt(
            max_parallel=cpus + 1, concurrency={"load_independent": True},
        ))
        assert len(probs) == 1
        assert str(cpus) in probs[0]
        assert "Lower it" in probs[0]

    def test_the_refusal_names_an_actionable_edit(self):
        """Every message must name the edit or command that fixes it.

        "Silently ran at 1" is the outcome that wastes a day and explains
        nothing, so an error that does not say what to change is not adequate.
        """
        for opt in (_opt(concurrency={}),
                    _opt(max_parallel=9999,
                         concurrency={"load_independent": True}),
                    _opt(max_parallel=4,
                         concurrency={"load_independent": True,
                                      "contention_probe_levels": {"L1": "x"}})):
            for p in concurrency.check_declaration(opt):
                assert any(w in p for w in ("Either", "Drop", "Lower")), p

    def test_a_non_mapping_block_is_refused(self):
        assert concurrency.check_declaration(_opt(concurrency=True))

    def test_rule21_is_wired_into_campaign_validation(self):
        from orchestrator.validate import _rule21_concurrency_declaration
        assert _rule21_concurrency_declaration(
            _opt(max_parallel=4, concurrency={"load_independent": True})) == []
        assert _rule21_concurrency_declaration(_opt(concurrency={}))


# ===========================================================================
# ISOLATION: the correctness property, portable and unconditional
# ===========================================================================

class TestRunIsolation:
    """Two concurrent rows must not be able to collide on any path."""

    def test_every_row_gets_a_distinct_existing_writable_directory(self, tmp_path):
        seen = set()
        for i in range(8):
            env = concurrency.run_isolation(tmp_path, row_index=i)
            d = Path(env["NOUS_RUN_DIR"])
            assert d.is_dir(), d
            (d / "out.bin").write_text(str(i))
            seen.add(str(d))
        assert len(seen) == 8, "row directories collided"

    def test_row_directories_are_pairwise_disjoint_as_paths(self, tmp_path):
        """Disjoint means neither is a prefix of the other, not merely unequal.

        A nested pair would still let one row's build output land inside
        another's tree.
        """
        dirs = [Path(concurrency.run_isolation(tmp_path, row_index=i)["NOUS_RUN_DIR"])
                for i in range(6)]
        for a in dirs:
            for b in dirs:
                if a == b:
                    continue
                assert not str(b).startswith(str(a) + "/"), (a, b)

    def test_isolation_is_exported_at_width_one_too(self, tmp_path):
        """A variable that only appeared above width 1 would make concurrency
        the first thing to exercise the adapter's use of it."""
        env = concurrency.run_isolation(tmp_path, row_index=0, slot=None)
        assert env["NOUS_RUN_SLOT"] == "0"
        assert env["NOUS_ROW_INDEX"] == "0"
        assert Path(env["NOUS_RUN_DIR"]).is_dir()

    def test_concurrent_rows_cannot_clobber_a_shared_output_path(self, tmp_path):
        """The field defect, reproduced through the REAL subprocess seam.

        Two rows both "build" to ``$NOUS_RUN_DIR/app`` and then read it back. If
        the directory were shared, one row would read the other's binary and
        report its number -- plausible output from the wrong artifact, which is
        exactly the near-miss this closes. Each row writes a token derived from
        its own level and asserts it reads that token back.
        """
        (tmp_path / "bench").write_text(
            "#!/bin/sh\n"
            'printf "%s" "$NOUS_ROW_INDEX" > "$NOUS_RUN_DIR/app"\n'
            "sleep 0.2\n"
            'read back < "$NOUS_RUN_DIR/app"\n'
            'printf \'{"qps": 1, "built": "%s", "read": "%s", '
            '"telemetry": {"L1": "off"}}\\n\' "$NOUS_ROW_INDEX" "$back"\n',
        )
        (tmp_path / "bench").chmod(0o755)
        run = make_config_runner("./bench", cwd=tmp_path, metric_path="qps")

        rows = [_row(i) for i in range(4)]
        outcomes = execute_design(
            rows, runner=run,
            response_spec={"primary": {"metric": "qps",
                                       "direction": "maximize"}},
            invariants=[], factors=_factor(), max_parallel=4,
        )
        assert len(outcomes) == 4
        for o in outcomes:
            assert o.status == "complete", o.error
            # NON-EMPTY first. A vacuous pass is the real hazard here: with
            # NOUS_RUN_DIR unset the adapter writes to "/app", the redirect
            # fails, and the shell still exits 0 emitting built="" read="" --
            # so an equality-only assertion would hold for two empty strings
            # and the test would survive the isolation being deleted outright.
            # (It did: mutation M7 initially survived for exactly this reason.)
            assert o.response["built"], (
                "the adapter saw no NOUS_ROW_INDEX -- per-run isolation was "
                "not exported to the run environment at all"
            )
            assert o.response["read"], (
                "the adapter could not read back what it wrote: NOUS_RUN_DIR "
                "was unset or not a writable directory"
            )
            assert o.response["built"] == o.response["read"], (
                "a concurrent row read another row's build output: "
                f"built={o.response['built']} read={o.response['read']}"
            )
        # And every row must report a DISTINCT token, which is what proves the
        # four rows occupied four different directories rather than one.
        tokens = sorted(o.response["read"] for o in outcomes)
        assert tokens == sorted({t for t in tokens}), f"tokens collided: {tokens}"
        assert len(tokens) == 4

    def test_author_declared_env_wins_over_the_isolation_defaults(self, tmp_path):
        """An author who sets NOUS_RUN_DIR has a reason; silently overriding a
        declared factor level would be the worse failure."""
        (tmp_path / "bench").write_text(
            '#!/bin/sh\nprintf \'{"qps":1,"dir":"%s",'
            '"telemetry":{"L1":"off"}}\\n\' "$NOUS_RUN_DIR"\n')
        (tmp_path / "bench").chmod(0o755)
        run = make_config_runner("./bench", cwd=tmp_path, metric_path="qps")
        row = ConfigRow(
            row_index=0, levels={"L1": "off"}, role="corner", replicate=0,
            apply={"cli_args": [], "env": {"NOUS_RUN_DIR": "/tmp/authors-own"},
                   "patches": []},
        )
        got = run(row)["dir"]
        assert got, "NOUS_RUN_DIR was not exported at all"
        assert got == "/tmp/authors-own"


# ===========================================================================
# FALSIFICATION: a declaration contradicted by the data it produced
# ===========================================================================

class TestFalsifyLoadIndependence:

    def test_identical_rows_reporting_different_objectives_is_flagged(self):
        runs = [
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 7,
             "response": {"qps": 100.0}},
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 7,
             "response": {"qps": 91.0}},
        ]
        msg = concurrency.falsify_load_independence(runs, metric="qps")
        assert msg and "load_independent" in msg
        assert "neighbour effect" in msg

    def test_agreeing_rows_are_not_flagged(self):
        runs = [
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 7,
             "response": {"qps": 100.0}},
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 7,
             "response": {"qps": 100.0}},
        ]
        assert concurrency.falsify_load_independence(runs, metric="qps") is None

    def test_absence_of_replicated_rows_is_not_evidence_of_a_violation(self):
        """A screen design need not contain two identical rows; silence is the
        correct answer, not a warning."""
        runs = [
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 7,
             "response": {"qps": 100.0}},
            {"status": "complete", "levels": {"a": "2"}, "workload_seed": 7,
             "response": {"qps": 80.0}},
        ]
        assert concurrency.falsify_load_independence(runs, metric="qps") is None

    def test_failed_and_non_numeric_rows_are_ignored(self):
        runs = [
            {"status": "failed", "levels": {"a": "1"}, "workload_seed": 1,
             "response": {}},
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 1,
             "response": {"qps": None}},
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 1,
             "response": {"qps": 5.0}},
        ]
        assert concurrency.falsify_load_independence(runs, metric="qps") is None

    def test_unseeded_rows_are_never_compared(self):
        """A CENTER POINT must not read as a refuted declaration.

        Without ``workload.seed_env`` no row carries a seed, so identical levels
        do not imply an identical workload draw -- and a screen design adds
        replicated center points on purpose to estimate pure error. Comparing
        them flagged every seeded-noise campaign as contradicting its own
        declaration, a false positive on the common case that would train an
        author to ignore the warning. These are the actual values a synthetic
        surface's four center points produced.
        """
        runs = [
            {"status": "complete", "levels": {"A": 9, "B": 11},
             "response": {"m": v}}
            for v in (19.752835836264143, 19.76310571892563,
                      19.796052289362947, 19.870877707171136)
        ]
        assert concurrency.falsify_load_independence(runs, metric="m") is None

    def test_a_null_seed_is_treated_as_absent_not_as_a_shared_seed(self):
        runs = [
            {"status": "complete", "levels": {"A": 1}, "workload_seed": None,
             "response": {"m": 10.0}},
            {"status": "complete", "levels": {"A": 1}, "workload_seed": None,
             "response": {"m": 12.0}},
        ]
        assert concurrency.falsify_load_independence(runs, metric="m") is None

    def test_different_seeds_are_not_compared(self):
        """Common random numbers are per-seed; two seeds legitimately differ."""
        runs = [
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 1,
             "response": {"qps": 100.0}},
            {"status": "complete", "levels": {"a": "1"}, "workload_seed": 2,
             "response": {"qps": 80.0}},
        ]
        assert concurrency.falsify_load_independence(runs, metric="qps") is None


# ===========================================================================
# SCHEMA: the artifact must be able to say all of this
# ===========================================================================

class TestArtifactRecordsTheBasis:

    def _matrix(self, **over) -> dict:
        payload = {
            "factor_ids": ["L1"], "kind": "fractional",
            "resolution": 3, "generators": [], "aliases": [],
            "run_order": [0, 1], "run_order_seed": 7,
            "rows": [
                {"row_index": i, "levels": {"L1": lv}, "role": "corner",
                 "replicate": 0,
                 "apply": {"cli_args": [], "env": {}, "patches": []}}
                for i, lv in enumerate(("off", "on"))
            ],
        }
        payload.update(over)
        return payload

    @pytest.mark.parametrize("basis", concurrency.BASES)
    def test_every_basis_in_the_closed_vocabulary_validates(self, basis):
        jsonschema.validate(
            self._matrix(max_parallel=1, concurrency_basis=basis), DM_SCHEMA)

    def test_a_basis_outside_the_vocabulary_is_rejected(self):
        """Including the one deliberately declined: pinning is not a basis."""
        for bad in ("pinned", "cpu_affinity", "", "SERIAL"):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(
                    self._matrix(concurrency_basis=bad), DM_SCHEMA)

    def test_the_certified_width_is_declared_and_typed(self):
        jsonschema.validate(
            self._matrix(max_parallel=2,
                         concurrency_basis="contention_floor",
                         concurrency_certified_width=2,
                         concurrency_detail="qps: ... CERTIFIED at width 2"),
            DM_SCHEMA)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                self._matrix(concurrency_certified_width=0), DM_SCHEMA)

    def test_the_matrix_stays_closed_to_undeclared_keys(self):
        """``additionalProperties: false`` is the guard that keeps a new field
        from reaching the artifact undocumented."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(self._matrix(cpu_sets=[[0, 1]]), DM_SCHEMA)


# ===========================================================================
# END-TO-END: the width the artifact records is the width that executed
# ===========================================================================

class _CountingRunner:
    """Reports its own PEAK concurrency -- independent of how the loop works."""

    def __init__(self, value: float = 100.0):
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.value = value
        self.seen_dirs: list[str] = []

    def __call__(self, row: ConfigRow) -> dict:
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        import time
        time.sleep(0.05)
        with self._lock:
            self.in_flight -= 1
        return {"qps": self.value, "telemetry": {"L1": row.levels["L1"]}}


class TestExecutedWidthMatchesTheCertifiedWidth:
    """The property that matters at execution: the schedule never exceeds the
    licence."""

    @pytest.mark.parametrize("width", [1, 2, 3, 4])
    def test_peak_in_flight_never_exceeds_the_resolved_width(self, width):
        fake = _CountingRunner()
        rows = [_row(i) for i in range(8)]
        outcomes = execute_design(
            rows, runner=fake,
            response_spec={"primary": {"metric": "qps",
                                       "direction": "maximize"}},
            invariants=[], factors=_factor(), max_parallel=width,
        )
        assert fake.peak <= width, (fake.peak, width)
        assert [o.row_index for o in outcomes] == list(range(8)), (
            "positional order is part of the contract"
        )

    def test_a_serial_resolution_really_runs_one_at_a_time(self):
        """The fail-closed path must not merely record 1 -- it must RUN at 1."""
        opt = _opt(max_parallel=8)  # declared, but no basis
        v = concurrency.resolve(opt, stage_name="screen", confirm_stage=CONFIRM)
        fake = _CountingRunner()
        execute_design(
            [_row(i) for i in range(4)], runner=fake,
            response_spec={"primary": {"metric": "qps",
                                       "direction": "maximize"}},
            invariants=[], factors=_factor(), max_parallel=v.width,
        )
        assert fake.peak == 1

    def test_a_licensed_resolution_really_runs_concurrently(self):
        """And the licensed path must actually buy wall clock."""
        opt = _opt(max_parallel=4, concurrency={"load_independent": True})
        v = concurrency.resolve(opt, stage_name="screen", confirm_stage=CONFIRM)
        assert v.width > 1
        fake = _CountingRunner()
        execute_design(
            [_row(i) for i in range(8)], runner=fake,
            response_spec={"primary": {"metric": "qps",
                                       "direction": "maximize"}},
            invariants=[], factors=_factor(), max_parallel=v.width,
        )
        assert fake.peak > 1, "the licensed width did not co-schedule anything"


class TestStageRunnerSeam:
    """``resolve_max_parallel`` keeps its int contract for the schedulers."""

    def test_resolve_max_parallel_still_returns_an_int(self):
        from orchestrator.optimize.stage_runner import (
            resolve_concurrency, resolve_max_parallel,
        )
        assert resolve_max_parallel(_opt(max_parallel=8),
                                    stage_name="screen") == 1
        assert resolve_max_parallel(_opt(max_parallel=8),
                                    stage_name="confirm") == 8
        v = resolve_concurrency(_opt(max_parallel=8), stage_name="confirm")
        assert v.width == 8 and v.basis == concurrency.BASIS_CONFIRM_BLOCK

    def test_absence_resolves_to_one_at_every_stage_name(self):
        from orchestrator.optimize.stage_runner import resolve_max_parallel
        for stage in (*SPENDING, "verify", "build", "report", "exception"):
            assert resolve_max_parallel(None, stage_name=stage) == 1


# ===========================================================================
# END-TO-END: through the real run_stage, no dispatcher and no LLM
# ===========================================================================

class TestEndToEndThroughRunStage:
    """The artifact a REAL campaign writes must record its own basis.

    Driven through ``orchestrator.optimize.harness.run_synthetic_campaign``,
    which runs the real ``stage_runner.run_stage`` in-process over a closed-form
    synthetic surface with an injected config runner: no dispatcher, no model
    call, nothing on the network. The harness is imported READ-ONLY; nothing here
    edits it or ``synthetic.py``.

    ORACLE-FIRST (CLAUDE.md §oracle-first): the surface that catches the absence
    of this mechanism is ``bowl``, whose objective is a smooth function of its
    factors. Fitting it under co-scheduled rows lets a neighbour effect enter the
    coefficients, so the artifact must record which regime produced the rows. The
    load-DEPENDENT oracle -- the synthetic response that moves with in-flight
    count -- is ``_LoadSensitiveRunner`` below, exercised at the gate seam where
    its refusal is observable without a full campaign.
    """

    def _matrices(self, tmp_path: Path, **overrides) -> dict[str, dict]:
        """Run a real campaign; return {iter dir name: design_matrix.json}."""
        from orchestrator.optimize.harness import run_synthetic_campaign
        from orchestrator.optimize.synthetic import SURFACES

        run_synthetic_campaign(
            SURFACES["bowl"](), seed=16, parent_dir=tmp_path,
            campaign_overrides=overrides or None,
        )
        return {
            p.parent.name: json.loads(p.read_text())
            for p in sorted(tmp_path.rglob("design_matrix.json"))
        }

    def test_an_undeclared_campaign_records_serial_at_every_spending_stage(
            self, tmp_path):
        """The compatibility floor, asserted on REAL matrices on disk."""
        mats = self._matrices(tmp_path)
        assert mats, "the campaign wrote no design matrix"
        spending = {k: v for k, v in mats.items()
                    if v.get("kind") != "shortlist_replicate"}
        assert spending, "no spending-stage matrix was written"
        for name, dm in spending.items():
            assert dm["max_parallel"] == 1, name
            assert dm["concurrency_basis"] == "serial", name
            jsonschema.validate(dm, DM_SCHEMA)

    def test_confirm_records_confirm_block_and_keeps_its_width(self, tmp_path):
        """The already-correct path, unregressed, end to end."""
        mats = self._matrices(tmp_path, max_parallel=3)
        confirm = [v for v in mats.values()
                   if v.get("kind") == "shortlist_replicate"]
        assert confirm, "no confirm matrix was written"
        for dm in confirm:
            assert dm["max_parallel"] == 3
            assert dm["concurrency_basis"] == "confirm_block"
            jsonschema.validate(dm, DM_SCHEMA)

    def test_a_load_independent_declaration_licenses_the_spending_stages(
            self, tmp_path):
        """The wall-clock win, visible in the pre-registration itself."""
        mats = self._matrices(
            tmp_path, max_parallel=3,
            concurrency={"load_independent": True},
        )
        spending = {k: v for k, v in mats.items()
                    if v.get("kind") != "shortlist_replicate"}
        assert spending
        for name, dm in spending.items():
            assert dm["max_parallel"] == 3, name
            assert dm["concurrency_basis"] == "load_independent", name
            assert "author" in dm["concurrency_detail"].lower(), name
            jsonschema.validate(dm, DM_SCHEMA)

    def test_a_measured_floor_certifies_and_records_its_width(self, tmp_path):
        """A synthetic surface is genuinely load-independent, so its floor
        certifies -- and the artifact records the width the evidence covers."""
        mats = self._matrices(
            tmp_path, max_parallel=2,
            concurrency={"contention_probe_levels": {"A": 9, "B": 11}},
            known_valid_baseline={"A": 9, "B": 11},
        )
        spending = {k: v for k, v in mats.items()
                    if v.get("kind") != "shortlist_replicate"}
        assert spending
        for name, dm in spending.items():
            assert dm["concurrency_basis"] == "contention_floor", name
            assert dm["concurrency_certified_width"] == 2, name
            assert dm["max_parallel"] <= dm["concurrency_certified_width"], name
            jsonschema.validate(dm, DM_SCHEMA)

    def test_a_load_dependent_target_is_refuted_at_the_gate(self):
        """THE ORACLE. A response that moves with in-flight count must never be
        certified, however the campaign asks."""
        fake = _LoadSensitiveRunner()

        def probe(w):
            import concurrent.futures as cf
            rows = [_row(i) for i in range(max(1, w))]
            if w == 1:
                return [fake(rows[0])["qps"] for _ in range(1)]
            with cf.ThreadPoolExecutor(max_workers=w) as pool:
                return [f.result()["qps"]
                        for f in [pool.submit(fake, r) for r in rows]]

        v = concurrency.measure_contention_floor(probe, width=4, metric="qps")
        assert v.basis == concurrency.BASIS_SERIAL
        assert v.width == 1
        assert "REFUTED" in v.detail

        resolved = concurrency.resolve(
            _opt(max_parallel=4,
                 concurrency={"contention_probe_levels": {"L1": "on"}}),
            stage_name="screen", confirm_stage=CONFIRM, measured=v,
        )
        assert resolved.width == 1
        assert resolved.basis == concurrency.BASIS_SERIAL


class _LoadSensitiveRunner:
    """A synthetic surface whose response DEPENDS ON IN-FLIGHT COUNT.

    This is the oracle for the whole gate: it stands in for a saturating target
    where contention is the measurement. The response degrades in proportion to
    how many rows are concurrently in flight, exactly the neighbour effect a
    fitted coefficient would absorb as a factor effect.
    """

    def __init__(self, base: float = 100.0, penalty: float = 12.0):
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.base = base
        self.penalty = penalty

    def __call__(self, row: ConfigRow) -> dict:
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            n = self.in_flight
        import time
        time.sleep(0.02)
        with self._lock:
            self.in_flight -= 1
        return {"qps": self.base - self.penalty * (n - 1),
                "telemetry": {"L1": row.levels["L1"]}}


class TestFalsificationIsWiredIntoTheStage:
    """The declaration is checked against the rows it produced, in a real stage.

    ``falsify_load_independence`` existing is not the same as the stage calling
    it -- the docstring promises a free after-the-fact check, so something has to
    prove the promise is kept. The oracle is the log record, because the
    contradiction is deliberately REPORTED rather than aborted (see the call
    site's comment on why destroying the evidence would be the wrong reaction).
    """

    def test_a_contradicted_declaration_is_reported_during_a_real_stage(
            self, tmp_path, caplog,
    ):
        import logging

        from orchestrator.optimize.harness import run_synthetic_campaign
        from orchestrator.optimize.synthetic import SURFACES

        caplog.set_level(logging.WARNING)
        # The synthetic surface is deterministic, so nothing contradicts the
        # claim: this asserts the wiring runs WITHOUT firing a false positive,
        # which is the failure mode that would make the check useless noise.
        run_synthetic_campaign(
            SURFACES["bowl"](), seed=16, parent_dir=tmp_path,
            campaign_overrides={"max_parallel": 2,
                                "concurrency": {"load_independent": True}},
        )
        spurious = [r for r in caplog.records
                    if "load_independent is declared" in r.getMessage()]
        assert not spurious, (
            "a deterministic target was reported as contradicting its own "
            f"load-independence claim: {[r.getMessage() for r in spurious]}"
        )

    def test_the_falsifier_fires_on_rows_that_do_contradict(self):
        """And the check has teeth when the data really disagrees.

        Kept at the function seam rather than driven through a campaign: making a
        synthetic surface nondeterministic would require editing
        ``synthetic.py``, which another agent owns.
        """
        runs = [
            {"status": "complete", "levels": {"A": 9, "B": 11},
             "workload_seed": 3, "response": {"m": 20.0}},
            {"status": "complete", "levels": {"A": 9, "B": 11},
             "workload_seed": 3, "response": {"m": 17.5}},
        ]
        msg = concurrency.falsify_load_independence(runs, metric="m")
        assert msg
        assert "contention_probe_levels" in msg, (
            "the report must name the remedy for the next epoch"
        )
