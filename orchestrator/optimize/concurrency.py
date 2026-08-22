"""Parallel spending stages: the isolation that makes them safe, and the
evidence that decides their width.

An 18-row screen at 5-90 minutes a row is 2 to 5+ hours of wall clock on a
machine that is mostly idle, and reducing that is the point of this module. It
does it by separating three things the original confirm-only exclusion had
fused together.

    1. ISOLATION -- can two concurrent rows corrupt each other?
    2. CONTENTION -- can two concurrent rows perturb each other's MEASUREMENT?
    3. CPU AFFINITY -- can two concurrent rows be prevented from sharing a core?

(1) is portable, cheap, and by far the most important; it is a correctness
property and it is now enforced unconditionally (``run_isolation``). (2) is a
statistical property that depends on the TARGET, and it is settled by
measurement or by an explicit declaration rather than by blanket serialization.
(3) is Linux-only and, as argued at the bottom of this docstring, would not buy
what it appears to -- so it gates nothing here.

THE CONTENTION ARGUMENT, WHICH IS CORRECT AND IS WHY A GATE EXISTS AT ALL. The
spending stages (``screen`` / ``foldover`` / ``refine``) fit a response surface
over DISTINCT configurations. Co-scheduled rows contend for machine resources, so
a row's measured response comes to depend on which other rows happened to run
beside it. Contention lands UNEVENLY across a design -- a slow corner runs beside
different neighbours than a fast one -- and the fitted coefficients absorb that
unevenness as though it were a factor effect. Run-order randomization does not
help: a permutation spreads a TIME trend (a warming cache, a throttling machine)
across the design, and this is a NEIGHBOUR effect, which no permutation of the
same rows can average away. For an objective that measures where a system
SATURATES, contention is the measurement rather than noise around it.

But that argument is about LOAD-DEPENDENT objectives, and it is not true of
every target. A solver's iteration count, a compiler's output size, a
bit-identical correctness check, a discrete-event simulator's simulated latency:
none of these is a function of how busy the machine was. Penalising every
campaign for a property only some targets have is what shipped nothing before.

SO THE WIDTH RESTS ON A RECORDED BASIS, one of ``BASES``, and the campaign gets
real parallelism in the common cases:

  ``confirm_block``   -- a confirm replicate block. Every finalist is measured
                         exactly once per block, so contention is SYMMETRIC
                         across exactly the things being compared and cancels
                         out of the finalist-to-finalist difference terminal
                         discrimination reads. Unchanged, unconditional, and
                         already correct before this module existed.
  ``load_independent`` -- the campaign DECLARED the objective is not a function
                         of machine load. No measurement, full width. See the
                         argument for this hatch below.
  ``contention_floor`` -- MEASURED: the objective at the design's most
                         contention-sensitive corner moved less under
                         concurrency than the target's own serial noise floor.
                         Certified AT A WIDTH; a floor measured at 2 does not
                         license 8.
  ``serial``          -- width 1. No co-scheduling. What an unmeasured,
                         undeclared, load-dependent target gets.

WHY THE FLOOR IS MEASURED AT THE DESIGN'S EXTREME CORNER, NOT AT THE BASELINE.
This is the one place the obvious design is unsound, and it was caught by
simulating a saturating objective before it was built. Take a soft-knee
throughput ``load*cap/(load+cap)``, let co-scheduling steal 10% of capacity, and
let the target's serial noise be 2% (so a 2x-noise gate admits inflation under
4%):

    baseline corner (light load)    inflation  1.00%   PASSES a 4% gate
    mid corner                      inflation  5.26%   fails
    saturating corner (heavy load)  inflation  9.17%   fails

A floor measured at ``known_valid_baseline`` -- which is the cheap, light,
obvious corner, and the one ``--liveness`` already re-runs -- would therefore
CERTIFY the very design whose interesting corners it gets wrong by 9%. That is
not conservatism, it is the specific failure of measuring bias at the wrong
operating point: contention inflation grows with load, and the corners a
response-surface campaign cares about are the loaded ones. So
``contention_probe_levels`` measures at the corner the author names as the
heaviest, and defaults to refusing to certify rather than probing the baseline.

WHY A DECLARATION HATCH (``load_independent``) IS OFFERED, having declined the
CPU-pinning one. Both are author assertions, so the distinction needs stating.
A pinning record would assert a MECHANISM Nous supposedly applied -- "these
cores were disjoint" -- and would be false on its face for a shared GPU or
memory bus, i.e. Nous would be testifying to something untrue. A
``load_independent`` declaration asserts a property of the AUTHOR'S OWN TARGET
that only the author can know and that is usually structural and easy to be
right about ("my objective is an iteration count"). Nous records it as a claim
attributed to the author, not as a measurement it made. It is also cheaply
falsifiable: ``falsify_load_independence`` re-reads the rows the stage already
measured and flags a declaration that the data contradicts, for free and with no
extra runs. An author who declares it falsely gets a confounded surface, and the
artifact says whose claim it was.

WHY CPU PINNING IS NOT A BASIS. A disjoint cpu set partitions CPU time slices
and per-core L1/L2, and leaves shared: L3/LLC, memory bandwidth and controllers,
disk queue depth, page cache, NIC queues, thermal/turbo budget, and the GPU. Two
channels closed, seven open. Every worked example in ``examples/optimization/``
maximizes a throughput or minimizes a tail latency -- ``tokens_per_s`` on a
shared GPU, ``qps`` against a shared page cache, ``p99_latency_ms`` through a
shared network stack -- so pinning would isolate almost nothing those objectives
read while an artifact recording ``cpus: [0,1,2]`` per row testified to an
isolation the measurement never had. That is declined on the merits; it is
independent of ``os.sched_setaffinity`` being Linux-only, and no width here
depends on it.

Nothing in this module makes a next-state decision and nothing calls a model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Recorded in ``design_matrix.json`` as ``concurrency_basis``. A closed
#: vocabulary, on the same principle as the compiled policy's observation keys:
#: a reader must be able to enumerate every reason an epoch's rows were
#: co-scheduled.
BASIS_SERIAL = "serial"
BASIS_CONFIRM_BLOCK = "confirm_block"
BASIS_LOAD_INDEPENDENT = "load_independent"
BASIS_CONTENTION_FLOOR = "contention_floor"

BASES = (
    BASIS_SERIAL,
    BASIS_CONFIRM_BLOCK,
    BASIS_LOAD_INDEPENDENT,
    BASIS_CONTENTION_FLOOR,
)

#: Default width when a campaign declares a basis but no explicit
#: ``max_parallel``. Two cores are left for the orchestrator, the OS, and the
#: author's own shell, and the cap of 4 is not arbitrary: the field campaign's
#: own adapter spawned 4 concurrent subprocess probes INSIDE each row, so 4 rows
#: meant 16 processes on a 10-CPU box. Nous cannot see an adapter's internal
#: width, so the default stays modest and the author raises it knowing their own
#: fan-out. See ``docs/optimization-campaign-guide.md``.
DEFAULT_WIDTH_CAP = 4

#: Reserved cores, excluded from the default width for the reason above.
RESERVED_CPUS = 2

#: Multiple of the serial noise floor that concurrency-induced inflation must
#: stay under to certify a width. Same 2x convention ``--liveness`` uses to call
#: a factor "not demonstrably live", and for the same reason: an effect smaller
#: than twice the target's own run-to-run variation is not distinguishable from
#: it with a handful of samples.
NOISE_MULTIPLE = 2.0


class ConcurrencyDeclarationError(ValueError):
    """A campaign's concurrency declaration cannot be honoured as written.

    Raised at VALIDATION time, so the author learns before the campaign spends
    anything. The two silent alternatives are both defects of a different order:
    silently running at 1 when the author asked for 8 costs a day of wall clock
    and hides why, and silently running 8 uncertified corrupts the surface.
    """


@dataclass(frozen=True)
class Verdict:
    """The effective width, the reason for it, and the width it was certified at.

    ``width`` is the ceiling on in-flight runs; ``basis`` is from ``BASES``.
    ``certified_width`` is the width at which the evidence was obtained -- equal
    to ``width`` for a measured basis, and ``None`` when no measurement was
    involved (``serial``, ``confirm_block``, ``load_independent``). It exists
    because a contention floor measured at 2 does not license 8: the whole point
    of recording the basis is that a reader can check the evidence covers the
    schedule that ran.
    """

    width: int
    basis: str
    certified_width: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.basis not in BASES:
            raise ValueError(
                f"concurrency basis {self.basis!r} is not one of {BASES}: the "
                f"vocabulary is closed so a reader of design_matrix.json can "
                f"enumerate every reason an epoch's rows were co-scheduled.",
            )
        if self.width < 1:
            raise ValueError(
                f"concurrency width must be >= 1, got {self.width!r}: a bound "
                f"below one is not a schedule, it is a stall.",
            )
        if self.certified_width is not None and self.width > self.certified_width:
            raise ValueError(
                f"width {self.width} exceeds the width {self.certified_width} "
                f"the evidence was obtained at. A contention floor measured at "
                f"one width says nothing about a wider one -- inflation grows "
                f"with the number of neighbours -- so this is refused rather "
                f"than extrapolated.",
            )


def cpu_ceiling() -> int:
    """CPUs on the machine that will run the epoch; 1 when the platform is mute."""
    return os.cpu_count() or 1


def default_width() -> int:
    """The width a campaign gets when it declares a basis but no number.

    ``min(DEFAULT_WIDTH_CAP, cpu_count - RESERVED_CPUS)``, floored at 1. Modest
    on purpose: an adapter's OWN internal fan-out multiplies this, and Nous
    cannot see it.
    """
    return max(1, min(DEFAULT_WIDTH_CAP, cpu_ceiling() - RESERVED_CPUS))


def _block(opt: dict | None) -> dict:
    block = (opt or {}).get("concurrency")
    return block if isinstance(block, dict) else {}


def declared_width(opt: dict | None) -> int:
    """``optimization.max_parallel`` as declared, else the default for the basis.

    A campaign declaring a spending-stage basis but no explicit number gets
    ``default_width()`` rather than 1 -- the reframe's point: an author who says
    "my objective is an iteration count" should get a materially faster campaign
    without also having to pick a thread count. A campaign declaring NEITHER
    still resolves to 1 through ``resolve``, so nothing changes for the
    campaigns authored before this existed.

    A hand-edited non-integer resolves as absent rather than raising -- the same
    convention ``resolve_run_timeout`` uses, and for the same reason: turning an
    unschema-able campaign file into an abort at the measurement seam would
    attribute the failure to the wrong place.
    """
    raw = (opt or {}).get("max_parallel")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if _block(opt):
        return default_width()
    return 1


def declared_load_independent(opt: dict | None) -> bool:
    """Whether the author claims the objective is not a function of machine load."""
    return _block(opt).get("load_independent") is True


def contention_probe_levels(opt: dict | None) -> dict | None:
    """The corner the contention floor is measured at, if the author named one.

    Explicitly authored rather than derived, and deliberately NOT defaulted to
    ``known_valid_baseline``: see this module's docstring for the simulation
    showing a baseline-corner floor certifying a design it gets wrong by 9% at
    the corner that saturates. The author knows which corner loads their system
    hardest; Nous cannot infer it from levels alone.
    """
    levels = _block(opt).get("contention_probe_levels")
    return dict(levels) if isinstance(levels, dict) and levels else None


def resolve(opt: dict | None, *, stage_name: str, confirm_stage: str,
            measured: "Verdict | None" = None) -> Verdict:
    """The effective width and its basis for one stage.

    Ordering matters:

    * ``confirm`` gets the declared width on the replicate-block symmetry
      argument -- unconditional, consulting no measurement, because that
      argument does not depend on the objective's provenance and the confirm
      path was already correct. Regressing it is not on the table.
    * A spending stage with ``load_independent`` gets the declared width, capped
      at the machine's CPUs.
    * A spending stage with a MEASURED floor gets the narrower of the declared
      width and the width the floor was certified at -- never wider than the
      evidence.
    * Everything else is serial.
    """
    width = declared_width(opt)
    if stage_name == confirm_stage:
        return Verdict(width=width, basis=BASIS_CONFIRM_BLOCK)
    if declared_load_independent(opt):
        capped = max(1, min(width, cpu_ceiling()))
        return Verdict(
            width=capped, basis=BASIS_LOAD_INDEPENDENT,
            detail=(
                "the campaign declares optimization.concurrency."
                "load_independent: the objective is asserted by the AUTHOR not "
                "to be a function of machine load, so no contention floor was "
                "measured"
            ),
        )
    if measured is not None and measured.basis == BASIS_CONTENTION_FLOOR:
        allowed = max(1, min(width, measured.certified_width or 1))
        return Verdict(
            width=allowed, basis=BASIS_CONTENTION_FLOOR,
            certified_width=measured.certified_width, detail=measured.detail,
        )
    return Verdict(width=1, basis=BASIS_SERIAL,
                   detail=measured.detail if measured else "")


def check_declaration(opt: dict | None) -> list[str]:
    """Validation-time problems with a declared ``concurrency`` block.

    Called from ``validate_optimization_campaign``, so the author learns before
    spending. Fails CLOSED and ACTIONABLY -- every message names the edit or the
    command that fixes it, because "silently ran at 1" is the outcome that
    wastes a day and explains nothing.
    """
    problems: list[str] = []
    raw_block = (opt or {}).get("concurrency")
    if raw_block is None:
        return problems
    if not isinstance(raw_block, dict):
        return [
            "optimization.concurrency must be a mapping with "
            "load_independent and/or contention_probe_levels.",
        ]

    load_ind = declared_load_independent(opt)
    probe = contention_probe_levels(opt)
    width = declared_width(opt)

    if not load_ind and probe is None:
        problems.append(
            "optimization.concurrency declares neither load_independent nor "
            "contention_probe_levels, so it licenses no spending-stage "
            "concurrency and the epoch will run serially. Either set "
            "load_independent: true (asserting the objective is not a function "
            "of machine load -- an iteration count, an output size, a "
            "simulated time), or name contention_probe_levels: the design's "
            "most heavily loaded corner, where the floor will be measured.",
        )
    if load_ind and probe is not None:
        problems.append(
            "optimization.concurrency declares BOTH load_independent and "
            "contention_probe_levels. Drop one: load_independent asserts no "
            "measurement is needed, so measuring a floor as well records two "
            "different bases for one width and leaves a reader unable to tell "
            "which the rows rested on.",
        )
    cpus = cpu_ceiling()
    if width > cpus:
        problems.append(
            f"optimization.max_parallel={width} exceeds this machine's {cpus} "
            f"CPU(s) under optimization.concurrency. Refused rather than warned "
            f"about (as it is for confirm, where a run that mostly WAITS on a "
            f"remote service holds no core): more in-flight runs than cores "
            f"means the runs time-slice, which is contention that grows with "
            f"width and lands unevenly across the design. Lower it to at most "
            f"{cpus} (the default when max_parallel is omitted is "
            f"{default_width()}). Note the count is this machine's; if the "
            f"campaign runs elsewhere, compare against that host's cores.",
        )
    return problems


def measure_contention_floor(
    probe, *, width: int, metric: str, repeats: int = 3,
) -> Verdict:
    """Measure the serial noise floor, then the objective at ``width``.

    ``probe`` is an injected callable ``(width) -> list[float]`` returning the
    objective from that many co-scheduled runs of the SAME configuration -- the
    contention-probe corner. Injected rather than built here so this has one
    seam and the caller owns what a run means.

    The criterion: mean objective at ``width`` must differ from the serial mean
    by less than ``NOISE_MULTIPLE`` times the serial noise floor's own spread.
    If it does, contention at that width is not distinguishable from the
    target's own run-to-run variation, which is evidence -- for THIS target, at
    THIS width, at THIS corner -- rather than an assumption. The returned
    Verdict carries ``certified_width`` so no caller can widen past the
    evidence.

    Every failure mode -- too few samples, a raising probe, a non-numeric
    response, a zero-mean objective, inflation over the threshold -- returns a
    ``serial`` Verdict. That direction is deliberate: an unmeasurable target and
    a refuted one both fall back to the behaviour that needs no license.
    """
    if width < 2:
        return Verdict(width=1, basis=BASIS_SERIAL, detail=(
            f"a contention floor needs a width of at least 2 to co-schedule "
            f"anything, got {width}"
        ))
    reps = max(2, int(repeats or 2))
    try:
        serial_samples = []
        for _ in range(reps):
            vals = probe(1)
            serial_samples.extend(float(v) for v in _numeric(vals, metric))
    except (TypeError, ValueError) as exc:
        return Verdict(width=1, basis=BASIS_SERIAL,
                       detail=f"serial probe produced no usable objective: {exc}")
    except Exception as exc:
        return Verdict(width=1, basis=BASIS_SERIAL,
                       detail=f"serial probe raised {type(exc).__name__}: {exc}")
    if len(serial_samples) < 2:
        return Verdict(width=1, basis=BASIS_SERIAL, detail=(
            "fewer than 2 serial samples: a noise floor cannot be estimated "
            "from one run, and a floor of zero would certify every width"
        ))

    mean_s = sum(serial_samples) / len(serial_samples)
    var = sum((s - mean_s) ** 2 for s in serial_samples) / (len(serial_samples) - 1)
    sd = var ** 0.5
    if not mean_s:
        return Verdict(width=1, basis=BASIS_SERIAL, detail=(
            "the serial objective mean is 0, so relative inflation is "
            "undefined and no floor can be certified"
        ))
    try:
        conc_samples = [float(v) for v in _numeric(probe(width), metric)]
    except (TypeError, ValueError) as exc:
        return Verdict(width=1, basis=BASIS_SERIAL,
                       detail=f"concurrent probe produced no usable objective: {exc}")
    except Exception as exc:
        return Verdict(width=1, basis=BASIS_SERIAL,
                       detail=f"concurrent probe raised {type(exc).__name__}: {exc}")
    if not conc_samples:
        return Verdict(width=1, basis=BASIS_SERIAL, detail=(
            f"the concurrent probe at width {width} produced no measurements"
        ))

    mean_c = sum(conc_samples) / len(conc_samples)
    inflation = abs(mean_c - mean_s) / abs(mean_s)
    noise = abs(sd / mean_s)
    threshold = NOISE_MULTIPLE * noise
    detail = (
        f"{metric}: serial mean {mean_s:.6g} (sd {sd:.6g}, CV {noise * 100:.2f}%) "
        f"over {len(serial_samples)} run(s); at width {width} mean {mean_c:.6g} "
        f"over {len(conc_samples)} run(s); inflation {inflation * 100:.2f}% vs "
        f"threshold {NOISE_MULTIPLE:g} x CV = {threshold * 100:.2f}%"
    )
    # STRICTLY greater, not `>=`, and the boundary case is why. A perfectly
    # repeatable objective (sd == 0) has a zero noise floor and therefore a zero
    # threshold, and it is the STRONGEST evidence of load-independence available:
    # the objective did not move by one float bit under co-scheduling. A `>=`
    # comparison refused exactly that target, inverting the gate at its most
    # certain point -- a real bug this module's tests caught. Equality passes;
    # any real movement above a zero floor is a positive inflation and still
    # fails, so a zero noise floor stays maximally STRICT rather than permissive
    # -- it demands exact agreement, which is the bit-identity check.
    if inflation > threshold:
        return Verdict(width=1, basis=BASIS_SERIAL, detail=(
            f"{detail} -- REFUTED: co-scheduling moved the objective by more "
            f"than the target's own run-to-run variation, so a concurrent row's "
            f"response depends on its neighbours and the fit would absorb that "
            f"as a factor effect. The stage runs serially."
        ))
    return Verdict(
        width=width, basis=BASIS_CONTENTION_FLOOR, certified_width=width,
        detail=f"{detail} -- CERTIFIED at width {width}",
    )


def _numeric(vals, metric: str) -> list[float]:
    """Coerce a probe's return into a list of floats, or raise ValueError."""
    seq = vals if isinstance(vals, (list, tuple)) else [vals]
    out: list[float] = []
    for v in seq:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"non-numeric {metric!r}: {v!r}")
        out.append(float(v))
    if not out:
        raise ValueError(f"no {metric!r} measurements")
    return out


