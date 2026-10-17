"""Optimization campaign kind (``kind: optimization``).

Factorial / response-surface experimental design, as an alternative to the
reflective kind's sequential arm-based search. See
``docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md``
and ``docs/optimization-campaign-guide.md``.

This subpackage imports only the stdlib plus ``scipy.stats`` (already a
declared dependency). Do NOT add numpy / statsmodels / pandas / pyDOE3 /
hypothesis — property-testing frameworks belong to *target* repos, not to
the Nous harness.
"""
from __future__ import annotations

from orchestrator.optimize.stage import Stage
from orchestrator.optimize.stage_runner import (
    OptimizationAborted,
    StageOutcome,
    run_stage,
)

__all__ = ["OptimizationAborted", "Stage", "StageOutcome", "run_stage"]
