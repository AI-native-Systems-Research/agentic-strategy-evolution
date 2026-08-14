# `kind: optimization` Campaign Type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `kind: optimization` campaign type that solves optimization problems with factorial / response-surface experimental design instead of sequential one-factor-at-a-time search, cutting substantive LLM calls to ~3 per campaign while enforcing correctness in Python.

**Architecture:** A new `orchestrator/optimize/` subpackage owns factor parsing, design generation, matrix expansion, effect fitting, relation contracts, and the stage decision rule. `orchestrator/iteration.py` gains exactly one early delegation branch; no existing reflective code path is modified. Four stages (`verify` → `screen` → `refine` → `confirm`) map onto four normal Nous iterations, reusing the existing `Engine`, gates, ledger, and findings artifacts.

**Tech Stack:** Python 3.11+, stdlib only for design generation and effect estimation (`itertools`, `math`, `statistics`), `scipy.stats` for confidence intervals and the lack-of-fit F-test (already a declared dependency), `jsonschema` + `pyyaml` for validation, `pytest` for tests.

**Spec:** `docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md`

## Global Constraints

- **No live LLM calls in any test.** `tests/conftest.py` installs an autouse guard that strips API keys and blocks `api.anthropic.com` / `api.openai.com` / `api.litellm.ai`. If a test trips it, inject a fake at the dispatcher seam — never disable the guard. See root `CLAUDE.md`.
- **Behavioral tests only.** Assert what lands on disk, what schema-validates, and what the returned data says. Never assert "function X was called with Y", argv shape, or internal control flow. See `tests/CLAUDE.md`.
- **No new harness dependencies.** `orchestrator/optimize/` imports only the stdlib plus `scipy.stats` (already declared via `scipy>=1.11`). Do NOT add `numpy`, `statsmodels`, `pandas`, `pyDOE3`, or `hypothesis` to `pyproject.toml`. `numpy` is currently unused anywhere in `orchestrator/` — keep it that way. Property-testing frameworks (`hypothesis`, `rapid`, `proptest`) belong to *target* repos, never to Nous.
- **All float assertions use `math.isclose`, never `==`.** Verified: the closed-form effect estimator reproduces planted coefficients to within 8.9e-16, which fails `==`. Use `math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-12)`.
- **Reflective path must stay byte-identical in behavior.** A campaign with no `kind` field, or `kind: reflective`, must behave exactly as it does today. Task 12 is the regression gate for this.
- **`{level}` is the only interpolation token in the campaign spec.** Not `{value}`, not arbitrary templates.
- **Factor types are `numeric` and `choice` only.** The vocabulary `continuous` / `ordinal` / `categorical` was retired during design review; do not reintroduce it.
- **Test file naming:** flat `tests/test_<module>.py`, matching the existing 79-file layout.
- **Commit style:** conventional prefixes (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`). End every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Run the full suite before the final commit of each task:** `/opt/homebrew/bin/pytest -q`
  (expect ~1374 passed, 1 skipped as the pre-existing baseline). Note: pytest is
  NOT installed in the project venv — `.venv/bin/pytest` does not exist. Use the
  system binary for tests and `.venv/bin/python` for running Python directly.
  `numpy` IS importable via the venv (transitively through scipy), so the
  no-numpy rule cannot be enforced by import failure — verify it statically
  (AST import extraction, not grep: docstrings legitimately name the forbidden
  libraries as warnings).

## File Structure

**New — the subpackage:**

| File | Responsibility |
|---|---|
| `orchestrator/optimize/__init__.py` | Public API re-exports: `run_stage`, `StageOutcome`, `Stage` |
| `orchestrator/optimize/factors.py` | Parse/validate `factors`; `Factor` dataclass; coding to ±1; `grid` snapping |
| `orchestrator/optimize/design.py` | Full & fractional factorial generation; alias structure; central composite |
| `orchestrator/optimize/matrix.py` | Design matrix → concrete configs via `apply`; fidelity check vs `runs.jsonl` |
| `orchestrator/optimize/predicates.py` | Shared `{observable, op, value, when, when_not}` evaluation for manipulation / constraints / invariants |
| `orchestrator/optimize/effects.py` | Closed-form effect estimation, CIs, pure error, lack-of-fit F-test |
| `orchestrator/optimize/relations.py` | Relation contract checking; native-test verdict parsing |
| `orchestrator/optimize/stage.py` | Stage decision rule + escalation triggers |
| `orchestrator/optimize/artifacts.py` | Write `design_matrix.json` / `runs.jsonl` / `effects.json` / `relations.json`; project `findings.json` + `principle_updates.json` |
| `orchestrator/optimize/runner.py` | Tokenless per-config execution loop over an injected runner seam |

**New — schemas:**
`orchestrator/schemas/design_matrix.schema.json`, `effects.schema.json`, `relations.schema.json`, `runs_row.schema.json`

**New — docs:**
`docs/optimization-campaign-guide.md`

**Modified:**

| File | Change |
|---|---|
| `orchestrator/schemas/campaign.schema.yaml` | Add `kind`, `optimization` block |
| `orchestrator/validate.py` | Add `validate_optimization_campaign`, cross-field rules |
| `orchestrator/iteration.py:1106` | One delegation branch at the top of `run_iteration` |
| `orchestrator/iteration.py:1352` | Scope `format_tier_summary` to reflective kind |
| `orchestrator/cli.py:1072,1130` | `--auto-approve` becomes `default=None`; add `--interactive` |
| `orchestrator/campaign.py` | Resolve gate default from `kind` |
| `README.md`, `CLAUDE.md`, `docs/data-model.md` | Cross-link the new guide |

**Dependency order:** Tasks 1–2 (factors, predicates) are leaves. Task 3 (design) depends on 1. Task 4 (effects) depends on 1+3. Tasks 5–7 (matrix, relations, stage) depend on 1–4. Task 8 (artifacts) depends on 4+7. Task 9 (runner) depends on 5. Tasks 10–11 (schema, wiring) integrate. Task 12 is the regression gate. Task 13 is the guide.

---

### Task 1: Factor parsing, coding, and grid snapping

**Files:**
- Create: `orchestrator/optimize/__init__.py`, `orchestrator/optimize/factors.py`
- Test: `tests/test_optimize_factors.py`

**Interfaces produced** (later tasks depend on these exact names):
- `Factor` frozen dataclass: `id: str`, `name: str`, `type: str` (`"numeric"`|`"choice"`), `levels: tuple`, `grid: float | None`, `screen_levels: tuple`, `apply_spec: dict`, `manipulation: dict`, `relations: tuple[dict, ...]`
- `parse_factors(raw: list[dict]) -> list[Factor]` — `ValueError` with actionable message on bad input
- `screen_pair(f) -> tuple` — the two levels the screen uses (explicit `screen_levels`, else `(levels[0], levels[-1])`)
- `code_level(f, level) -> int` — `-1` low / `+1` high; `ValueError` if not in `screen_pair`
- `decode_coded(f, coded: float) -> object` — coded → real level, grid-snapped for `numeric`
- `snap_to_grid(value: float, grid: float | None) -> float`
- `is_refinable(f) -> bool` — `True` only for `numeric` with >2 levels

- [ ] **Step 1: Write the failing tests**

```python
"""Behavioral tests for optimization factor parsing (kind: optimization).

Asserts the parsed data, not internal calls. Float comparisons use
math.isclose — the closed-form arithmetic carries ~1e-16 representation
error and `==` would be flaky.
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.factors import (
    Factor,
    code_level,
    decode_coded,
    is_refinable,
    parse_factors,
    screen_pair,
    snap_to_grid,
)


def _numeric_raw(**over):
    raw = {
        "id": "L1", "name": "queue_count", "type": "numeric",
        "levels": [2, 4, 8, 16], "grid": 1,
        "apply": "--queues={level}",
        "manipulation": {"observable": "telemetry.queue_count",
                         "op": "==", "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "statement": "baseline reproduces baseline",
                       "native_test": "tests/prop_q.py::test_noop"}],
    }
    raw.update(over)
    return raw


def _choice_raw(**over):
    raw = {
        "id": "L5", "name": "batching", "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "B", "value": "{level}"},
        "manipulation": {"observable": "telemetry.mean_batch_size",
                         "op": ">", "value": 1, "when": "on"},
        "relations": [{"id": "R3", "kind": "correctness",
                       "statement": "off is byte-identical to baseline",
                       "native_test": "tests/prop_b.py::test_off_noop"}],
    }
    raw.update(over)
    return raw


def test_parses_numeric_and_choice_factors():
    fs = parse_factors([_numeric_raw(), _choice_raw()])
    assert [f.id for f in fs] == ["L1", "L5"]
    assert fs[0].type == "numeric" and fs[0].levels == (2, 4, 8, 16)
    assert fs[1].type == "choice" and fs[1].levels == ("off", "on")


def test_screen_pair_defaults_to_first_and_last():
    f = parse_factors([_numeric_raw()])[0]
    assert screen_pair(f) == (2, 16)


def test_explicit_screen_levels_override_the_extremes():
    f = parse_factors([_numeric_raw(screen_levels=[4, 8])])[0]
    assert screen_pair(f) == (4, 8)


def test_screen_levels_must_be_members_of_levels():
    with pytest.raises(ValueError, match="screen_levels"):
        parse_factors([_numeric_raw(screen_levels=[3, 16])])


def test_coding_maps_low_to_minus_one_and_high_to_plus_one():
    f = parse_factors([_numeric_raw()])[0]
    assert code_level(f, 2) == -1
    assert code_level(f, 16) == +1


def test_coding_rejects_a_level_outside_the_screen_pair():
    f = parse_factors([_numeric_raw()])[0]
    with pytest.raises(ValueError):
        code_level(f, 4)


def test_choice_factor_codes_by_position():
    f = parse_factors([_choice_raw()])[0]
    assert code_level(f, "off") == -1
    assert code_level(f, "on") == +1


@pytest.mark.parametrize("value,grid,want", [
    (4.7, 1, 5.0),
    (4.2, 1, 4.0),
    (6.3, 2, 6.0),
    (7.1, 2, 8.0),
    (0.0273, None, 0.0273),
])
def test_snap_to_grid(value, grid, want):
    assert math.isclose(snap_to_grid(value, grid), want, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_snaps_numeric_to_the_grid():
    f = parse_factors([_numeric_raw()])[0]
    # midpoint of the screen pair (2, 16) is 9; grid=1 keeps it integral
    assert math.isclose(decode_coded(f, 0.0), 9.0, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_without_grid_keeps_the_interpolated_value():
    f = parse_factors([_numeric_raw(levels=[0.75, 0.95], grid=None)])[0]
    assert math.isclose(decode_coded(f, 0.0), 0.85, rel_tol=1e-9, abs_tol=1e-12)


def test_decode_coded_on_choice_returns_a_declared_level():
    f = parse_factors([_choice_raw()])[0]
    assert decode_coded(f, -1) == "off"
    assert decode_coded(f, +1) == "on"


def test_only_multilevel_numeric_factors_are_refinable():
    numeric_multi = parse_factors([_numeric_raw()])[0]
    numeric_two = parse_factors([_numeric_raw(levels=[2, 16])])[0]
    choice = parse_factors([_choice_raw()])[0]
    assert is_refinable(numeric_multi) is True
    assert is_refinable(numeric_two) is False
    assert is_refinable(choice) is False


def test_retired_type_vocabulary_is_rejected_with_a_helpful_message():
    with pytest.raises(ValueError, match="numeric.*choice"):
        parse_factors([_numeric_raw(type="ordinal")])


def test_bare_string_apply_is_normalised_to_a_cli_flag_spec():
    f = parse_factors([_numeric_raw()])[0]
    assert f.apply_spec == {"kind": "cli_flag", "template": "--queues={level}"}


def test_fewer_than_two_levels_is_rejected():
    with pytest.raises(ValueError, match="at least 2"):
        parse_factors([_numeric_raw(levels=[4])])


def test_duplicate_factor_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        parse_factors([_numeric_raw(), _numeric_raw()])


def test_missing_correctness_relation_is_rejected():
    only_behavioral = [{"id": "R9", "kind": "behavioral", "statement": "monotone",
                        "native_test": "t.py::test_m"}]
    with pytest.raises(ValueError, match="correctness"):
        parse_factors([_numeric_raw(relations=only_behavioral)])


def test_missing_manipulation_is_rejected():
    raw = _numeric_raw()
    del raw["manipulation"]
    with pytest.raises(ValueError, match="manipulation"):
        parse_factors([raw])


def test_manipulation_with_both_when_and_when_not_is_rejected():
    bad = {"observable": "x", "op": "==", "value": 1, "when": "on", "when_not": "off"}
    with pytest.raises(ValueError, match="when"):
        parse_factors([_numeric_raw(manipulation=bad)])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_factors.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'orchestrator.optimize'`

- [ ] **Step 3: Create the package `__init__.py`**

```python
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
```

- [ ] **Step 4: Implement `factors.py`**

```python
"""Factor declaration parsing for optimization campaigns.

A factor is one knob the campaign varies. ``type`` answers a domain
question, not a statistics question: are values *between* the declared
levels runnable?

  * ``numeric`` — interpolation is meaningful (thresholds, ratios, counts).
    ``grid`` snaps a fitted optimum to a runnable step so ``confirm``
    never tries to run K=4.7.
  * ``choice`` — nothing lives between the levels (policies, mechanisms,
    on/off).

The retired vocabulary ``continuous`` / ``ordinal`` / ``categorical`` is
rejected with a pointer to the replacement: it made authors reason about
how fitting works, and the fitting question is fully determined by
``type`` + ``grid``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_TYPES = ("numeric", "choice")
_CMP_KEYS = frozenset({"observable", "metric", "op", "value", "when", "when_not"})


@dataclass(frozen=True)
class Factor:
    """One declared factor. Immutable so a parsed design can't drift."""

    id: str
    name: str
    type: str
    levels: tuple
    grid: float | None
    screen_levels: tuple
    apply_spec: dict
    manipulation: dict
    relations: tuple[dict, ...]


def _normalise_apply(raw: Any, factor_id: str) -> dict:
    """A bare string is CLI-flag shorthand: ``"--queues={level}"``."""
    if isinstance(raw, str):
        return {"kind": "cli_flag", "template": raw}
    if isinstance(raw, dict) and raw.get("kind"):
        return dict(raw)
    raise ValueError(
        f"factor {factor_id!r}: 'apply' must be a template string "
        f"(e.g. \"--queues={{level}}\") or a dict with a 'kind' of "
        f"cli_flag / env_var / config_patch; got {raw!r}",
    )


def _check_manipulation(man: Any, factor_id: str) -> dict:
    if not isinstance(man, dict) or not man:
        raise ValueError(
            f"factor {factor_id!r}: a 'manipulation' check is required — it is "
            f"how Nous verifies the lever actually engaged. Use "
            f"{{observable: <telemetry path>, op: '==', value: '{{level}}'}}.",
        )
    unknown = set(man) - _CMP_KEYS
    if unknown:
        raise ValueError(
            f"factor {factor_id!r}: manipulation has unknown key(s) "
            f"{sorted(unknown)}; allowed: {sorted(_CMP_KEYS)}",
        )
    if "when" in man and "when_not" in man:
        raise ValueError(
            f"factor {factor_id!r}: manipulation may set 'when' or 'when_not', "
            f"not both — they are complementary level guards.",
        )
    if not man.get("op"):
        raise ValueError(f"factor {factor_id!r}: manipulation needs an 'op'.")
    return dict(man)


def _check_relations(rels: Any, factor_id: str) -> tuple[dict, ...]:
    rels = list(rels or [])
    if not any(r.get("kind") == "correctness" for r in rels if isinstance(r, dict)):
        raise ValueError(
            f"factor {factor_id!r}: at least one relation with "
            f"kind: correctness is required. A 'behavioral' relation alone is "
            f"not enough — behavioral violations are recorded as findings and "
            f"never fail the campaign, so nothing would catch a broken lever.",
        )
    for r in rels:
        if r.get("kind") not in ("correctness", "behavioral"):
            raise ValueError(
                f"factor {factor_id!r}: relation {r.get('id')!r} has kind "
                f"{r.get('kind')!r}; must be 'correctness' or 'behavioral'.",
            )
        if not r.get("native_test"):
            raise ValueError(
                f"factor {factor_id!r}: relation {r.get('id')!r} needs a "
                f"'native_test' identifier — the test lives in the TARGET "
                f"repo's own test tree and runs under its own runner.",
            )
    return tuple(dict(r) for r in rels)


def parse_factors(raw: list[dict]) -> list[Factor]:
    """Parse and validate a campaign's ``optimization.factors`` list."""
    if not raw:
        raise ValueError("optimization.factors must declare at least one factor")

    out: list[Factor] = []
    seen: set[str] = set()
    for entry in raw:
        fid = str(entry.get("id") or "")
        if not fid:
            raise ValueError("every factor needs an 'id' (e.g. L1)")
        if fid in seen:
            raise ValueError(f"duplicate factor id {fid!r}")
        seen.add(fid)

        ftype = entry.get("type")
        if ftype not in VALID_TYPES:
            raise ValueError(
                f"factor {fid!r}: type must be 'numeric' or 'choice' (got "
                f"{ftype!r}). Ask: are values BETWEEN the declared levels "
                f"runnable? Yes -> numeric. No -> choice. The older "
                f"continuous/ordinal/categorical vocabulary was retired.",
            )

        levels = tuple(entry.get("levels") or ())
        if len(levels) < 2:
            raise ValueError(
                f"factor {fid!r}: 'levels' needs at least 2 entries "
                f"(got {list(levels)!r})",
            )

        screen = entry.get("screen_levels")
        if screen is None:
            screen_pair_ = (levels[0], levels[-1])
        else:
            screen_pair_ = tuple(screen)
            if len(screen_pair_) != 2:
                raise ValueError(
                    f"factor {fid!r}: screen_levels must name exactly 2 levels",
                )
            missing = [s for s in screen_pair_ if s not in levels]
            if missing:
                raise ValueError(
                    f"factor {fid!r}: screen_levels {missing!r} are not members "
                    f"of levels {list(levels)!r}",
                )

        grid = entry.get("grid")
        out.append(Factor(
            id=fid,
            name=str(entry.get("name") or fid),
            type=ftype,
            levels=levels,
            grid=float(grid) if grid is not None else None,
            screen_levels=screen_pair_,
            apply_spec=_normalise_apply(entry.get("apply"), fid),
            manipulation=_check_manipulation(entry.get("manipulation"), fid),
            relations=_check_relations(entry.get("relations"), fid),
        ))
    return out


def screen_pair(f: Factor) -> tuple:
    """The two levels the screening design uses for ``f``."""
    return f.screen_levels


def code_level(f: Factor, level: Any) -> int:
    """Map a real level onto the ±1 coding the design matrix uses."""
    low, high = f.screen_levels
    if level == low:
        return -1
    if level == high:
        return +1
    raise ValueError(
        f"factor {f.id!r}: level {level!r} is not part of the screen pair "
        f"{f.screen_levels!r}; only the screen pair has a ±1 coding.",
    )


def snap_to_grid(value: float, grid: float | None) -> float:
    """Round ``value`` to the nearest multiple of ``grid``."""
    if grid is None:
        return float(value)
    if grid <= 0:
        raise ValueError(f"grid must be > 0 (got {grid!r})")
    return round(float(value) / grid) * grid


def decode_coded(f: Factor, coded: float) -> Any:
    """Turn a coded (±1-scaled) value back into a runnable level.

    ``choice`` factors have no interior, so the sign picks a declared
    level. ``numeric`` factors interpolate between the screen pair and then
    snap to ``grid`` — so the value handed to ``confirm`` is one the target
    can actually run.
    """
    low, high = f.screen_levels
    if f.type == "choice":
        return high if coded > 0 else low
    mid = (float(low) + float(high)) / 2.0
    half = (float(high) - float(low)) / 2.0
    return snap_to_grid(mid + coded * half, f.grid)


def is_refinable(f: Factor) -> bool:
    """Whether ``f`` can carry curvature in the refine stage."""
    return f.type == "numeric" and len(f.levels) > 2
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_factors.py -q`
Expected: all pass.

- [ ] **Step 6: Run the full suite for regressions**

Run: `/opt/homebrew/bin/pytest -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/optimize/__init__.py orchestrator/optimize/factors.py tests/test_optimize_factors.py
git commit -m "$(cat <<'EOF'
feat(optimize): factor parsing, ±1 coding, and grid snapping

Factors declare type: numeric | choice — a domain question ("are values
between the levels runnable?") rather than a statistics one. grid snaps a
fitted optimum to a runnable step so confirm never tries to run K=4.7.

Rejects the retired continuous/ordinal/categorical vocabulary, factors
without a manipulation check, and factors whose only relation is
behavioral (nothing would then catch a broken lever).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Shared predicate evaluation

**Files:**
- Create: `orchestrator/optimize/predicates.py`
- Test: `tests/test_optimize_predicates.py`

**Interfaces produced:**
- `Verdict` frozen dataclass: `ok: bool`, `detail: str`, `skipped: bool`
- `evaluate(pred: dict, observed: dict, *, level=None) -> Verdict` — resolves a dotted `observable`/`metric` path in `observed`, interpolates `{level}`, applies `op`. Returns `skipped=True` when a `when`/`when_not` guard excludes this level.
- `is_trivial(pred: dict) -> bool` — `True` for predicates that cannot fail (`> 0` on a count, `!= null`, bare truthiness)
- `OPS: dict[str, callable]` — `==`, `!=`, `>`, `>=`, `<`, `<=`

One comparison vocabulary serves `manipulation`, `response.constraints`, `response.regimes`, and `design_space.invariants`. No bespoke assertion mini-language.

- [ ] **Step 1: Write the failing tests**

```python
"""Behavioral tests for the shared predicate vocabulary."""
from __future__ import annotations

import pytest

from orchestrator.optimize.predicates import Verdict, evaluate, is_trivial


def test_equality_on_a_dotted_observable_path():
    v = evaluate({"observable": "telemetry.queue_count", "op": "==", "value": 8},
                 {"telemetry": {"queue_count": 8}})
    assert v.ok is True and v.skipped is False


def test_failing_comparison_reports_both_sides_in_detail():
    v = evaluate({"observable": "telemetry.queue_count", "op": "==", "value": 8},
                 {"telemetry": {"queue_count": 2}})
    assert v.ok is False
    assert "2" in v.detail and "8" in v.detail


def test_level_token_is_interpolated_into_the_expected_value():
    v = evaluate({"observable": "config.tp_low", "op": "==", "value": "{level}"},
                 {"config": {"tp_low": 0.02}}, level=0.02)
    assert v.ok is True


def test_missing_observable_is_a_failure_not_a_crash():
    v = evaluate({"observable": "telemetry.absent", "op": "==", "value": 1},
                 {"telemetry": {}})
    assert v.ok is False
    assert "absent" in v.detail


def test_when_guard_skips_the_check_at_other_levels():
    pred = {"observable": "telemetry.mean_batch_size", "op": ">",
            "value": 1, "when": "on"}
    assert evaluate(pred, {"telemetry": {"mean_batch_size": 1}}, level="off").skipped is True
    assert evaluate(pred, {"telemetry": {"mean_batch_size": 4}}, level="on").ok is True


def test_when_not_guard_applies_everywhere_except_the_named_level():
    pred = {"observable": "telemetry.stop_events", "op": ">",
            "value": 0, "when_not": "off"}
    assert evaluate(pred, {"telemetry": {"stop_events": 0}}, level="off").skipped is True
    assert evaluate(pred, {"telemetry": {"stop_events": 3}}, level=0.004).ok is True


def test_guards_accept_a_list_of_levels():
    pred = {"observable": "x", "op": ">", "value": 0, "when": ["a", "b"]}
    assert evaluate(pred, {"x": 0}, level="c").skipped is True
    assert evaluate(pred, {"x": 5}, level="b").ok is True


def test_metric_key_is_accepted_as_an_alias_for_observable():
    v = evaluate({"metric": "drawdown", "op": ">=", "value": -0.60},
                 {"drawdown": -0.42})
    assert v.ok is True


@pytest.mark.parametrize("op,observed,expected,want", [
    (">", 5, 3, True), (">", 3, 5, False),
    (">=", 5, 5, True), ("<", 1, 2, True),
    ("<=", 2, 2, True), ("!=", 1, 2, True),
])
def test_operator_table(op, observed, expected, want):
    v = evaluate({"observable": "m", "op": op, "value": expected}, {"m": observed})
    assert v.ok is want


def test_unknown_operator_raises_with_the_allowed_set():
    with pytest.raises(ValueError, match="op"):
        evaluate({"observable": "m", "op": "=~", "value": 1}, {"m": 1})


@pytest.mark.parametrize("pred,want", [
    ({"observable": "throughput", "op": ">", "value": 0}, True),
    ({"observable": "x", "op": "!=", "value": None}, True),
    ({"observable": "telemetry.queue_count", "op": "==", "value": "{level}"}, False),
    ({"observable": "telemetry.transfer_path", "op": "==", "value": "p2p"}, False),
    ({"observable": "drawdown", "op": ">=", "value": -0.60}, False),
])
def test_is_trivial_flags_predicates_that_cannot_fail(pred, want):
    assert is_trivial(pred) is want
```

- [ ] **Step 2: Run to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_predicates.py -q`
Expected: `ModuleNotFoundError: ... predicates`

- [ ] **Step 3: Implement `predicates.py`**

```python
"""One comparison vocabulary for every check in an optimization campaign.

``manipulation`` (did the lever engage?), ``response.constraints`` (is this
config admissible?), ``response.regimes`` (does it hold in every regime?)
and ``design_space.invariants`` (did we stay inside the declared design
space?) all share the shape::

    {observable | metric: <dotted path>, op: <comparator>, value: <expected>}

Optional ``when`` / ``when_not`` restrict which levels a check applies to,
because a check is often meaningless at one level (a batch-size assertion
says nothing when batching is off).
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any

OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_MISSING = object()


@dataclass(frozen=True)
class Verdict:
    """Outcome of one predicate evaluation."""

    ok: bool
    detail: str = ""
    skipped: bool = False


def _resolve(path: str, observed: dict) -> Any:
    """Walk a dotted path through nested dicts; ``_MISSING`` when absent."""
    cur: Any = observed
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _guard_excludes(pred: dict, level: Any) -> bool:
    """Whether a ``when`` / ``when_not`` guard excludes this level."""
    def _members(raw):
        return raw if isinstance(raw, (list, tuple)) else [raw]

    if "when" in pred:
        return level not in _members(pred["when"])
    if "when_not" in pred:
        return level in _members(pred["when_not"])
    return False


def evaluate(pred: dict, observed: dict, *, level: Any = None) -> Verdict:
    """Evaluate one predicate against an observation dict."""
    op_name = pred.get("op")
    if op_name not in OPS:
        raise ValueError(
            f"predicate op must be one of {sorted(OPS)} (got {op_name!r})",
        )

    if _guard_excludes(pred, level):
        return Verdict(ok=True, skipped=True,
                       detail=f"skipped at level {level!r}")

    path = pred.get("observable") or pred.get("metric")
    if not path:
        raise ValueError("predicate needs an 'observable' (or 'metric') path")

    got = _resolve(path, observed)
    if got is _MISSING:
        return Verdict(
            ok=False,
            detail=(f"{path!r} not present in the observation — the target did "
                    f"not emit it, so the check cannot pass"),
        )

    want = pred.get("value")
    if want == "{level}":
        want = level

    ok = bool(OPS[op_name](got, want))
    return Verdict(
        ok=ok,
        detail=f"{path} = {got!r} {op_name} {want!r} -> {'ok' if ok else 'FAIL'}",
    )


def is_trivial(pred: dict) -> bool:
    """Whether a predicate is so weak it cannot meaningfully fail.

    A lazy check manufactures false confidence and is worse than none: it
    makes a broken lever look verified. Mirrors the floor
    ``validate_evidence`` applies to principles.
    """
    op_name = pred.get("op")
    value = pred.get("value")
    if value == "{level}":
        return False
    if op_name == "!=" and value is None:
        return True
    if op_name == ">" and isinstance(value, (int, float)) and value == 0:
        return True
    if op_name in (">=",) and isinstance(value, (int, float)) and value == 0:
        return True
    return False
```

- [ ] **Step 4: Run to verify they pass**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_predicates.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/optimize/predicates.py tests/test_optimize_predicates.py
git commit -m "$(cat <<'EOF'
feat(optimize): shared predicate vocabulary for all four check families

manipulation, response.constraints, response.regimes and
design_space.invariants share one {observable, op, value} shape, so there
is no bespoke assertion mini-language to learn or mis-type. when /
when_not guard which levels a check applies to.

is_trivial() flags predicates that cannot fail (> 0, != null): a lazy
check makes a broken lever look verified, which is worse than no check.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Design generation — factorial, fractional, central composite

**Files:**
- Create: `orchestrator/optimize/design.py`
- Test: `tests/test_optimize_design.py`

**Interfaces produced:**
- `DesignPoint` frozen dataclass: `coded: tuple[float, ...]`, `role: str` (`"corner"`|`"center"`|`"axial"`), `replicate: int`
- `Design` frozen dataclass: `points: tuple[DesignPoint, ...]`, `factor_ids: tuple[str, ...]`, `resolution: int | None`, `generators: tuple[tuple[int, ...], ...]`, `kind: str`
- `full_factorial(factor_ids) -> Design`
- `fractional_factorial(factor_ids, resolution: int) -> Design` — picks the smallest run count achieving `resolution`; `ValueError` when unachievable
- `central_composite(factor_ids, *, center_points: int, alpha: float | None = None) -> Design` — rotatable α defaults to `(2**k)**0.25`
- `with_center_points(design, n: int) -> Design`
- `alias_pairs(design) -> list[tuple[str, str]]` — confounded term pairs, as `("AB", "C")` style labels
- `is_orthogonal(design) -> bool`
- `min_runs_for(k: int, resolution: int) -> int`

**Known-answer oracles** (verified before writing this plan — do not weaken them):
- 5 factors at resolution V → **16 runs**, generator `E=ABCD`, zero aliasing among mains and 2-factor interactions.
- 7 factors at resolution III → 8 runs, generators `D=AB, E=AC, F=BC, G=ABC` (Box–Hunter–Hunter); exactly 21 two-factor interactions alias onto main effects.

- [ ] **Step 1: Write the failing tests**

```python
"""Behavioral tests for design generation.

The oracles here are external: published fractional-factorial generators
and the defining relations they imply. Tests assert the alias structure the
textbook predicts, never "what my generator produced".
"""
from __future__ import annotations

import itertools
import math

import pytest

from orchestrator.optimize.design import (
    alias_pairs,
    central_composite,
    fractional_factorial,
    full_factorial,
    is_orthogonal,
    min_runs_for,
    with_center_points,
)

FIVE = ("A", "B", "C", "D", "E")
SEVEN = ("A", "B", "C", "D", "E", "F", "G")


def _corners(design):
    return [p for p in design.points if p.role == "corner"]


def _column(design, idx):
    return [p.coded[idx] for p in _corners(design)]


def _product_column(design, idxs):
    return [math.prod(p.coded[i] for i in idxs) for p in _corners(design)]


def test_full_factorial_run_count_is_two_to_the_k():
    d = full_factorial(("A", "B", "C"))
    assert len(_corners(d)) == 8
    assert d.factor_ids == ("A", "B", "C")


def test_full_factorial_columns_are_balanced():
    d = full_factorial(("A", "B", "C"))
    for j in range(3):
        assert sum(_column(d, j)) == 0


def test_full_factorial_is_orthogonal():
    assert is_orthogonal(full_factorial(("A", "B", "C", "D"))) is True


def test_resolution_v_for_five_factors_needs_sixteen_runs():
    # Published: 2^(5-1) with E = ABCD is the minimum res-V design.
    assert min_runs_for(5, 5) == 16
    d = fractional_factorial(FIVE, resolution=5)
    assert len(_corners(d)) == 16


def test_resolution_v_design_has_no_aliasing_among_mains_and_two_factor_terms():
    d = fractional_factorial(FIVE, resolution=5)
    assert alias_pairs(d) == []


def test_resolution_v_main_effect_columns_are_mutually_orthogonal():
    d = fractional_factorial(FIVE, resolution=5)
    n = len(_corners(d))
    for i, j in itertools.combinations(range(5), 2):
        dot = sum(a * b for a, b in zip(_column(d, i), _column(d, j)))
        assert dot == 0, f"columns {i},{j} not orthogonal"
    assert all(sum(_column(d, j)) == 0 for j in range(5))
    assert n == 16


def test_resolution_three_for_seven_factors_is_eight_runs():
    # Box-Hunter-Hunter saturated design: D=AB, E=AC, F=BC, G=ABC.
    d = fractional_factorial(SEVEN, resolution=3)
    assert len(_corners(d)) == 8


def test_resolution_three_aliases_two_factor_terms_onto_main_effects():
    d = fractional_factorial(SEVEN, resolution=3)
    pairs = alias_pairs(d)
    # Every 2fi in a saturated 2^(7-4) is confounded with something.
    assert pairs, "res III must report aliasing"
    labels = {"".join(sorted(a)) + "=" + b for a, b in pairs}
    assert "AB=D" in labels or "D=AB" in {f"{b}={''.join(sorted(a))}" for a, b in pairs}


def test_requesting_an_unachievable_resolution_fails_loudly():
    with pytest.raises(ValueError, match="resolution"):
        fractional_factorial(("A", "B"), resolution=7)


def test_center_points_sit_at_the_origin():
    d = with_center_points(full_factorial(("A", "B")), 3)
    centers = [p for p in d.points if p.role == "center"]
    assert len(centers) == 3
    assert all(all(c == 0 for c in p.coded) for p in centers)


def test_center_point_replicate_indices_are_distinct():
    d = with_center_points(full_factorial(("A", "B")), 4)
    centers = [p for p in d.points if p.role == "center"]
    assert sorted(p.replicate for p in centers) == [0, 1, 2, 3]


def test_central_composite_has_corners_center_and_axial_points():
    d = central_composite(("A", "B"), center_points=4)
    roles = {p.role for p in d.points}
    assert roles == {"corner", "center", "axial"}
    # 2 factors -> 4 corners + 2*2 axial + 4 center
    assert len(_corners(d)) == 4
    assert len([p for p in d.points if p.role == "axial"]) == 4
    assert len([p for p in d.points if p.role == "center"]) == 4


def test_central_composite_axial_distance_is_rotatable_by_default():
    d = central_composite(("A", "B"), center_points=2)
    want = (2 ** 2) ** 0.25  # = sqrt(2) for k=2
    axial = [p for p in d.points if p.role == "axial"]
    for p in axial:
        nonzero = [c for c in p.coded if c != 0]
        assert len(nonzero) == 1
        assert math.isclose(abs(nonzero[0]), want, rel_tol=1e-9, abs_tol=1e-12)


def test_central_composite_axial_points_vary_one_factor_at_a_time():
    d = central_composite(("A", "B", "C"), center_points=2)
    for p in [q for q in d.points if q.role == "axial"]:
        assert sum(1 for c in p.coded if c != 0) == 1


def test_designs_are_deterministic_across_calls():
    a = fractional_factorial(FIVE, resolution=5)
    b = fractional_factorial(FIVE, resolution=5)
    assert [p.coded for p in a.points] == [p.coded for p in b.points]
```

- [ ] **Step 2: Run to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_design.py -q`
Expected: `ModuleNotFoundError: ... design`

- [ ] **Step 3: Implement `design.py`**

```python
"""Factorial and response-surface design generation.

Pure stdlib arithmetic: a design is a list of ±1-coded points, and for the
orthogonal designs this module emits, every effect estimate has an exact
closed form (contrast / N). That keeps the numerics auditable and keeps
numpy out of the harness.

Fractional designs use published generators. A 2^(k-p) design is built by
taking p base factors' full factorial and defining each remaining factor as
a product of base columns; which products you pick determines the
resolution. ``_GENERATORS`` records the standard choices so the alias
structure matches the textbook rather than whatever this module happens to
compute.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

# Standard generator sets, keyed (n_factors, resolution) -> (n_base,
# generator tuples over base column indices). Sources: Box, Hunter & Hunter,
# *Statistics for Experimenters*, 2e, Table 6.5; Montgomery, *Design and
# Analysis of Experiments*, 8e, Table 8.14.
_GENERATORS: dict[tuple[int, int], tuple[int, tuple[tuple[int, ...], ...]]] = {
    # resolution V — no 2fi aliased with a main effect or another 2fi
    (5, 5): (4, ((0, 1, 2, 3),)),                    # E = ABCD, 16 runs
    (6, 5): (5, ((0, 1, 2, 3, 4),)),                 # F = ABCDE, 32 runs
    (7, 5): (6, ((0, 1, 2, 3),)),                    # G = ABCD, 64 runs
    (8, 5): (6, ((0, 1, 2, 3), (0, 1, 4, 5))),       # G = ABCD, H = ABEF, 64 runs
    # resolution IV — mains clear of 2fi; 2fi aliased in pairs
    (4, 4): (3, ((0, 1, 2),)),                       # D = ABC, 8 runs
    (5, 4): (4, ((0, 1, 2),)),                       # 16 runs
    (6, 4): (4, ((0, 1, 2), (0, 1, 3))),             # 16 runs
    (7, 4): (4, ((0, 1, 2), (0, 1, 3), (0, 2, 3))),  # 16 runs
    (8, 4): (4, ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))),  # 16 runs
    # resolution III — saturated; 2fi aliased onto mains
    (7, 3): (3, ((0, 1), (0, 2), (1, 2), (0, 1, 2))),  # 8 runs
}


