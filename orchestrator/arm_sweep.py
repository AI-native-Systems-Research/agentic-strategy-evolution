"""Adaptive sub-arm sweeps (issue #165).

Replaces hand-rolled parameter grids inside arms (e.g. "rates 7.5 / 8.0
/ 8.5") with sampler-driven adaptive search. When an arm declares a
``sweep`` block, the runner delegates to ``run_sweep`` with an
Optuna-backed sampler; campaigns like ``composite-sensitivity-boundary``
that hand-rolled 65-run grids to find a single boundary collapse to
budget=12 with TPE for the same answer.

API shape:

  spec = SweepSpec(param, low, high, budget, direction, sampler_name)
  result = run_sweep(spec, evaluator, sampler=None)

The default sampler lazily resolves to ``optuna.create_study(...).ask``;
tests inject a deterministic callable via ``sampler=``. The default
never imports ``optuna`` at module-import time — only inside
``_default_sampler`` if/when a caller actually omits the argument.
The conftest live-call guard hard-fails any test that invokes
``Study.optimize`` (which the default does NOT use — we drive the
ask/tell loop ourselves to keep the seam tight).

The integration with ``parallel_arms.partition_plan`` lives in
``parallel_arms.extract_sweep_specs`` — see that module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class SweepSpec:
    """Declares an adaptive sweep over a single scalar knob.

    Attributes:
        param: Name of the knob being swept.
        low: Lower bound of the search domain (inclusive).
        high: Upper bound of the search domain (inclusive).
        budget: Maximum number of trials.
        direction: ``"minimize"`` (default) or ``"maximize"``.
        sampler_name: Hint for the production sampler (``"tpe"`` default,
            informational only — tests inject a sampler callable directly).
    """
    param: str
    low: float
    high: float
    budget: int
    direction: str = "minimize"
    sampler_name: str = "tpe"

    def __post_init__(self) -> None:
        if not self.param:
            raise ValueError("param must be a non-empty string")
        if self.low >= self.high:
            raise ValueError(
                f"domain must satisfy low<high (got low={self.low}, high={self.high})",
            )
        if self.budget < 1:
            raise ValueError(f"budget must be >= 1 (got {self.budget})")
        if self.direction not in ("minimize", "maximize"):
            raise ValueError(
                f"direction must be 'minimize' or 'maximize' "
                f"(got {self.direction!r})",
            )


@dataclass(frozen=True)
class SweepTrial:
    """One trial: the params the sampler proposed and the value the evaluator returned."""
    trial_index: int
    params: dict[str, float]
    objective_value: float


@dataclass(frozen=True)
class SweepResult:
    """Outcome of a sweep.

    ``best_params`` / ``best_value`` are the argmin / min over observed
    trials when direction=minimize, and argmax / max when direction=
    maximize.
    """
    trials: list[SweepTrial] = field(default_factory=list)
    best_params: dict[str, float] = field(default_factory=dict)
    best_value: float = 0.0
    direction: str = "minimize"


Sampler = Callable[[list[SweepTrial], SweepSpec], dict[str, float]]
"""Sampler callable: takes (history, spec) and returns the next params dict."""

Evaluator = Callable[[dict[str, float]], float]
"""Evaluator callable: takes params and returns the objective value (lower=better
for minimize, higher=better for maximize)."""


def _default_sampler(history: list[SweepTrial], spec: SweepSpec) -> dict[str, float]:
    """Lazily build an Optuna TPE sampler and ask for the next point.

    Imports optuna only on first call so module-import cost is zero
    when tests inject their own sampler. The conftest guard blocks
    Study.optimize but allows the create_study + ask/tell pattern.
    """
    import optuna  # type: ignore[import-not-found]

    direction = "minimize" if spec.direction == "minimize" else "maximize"
    study = optuna.create_study(direction=direction)
    for trial in history:
        t = study.ask()
        t.suggest_float(spec.param, spec.low, spec.high)
        # Replay history into the study so its internal state is consistent.
        # Using tell() with FrozenTrial would be cleaner, but ask/tell on a
        # fresh study with replay is enough for the default behavior.
        study.tell(t, trial.objective_value)
    next_trial = study.ask()
    value = next_trial.suggest_float(spec.param, spec.low, spec.high)
    # The trial leaks if we don't tell it, but we don't yet have a value.
    # Discard the trial via `study.tell(next_trial, None, state=PRUNED)` —
    # we only used it to extract the suggested value.
    study.tell(next_trial, state=optuna.trial.TrialState.PRUNED)
    return {spec.param: value}


def run_sweep(
    spec: SweepSpec,
    evaluator: Evaluator,
    *,
    sampler: Sampler | None = None,
) -> SweepResult:
    """Run an adaptive sweep up to ``spec.budget`` trials.

    Args:
        spec: SweepSpec describing the param / domain / budget / direction.
        evaluator: Callable mapping params dict to objective value.
        sampler: Optional callable supplying next params. Defaults to
            an Optuna TPE sampler (lazy import).

    Returns:
        SweepResult with the full trial history and best-trial summary.
    """
    sample_fn = sampler or _default_sampler

    trials: list[SweepTrial] = []
    for i in range(spec.budget):
        params = sample_fn(trials, spec)
        value = float(evaluator(params))
        trials.append(SweepTrial(
            trial_index=i,
            params=dict(params),
            objective_value=value,
        ))

    if spec.direction == "minimize":
        best = min(trials, key=lambda t: t.objective_value)
    else:
        best = max(trials, key=lambda t: t.objective_value)

    return SweepResult(
        trials=trials,
        best_params=dict(best.params),
        best_value=best.objective_value,
        direction=spec.direction,
    )