def falsify_load_independence(runs: list[dict], *, metric: str) -> str | None:
    """Contradict a ``load_independent`` claim from rows already measured. Free.

    A declaration is an author assertion Nous cannot verify up front without
    spending runs it was trying to save. But it IS falsifiable afterwards at zero
    cost, from ``runs.jsonl``: if two rows carrying IDENTICAL factor levels and
    THE SAME RECORDED WORKLOAD SEED reported different objectives, the objective
    is a function of something other than the configuration -- machine load being
    the candidate the declaration ruled out.

    A RECORDED SEED IS REQUIRED, and this is the check's load-bearing
    precondition rather than a detail. Without ``optimization.workload.seed_env``
    no row carries a seed, so "identical levels" does NOT imply "identical
    workload draw" -- and a legitimately stochastic target's CENTER POINTS
    (replicated rows at the same levels, which a screen design adds on purpose to
    estimate pure error) differ for reasons that have nothing to do with
    co-scheduling. Comparing them would report every seeded-noise campaign as
    contradicting its own declaration, which is a false positive on the common
    case and would train an author to ignore the warning. So rows whose seed is
    absent are SKIPPED: this check can only ever fire where a seed genuinely
    pinned the draw and the objective moved anyway.

    Returns a warning string, or ``None`` when nothing contradicts the claim.
    Deliberately a REPORT rather than an abort: replicated identical rows with a
    shared seed are not guaranteed to exist at all, so absence of evidence is
    common and is not evidence of a violation; and by the time these rows exist
    the runs are already spent, so aborting would destroy the data that proves
    the problem instead of surfacing it. The author needs to know for the NEXT
    epoch.
    """
    groups: dict[tuple, list[float]] = {}
    for row in runs or []:
        if row.get("status") != "complete":
            continue
        resp = row.get("response") or {}
        val = resp.get(metric)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        seed = row.get("workload_seed")
        if seed is None:
            # No recorded seed: identical levels do not imply an identical
            # workload draw, so a difference here is not attributable. See the
            # docstring -- this is what keeps a stochastic target's center
            # points from reading as a refuted declaration.
            continue
        levels = row.get("levels") or {}
        key = (tuple(sorted((str(k), str(v)) for k, v in levels.items())), seed)
        groups.setdefault(key, []).append(float(val))
    for key, vals in groups.items():
        if len(vals) < 2:
            continue
        if len(set(vals)) > 1:
            lo, hi = min(vals), max(vals)
            spread = (hi - lo) / abs(hi) if hi else float("inf")
            return (
                f"optimization.concurrency.load_independent is declared, but "
                f"rows with identical levels and the same workload seed "
                f"reported different {metric}: {sorted(vals)!r} (spread "
                f"{spread * 100:.2f}%). A load-INDEPENDENT objective is a "
                f"function of the configuration alone, so identical "
                f"configurations must report identical values. Either the "
                f"objective does depend on machine load -- in which case the "
                f"declaration is wrong and this epoch's concurrent rows carry a "
                f"neighbour effect the fit absorbed as a factor effect -- or the "
                f"target has an unseeded source of randomness that "
                f"workload.seed_env does not reach. Re-run the next epoch with "
                f"contention_probe_levels instead of load_independent."
            )
    return None