@dataclass(frozen=True)
class DesignPoint:
    """One row of the design, in ±1 coded space."""

    coded: tuple[float, ...]
    role: str = "corner"
    replicate: int = 0


@dataclass(frozen=True)
class Design:
    """A generated design plus the provenance needed to defend its claims."""

    points: tuple[DesignPoint, ...]
    factor_ids: tuple[str, ...]
    kind: str = "full"
    resolution: int | None = None
    generators: tuple[tuple[int, ...], ...] = ()

    @property
    def corners(self) -> tuple[DesignPoint, ...]:
        return tuple(p for p in self.points if p.role == "corner")


def min_runs_for(k: int, resolution: int) -> int:
    """Run count of the smallest tabulated design for ``k`` factors."""
    entry = _GENERATORS.get((k, resolution))
    if entry is None:
        if resolution <= 2:
            raise ValueError("resolution must be >= 3")
        return 2 ** k          # fall back to the full factorial
    n_base, _ = entry
    return 2 ** n_base


def full_factorial(factor_ids) -> Design:
    """All 2^k corners, in a deterministic order."""
    ids = tuple(factor_ids)
    pts = tuple(
        DesignPoint(coded=tuple(float(v) for v in combo))
        for combo in itertools.product((-1, 1), repeat=len(ids))
    )
    return Design(points=pts, factor_ids=ids, kind="full", resolution=None)


