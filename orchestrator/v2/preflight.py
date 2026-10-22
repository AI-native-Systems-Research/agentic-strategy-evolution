"""Nous v2 preflight check (spec 3.5, B4).

Runs at campaign start to verify hooks and validators work correctly
before spending any tokens.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .validators import validate_artifact, ValidatorContext

logger = logging.getLogger(__name__)

# ── Known-good fixtures for each artifact type ───────────────────────────

_HYP_TEMPLATE = {
    "role": "main", "family": "f1", "mechanism": "m",
    "prediction": {"metric": "x", "direction": "increase"},
    "control": "baseline", "falsified_if": "x <= baseline", "claim_ids": ["c1"],
}
_GOOD_BASELINE = {
    "task_type": "optimize", "command": "run.sh", "git_sha": "a1b2c3d",
    "observation": {"score": 42}, "metrics_path": "metrics.json",
    "noise": {"deterministic": True},
}
_BAD_BASELINE = {"task_type": "optimize"}
_GOOD_BUNDLE = {"hypotheses": [
    {"id": "h1", **_HYP_TEMPLATE},
    {"id": "h2", **_HYP_TEMPLATE, "role": "alt", "family": "f2", "mechanism": "m2"},
]}
_BAD_BUNDLE = {"hypotheses": []}


def _check_validators(work_dir: Path) -> list[str]:
    """Run validators on good and bad fixtures; return errors."""
    errors: list[str] = []
    ctx = ValidatorContext(work_dir=work_dir)

    # Good fixtures must pass
    for name, fixture in [("baseline", _GOOD_BASELINE), ("bundle", _GOOD_BUNDLE)]:
        result = validate_artifact(name, fixture, ctx)
        if result:
            errors.append(f"preflight: validator {name!r} rejected known-good fixture: {result}")

    # Bad fixtures must fail
    for name, fixture in [("baseline", _BAD_BASELINE), ("bundle", _BAD_BUNDLE)]:
        result = validate_artifact(name, fixture, ctx)
        if not result:
            errors.append(f"preflight: validator {name!r} accepted known-bad fixture")

    return errors


async def _check_stop_hook(hooks: dict[str, list]) -> list[str]:
    """Run the Stop hook on a fake input to verify it works."""
    errors: list[str] = []
    stop_matchers = hooks.get("Stop", [])
    if not stop_matchers:
        errors.append("preflight: no Stop hook registered")
        return errors

    fake_input = {"stop_reason": "end_turn"}
    for matcher in stop_matchers:
        for cb in matcher.hooks:
            try:
                result = await cb(fake_input, None, {"signal": None})
                if not isinstance(result, dict):
                    errors.append(f"preflight: Stop hook returned {type(result).__name__}, expected dict")
            except Exception as exc:
                errors.append(f"preflight: Stop hook raised {type(exc).__name__}: {exc}")

    return errors


async def run_preflight(
    hooks: dict[str, list],
    *,
    work_dir: Path,
    override_schema_check: Callable[[], list[str]] | None = None,
) -> list[str]:
    """Run all preflight checks. Returns list of errors (empty = pass)."""
    errors: list[str] = []

    if override_schema_check is not None:
        errors.extend(override_schema_check())
    else:
        errors.extend(_check_validators(work_dir))

    try:
        hook_errors = await _check_stop_hook(hooks)
        errors.extend(hook_errors)
    except Exception as exc:
        errors.append(f"preflight: Stop hook check failed: {exc}")

    return errors