def run_isolation(cwd, *, row_index: int, slot: int | None = None) -> dict[str, str]:
    """Per-run scratch paths exported to the adapter. Portable, unconditional.

    THE DEFECT THIS CLOSES, and it is a correctness one rather than a
    statistical one. Nous exported no per-run directory, so every row ran with
    the same ``cwd`` and no unique path to write into. In the field campaign the
    worst near-miss was two rows sharing one ``go build -o`` output path:
    plausible numbers produced from the wrong binary, with nothing in any
    artifact to show it. ``config_patch`` already materialises a per-run copy of
    every patched config file (under a fresh ``uuid4`` subdirectory), so the
    INPUT side was already isolated; this is the output side.

    Three variables, all pointing into one per-row directory:

      ``NOUS_RUN_DIR``   -- a private, existing, writable directory for this row.
      ``NOUS_ROW_INDEX`` -- the row's index, for a name the adapter derives.
      ``NOUS_RUN_SLOT``  -- which concurrency slot the row occupies, or 0.

    An adapter that writes its build output, metrics file, or temp data under
    ``NOUS_RUN_DIR`` cannot collide with a co-scheduled sibling. Nous cannot
    force it to -- an adapter that hardcodes a shared path still collides -- so
    this is a facility plus a documented contract (``docs/targets.md``), not a
    guarantee Nous can enforce alone. It is exported at EVERY width, including
    1, so the same adapter code path runs serially and concurrently; a variable
    that only appeared above width 1 would make concurrency the first thing to
    exercise it.
    """
    from pathlib import Path

    root = Path(cwd) / f"row-{int(row_index)}"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "NOUS_RUN_DIR": str(root),
        "NOUS_ROW_INDEX": str(int(row_index)),
        "NOUS_RUN_SLOT": str(int(slot or 0)),
    }