def fractional_factorial(factor_ids, resolution: int) -> Design:
    """A 2^(k-p) design achieving ``resolution`` using published generators."""
    ids = tuple(factor_ids)
    k = len(ids)
    if resolution < 3:
        raise ValueError(
            f"resolution must be >= 3 (got {resolution}); resolution II would "
            f"alias main effects with each other and estimate nothing.",
        )
    entry = _GENERATORS.get((k, resolution))
    if entry is None:
        if 2 ** k <= min_runs_for(k, resolution):
            return full_factorial(ids)
        raise ValueError(
            f"no tabulated resolution-{resolution} design for {k} factors. "
            f"Options: use the full factorial ({2 ** k} runs), reduce the "
            f"factor count, or accept a lower resolution and its aliasing.",
        )
    n_base, gens = entry
    pts = []
    for base in itertools.product((-1, 1), repeat=n_base):
        row = [float(v) for v in base]
        for g in gens:
            row.append(float(math.prod(base[i] for i in g)))
        pts.append(DesignPoint(coded=tuple(row)))
    return Design(
        points=tuple(pts), factor_ids=ids, kind="fractional",
        resolution=resolution, generators=gens,
    )


def with_center_points(design: Design, n: int) -> Design:
    """Append ``n`` replicated center points at the origin.

    Center points buy the pure-error estimate that makes a lack-of-fit test
    possible — without them the campaign cannot say whether its own model
    form is adequate.
    """
    if n < 0:
        raise ValueError(f"center_points must be >= 0 (got {n})")
    origin = tuple(0.0 for _ in design.factor_ids)
    centers = tuple(
        DesignPoint(coded=origin, role="center", replicate=i) for i in range(n)
    )
    return Design(
        points=design.points + centers, factor_ids=design.factor_ids,
        kind=design.kind, resolution=design.resolution,
        generators=design.generators,
    )


def central_composite(factor_ids, *, center_points: int,
                      alpha: float | None = None) -> Design:
    """Corners + axial (star) points + replicated centers.

    ``alpha`` defaults to the rotatable value (2^k)^(1/4), which makes the
    prediction variance depend only on distance from the center.
    """
    ids = tuple(factor_ids)
    k = len(ids)
    if k < 1:
        raise ValueError("central_composite needs at least 1 factor")
    a = float(alpha) if alpha is not None else (2 ** k) ** 0.25

    base = full_factorial(ids)
    axial: list[DesignPoint] = []
    for j in range(k):
        for sign in (-1.0, 1.0):
            coded = [0.0] * k
            coded[j] = sign * a
            axial.append(DesignPoint(coded=tuple(coded), role="axial"))

    combined = Design(
        points=base.points + tuple(axial), factor_ids=ids,
        kind="central_composite", resolution=None,
    )
    return with_center_points(combined, center_points)


def _label(idxs, factor_ids) -> str:
    return "".join(factor_ids[i] for i in sorted(idxs))


def is_orthogonal(design: Design) -> bool:
    """Whether every pair of main-effect columns is orthogonal over corners."""
    corners = design.corners
    k = len(design.factor_ids)
    for i, j in itertools.combinations(range(k), 2):
        if sum(p.coded[i] * p.coded[j] for p in corners) != 0:
            return False
    return all(sum(p.coded[j] for p in corners) == 0 for j in range(k))


def alias_pairs(design: Design) -> list[tuple[str, str]]:
    """Confounded (two-factor-interaction, other-term) label pairs.

    Reports 2fi aliased onto a main effect and 2fi aliased onto another 2fi.
    An empty list means every main effect and two-factor interaction is
    separately estimable — the resolution-V property.
    """
    corners = design.corners
    if not corners:
        return []
    k = len(design.factor_ids)
    ids = design.factor_ids

    mains = {ids[j]: tuple(p.coded[j] for p in corners) for j in range(k)}
    twofi = {
        _label((i, j), ids): tuple(p.coded[i] * p.coded[j] for p in corners)
        for i, j in itertools.combinations(range(k), 2)
    }

    out: list[tuple[str, str]] = []
    for label, col in twofi.items():
        for mname, mcol in mains.items():
            if col == mcol:
                out.append((label, mname))
    for (l1, c1), (l2, c2) in itertools.combinations(twofi.items(), 2):
        if c1 == c2:
            out.append((l1, l2))
    return sorted(out)
```

- [ ] **Step 4: Run to verify they pass**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_design.py -q`
Expected: all pass. If `test_resolution_three_aliases...` fails, the generator table is wrong — fix `_GENERATORS`, never the assertion.

- [ ] **Step 5: Cross-check the alias claim independently**

Run:
```bash
.venv/bin/python -c "
from orchestrator.optimize.design import fractional_factorial, alias_pairs, is_orthogonal
d5 = fractional_factorial(('A','B','C','D','E'), resolution=5)
print('res V: runs=', len(d5.corners), 'aliases=', alias_pairs(d5), 'orth=', is_orthogonal(d5))
d7 = fractional_factorial(('A','B','C','D','E','F','G'), resolution=3)
print('res III: runs=', len(d7.corners), 'n_aliases=', len(alias_pairs(d7)))
"
```
Expected: `res V: runs= 16 aliases= [] orth= True` and `res III: runs= 8 n_aliases= 21`.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/optimize/design.py tests/test_optimize_design.py
git commit -m "$(cat <<'EOF'
feat(optimize): factorial, fractional, and central-composite designs

Fractional designs use published generators (Box-Hunter-Hunter;
Montgomery Table 8.14) so the alias structure matches the textbook rather
than whatever the code happens to compute. Verified: 5 factors at
resolution V is 16 runs with E=ABCD and zero aliasing; 7 factors at
resolution III is 8 runs with 21 two-factor interactions confounded onto
main effects.

alias_pairs() returning [] is the resolution-V property -- every main
effect and 2-factor interaction separately estimable. That matters because
ordering-theorem's headline finding IS an interaction (preemption + FIFO
= 7.3x worse), which a main-effects-only screen inverts.

Center points are what make a lack-of-fit test possible; without them a
campaign cannot say whether its own model form is adequate.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Effect estimation, confidence intervals, lack-of-fit

**Files:**
- Create: `orchestrator/optimize/effects.py`
- Test: `tests/test_optimize_effects.py`

**Interfaces produced:**
- `Effect` frozen dataclass: `label: str`, `terms: tuple[str, ...]`, `estimate: float`, `se: float | None`, `ci_low: float | None`, `ci_high: float | None`, `significant: bool | None`
- `Fit` frozen dataclass: `intercept: float`, `effects: tuple[Effect, ...]`, `pure_error_var: float | None`, `pure_error_df: int`, `lack_of_fit_f: float | None`, `lack_of_fit_p: float | None`, `n_runs: int`, `aliases: tuple[tuple[str, str], ...]`
- `fit_effects(design, responses, *, factor_ids, include_interactions=True, alpha=0.05) -> Fit`
- `pure_error(center_responses) -> tuple[float, int]` — `(variance, df)`
- `dropped_factors(fit, factor_ids) -> list[str]` — factors whose CI contains zero
- `solve_stationary_point(fit, factor_ids) -> dict[str, float] | None` — coded optimum from a fitted quadratic; `None` when the surface has no interior stationary point

**Correctness oracle** (verified before writing this plan — reproduce it exactly): for a balanced orthogonal ±1 design, the OLS coefficient equals `contrast / N` in closed form, and both recover planted coefficients to within 8.9e-16. The planted case **must** include the L5 sign flip — main effect `-0.95`, interaction `+1.60` — so the fitter is proven to recover a factor that is harmful alone and beneficial in combination. That is the single scenario that defeated five of seven optimizers in the motivating study.

- [ ] **Step 1: Write the failing tests**

```python
"""Behavioral tests for effect estimation.

The oracle is a planted linear model: synthesize responses from known
coefficients, fit them, and assert the recovered values match the planted
ones. That is independent of this module's implementation — a wrong fitter
cannot fake it.

Every float assertion uses math.isclose: the closed form carries ~1e-16
representation error and `==` would be flaky (verified).
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize.design import (
    central_composite,
    fractional_factorial,
    full_factorial,
    with_center_points,
)
from orchestrator.optimize.effects import (
    dropped_factors,
    fit_effects,
    pure_error,
    solve_stationary_point,
)

TOL = {"rel_tol": 1e-9, "abs_tol": 1e-9}


def _synth(design, factor_ids, intercept, mains, inter=None):
    """Response values from a known linear model over the design's corners."""
    inter = inter or {}
    out = []
    for p in design.points:
        if p.role != "corner":
            out.append(intercept)          # center/axial at the model's center
            continue
        y = intercept
        for j, fid in enumerate(factor_ids):
            y += mains.get(fid, 0.0) * p.coded[j]
        for (a, b), coef in inter.items():
            ia, ib = factor_ids.index(a), factor_ids.index(b)
            y += coef * p.coded[ia] * p.coded[ib]
        out.append(y)
    return out


def test_recovers_planted_main_effects_on_a_full_factorial():
    ids = ("A", "B", "C")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=False)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(fit.intercept, 10.0, **TOL)
    assert math.isclose(got["A"], -0.95, **TOL)
    assert math.isclose(got["B"], 2.0, **TOL)
    assert math.isclose(got["C"], 0.5, **TOL)


def test_recovers_the_l5_sign_flip_negative_main_positive_interaction():
    """The motivating case: batching is -9.5% alone but required for the
    winning compound. A fitter that cannot separate these is useless here.
    """
    ids = ("A", "B", "C")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.5},
                {("A", "B"): 1.6})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["A"], -0.95, **TOL), "main effect must stay negative"
    assert math.isclose(got["AB"], 1.6, **TOL), "interaction must stay positive"
    assert got["A"] < 0 < got["AB"]
    # the compound beats the sum of the parts at the (+1,+1) corner
    assert got["A"] + got["B"] + got["AB"] > got["B"]


def test_recovers_planted_effects_on_a_resolution_v_fractional_design():
    ids = ("A", "B", "C", "D", "E")
    d = fractional_factorial(ids, resolution=5)
    ys = _synth(d, ids, 5.0,
                {"A": 1.0, "B": -0.4, "C": 0.0, "D": 0.25, "E": 0.75},
                {("A", "B"): 0.9})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["A"], 1.0, **TOL)
    assert math.isclose(got["B"], -0.4, **TOL)
    assert math.isclose(got["E"], 0.75, **TOL)
    assert math.isclose(got["AB"], 0.9, **TOL)
    assert math.isclose(got["C"], 0.0, **TOL)


def test_a_null_factor_is_estimated_at_zero():
    ids = ("A", "B")
    d = full_factorial(ids)
    ys = _synth(d, ids, 3.0, {"A": 1.5, "B": 0.0})
    fit = fit_effects(d, ys, factor_ids=ids)
    got = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(got["B"], 0.0, **TOL)


def test_pure_error_from_replicated_center_points():
    reps = [10.02, 9.97, 10.05, 9.99, 10.01]
    var, df = pure_error(reps)
    assert df == 4
    assert math.isclose(var, 0.00092, rel_tol=1e-6)


def test_pure_error_needs_at_least_two_replicates():
    var, df = pure_error([10.0])
    assert var is None and df == 0


def test_confidence_interval_excludes_zero_for_a_real_effect():
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0, "D": 0.0, "E": 0.0})
    # perturb the center replicates so pure error is non-zero
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.02, -0.03, 0.05, -0.01, 0.01], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    by = {e.label: e for e in fit.effects}
    assert by["A"].ci_high is not None and by["A"].ci_high < 0
    assert by["A"].significant is True
    assert by["C"].significant is False


def test_dropped_factors_are_those_whose_interval_contains_zero():
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0, "D": 0.0, "E": 0.0})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.02, -0.03, 0.05, -0.01, 0.01], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    dropped = dropped_factors(fit, ids)
    assert "A" not in dropped and "B" not in dropped
    assert {"C", "D", "E"} <= set(dropped)


def test_lack_of_fit_is_reported_when_center_points_exist():
    ids = ("A", "B")
    d = with_center_points(full_factorial(ids), 4)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.01, -0.01, 0.02, -0.02], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.pure_error_df == 3
    assert fit.lack_of_fit_p is not None


def test_strong_curvature_is_detected_as_lack_of_fit():
    """Center response far from the corner mean means the linear model is
    inadequate — the trigger that escalates to the model (spec 6.3).
    """
    ids = ("A", "B")
    d = with_center_points(full_factorial(ids), 4)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    # Center values must be far from the corner mean (that is the curvature)
    # AND mutually distinct (that is the pure-error estimate). Identical
    # replicates give pure_error_var == 0, which correctly short-circuits the
    # F test and would leave lack_of_fit_p as None — the test would then be
    # asserting against its own setup.
    for offset, i in zip([0.0, -0.02, 0.02, -0.01], centers):
        ys[i] = 14.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.lack_of_fit_p is not None and fit.lack_of_fit_p < 0.05


def test_significance_uses_the_terms_own_column_not_the_total_row_count():
    """The defect this guards was invisible to every other test.

    A scalar se = sqrt(pe_var / n_total) understates a main effect's standard
    error, because centre points inflate n without loading a ±1 column. On
    this design (16 corners, 21 rows) the CI half-width comes out 1.1456x too
    narrow, which reports factors as significant when they are inside the
    noise floor. `dropped_factors` keys off `significant`, and the stage rule
    keys off `dropped_factors`, so the campaign would carry noise into the
    refine stage. Every planted effect elsewhere in this file sits far from
    the boundary, so only a boundary case catches it.
    """
    ids = ("A", "B", "C", "D", "E")
    d = with_center_points(fractional_factorial(ids, resolution=5), 5)
    perturb = [0.0, 0.02, -0.03, 0.05, -0.01]
    ys, ci = [], 0
    for p in d.points:
        if p.role == "center":
            ys.append(10.0 + perturb[ci])
            ci += 1
        else:
            ys.append(10.0 + 0.02 * p.coded[0])   # inside the noise floor
    fit = fit_effects(d, ys, factor_ids=ids)
    a = next(e for e in fit.effects if e.label == "A")
    n_corners = len([p for p in d.points if p.role == "corner"])
    assert math.isclose(a.se, math.sqrt(fit.pure_error_var / n_corners),
                        rel_tol=1e-9, abs_tol=1e-12)
    assert a.significant is False, (
        "a 0.02 effect is inside this design's noise floor; reporting it as "
        "significant is the false positive the scalar-se bug produced"
    )


def test_no_center_points_means_no_lack_of_fit_verdict():
    ids = ("A", "B")
    d = full_factorial(ids)
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.pure_error_var is None
    assert fit.lack_of_fit_p is None
    assert all(e.significant is None for e in fit.effects)


def test_response_length_must_match_the_design():
    ids = ("A", "B")
    d = full_factorial(ids)
    with pytest.raises(ValueError, match="length"):
        fit_effects(d, [1.0, 2.0], factor_ids=ids)


def test_aliases_are_carried_onto_the_fit_as_a_caveat():
    ids = ("A", "B", "C", "D", "E", "F", "G")
    d = fractional_factorial(ids, resolution=3)
    ys = _synth(d, ids, 1.0, {"A": 1.0})
    # include_interactions=False is REQUIRED here: this saturated design has 8
    # runs, so a model with 21 two-factor interactions (29 terms total) is not
    # estimable and fit_effects correctly raises. The property under test is
    # that aliasing propagates to the Fit, which needs no interaction terms.
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=False)
    assert fit.aliases, "a res-III fit must carry its aliasing forward"


def test_stationary_point_of_a_known_quadratic():
    """y = 10 - 2*(a-0.5)^2 peaks at a=0.5 in coded space."""
    ids = ("A", "B")
    d = central_composite(ids, center_points=3)
    ys = []
    for p in d.points:
        a, b = p.coded
        ys.append(10.0 - 2.0 * (a - 0.5) ** 2 - 1.0 * b ** 2)
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=True)
    sp = solve_stationary_point(fit, ids)
    assert sp is not None
    assert math.isclose(sp["A"], 0.5, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(sp["B"], 0.0, rel_tol=1e-6, abs_tol=1e-6)


def test_stationary_point_is_none_without_curvature_terms():
    ids = ("A", "B")
    d = full_factorial(ids)          # no axial points -> no quadratic terms
    ys = _synth(d, ids, 10.0, {"A": 1.0, "B": 0.5})
    fit = fit_effects(d, ys, factor_ids=ids)
    assert solve_stationary_point(fit, ids) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_effects.py -q`
Expected: `ModuleNotFoundError: ... effects`

- [ ] **Step 3: Implement `effects.py`**

```python
"""Effect estimation for orthogonal factorial designs.

For a balanced ±1-coded orthogonal design the least-squares coefficient of
any term has the exact closed form::

    beta_j = sum_i (x_ij * y_i) / N          # contrast / N

Verified equal to numpy.linalg.lstsq to machine precision. Using the closed
form keeps the arithmetic auditable and keeps numpy out of the harness.

Non-orthogonal designs (central composite with axial points) need a general
solve; ``_solve_normal_equations`` does Gaussian elimination with partial
pivoting on the normal equations — small systems (k <= 8 means at most ~45
terms), so a direct solve is fine and needs no external library.

Confidence intervals come from the pure-error variance supplied by
replicated center points. Without center points there is no independent
error estimate, so significance is left as ``None`` rather than guessed:
reporting a fabricated interval would be worse than reporting none.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import variance

from scipy.stats import f as fisher_f
from scipy.stats import t as student_t

from orchestrator.optimize.design import Design, alias_pairs


@dataclass(frozen=True)
class Effect:
    """One estimated model term."""

    label: str
    terms: tuple[str, ...]
    estimate: float
    se: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    significant: bool | None = None


@dataclass(frozen=True)
class Fit:
    """A fitted model plus everything needed to defend or doubt it."""

    intercept: float
    effects: tuple[Effect, ...]
    n_runs: int
    pure_error_var: float | None = None
    pure_error_df: int = 0
    lack_of_fit_f: float | None = None
    lack_of_fit_p: float | None = None
    aliases: tuple[tuple[str, str], ...] = ()
    quadratic: tuple[Effect, ...] = ()


def pure_error(center_responses) -> tuple[float | None, int]:
    """Sample variance and df of replicated center points."""
    vals = list(center_responses)
    if len(vals) < 2:
        return None, 0
    return variance(vals), len(vals) - 1


def _solve_normal_equations(cols: list[list[float]], ys: list[float]) -> list[float]:
    """Least squares via the normal equations, Gaussian elimination."""
    p = len(cols)
    a = [[sum(cols[i][r] * cols[j][r] for r in range(len(ys))) for j in range(p)]
         for i in range(p)]
    b = [sum(cols[i][r] * ys[r] for r in range(len(ys))) for i in range(p)]

    for col in range(p):
        pivot = max(range(col, p), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError(
                "design matrix is singular — the requested terms are not "
                "estimable from these runs (too few distinct configurations)",
            )
        a[col], a[pivot] = a[pivot], a[col]
        b[col], b[pivot] = b[pivot], b[col]
        for r in range(p):
            if r == col:
                continue
            factor = a[r][col] / a[col][col]
            for c in range(col, p):
                a[r][c] -= factor * a[col][c]
            b[r] -= factor * b[col]
    return [b[i] / a[i][i] for i in range(p)]


def fit_effects(design: Design, responses, *, factor_ids,
                include_interactions: bool = True,
                alpha: float = 0.05) -> Fit:
    """Fit main effects (+ 2-factor interactions, + curvature when present)."""
    ids = tuple(factor_ids)
    ys = [float(v) for v in responses]
    if len(ys) != len(design.points):
        raise ValueError(
            f"responses length {len(ys)} != design length "
            f"{len(design.points)}; every planned run needs exactly one "
            f"response value",
        )

    k = len(ids)
    pts = design.points
    has_axial = any(p.role == "axial" for p in pts)

    labels: list[str] = []
    terms: list[tuple[str, ...]] = []
    cols: list[list[float]] = [[1.0] * len(pts)]     # intercept
    labels.append("(intercept)")
    terms.append(())

    for j, fid in enumerate(ids):
        labels.append(fid)
        terms.append((fid,))
        cols.append([p.coded[j] for p in pts])

    if include_interactions and k >= 2:
        for i, j in itertools.combinations(range(k), 2):
            labels.append(f"{ids[i]}{ids[j]}")
            terms.append((ids[i], ids[j]))
            cols.append([p.coded[i] * p.coded[j] for p in pts])

    quad_start = len(labels)
    if has_axial:
        for j, fid in enumerate(ids):
            labels.append(f"{fid}^2")
            terms.append((fid, fid))
            cols.append([p.coded[j] ** 2 for p in pts])

    coefs = _solve_normal_equations(cols, ys)

    centers = [y for p, y in zip(pts, ys) if p.role == "center"]
    pe_var, pe_df = pure_error(centers)

    n = len(pts)
    tcrit = None
    if pe_var is not None and pe_var > 0 and pe_df > 0:
        tcrit = float(student_t.ppf(1 - alpha / 2, pe_df))

    built: list[Effect] = []
    quads: list[Effect] = []
    for idx in range(1, len(labels)):
        est = coefs[idx]
        lo = hi = None
        sig = None
        se = None
        if tcrit is not None and pe_var is not None:
            # Per-term standard error from THIS term's own column sum of
            # squares. A single scalar sqrt(pe_var/n) is wrong: center points
            # contribute 0 to a ±1 column, so they inflate n without
            # informing a main effect, understating its SE (by √2 on a
            # 2-factor + 4-centre design; 14.6% on res-V 5-factor + 5
            # centres). That biases `significant` — and therefore
            # `dropped_factors` and the stage rule — toward false positives.
            #
            # sqrt(pe_var / Σx²) equals the exact sigma·sqrt((X'X)⁻¹_jj) only
            # when the term's column is orthogonal to every other column.
            # That holds for main effects and 2-factor interactions on every
            # design this module generates, which are the terms that drive
            # `dropped_factors` and the stage rule. It does NOT hold for the
            # intercept or the pure-quadratic terms on a central composite,
            # where those columns are mutually correlated — verified on a
            # 2-factor CCD: exact SE 0.4208 vs 0.2887 from this formula.
            # Quadratic terms therefore carry an OPTIMISTIC (too narrow) CI;
            # they are reported for surface curvature, never used as a
            # significance gate. `solve_stationary_point` uses the estimates
            # themselves, not their intervals.
            ssq = sum(c * c for c in cols[idx])
            if ssq > 0:
                se = math.sqrt(pe_var / ssq)
                lo, hi = est - tcrit * se, est + tcrit * se
                sig = not (lo <= 0.0 <= hi)
        eff = Effect(label=labels[idx], terms=terms[idx], estimate=est,
                     se=se, ci_low=lo, ci_high=hi, significant=sig)
        (quads if idx >= quad_start else built).append(eff)

    lof_f = lof_p = None
    if pe_var is not None and pe_var > 0 and pe_df > 0:
        resid = [
            ys[r] - sum(coefs[c] * cols[c][r] for c in range(len(cols)))
            for r in range(n)
        ]
        ss_resid = sum(v * v for v in resid)
        ss_pe = pe_var * pe_df
        df_resid = n - len(cols)
        df_lof = df_resid - pe_df
        if df_lof > 0:
            ss_lof = max(ss_resid - ss_pe, 0.0)
            lof_f = (ss_lof / df_lof) / pe_var
            lof_p = float(1.0 - fisher_f.cdf(lof_f, df_lof, pe_df))

    return Fit(
        intercept=coefs[0], effects=tuple(built), n_runs=n,
        pure_error_var=pe_var, pure_error_df=pe_df,
        lack_of_fit_f=lof_f, lack_of_fit_p=lof_p,
        aliases=tuple(alias_pairs(design)), quadratic=tuple(quads),
    )


def dropped_factors(fit: Fit, factor_ids) -> list[str]:
    """Factors whose main effect is indistinguishable from zero.

    With no pure-error estimate nothing can be dropped — an unknown effect
    is not a null effect.
    """
    out: list[str] = []
    for fid in factor_ids:
        for e in fit.effects:
            if e.terms == (fid,):
                if e.significant is False:
                    out.append(fid)
                break
    return out


def solve_stationary_point(fit: Fit, factor_ids) -> dict[str, float] | None:
    """Coded-space stationary point of the fitted quadratic surface.

    Solves ``2B x + b = 0`` where ``b`` holds the linear coefficients and
    ``B`` the quadratic/interaction terms. Returns ``None`` when the fit has
    no curvature terms (a plane has no interior optimum).
    """
    ids = tuple(factor_ids)
    if not fit.quadratic:
        return None
    k = len(ids)
    idx = {f: i for i, f in enumerate(ids)}

    b = [0.0] * k
    for e in fit.effects:
        if len(e.terms) == 1:
            b[idx[e.terms[0]]] = e.estimate

    B = [[0.0] * k for _ in range(k)]
    for e in fit.quadratic:
        i = idx[e.terms[0]]
        B[i][i] = e.estimate
    for e in fit.effects:
        if len(e.terms) == 2 and e.terms[0] != e.terms[1]:
            i, j = idx[e.terms[0]], idx[e.terms[1]]
            B[i][j] = B[j][i] = e.estimate / 2.0

    a = [[2.0 * B[i][j] for j in range(k)] for i in range(k)]
    rhs = [-b[i] for i in range(k)]
    try:
        for col in range(k):
            pivot = max(range(col, k), key=lambda r: abs(a[r][col]))
            if abs(a[pivot][col]) < 1e-12:
                return None
            a[col], a[pivot] = a[pivot], a[col]
            rhs[col], rhs[pivot] = rhs[pivot], rhs[col]
            for r in range(k):
                if r == col:
                    continue
                f = a[r][col] / a[col][col]
                for c in range(col, k):
                    a[r][c] -= f * a[col][c]
                rhs[r] -= f * rhs[col]
        return {ids[i]: rhs[i] / a[i][i] for i in range(k)}
    except ZeroDivisionError:
        return None
```

- [ ] **Step 4: Run to verify they pass**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_effects.py -q`
Expected: all pass. The L5 test is the one that matters most — if it fails, stop and fix the fitter before proceeding.

- [ ] **Step 5: Independently cross-check the closed form**

Run:
```bash
.venv/bin/python -c "
import itertools, math
from orchestrator.optimize.design import full_factorial
from orchestrator.optimize.effects import fit_effects
ids=('A','B','C'); d=full_factorial(ids)
b0,bA,bB,bC,bAB=10.0,-0.95,2.0,0.5,1.6
ys=[b0+bA*p.coded[0]+bB*p.coded[1]+bC*p.coded[2]+bAB*p.coded[0]*p.coded[1] for p in d.points]
fit=fit_effects(d,ys,factor_ids=ids)
got={e.label:e.estimate for e in fit.effects}
# closed form (contrast/N), computed here independently of effects.py
def contrast(cols):
    return sum(math.prod(p.coded[c] for c in cols)*y
               for p,y in zip(d.points,ys))/len(d.points)
print('A  fitted', round(got['A'],12), ' closed-form', round(contrast([0]),12))
print('AB fitted', round(got['AB'],12), ' closed-form', round(contrast([0,1]),12))
print('planted A=-0.95 AB=+1.60 -> harmful alone, beneficial in compound')
"
```
Expected: fitted and closed-form values agree to 12 decimals for both terms.

- [ ] **Step 6: Run the full suite**

Run: `/opt/homebrew/bin/pytest -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/optimize/effects.py tests/test_optimize_effects.py
git commit -m "$(cat <<'EOF'
feat(optimize): effect estimation, CIs, and lack-of-fit

For orthogonal +/-1 designs the OLS coefficient has the exact closed form
contrast/N, verified equal to numpy lstsq to machine precision -- so the
arithmetic stays auditable and numpy stays out of the harness.
Non-orthogonal (central-composite) fits use a direct solve of the normal
equations; the systems are tiny.

The load-bearing test plants the L5 sign flip -- main effect -0.95,
interaction +1.60 -- and asserts the fitter recovers both. That is exactly
the landscape that defeated five of seven optimizers in the motivating
study: a factor harmful alone and required for the winning compound.

Significance is left as None when there are no replicated center points,
rather than guessed. An unknown effect is not a null effect, and a
fabricated interval is worse than an absent one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Matrix expansion and fidelity checking

**Files:**
- Create: `orchestrator/optimize/matrix.py`
- Test: `tests/test_optimize_matrix.py`

**Interfaces produced:**
- `ConfigRow` frozen dataclass: `row_index: int`, `levels: dict[str, object]`, `role: str`, `replicate: int`, `apply: dict` (`{"cli_args": [...], "env": {...}, "patches": [...]}`)
- `expand(design, factors) -> list[ConfigRow]` — matrix rows → concrete runnable configs
- `matrix_payload(design, factors, *, run_order_seed: int) -> dict` — the `design_matrix.json` body, including randomized `run_order`
- `randomized_run_order(n: int, seed: int) -> list[int]` — deterministic given the seed
- `check_fidelity(payload: dict, runs: list[dict]) -> list[str]` — returns violation strings; empty means the executed configs match the pre-registered matrix exactly
- `check_invariants(invariants: list[dict], observed: dict, *, level=None) -> list[str]`

**Test assertions to write** (mechanical task — write these as behavioral tests; no full bodies needed here, each is 3–6 lines):
1. `expand` produces one `ConfigRow` per design point, in design order.
2. A `numeric` factor at coded `-1` yields its low screen level in `levels`; at `+1` its high level.
3. A `cli_flag` `apply` renders `{level}` into `apply["cli_args"]` (e.g. `["--queues=2"]`).
4. An `env_var` `apply` renders into `apply["env"]` as `{"CERTUS_BATCHING": "on"}`.
5. A `config_patch` `apply` renders into `apply["patches"]` with `path`, `pointer`, `value`.
6. Center-point rows carry `role == "center"` and midpoint levels (grid-snapped).
7. `randomized_run_order(16, seed=42)` is a permutation of `range(16)` and is **identical** across two calls with the same seed, and **differs** for seed 43.
8. `matrix_payload` includes `factor_ids`, `resolution`, `generators`, `aliases`, `run_order`, `run_order_seed`, and one entry per row. **`aliases` must be populated from `design.alias_pairs(design)`, not left empty** — `design_matrix.json` is the pre-registered artifact a reader consults to judge what the screen can estimate, so an empty list on a confounded design would assert the opposite of the truth. Assert both directions: a resolution-III design's payload carries a non-empty list matching `len(alias_pairs(design))`, and a resolution-V design's carries an empty one (the res-V property must be visible in the artifact, not merely absent).
9. `check_fidelity` returns `[]` when every run's `levels` match the payload row at the same `row_index`.
10. `check_fidelity` reports a violation naming the factor, the expected level, and the observed level when one run drifts.
11. `check_fidelity` reports a violation when a planned `row_index` has no corresponding run (silently skipped cell).
12. `check_fidelity` reports a violation when a run carries a `row_index` absent from the payload (an unplanned extra run).
13. `check_invariants` returns `[]` when all invariants hold; returns one string per violated invariant, each naming the invariant `id` and `statement`.
14. `check_invariants` treats a missing observable as a violation (cannot pass what was not emitted).

- [ ] **Step 1: Write the tests above in `tests/test_optimize_matrix.py`**

Follow the house style: module docstring naming the behavior under test, a `_factor(**over)` helper mirroring `tests/test_optimize_factors.py`, `math.isclose` for any float level. Reuse `parse_factors` to build factors rather than constructing `Factor` directly — that keeps the test coupled to the public seam.

- [ ] **Step 2: Run to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_matrix.py -q`
Expected: `ModuleNotFoundError: ... matrix`

- [ ] **Step 3: Implement `matrix.py`**

Key implementation notes (do not deviate — these are correctness requirements from the spec):
- `randomized_run_order` uses `random.Random(seed).shuffle` on a local list. Never the global `random` module state, or the order stops being reproducible from the recorded seed.
- Run order is randomized **and recorded** so that time-ordered drift (thermal, cache warming) cannot masquerade as a factor effect, while the campaign stays reproducible.
- `check_fidelity` compares by `row_index` on both sides and reports three distinct violation classes: level drift, missing planned row, unplanned extra row. All three are hard failures per spec §6.4 — a silently skipped cell changes the design's resolution.
- `expand` renders `{level}` only. No other token, no arbitrary template evaluation.
- For `role == "center"`, a `numeric` factor's level is `decode_coded(f, 0.0)` (grid-snapped); a `choice` factor has no midpoint, so center rows pin it to its low level and the payload records `center_choice_pinned: true` for that factor.

- [ ] **Step 4: Run to verify they pass**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_matrix.py -q`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/optimize/matrix.py tests/test_optimize_matrix.py
git commit -m "$(cat <<'EOF'
feat(optimize): matrix expansion, randomized run order, fidelity checking

expand() turns a coded design row into a runnable config via each factor's
apply spec -- the seam that removes the LLM from the inner loop. {level} is
the only interpolation token.

Run order is randomized from a recorded seed, so time-ordered drift
(thermal, cache warming) cannot masquerade as a factor effect while the
campaign stays reproducible.

check_fidelity reports three violation classes -- level drift, missing
planned row, unplanned extra row. All three are hard failures: a silently
skipped cell changes the design's actual resolution, so tolerating it would
let the campaign overstate what it can estimate.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Relation contracts and native-test verdicts

**Files:**
- Create: `orchestrator/optimize/relations.py`
- Test: `tests/test_optimize_relations.py`

**Interfaces produced:**
- `RelationVerdict` frozen dataclass: `relation_id: str`, `factor_id: str`, `kind: str`, `native_test: str`, `passed: bool`, `detail: str`
- `required_relations(factors) -> list[tuple[str, dict]]` — `(factor_id, relation)` pairs
- `parse_pytest_json_report(payload: dict) -> dict[str, bool]` — test node id → passed
- `parse_junit_xml(text: str) -> dict[str, bool]` — `classname.name` → passed
- `reconcile(factors, results: dict[str, bool]) -> list[RelationVerdict]` — a declared relation with no matching result is `passed=False` with detail "declared but not executed"
- `classify_failures(verdicts) -> tuple[list[RelationVerdict], list[RelationVerdict]]` — `(correctness_failures, behavioral_failures)`

**Test assertions to write:**
1. `required_relations` returns every relation across all factors, tagged with its factor id.
2. `parse_pytest_json_report` maps `tests[].nodeid` → `outcome == "passed"`.
3. `parse_junit_xml` marks a testcase with a nested `<failure>` as not passed, and a bare testcase as passed.
4. `reconcile` marks a declared relation absent from the results as `passed=False` with a detail containing "not executed" — **the load-bearing case**: a relation nobody ran must never look satisfied.
5. `reconcile` matches on exact `native_test` identifier.
6. `classify_failures` puts a failed `correctness` relation in the first list and a failed `behavioral` one in the second.
7. `classify_failures` returns empty lists when everything passed.
8. A `behavioral` failure never appears in the correctness list even when it is the only failure (protects the L5-style discovery from being treated as a crash).

- [ ] **Step 1: Write the tests in `tests/test_optimize_relations.py`**

Include a docstring paragraph explaining why #8 exists: monotonicity violations are discoveries, not bugs, and conflating them with broken code would make the campaign blind to exactly the non-monotonic compounds it exists to find.

- [ ] **Step 2: Run to verify they fail**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_relations.py -q`

- [ ] **Step 3: Implement `relations.py`**

Notes:
- Nous never generates or interprets target-language test code. It checks a **contract**: each declared relation names a `native_test`; the declared `test_command` ran; that identifier appears in the results; it passed. Generator/library choice (`hypothesis`, `rapid`, `proptest`, RapidCheck) belongs to the target repo.
- Support both pytest JSON report and JUnit XML, since those cover the overwhelming majority of target runners. Unknown formats raise with a message naming both supported shapes.
- "Declared but not executed" must be a failure, never a pass. Otherwise a typo'd `native_test` id silently disables a correctness gate.

- [ ] **Step 4: Run to verify they pass, then commit**

```bash
/opt/homebrew/bin/pytest tests/test_optimize_relations.py -q
git add orchestrator/optimize/relations.py tests/test_optimize_relations.py
git commit -m "$(cat <<'EOF'
feat(optimize): relation contracts over target-native property tests

Nous checks a contract, never test code: each relation names a native_test,
the declared test_command runs, and the identifier must appear in the
results having passed. hypothesis / rapid / proptest / RapidCheck are the
target repo's business, so the harness needs zero language knowledge.

A relation declared but absent from the results is a FAILURE, not a pass --
otherwise a typo'd identifier silently disables a correctness gate.

classify_failures keeps behavioral violations out of the correctness
bucket: a monotonicity break is a discovery (L5 was -9.5% alone and
required for the winning compound), and hard-failing on it would make the
campaign blind to what it exists to find.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Stage decision rule and escalation triggers

**Files:**
- Create: `orchestrator/optimize/stage.py`
- Test: `tests/test_optimize_stage.py`

**Interfaces produced:**
- `Stage` str-Enum: `VERIFY = "verify"`, `SCREEN = "screen"`, `REFINE = "refine"`, `CONFIRM = "confirm"`
- `Trigger` str-Enum: `ALL_WITHIN_NOISE`, `LACK_OF_FIT`, `OPTIMUM_OUTSIDE_HULL`, `BEHAVIORAL_VIOLATION`
- `StageDecision` frozen dataclass: `next_stage: Stage | None`, `triggers: tuple[Trigger, ...]`, `surviving: tuple[str, ...]`, `dropped: tuple[str, ...]`, `rationale: str`
- `stage_for_iteration(campaign: dict, iteration: int) -> Stage`
- `decide_after_screen(fit, factors, *, alpha=0.05) -> StageDecision`
- `decide_after_refine(fit, factors, stationary: dict | None) -> StageDecision`

**Test assertions to write:**
1. `stage_for_iteration` maps 1→VERIFY, 2→SCREEN, 3→REFINE, 4→CONFIRM by default.
2. An explicit `optimization.stages: [verify, screen, confirm]` list overrides the default mapping by index.
3. An out-of-range iteration returns `CONFIRM` (never a fresh SCREEN, which would spend budget re-screening).
4. `decide_after_screen` drops factors whose CI contains zero and keeps the rest in `surviving`.
5. With ≥1 surviving refinable factor (`numeric`, >2 levels), `next_stage == REFINE`.
6. With only `choice` factors surviving, `next_stage == CONFIRM` — skipping a refine that has nothing to refine.
7. With only 2-level `numeric` factors surviving, `next_stage == CONFIRM`.
8. When **every** factor is within noise, `ALL_WITHIN_NOISE` is in `triggers` (the factor set was wrong → re-consult the model).
9. When `fit.lack_of_fit_p < 0.05`, `LACK_OF_FIT` is in `triggers`.
10. `decide_after_refine` with a stationary point inside `[-1, 1]` on every axis → `next_stage == CONFIRM`, no `OPTIMUM_OUTSIDE_HULL`.
11. `decide_after_refine` with any coordinate outside `[-1, 1]` → `OPTIMUM_OUTSIDE_HULL` trigger (ranges were too narrow).
12. `decide_after_refine` with `stationary is None` → `CONFIRM` at the best observed corner, with a rationale saying so.
13. `rationale` is non-empty in every decision (it is projected into `findings.json`, so an empty one would produce an evidence-free finding).

- [ ] **Step 1: Write the tests in `tests/test_optimize_stage.py`**

Build `Fit` objects directly here — this is a pure decision rule over a fitted model, so constructing `Effect`/`Fit` literals is the clearest way to cover each branch. Use the real dataclasses from `effects.py`, not fakes, so a signature change breaks the test.

- [ ] **Step 2–4: Run (fail), implement, run (pass)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_stage.py -q`

Implementation notes:
- Pure function of `(Fit, factors)`. No I/O, no LLM, no randomness — this is the "adaptivity is arithmetic" claim from the spec, and it must be testable in isolation.
- Iteration N+1 inherits effect sizes and CIs, not prose. Do not add a summarization step here.
- Escalation triggers are *reported*, not acted on: `stage.py` decides the next stage and names the triggers; `iteration.py` decides whether a trigger warrants a model call.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/optimize/stage.py tests/test_optimize_stage.py
git commit -m "$(cat <<'EOF'
feat(optimize): pure-Python stage decision rule and escalation triggers

Between-stage adaptation is arithmetic on effect sizes, not a model call:
drop factors whose CI contains zero, refine when a multi-level numeric
factor survives, otherwise go straight to confirm. Iteration N+1 inherits
estimates and intervals rather than prose, which is a stronger form of
"use what N learned" than principle-passing alone.

Four triggers name the cases where Python cannot decide and the model
should be re-consulted: every factor within noise (wrong factor set),
significant lack of fit (wrong model form), stationary point outside the
declared hull (ranges too narrow), and a behavioral relation violation
(possible real non-monotonicity worth interpreting).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Artifacts — schemas, writers, and the findings projection

**Files:**
- Create: `orchestrator/schemas/design_matrix.schema.json`, `orchestrator/schemas/effects.schema.json`, `orchestrator/schemas/relations.schema.json`, `orchestrator/schemas/runs_row.schema.json`
- Create: `orchestrator/optimize/artifacts.py`
- Test: `tests/test_optimize_artifacts.py`

**Interfaces produced:**
- `write_design_matrix(iter_dir: Path, payload: dict) -> Path`
- `append_run(iter_dir: Path, row: dict) -> None` — appends one JSON line to `runs.jsonl`
- `read_runs(iter_dir: Path) -> list[dict]`
- `write_effects(iter_dir: Path, fit, *, factors, stage: str) -> Path`
- `write_relations(iter_dir: Path, verdicts) -> Path`
- `project_findings(fit, *, factors, stage, decision, iteration, bundle_ref) -> dict` — a `findings.schema.json`-conformant dict built deterministically from the fit
- `project_principle_updates(fit, *, factors, stage) -> dict`

**This is the task that makes "0 LLM calls at screen/refine" true while still writing the durable artifact set.** A fitted effect with a CI already contains a claim, a direction, a magnitude, and quantitative evidence, so restating it in prose costs tokens without adding information. Follows the pure-Python `meta_findings.py` (#155) precedent.

**Test assertions to write:**
1. `write_design_matrix` output validates against `design_matrix.schema.json`.
2. `append_run` then `read_runs` round-trips rows in order; the file is valid JSONL (one object per line).
3. Each appended row validates against `runs_row.schema.json`.
4. `write_effects` output validates against `effects.schema.json` and carries `pure_error_var`, `lack_of_fit_p`, and per-effect `ci_low`/`ci_high`.
5. `write_effects` records `aliases` when the design was fractional — the caveat must survive into the artifact.
6. `write_relations` output validates against `relations.schema.json` and records `native_test` per verdict.
7. `project_findings` output validates against the **existing** `findings.schema.json` (do not modify that schema).
8. `project_findings` emits one entry per surviving effect whose evidence string contains the estimate, the CI bounds, and the run count.
9. `project_findings` emits a NULL-result entry per dropped factor naming the noise floor it fell below.
10. `project_findings` sets `experiment_valid: false` when a correctness relation failed.
11. `project_principle_updates` output validates against `principles.schema.json` and every entry carries numeric evidence (so `validate_evidence`'s floor passes by construction).
12. Writing twice with identical input produces byte-identical files (determinism — no timestamps inside the payload body; timestamps belong to the enclosing envelope only where the existing schemas already require them).

- [ ] **Step 1: Write the four schemas**

Model them on the existing `orchestrator/schemas/*.schema.json` house style: `$schema`, `$id` under the project URL, `title`, `description` citing the spec, `required`, `additionalProperties: false`, and a `description` on every property. These are read by AI authors, so descriptions carry intent plus an example.

- [ ] **Step 2: Write the tests, run them (fail), implement `artifacts.py`, run again (pass)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_artifacts.py -q`

Implementation notes:
- Use `orchestrator.util.atomic_write` for every whole-file write, matching the rest of the codebase.
- `runs.jsonl` is append-only; never rewrite it. A crashed run must leave the completed rows intact.
- The findings projection must **not** invent prose. Each `discrepancy_analysis` / evidence string is assembled from numbers: estimate, CI, n, and the factor's declared statement.
- Determinism: sort effects by descending `abs(estimate)` for stable output ordering.

- [ ] **Step 3: Commit**

```bash
git add orchestrator/schemas/design_matrix.schema.json orchestrator/schemas/effects.schema.json orchestrator/schemas/relations.schema.json orchestrator/schemas/runs_row.schema.json orchestrator/optimize/artifacts.py tests/test_optimize_artifacts.py
git commit -m "$(cat <<'EOF'
feat(optimize): artifact schemas and the deterministic findings projection

Four new schemas (design_matrix, runs_row, effects, relations) plus writers
using atomic_write. runs.jsonl is append-only so a crash leaves completed
rows intact.

project_findings() is what makes "zero LLM calls at screen and refine" true
without dropping the durable artifact set: a fitted effect with a
confidence interval already contains a claim, a direction, a magnitude and
quantitative evidence, so restating it in prose would cost tokens and add
nothing. Pure Python, following the meta_findings (#155) precedent, and it
validates against the UNCHANGED findings schema -- so /post-campaign,
index-wiki, visualize-campaign and the registry keep working untouched.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: The tokenless execution loop

**Files:**
- Create: `orchestrator/optimize/runner.py`
- Test: `tests/test_optimize_runner.py`

**Interfaces produced:**
- `RunOutcome` frozen dataclass: `row_index: int`, `status: str` (`"complete"`|`"failed"`|`"infeasible"`|`"rejected"`), `response: dict`, `manipulation: list`, `invariants: list`, `duration_ms: int`, `error: str`
- `ConfigRunner` protocol: `__call__(row: ConfigRow) -> dict` — returns the observation dict (response metrics + telemetry)
- `execute_design(rows, *, runner, response_spec, invariants, factors, on_row=None, integrity_check=None, max_retries=1) -> list[RunOutcome]`
- `build_cache_key(row: ConfigRow, *, patch_hash: str) -> str`

**Test assertions to write** (all with an injected fake runner — no LLM, no subprocess):
1. `execute_design` calls the runner once per row and returns outcomes in row order.
2. A row whose manipulation predicate fails is retried once, then marked `failed` if it fails again.
3. A row whose manipulation predicate passes on retry is marked `complete`.
4. A row violating a `design_space` invariant is `rejected` and its response is **excluded** from the returned fitting inputs.
5. A row violating a `response.constraints` entry is `infeasible` but **retained** in the outcomes (it is real data about the space).
6. A response above `response.ceiling` is `rejected` with an error naming the ceiling — physically impossible means the instrumentation is lying.
7. A runner raising an exception yields `status == "failed"` with the exception type in `error`, and does not abort the remaining rows.
8. `on_row` callback fires once per completed row (this is how `runs.jsonl` gets appended incrementally).
9. `build_cache_key` is identical for two rows with the same levels and patch hash, and differs when any level or the patch hash changes.
10. A held-out metric present in the observation is recorded but **not** returned among fitting inputs (leakage guard at the execution boundary).
11. When `optimization.integrity_command` is declared, it runs once per config and a non-zero exit marks the row `rejected` with the command's stderr in `error`.
12. When `integrity_command` is absent, no integrity check runs and rows are unaffected (the field is optional).
13. An integrity failure is `rejected`, not `infeasible` — corrupt output is not data about the design space, so it must never reach the fitter.

- [ ] **Step 1: Write the tests in `tests/test_optimize_runner.py`**

The fake runner is a dict-driven callable: `{row_index: observation}`. Use a `_RecordingRunner` class following the `_ScriptedRunner` pattern in `tests/test_sdk_dispatch.py` so arguments are captured for assertion without coupling to internal call shapes.

- [ ] **Step 2–4: Run (fail), implement, run (pass)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_runner.py -q`

Implementation notes:
- Zero LLM involvement. The runner seam is injected exactly like `parallel_arms.run_units`' `runner` parameter, which is what makes this testable at all.
- Retry once on manipulation failure, then drop the **factor** (not the campaign) and let the caller refit with recomputed aliasing, per spec §6.4.
- Never raise out of the loop for a single bad row: partial failure degrades the claim (reported resolution drops, dropped factors named), it does not silently proceed.
- The leakage guard here is belt-and-braces with the validator: held-out metrics are stripped from fitting inputs at the point of observation, so they cannot reach `fit_effects` even if a caller is careless.
- `integrity_command` is the third guardrail alongside manipulation predicates and the ceiling check. Run it per config via the same injected seam as the runner (so tests inject a fake and never shell out), and treat a non-zero exit as `rejected`: corrupt output is not evidence about the design space, and admitting it would contaminate every effect estimate that includes that cell.
- `execute_design` takes an optional `integrity_check: Callable[[ConfigRow], tuple[bool, str]]`. Production wires it to a subprocess invocation of `integrity_command`; tests inject a callable. Never call `subprocess` directly from `execute_design`.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/optimize/runner.py tests/test_optimize_runner.py
git commit -m "$(cat <<'EOF'
feat(optimize): tokenless per-config execution loop

Expand row -> apply levels -> build (content-hash cached) -> run -> parse ->
check manipulation -> check invariants -> check constraints -> record. No
model call anywhere in the loop; that is where the budget win comes from.

Failure consequences are deliberately asymmetric (spec 6.4): an invariant
violation or above-ceiling response is rejected, a constraint violation is
infeasible-but-retained (real data about the space), a manipulation failure
retries once then drops the factor, and a crashed run degrades the claim
rather than aborting the sweep. Held-out metrics are stripped from fitting
inputs at the observation boundary so they cannot reach the fitter even via
a careless caller.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Campaign schema and validator

**Files:**
- Modify: `orchestrator/schemas/campaign.schema.yaml`
- Modify: `orchestrator/validate.py`
- Test: `tests/test_optimize_campaign_schema.py`

**Interfaces produced:**
- `validate.validate_optimization_campaign(campaign: dict) -> list[str]` — cross-field rules JSON Schema cannot express; returns actionable repair messages
- `validate.campaign_kind(campaign: dict) -> str` — `"reflective"` (default) or `"optimization"`

**Schema additions** (keep `additionalProperties: false` throughout):
- Top-level `kind: {type: string, enum: [reflective, optimization], default: reflective}`
- Top-level `optimization` object with `response`, `factors`, `design`, and optional `design_space`, `guidance`, `test_command`, `integrity_command`, `stages`
- `response`: required `primary` (`metric`, `direction`), optional `constraints`, `regimes`, `held_out`, `ceiling`, `noise_estimate_pct`
- `factors[]`: required `id`, `name`, `type` (enum `[numeric, choice]`), `levels` (minItems 2), `apply`, `manipulation`, `relations` (minItems 1); optional `grid`, `screen_levels`
- `relations[]`: required `id`, `kind` (enum `[correctness, behavioral]`), `statement`, `native_test`
- `design`: `screen` (`resolution`, `center_points`), `refine` (`kind`, `center_points`), `confirm` (`replicates`), optional `max_runs`
- `design_space`: `invariants[]` with required `id`, `statement`, `observable`, `op`, `value`
- `guidance`: optional `factor_nomination`, `interpretation` (strings only — exactly two slots, `additionalProperties: false`)
- Every `description` carries intent plus a concrete example and points to `docs/optimization-campaign-guide.md`.

**Cross-field rules in `validate_optimization_campaign`:**
1. `kind: optimization` requires an `optimization` block; `kind: reflective` (or absent) forbids one.
2. A `held_out` metric must not equal `response.primary.metric` nor appear in `constraints`/`regimes` — the leakage guard.
3. Every `screen_levels` entry must be a member of that factor's `levels`.
4. `refine.kind` requires ≥2 factors satisfying `is_refinable`; otherwise the message says to drop `refine` or add levels.
5. Each factor needs ≥1 `correctness` relation.
6. No `manipulation` or invariant predicate may be trivially true (`predicates.is_trivial`).
7. `design.screen.resolution < 5` with >1 factor produces a **warning** naming the aliased pairs — main-effects-only screening is the OFAT failure mode in disguise.
8. `min_runs_for(k, resolution)` exceeding `design.max_runs` is an **error** offering the two honest options (raise the budget, or accept the lower resolution and its named aliasing) — never a silent downgrade.
9. `complexity_tier` / `tier_justification` present under `kind: optimization` is an error (§7.2 — the tier ladder is reflective-only; do not half-adopt both disciplines).
10. A knob in `target_system.controllable_knobs` appearing in neither `factors` nor `locked_parameters` produces a **warning** (the "what did you forget to control" check).

**Test assertions to write:**
1. A minimal valid optimization campaign passes `jsonschema.validate` against the schema.
2. Every existing example campaign in `examples/` still validates (no `kind` → treated as reflective).
3. `type: ordinal` is rejected by the schema enum.
4. A factor with one level is rejected.
5. A relation without `native_test` is rejected.
6. `guidance` with a third slot is rejected (`additionalProperties: false`).
7. Each of the ten cross-field rules above: one test per rule, asserting the message contains the actionable hint (not just that it failed).
8. `campaign_kind` returns `"reflective"` for a campaign with no `kind`.
9. The full `§11` worked example from the spec validates end-to-end. **Extract it programmatically** from the spec file so the doc and the schema cannot drift:
   ```python
   import re, yaml
   spec = (Path(__file__).parents[1] / "docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md").read_text()
   blocks = re.findall(r"```yaml\n(.*?)```", spec, re.S)
   candidates = [yaml.safe_load(b) for b in blocks]
   full = [c for c in candidates if isinstance(c, dict) and "research_question" in c]
   assert full, "spec must contain a complete worked example"
   ```
   Then assert each such campaign passes both the schema and `validate_optimization_campaign` with zero errors.

- [ ] **Step 1: Write the tests, run them (fail)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_campaign_schema.py -q`

- [ ] **Step 2: Add the schema block, run again**

- [ ] **Step 3: Add `validate_optimization_campaign` + `campaign_kind` to `validate.py`, run again (pass)**

Place them beside the existing `_validate_locked_parameters` family and follow its return-list-of-strings convention. Distinguish errors from warnings the way `compute_campaign_spec_diff` already does.

- [ ] **Step 4: Run the full suite, then commit**

```bash
/opt/homebrew/bin/pytest -q
git add orchestrator/schemas/campaign.schema.yaml orchestrator/validate.py tests/test_optimize_campaign_schema.py
git commit -m "$(cat <<'EOF'
feat(schema): kind field and the optimization campaign block

Adds kind: [reflective, optimization] defaulting to reflective, so every
existing campaign is unaffected, plus the optimization block (response,
factors, design, design_space, guidance).

Ten cross-field rules JSON Schema cannot express live in
validate_optimization_campaign, each returning an actionable repair message
because these campaigns are authored by AI and a bare rejection is not
actionable. Two are load-bearing: held-out metrics may not appear in any
fitting input (the symphony-generation leakage class), and a resolution
whose run count exceeds max_runs is an error offering the two honest
options rather than a silent downgrade.

complexity_tier under kind: optimization is rejected -- the #159 tier
ladder is reflective-only, and a pre-registered design matrix strengthens
the anti-p-hacking property the ladder protects.

A test extracts the spec's worked example programmatically and validates
it, so the authoring documentation and the schema cannot drift.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Wire into `iteration.py` and kind-scoped gate defaults

**Files:**
- Modify: `orchestrator/iteration.py` (delegation at `run_iteration`, ~line 1106; tier guard at ~line 1352)
- Modify: `orchestrator/cli.py` (flags at ~lines 1072, 1130)
- Modify: `orchestrator/campaign.py` (gate default resolution)
- Create: `orchestrator/optimize/stage_runner.py` — the `run_stage` entry point re-exported from `__init__`
- Test: `tests/test_optimize_iteration.py`, `tests/test_optimize_gate_defaults.py`

**Interfaces produced:**
- `optimize.run_stage(campaign, work_dir, *, iteration, stage, dispatcher, runner, auto_approve, gate) -> IterationOutcome`
- `cli.resolve_gate_mode(args, campaign) -> bool` — returns effective `auto_approve`

**Gate-default resolution order** (spec §7.1): `--interactive` > explicit `--auto-approve` > kind default (`optimization` → auto-approve on; `reflective` → off). This requires changing `--auto-approve` from `store_true` to `default=None` so "not supplied" is distinguishable from "supplied false"; without that the kind default would clobber an explicit choice.

**Test assertions to write:**

*`tests/test_optimize_gate_defaults.py`:*
1. `resolve_gate_mode` returns `True` for `kind: optimization` with no flags.
2. Returns `False` for `kind: reflective` with no flags.
3. Returns `False` for `kind: optimization` with `--interactive`.
4. Returns `True` for `kind: reflective` with explicit `--auto-approve`.
5. `--interactive` beats `--auto-approve` for both kinds.
6. A campaign with no `kind` behaves exactly as `reflective`.

*`tests/test_optimize_iteration.py`* (end-to-end, `StubDispatcher` + fake runner, zero LLM calls):
7. A four-stage optimization campaign runs to completion and the engine reaches `DONE`.
8. After the run, each `runs/iter-N/` contains `design_matrix.json`, `runs.jsonl`, `effects.json`, `relations.json`, and `findings.json`.
9. Every one of those files schema-validates.
10. `ledger.json` has one row per completed iteration.
11. `meta_findings.json` exists at the campaign root (terminal-transition artifact preserved).
12. `best_found.json` exists and its `top_k` is ordered by descending score.
13. `state.json` records the stage for each iteration.
14. A correctness-relation failure at `verify` aborts the campaign and no `screen` runs execute.
15. A design-matrix fidelity violation hard-fails **even with `auto_approve=True`** — the #246 discipline extended to the matrix.
16. A `behavioral` relation violation does **not** abort; it appears in `findings.json`.

- [ ] **Step 1: Write both test files, run them (fail)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_iteration.py tests/test_optimize_gate_defaults.py -q`

- [ ] **Step 2: Add the delegation branch at the top of `run_iteration`**

Insert immediately after the existing `agent` validation, before any state inspection:

```python
    # kind: optimization delegates the whole iteration to the factorial
    # stage runner (spec §4). The reflective path below is untouched.
    from orchestrator.validate import campaign_kind
    if campaign_kind(campaign) == "optimization":
        from orchestrator.optimize import run_stage
        from orchestrator.optimize.stage import stage_for_iteration
        return run_stage(
            campaign, work_dir,
            iteration=iteration,
            stage=stage_for_iteration(campaign, iteration),
            model=model, timeout=timeout, agent=agent,
            auto_approve=auto_approve, max_cli_retries=max_cli_retries,
        )
```

- [ ] **Step 3: Scope the tier panel to the reflective kind**

At the `format_tier_summary` call site (~line 1352), the optimization path never reaches it because of the early return in Step 2. Add a comment recording that, so a future reader does not add a second call:

```python
        # Issue #159: complexity-tier panel. Reflective-kind only — the
        # optimization kind returns early in run_stage (spec §7.2), since a
        # pre-registered design matrix strengthens the anti-p-hacking
        # property this ladder protects rather than needing it.
```

- [ ] **Step 4: Change the CLI flags**

```python
    p_run.add_argument(
        "--auto-approve", action="store_const", const=True, default=None,
        help="Auto-approve all human gates. Default for kind: optimization "
             "campaigns; opt-in for kind: reflective. See "
             "'--auto-approve safety preconditions' (#255 / F10).",
    )
    p_run.add_argument(
        "--interactive", action="store_true",
        help="Force interactive gates even for kind: optimization campaigns.",
    )
```

Mirror both on `p_resume`. Then route both call sites (`cli.py:265`, `cli.py:360`) through `resolve_gate_mode(args, campaign)`.

- [ ] **Step 5: Implement `stage_runner.py`, run the tests (pass)**

The stage runner composes the earlier tasks and owns the phase transitions:
`DESIGN` (verify/confirm: one model call; screen/refine: matrix generation only) → `HUMAN_DESIGN_GATE` → `EXECUTE_ANALYZE` (the tokenless loop) → `HUMAN_FINDINGS_GATE` → `DONE`. Reuse `_enter_phase`, `Engine`, `HumanGate`, `append_ledger_row`, and the existing `best_found` / `meta_findings` writers rather than reimplementing any of them.

- [ ] **Step 6: Run the full suite, then commit**

```bash
/opt/homebrew/bin/pytest -q
git add orchestrator/iteration.py orchestrator/cli.py orchestrator/campaign.py orchestrator/optimize/stage_runner.py tests/test_optimize_iteration.py tests/test_optimize_gate_defaults.py
git commit -m "$(cat <<'EOF'
feat(optimize): wire the optimization kind into the iteration loop

One early delegation branch in run_iteration; the reflective path's code is
not modified. The four stages reuse the existing Engine, gates, ledger,
best_found and meta_findings machinery, so the durable artifact set lands
unchanged and /post-campaign keeps working.

Gate defaults become kind-scoped rather than flipping the global flag:
optimization campaigns auto-approve (no per-stage human decision changes
what happens next), reflective keeps opt-in, and a new --interactive forces
prompting for either. --auto-approve moves from store_true to default=None
so an explicit choice is distinguishable from an absent one and the kind
default cannot clobber it.

Matrix-fidelity violations hard-fail even under auto-approve, extending the
#246 spec-fidelity discipline from locked_parameters to the design matrix.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Reflective-path regression gate

**Files:**
- Test: `tests/test_optimize_no_regression.py`

This task adds no production code. Its only job is to prove the central architectural guarantee: **a campaign without `kind` behaves exactly as it does today.**

**Test assertions to write:**
1. Every campaign yaml under `examples/` validates against the updated schema.
2. `campaign_kind` returns `"reflective"` for each of them.
3. `validate_optimization_campaign` returns `[]` (not an error) for a reflective campaign with no `optimization` block.
4. `validate_design` on an existing reflective fixture produces the same result before and after the change — assert against the fixture's known-good expected output, not a snapshot of current behavior.
5. `resolve_gate_mode` with no flags on a reflective campaign is `False`, matching today's `store_true` default.
6. An end-to-end reflective iteration via `StubDispatcher` still writes `bundle.yaml`, `findings.json`, `principle_updates.json`, and a ledger row.
7. `format_tier_summary` is still exercised on the reflective path (assert the gate panel content appears for a reflective campaign with a `complexity_tier`).

- [ ] **Step 1: Write the tests**

- [ ] **Step 2: Run them**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_no_regression.py -q`
Expected: all pass. Any failure here means the optimization work leaked into the reflective path — fix the leak, never the test.

- [ ] **Step 3: Run the entire suite one final time**

Run: `/opt/homebrew/bin/pytest -q`
Expected: the full suite green, including all 79 pre-existing test files.

- [ ] **Step 4: Commit**

```bash
git add tests/test_optimize_no_regression.py
git commit -m "$(cat <<'EOF'
test: prove the reflective path is unchanged by the optimization kind

The central architectural guarantee of the optimize/ subpackage is that a
campaign with no kind field behaves exactly as before. This asserts it
directly: existing examples still validate, campaign_kind defaults to
reflective, gate defaults match the old store_true behaviour, the tier
panel still renders on the reflective path, and an end-to-end reflective
iteration still produces its full artifact set.

A failure here means optimization work leaked into the shared path.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: The authoring guide

**Files:**
- Create: `docs/optimization-campaign-guide.md`
- Modify: `README.md`, `CLAUDE.md`, `docs/data-model.md`
- Test: `tests/test_optimize_guide_examples.py`

Optimization campaigns will be authored by AI, so the guide **is** the authoring interface and ambiguity in it produces invalid campaigns rather than a human who asks a clarifying question. It is a first-class deliverable, not documentation-after-the-fact.

**Guide contents:**
1. **Mental model** — why factorial beats OFAT; the composition barrier; screen → refine → confirm; where the tokens go (~3 substantive model calls against 60–90 runs, with iter-1 carrying nearly all the cost).
2. **Field-by-field walkthrough** of the `optimization` block, each field with intent + a concrete example.
3. **Four worked end-to-end examples**, each a complete, valid campaign yaml:
   - *multi-level grid* — `candidate-threshold-robustness`, 1350 cells → ~40 runs
   - *categorical mechanism factorial* — `ordering-theorem`, whose headline finding is a 7.3× interaction that a main-effects screen inverts
   - *constrained multi-regime* — `composite-sensitivity-boundary`, where the answer is a per-regime trade
   - *binary throughput levers* — the Certus cold-read case, including the L5 sign flip
4. **"Declare as factor vs lock vs assert as invariant"** inventory, mirroring the #245 "what to lock" inventory, with the decision test: *would you be upset to discover this was violated after 60 runs?*
5. **Steering** — the three channels (`guidance` shapes what the model proposes; `design_space.invariants` bound what Python executes; `target_system.description` carries narrative framing).
6. **Anti-patterns**, each with a wrong/right pair:
   - trivial manipulation predicates (`> 0`)
   - held-out leakage
   - main-effects-only screening when interactions are expected
   - monotonicity misclassified as `correctness` (would have hard-failed on L5 — the study's single most important finding)
   - treating a constrained multi-regime conjunction as a scalar objective
   - putting an enforceable directive in `guidance` instead of `invariants` (the #221 failure mode)
   - `type: numeric` on a factor whose levels include a non-numeric sentinel like `off`

**Test assertions to write** — the guide's examples must be executable truth, not prose:
1. Extract every ```yaml block from the guide; each must parse.
2. Every block that is a complete campaign (has `research_question`) must pass the campaign schema.
3. Every such campaign must pass `validate_optimization_campaign` with zero errors.
4. Every factor in every example must have ≥1 `correctness` relation and a non-trivial `manipulation` predicate (asserted via `predicates.is_trivial`).
5. No example may use the retired `ordinal` / `categorical` / `continuous` type vocabulary.
6. No example may name a `held_out` metric anywhere in `primary`, `constraints`, or `regimes`.

This test is why the guide can be trusted: an example that would fail its own validator is the single most damaging thing a doc for AI authors can contain. (This check already earned its keep during design review — it caught a spec example whose factor declared only a `behavioral` relation.)

- [ ] **Step 1: Write `tests/test_optimize_guide_examples.py` first**

TDD applies to documentation here: the test defines what a correct example is, then the guide satisfies it.

- [ ] **Step 2: Run it (fail — no guide yet)**

Run: `/opt/homebrew/bin/pytest tests/test_optimize_guide_examples.py -q`
Expected: failure on the missing file.

- [ ] **Step 3: Write the guide**

- [ ] **Step 4: Run the test (pass)**

Fix the **guide**, never the test, when an example fails.

- [ ] **Step 5: Add the cross-links**

- `README.md` — one line in the docs list.
- `CLAUDE.md` — a short `## Optimization campaigns (kind: optimization)` section noting that the tier ladder is reflective-only and pointing at the guide.
- `docs/data-model.md` — the four new artifacts and their schemas.

- [ ] **Step 6: Run the full suite, then commit**

```bash
/opt/homebrew/bin/pytest -q
git add docs/optimization-campaign-guide.md tests/test_optimize_guide_examples.py README.md CLAUDE.md docs/data-model.md
git commit -m "$(cat <<'EOF'
docs: authoring guide for kind: optimization campaigns

These campaigns are authored by AI, so the guide is the authoring
interface: ambiguity produces invalid campaigns rather than a human who
asks a clarifying question. Four complete worked examples drawn from the
real corpus (candidate-threshold-robustness' 1350-cell grid,
ordering-theorem's 7.3x interaction, composite-sensitivity-boundary's
per-regime trade, and the Certus L5 sign flip), a factor-vs-lock-vs-invariant
inventory, and seven anti-patterns with wrong/right pairs.

A test extracts every yaml block and asserts it parses, schema-validates,
passes the cross-field validator, uses no retired type vocabulary, and
leaks no held-out metric. An example that fails its own validator is the
most damaging thing a doc for AI authors can contain -- this check already
caught one during design review.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification checklist

Run before declaring the feature complete:

- [ ] `/opt/homebrew/bin/pytest -q` — full suite green
- [ ] `/opt/homebrew/bin/pytest tests/test_optimize_*.py -q` — all new tests green
- [ ] Alias oracle: `res V` on 5 factors is 16 runs with **zero** aliases; `res III` on 7 factors is 8 runs with 21 aliases
- [ ] L5 oracle: `fit_effects` recovers main `-0.95` and interaction `+1.60` from the planted model
- [ ] Reflective regression: `tests/test_optimize_no_regression.py` green
- [ ] `git grep -n "numpy\|statsmodels\|pandas\|pyDOE3\|hypothesis" orchestrator/` returns nothing
- [ ] `git diff main --stat -- orchestrator/iteration.py` shows only the delegation branch and the tier comment
- [ ] Guide examples: `tests/test_optimize_guide_examples.py` green
- [ ] All three guardrails fire in tests: manipulation predicate, `integrity_command`, and `response.ceiling`
- [ ] Leakage guard proven at both layers: validator rejects a `held_out` metric in a fitting input, and `execute_design` strips it at the observation boundary
- [ ] An end-to-end stub campaign leaves a complete, schema-valid artifact set that `/post-campaign` can index

## Notes for the implementer

**Three snippets are deliberately indented fragments**, not standalone modules: the `run_iteration` delegation branch (Task 11 Step 2), the tier-panel comment (Task 11 Step 3), and the CLI flag definitions (Task 11 Step 4). Insert them at the indicated call sites at the surrounding indentation level rather than pasting them at module top level.

**When a test and the implementation disagree, the test is usually right.** Three assertions encode externally-verified oracles and must not be weakened to make code pass:
- resolution V on 5 factors → 16 runs, zero aliases (published generator `E=ABCD`)
- resolution III on 7 factors → 8 runs, 21 aliased pairs (Box–Hunter–Hunter)
- `fit_effects` recovers planted main `-0.95` **and** interaction `+1.60` from the same fit

If one fails, the generator table or the fitter is wrong. Fix the code.

**Float comparisons.** The closed-form estimator carries ~8.9e-16 representation error (measured). Every numeric assertion uses `math.isclose(..., rel_tol=1e-9, abs_tol=1e-12)`; `==` will be intermittently flaky and must not appear in a float assertion.
