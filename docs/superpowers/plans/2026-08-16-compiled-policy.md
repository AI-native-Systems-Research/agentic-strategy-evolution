# Compiled Experimental Policies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `nousko` branch's fixed-schedule factorial DOE into the paper's compiled, decision-directed experimental policy — with a synthetic-target oracle proving it, an argmax-over-valid-space recommendation, a residual-regret certificate, terminal discrimination over finalists, foldover-when-consequential, epoch/exception semantics, build-stage oracles, and readiness for vLLM/Qdrant/Knative-class targets.

**Architecture:** `policy.json` is data compiled by pure Python at the end of `verify` and interpreted by a pure `step()` function over a closed observation vocabulary; `stage_runner.run_stage` becomes the interpreter's executor. A synthetic target (`synthetic.py` + `harness.py`) with known optima is the oracle for every statistical claim. New modules `decide.py` (argmax over $\mathcal X_{valid}$) and `certificate.py` (regret bounds) feed a generalized `confirm` (shortlist + fresh replicates + Holm bound) and an inline `report`/`exception` terminal.

**Tech Stack:** Python 3.11+, stdlib + `scipy.stats` (already a dependency via `effects.py`), `jsonschema` (already used for artifact schemas), pytest. No numpy in the harness (existing convention).

**Spec:** `docs/superpowers/specs/2026-08-16-compiled-policy-design.md` — read it first; every task below cites a section of it. The paper is `../papers/nousko/paper.tex` (outside this repo).

## Global Constraints

- **No test may make a live LLM call** (CLAUDE.md). The synthetic target and every harness test are zero-LLM by construction. `build` remains the only model call; tests of it use `sdk_runner=` fakes.
- **Behavioral tests only**: assert artifacts on disk, returned dataclasses, schema conformance. Never assert mock call shapes.
- **No numpy** in `orchestrator/optimize/` (existing convention: closed-form/Gaussian elimination; `scipy.stats` is allowed for distributions).
- **Backward compatibility is not the goal; correctness against the spec is** (spec §2.7, added after Task 6: `nous` has not GA'd, so nothing depends on today's observable output being stable). Every existing test in `tests/test_optimize_*.py` must keep passing OR have its assertion consciously changed with a stated, spec-correct reason in the task report — silent weakening is still forbidden, but an explained behaviour change is no longer a risk to justify against a preservation bar. Legacy `optimization.stages` lists keep working because the spec requires it (§3.1's registration guarantee), not because of a backward-compat rule.
- **Zero model tokens inside an epoch**: no task may add a dispatcher/SDK call to any state other than `build`.
- **Every hard-fail fires under `auto_approve=True`** (the kind's default).
- Run the full suite with `python -m pytest tests/ -q -x` before every commit. Branch: `nousko`. Commit messages follow the existing `feat(optimize):` / `fix(optimize):` / `test(optimize):` / `docs(optimize):` style.
- Python style: `from __future__ import annotations`, frozen dataclasses for value types, module docstrings that say *why* (match neighbours).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `orchestrator/optimize/synthetic.py` (new) | Surfaces with known optima; in-process `ConfigRunner`; `python -m` CLI | 2 |
| `orchestrator/optimize/harness.py` (new) | Drive a full synthetic campaign through `run_stage`; return recommendation vs truth | 3 |
| `orchestrator/schemas/policy.schema.json` (new) | Shape of `policy.json` | 4 |
| `orchestrator/optimize/policy.py` (new) | `compile_policy`, `policy_hash`, `step`, `check_policy`, `enumerate_paths`, transitions I/O | 4, 5 |
| `orchestrator/optimize/stage_runner.py` (modify) | Compile at verify; resolve state from transitions; record transitions; inline `report`/`exception`; generalized `confirm` | 6, 9, 10, 11, 12, 14 |
| `orchestrator/optimize/stage.py` (modify) | Expose observations dict from `StageDecision`; add `Stage.FOLDOVER/REPORT/EXCEPTION` | 5, 10, 11 |
| `orchestrator/optimize/decide.py` (new) | `predict`, `candidates`, `recommend`, `alias_consequential` | 7, 10 |
| `orchestrator/optimize/certificate.py` (new) | `model_regret_bound`, `terminal_regret_bound`, `resolve_epsilon` | 8, 9 |
| `orchestrator/optimize/design.py` (modify) | `foldover()` | 10 |
| `orchestrator/optimize/build.py` (modify) | mechanism patch + hash; pre-build test snapshot; baseline equivalence | 12, 13 |
| `orchestrator/optimize/matrix.py` (modify) | workload seed per row | 14 |
| `orchestrator/optimize/runner.py` (modify) | inject workload seed env | 14 |
| `orchestrator/validate.py` (modify) | rules 13–16 (baseline, policy block, workload, shortlist) | 9, 13, 14 |
| `orchestrator/schemas/campaign.schema.yaml` (modify) | `optimization.policy`, `known_valid_baseline`, `workload`, `design.confirm.shortlist_size` | 9, 13, 14 |
| `orchestrator/campaign.py` (modify) | `max_iterations` floor from policy longest path | 6 |
| `examples/optimization/*.yaml`, `docs/targets.md` (new) | systems-target campaigns | 15 |
| `CLAUDE.md`, `docs/optimization-campaign-guide.md`, `docs/data-model.md` (modify) | truth-in-docs; policy docs | 1, 16 |
| `tests/test_optimize_synthetic.py`, `test_optimize_harness.py`, `test_optimize_policy.py`, `test_optimize_decide.py`, `test_optimize_certificate.py`, `test_optimize_foldover.py`, `test_optimize_epoch.py`, `test_optimize_build_oracles.py`, `test_optimize_workload.py`, `test_optimize_examples.py` (new) | | 2–15 |

Interfaces shared across tasks (exact names — later tasks depend on them):

```python
# synthetic.py
@dataclass(frozen=True)
class Surface:
    name: str
    factors: tuple[dict, ...]            # raw factor dicts as in campaign YAML
    fn: Callable[[dict], float]          # levels -> noiseless response
    noise_sd: float = 0.0
    drift_per_run: float = 0.0           # added as drift_per_run * run_counter
    invalid: Callable[[dict], bool] | None = None   # levels -> True if not in X_valid
    exception_at: dict | None = None     # levels subset that makes the target emit NaN
    direction: str = "maximize"
SURFACES: dict[str, Callable[[], Surface]]
def candidate_grid(factors_raw: list[dict], *, max_numeric_points: int = 9) -> list[dict]
def true_optimum(surface: Surface) -> tuple[dict, float]
def make_synthetic_runner(surface: Surface, *, seed: int) -> Callable[[ConfigRow], dict]

# harness.py
@dataclass(frozen=True)
class SyntheticResult:
    recommendation: dict; basis: str; residual_regret: float | None
    residual_regret_terminal: float | None; true_optimum: dict; true_best: float
    true_gap: float; path: list[str]; work_dir: Path; report: dict
def synthetic_campaign(surface: Surface, **overrides) -> dict
def run_synthetic_campaign(surface: Surface, *, seed: int, parent_dir: Path,
                           campaign_overrides: dict | None = None,
                           max_iterations: int = 8) -> SyntheticResult

# policy.py
OBSERVATION_KEYS: frozenset[str]
def compile_policy(campaign: dict, *, mechanism_patch_hash: str = "", epoch: int = 1) -> dict
def policy_hash(policy: dict) -> str
def write_policy(work_dir: Path, policy: dict) -> Path
def read_policy(work_dir: Path) -> dict | None
def check_policy(policy: dict) -> list[str]
def step(policy: dict, state: str, observations: dict) -> tuple[str, dict]
def enumerate_paths(policy: dict, *, max_len: int = 12) -> list[list[str]]
def longest_path(policy: dict) -> int
def append_transition(work_dir: Path, row: dict) -> None
def read_transitions(work_dir: Path) -> list[dict]
def current_state(policy: dict, work_dir: Path) -> str
def pre_epoch_stages(campaign: dict) -> list[str]

# decide.py
@dataclass(frozen=True)
class Candidate: levels: dict; coded: dict; predicted: float
def predict(fit: Fit, coded: dict) -> float
def candidates(fit_ids, factors, *, held_fixed: dict, exclude_levels: list[dict] = ()) -> list[Candidate]
def recommend(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
              exclude_levels: list[dict] = ()) -> Candidate
def alias_consequential(fit: Fit, factors, *, direction, fitted_ids, held_fixed) -> list[tuple[str, str]]

# certificate.py
@dataclass(frozen=True)
class RegretBound: value: float | None; challenger: dict | None; delta: float; method: str; detail: str
def model_regret_bound(fit: Fit, cands: list[Candidate], xhat: Candidate, *, delta: float, direction: str) -> RegretBound
def terminal_regret_bound(samples: dict[str, list[float]], best: str, *, delta: float, direction: str, paired: bool) -> RegretBound
def resolve_epsilon(spec: dict, reference: float) -> float
```

---

## Phase 0 — Truth in docs

### Task 1: Remove the phantom model calls from the docs

**Files:**
- Modify: `orchestrator/optimize/stage_runner.py:15-18`
- Modify: `CLAUDE.md` (section "Optimization campaigns (kind: optimization)")
- Modify: `docs/optimization-campaign-guide.md` (call table near line 155; `guidance.interpretation` mentions near lines 328, 1092)
- Modify: `orchestrator/campaign.py:56-65` (comment above `OPTIMIZATION_MODEL`)
- Test: `tests/test_optimize_docs_claims.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing test** — the docs must not claim calls the code does not make.

```python
"""The guide/CLAUDE.md must describe the model calls the kind actually makes.

Spec §1: the branch's docs claimed verify and confirm each make a model call;
neither does. This test greps for the retired claims so they cannot return.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED = [
    "one model call interprets the fitted surface",
    "one model call authors the mechanism + its native tests.",  # was attributed to verify
    "interpretation (at the end) | 1",
]


def test_docs_do_not_claim_verify_or_confirm_model_calls():
    for rel in ("CLAUDE.md", "docs/optimization-campaign-guide.md",
                "orchestrator/optimize/stage_runner.py"):
        text = (ROOT / rel).read_text()
        for phrase in RETIRED:
            assert phrase not in text, f"{rel} still says {phrase!r}"


def test_claude_md_states_the_true_call_count():
    text = (ROOT / "CLAUDE.md").read_text()
    assert "the only model call in the kind is `build`" in text
```

- [ ] **Step 2: Run it** — `python -m pytest tests/test_optimize_docs_claims.py -q` → FAIL (phrases present).

- [ ] **Step 3: Edit the docs.** In `stage_runner.py` replace the four-bullet list with:

```
  * ``build``   — the ONLY model call in this kind: authors the mechanism and
                  its native tests (opt-in; see build.py).
  * ``verify``  — pure Python: runs test_command, reconciles relations, and
                  compiles the experimental policy (policy.py).
  * ``screen`` / ``foldover`` / ``refine`` / ``confirm`` — spending states of
                  the compiled epoch. ZERO model calls.
  * ``report`` / ``exception`` — inline terminal states. ZERO model calls.
```

In `CLAUDE.md`'s optimization section replace "Substantive model calls per campaign: ~3, against 60–90 tokenless benchmark runs." with "**Model calls per campaign: 0 without `build`, 1 with it — the only model call in the kind is `build`.** Compilation of the experimental policy is deterministic Python; every state inside the compiled epoch is tokenless (see `docs/superpowers/specs/2026-08-16-compiled-policy-design.md`)." Also replace "the model proposes factors once (stage `verify`) … and the model interprets the fitted surface once at the end" with "the campaign author (human or an AI writing the YAML) declares factors; `verify` certifies them and compiles the policy; Python drives the epoch; `report` writes the recommendation and its residual-regret certificate". In the guide, change the call table row `interpretation (at the end) | 1` to `report (at the end) | 0 | pure Python: recommendation + certificate` and mark `guidance.interpretation` / `guidance.factor_nomination` as "**reserved, not read by any stage**". In `campaign.py` comment: "one `build` (which authors …), and nothing else — verify/screen/refine/confirm/report are tokenless".

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_docs_claims.py tests/test_optimize_guide_examples.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "docs(optimize): the only model call in the kind is build"`.

---

## Phase 1 — The oracle: synthetic target and harness

### Task 2: Synthetic surfaces with known optima

**Files:**
- Create: `orchestrator/optimize/synthetic.py`
- Test: `tests/test_optimize_synthetic.py`

**Interfaces:**
- Consumes: `orchestrator.optimize.matrix.ConfigRow`, `orchestrator.optimize.factors.parse_factors`, `snap_to_grid`.
- Produces: `Surface`, `SURFACES`, `candidate_grid`, `true_optimum`, `make_synthetic_runner`, `main` (see File Structure block).

Surfaces (spec §3.5, each named for the failure it catches):

| key | factors | fn (levels → m) | catches |
|---|---|---|---|
| `additive` | A∈[2,16] numeric grid 1 (levels 2,4,8,16); B∈[2,16] same; C choice off/on | `10 - 0.05A + 0.20B + (2 if C=="on" else 0)` | baseline sanity |
| `interaction_only` | A,B,C,D numeric 2-level [2,16] | `10 + 0.02*A*B` (mains null when centred) | res-IV aliasing consequential → foldover |
| `bowl` | A,B numeric levels 2,4,8,16 grid 1 | `20 - 0.05*(A-9)**2 - 0.05*(B-11)**2` | refine → confirm at interior max (A=9,B=11) |
| `bowl_out_of_hull` | same factors | `20 - 0.05*(A-30)**2 - 0.05*(B-11)**2` | optimum outside hull → exception |
| `saddle` | A,B numeric levels 2,4,8,16 grid 1 | `10 + 0.05*(A-9)**2 - 0.05*(B-11)**2` | stationary point ≠ argmax |
| `choice_x_numeric` | A numeric levels 2,4,8,16; C choice off/on | `10 + (0.5*A if C=="on" else -0.5*A)` | held-fixed choice loses the optimum |
| `drift` | A,B numeric 2-level | `additive`-like + `drift_per_run=0.05` | randomization protects the fit |
| `sla` | A,B numeric levels 2,4,8,16; observation also emits `p99_ms = 2*A + B` | `10 + 0.5*A + 0.2*B`, invalid when `p99_ms > 40` | argmax restricted to valid |
| `nan_at_corner` | A,B numeric 2-level | additive; `exception_at={"A":16,"B":16}` emits NaN | semantic exception ends the epoch |

- [ ] **Step 1: Write the failing tests**

```python
"""The synthetic target is the oracle for the whole optimization kind.

Every surface knows its own optimum, so a campaign's recommendation can be
judged against truth rather than against artifacts. Zero LLM, zero subprocess
in the in-process runner; the CLI exists so the same surface can be a real
run_command for smoke tests.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys

import pytest

from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.synthetic import (
    SURFACES, Surface, candidate_grid, make_synthetic_runner, true_optimum,
)


def _row(levels, idx=0):
    return ConfigRow(row_index=idx, levels=dict(levels), role="corner",
                     replicate=0, apply={})


@pytest.mark.parametrize("key", sorted(SURFACES))
def test_every_surface_declares_parseable_factors_and_a_reachable_optimum(key):
    from orchestrator.optimize.factors import parse_factors
    s = SURFACES[key]()
    parse_factors(list(s.factors))                      # valid campaign factors
    opt, best = true_optimum(s)
    assert set(opt) == {f["id"] for f in s.factors}
    assert math.isfinite(best)
    if s.invalid is not None:
        assert not s.invalid(opt)                       # optimum is inside X_valid


def test_true_optimum_of_the_saddle_is_a_corner_not_the_stationary_point():
    s = SURFACES["saddle"]()
    opt, best = true_optimum(s)
    # f = 10 + 0.05(A-9)^2 - 0.05(B-11)^2 : max at A far from 9, B near 11
    assert opt["A"] in (2, 16) and opt["B"] in (8, 16)
    assert best > s.fn({"A": 9, "B": 11})


def test_runner_emits_metric_manipulation_observables_and_seeded_noise():
    s = SURFACES["additive"]()
    r1 = make_synthetic_runner(s, seed=1)
    r2 = make_synthetic_runner(s, seed=1)
    o1 = r1(_row({"A": 4, "B": 8, "C": "on"}))
    o2 = r2(_row({"A": 4, "B": 8, "C": "on"}))
    assert o1["cfg"] == {"a": 4, "b": 8, "c": "on"}
    assert o1["m"] == o2["m"]                            # same seed, same noise
    assert abs(o1["m"] - s.fn({"A": 4, "B": 8, "C": "on"})) < 5 * s.noise_sd + 1e-9


def test_drift_surface_adds_run_counter_drift():
    s = SURFACES["drift"]()
    r = make_synthetic_runner(s, seed=0)
    first = r(_row({"A": 2, "B": 2}))["m"]
    for _ in range(9):
        r(_row({"A": 2, "B": 2}))
    tenth = r(_row({"A": 2, "B": 2}))["m"]
    assert tenth - first == pytest.approx(10 * s.drift_per_run, abs=6 * s.noise_sd)


def test_nan_surface_emits_nan_only_at_the_declared_corner():
    s = SURFACES["nan_at_corner"]()
    r = make_synthetic_runner(s, seed=0)
    assert math.isnan(r(_row({"A": 16, "B": 16}))["m"])
    assert math.isfinite(r(_row({"A": 2, "B": 16}))["m"])


def test_sla_surface_emits_the_constraint_observable():
    s = SURFACES["sla"]()
    obs = make_synthetic_runner(s, seed=0)(_row({"A": 16, "B": 16}))
    assert obs["p99_ms"] == 2 * 16 + 16
    assert s.invalid({"A": 16, "B": 16}) is True


def test_candidate_grid_enumerates_declared_levels_and_snapped_interior():
    s = SURFACES["bowl"]()
    grid = candidate_grid(list(s.factors))
    assert {"A": 2, "B": 2} in grid and {"A": 16, "B": 16} in grid
    assert {"A": 9, "B": 11} in grid                    # interior grid point


def test_cli_emits_the_same_json_as_the_in_process_runner():
    s = SURFACES["additive"]()
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.optimize.synthetic",
         "--surface", "additive", "--seed", "3", "--a=4", "--b=8", "--c=on"],
        capture_output=True, text=True, check=True,
    )
    obs = json.loads(proc.stdout.strip().splitlines()[-1])
    assert obs["m"] == make_synthetic_runner(s, seed=3)(_row({"A": 4, "B": 8, "C": "on"}))["m"]
```

- [ ] **Step 2: Run** `python -m pytest tests/test_optimize_synthetic.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `orchestrator/optimize/synthetic.py`**

```python
"""Synthetic targets with KNOWN response surfaces — the oracle for this kind.

Why this module exists
----------------------
Every "observed on a real campaign" comment in this package records a bug the
test suite did not catch, because the tests checked artifacts and mocks and
nothing checked the ANSWER. A surface whose optimum is known lets a test
assert that the recommendation lands on it, that the certificate covers it,
and that the policy took the branch it should — with zero LLM calls and zero
subprocesses (in-process runner) or, through ``python -m``, as a real
``run_command`` for ``nous validate --smoke``.

Each surface is named for the historical failure it catches (see the table
in docs/superpowers/plans/2026-08-16-compiled-policy.md, Task 2).
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestrator.optimize.factors import snap_to_grid


@dataclass(frozen=True)
class Surface:
    name: str
    factors: tuple[dict, ...]
    fn: Callable[[dict], float]
    noise_sd: float = 0.0
    drift_per_run: float = 0.0
    invalid: Callable[[dict], bool] | None = None
    exception_at: dict | None = None
    direction: str = "maximize"
    extra_observables: Callable[[dict], dict] = field(default=lambda lv: {})


def _numeric(fid: str, levels=(2, 4, 8, 16), grid=1) -> dict:
    return {
        "id": fid, "name": fid.lower(), "type": "numeric",
        "levels": list(levels), "grid": grid,
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"cfg.{fid.lower()}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"R{fid}", "kind": "correctness",
                       "statement": f"{fid} at baseline reproduces baseline",
                       "native_test": f"tests/prop_{fid.lower()}.py::test_noop"}],
    }


def _choice(fid: str, levels=("off", "on")) -> dict:
    return {
        "id": fid, "name": fid.lower(), "type": "choice", "levels": list(levels),
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"cfg.{fid.lower()}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"R{fid}", "kind": "correctness",
                       "statement": f"{fid} off is byte-identical to baseline",
                       "native_test": f"tests/prop_{fid.lower()}.py::test_noop"}],
    }


def _additive() -> Surface:
    return Surface(
        name="additive", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), _choice("C")),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"] + (2.0 if lv["C"] == "on" else 0.0),
    )


def _interaction_only() -> Surface:
    return Surface(
        name="interaction_only", noise_sd=0.05,
        factors=tuple(_numeric(f, levels=(2, 16)) for f in "ABCD"),
        fn=lambda lv: 10 + 0.02 * (lv["A"] - 9) * (lv["B"] - 9),
    )


def _bowl(a0=9.0, b0=11.0, name="bowl") -> Surface:
    return Surface(
        name=name, noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 20 - 0.05 * (lv["A"] - a0) ** 2 - 0.05 * (lv["B"] - b0) ** 2,
    )


def _saddle() -> Surface:
    return Surface(
        name="saddle", noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.05 * (lv["A"] - 9) ** 2 - 0.05 * (lv["B"] - 11) ** 2,
    )


def _choice_x_numeric() -> Surface:
    return Surface(
        name="choice_x_numeric", noise_sd=0.05,
        factors=(_numeric("A"), _choice("C")),
        fn=lambda lv: 10 + (0.5 * lv["A"] if lv["C"] == "on" else -0.5 * lv["A"]),
    )


def _drift() -> Surface:
    return Surface(
        name="drift", noise_sd=0.05, drift_per_run=0.05,
        factors=(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16))),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"],
    )


def _sla() -> Surface:
    return Surface(
        name="sla", noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.5 * lv["A"] + 0.2 * lv["B"],
        invalid=lambda lv: (2 * lv["A"] + lv["B"]) > 40,
        extra_observables=lambda lv: {"p99_ms": 2 * lv["A"] + lv["B"]},
    )


def _nan_at_corner() -> Surface:
    return Surface(
        name="nan_at_corner", noise_sd=0.05,
        factors=(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16))),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"],
        exception_at={"A": 16, "B": 16},
    )


SURFACES: dict[str, Callable[[], Surface]] = {
    "additive": _additive,
    "interaction_only": _interaction_only,
    "bowl": _bowl,
    "bowl_out_of_hull": lambda: _bowl(a0=30.0, name="bowl_out_of_hull"),
    "saddle": _saddle,
    "choice_x_numeric": _choice_x_numeric,
    "drift": _drift,
    "sla": _sla,
    "nan_at_corner": _nan_at_corner,
}


def candidate_grid(factors_raw: list[dict], *, max_numeric_points: int = 9) -> list[dict]:
    """Every level combination worth predicting: declared levels, plus for
    numeric factors with a grid up to ``max_numeric_points`` snapped points
    spanning [min, max]. Deterministic order."""
    axes: list[list[Any]] = []
    ids: list[str] = []
    for f in factors_raw:
        ids.append(f["id"])
        levels = list(f["levels"])
        if f["type"] == "numeric" and f.get("grid") is not None:
            lo, hi = float(min(levels)), float(max(levels))
            n = max(2, int(max_numeric_points))
            pts = {snap_to_grid(lo + (hi - lo) * i / (n - 1), float(f["grid"])) for i in range(n)}
            pts.update(levels)
            axes.append(sorted(pts))
        else:
            axes.append(levels)
    return [dict(zip(ids, combo)) for combo in itertools.product(*axes)]


def true_optimum(surface: Surface) -> tuple[dict, float]:
    """Best VALID level combination on the candidate grid, by ``direction``."""
    best_lv, best_v = None, None
    sign = 1.0 if surface.direction == "maximize" else -1.0
    for lv in candidate_grid(list(surface.factors)):
        if surface.invalid is not None and surface.invalid(lv):
            continue
        v = surface.fn(lv)
        if best_v is None or sign * v > sign * best_v:
            best_lv, best_v = lv, v
    assert best_lv is not None, "surface has no valid point"
    return best_lv, best_v


def _observe(surface: Surface, levels: dict, *, rng: random.Random, run_counter: int) -> dict:
    lv = dict(levels)
    if surface.exception_at and all(lv.get(k) == v for k, v in surface.exception_at.items()):
        m = float("nan")
    else:
        m = surface.fn(lv) + rng.gauss(0.0, surface.noise_sd) + surface.drift_per_run * run_counter
    obs = {"cfg": {k.lower(): v for k, v in lv.items()}, "m": m}
    obs.update(surface.extra_observables(lv))
    return obs


def make_synthetic_runner(surface: Surface, *, seed: int) -> Callable:
    """An in-process ``ConfigRunner``: seeded noise, monotone run counter."""
    rng = random.Random(seed)
    counter = {"n": 0}

    def run(row) -> dict:
        obs = _observe(surface, row.levels, rng=rng, run_counter=counter["n"])
        counter["n"] += 1
        return obs
    return run


def main(argv: list[str] | None = None) -> int:
    """``python -m orchestrator.optimize.synthetic --surface K --seed S --a=4 ...``

    Emits ONE JSON object on stdout, the contract every real target's
    run_command must meet. ``run_counter`` is passed explicitly (``--run``)
    because a subprocess has no memory across calls."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", required=True, choices=sorted(SURFACES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run", type=int, default=0)
    known, rest = ap.parse_known_args(argv)
    surface = SURFACES[known.surface]()
    levels: dict = {}
    by_lower = {f["id"].lower(): f for f in surface.factors}
    for tok in rest:
        if not tok.startswith("--") or "=" not in tok:
            print(f"unrecognised argument {tok!r}", file=sys.stderr)
            return 2
        k, v = tok[2:].split("=", 1)
        f = by_lower.get(k)
        if f is None:
            print(f"unknown factor flag --{k}", file=sys.stderr)
            return 2
        levels[f["id"]] = int(v) if f["type"] == "numeric" else v
    rng = random.Random(known.seed)
    print(json.dumps(_observe(surface, levels, rng=rng, run_counter=known.run)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_synthetic.py -q` → PASS. (If `test_true_optimum_of_the_saddle…` fails on the exact corner, print `true_optimum` and adjust the assertion to the actual corner — the point is that it is a corner, not (9, 11).)

- [ ] **Step 5: Commit** — `git add orchestrator/optimize/synthetic.py tests/test_optimize_synthetic.py && git commit -m "feat(optimize): synthetic surfaces with known optima as the machinery oracle"`.

### Task 3: Harness — run a whole synthetic campaign and compare with truth

**Files:**
- Create: `orchestrator/optimize/harness.py`
- Test: `tests/test_optimize_harness.py`

**Interfaces:**
- Consumes: `synthetic.Surface/SURFACES/true_optimum/make_synthetic_runner`; `stage_runner.run_stage`; `iteration.setup_work_dir`; `IterationOutcome`.
- Produces: `SyntheticResult`, `synthetic_campaign`, `run_synthetic_campaign`.

Until Task 6 the harness drives the legacy schedule (`stage=None`, iteration index decides). It reads the recommendation from `report.json` when present (Task 9+), else from `runs/iter-N/confirmation.json`'s `confirmed_at_levels` (today's artifact). Tests that encode the *paper's* behaviour but fail today are marked `xfail(strict=True)` with the task number that flips them — the harness proving it catches the known bugs is the point.

- [ ] **Step 1: Write the failing tests**

```python
"""End-to-end oracle tests: a synthetic campaign's answer vs. the truth.

xfail(strict=True) marks encode behaviour the paper requires and the branch
does not yet deliver; each names the task that must flip it. A strict xfail
that starts passing FAILS the suite, so flipping is deliberate.
"""
from __future__ import annotations

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def _gap_pct(res):
    return abs(res.true_gap) / max(abs(res.true_best), 1e-9) * 100.0


def test_additive_surface_recommendation_is_within_two_percent_of_truth(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    assert res.recommendation, res.report
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


def test_bowl_surface_confirms_near_the_interior_maximum(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=2, parent_dir=tmp_path)
    assert abs(res.recommendation["A"] - 9) <= 1 and abs(res.recommendation["B"] - 11) <= 1


@pytest.mark.xfail(strict=True, reason="Task 7: argmax over X_valid replaces the stationary point")
def test_saddle_surface_recommends_a_corner_not_the_saddle_point(tmp_path):
    res = run_synthetic_campaign(SURFACES["saddle"](), seed=3, parent_dir=tmp_path)
    assert _gap_pct(res) <= 2.0, (res.recommendation, res.true_optimum)


@pytest.mark.xfail(strict=True, reason="Task 7: choice factors enter the argmax instead of being held at levels[0]")
def test_choice_x_numeric_recommends_the_on_branch(tmp_path):
    res = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=4, parent_dir=tmp_path)
    assert res.recommendation["C"] == "on" and _gap_pct(res) <= 2.0


@pytest.mark.xfail(strict=True, reason="Task 9: finalists measured infeasible at confirm are excluded from the recommendation")
def test_sla_surface_never_recommends_an_invalid_point(tmp_path):
    s = SURFACES["sla"]()
    res = run_synthetic_campaign(
        s, seed=5, parent_dir=tmp_path,
        campaign_overrides={"response": {"primary": {"metric": "m", "direction": "maximize"},
                                          "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}},
    )
    assert not s.invalid(res.recommendation), res.recommendation


@pytest.mark.xfail(strict=True, reason="Task 11: an out-of-hull optimum ends the epoch instead of confirming anyway")
def test_bowl_out_of_hull_ends_the_epoch(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=6, parent_dir=tmp_path)
    assert res.path[-1] == "exception"


@pytest.mark.xfail(strict=True, reason="Task 11: a NaN response is a semantic exception, not a fit over the remaining rows")
def test_nan_corner_ends_the_epoch(tmp_path):
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=7, parent_dir=tmp_path)
    assert res.path[-1] == "exception"
```

- [ ] **Step 2: Run** → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `orchestrator/optimize/harness.py`**

```python
"""Drive a whole optimization campaign against a synthetic surface.

Zero LLM: build is never declared, verify gets ``test_results`` with every
declared relation passing, and the config runner is
``synthetic.make_synthetic_runner``. Returns the recommendation next to the
truth so tests can assert on the ANSWER (spec §3.5, oracle 1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator.optimize.synthetic import Surface, make_synthetic_runner, true_optimum


@dataclass(frozen=True)
class SyntheticResult:
    recommendation: dict
    basis: str
    residual_regret: float | None
    residual_regret_terminal: float | None
    true_optimum: dict
    true_best: float
    true_gap: float
    path: list[str]
    work_dir: Path
    report: dict


def synthetic_campaign(surface: Surface, **overrides) -> dict:
    """A valid ``kind: optimization`` campaign dict for ``surface``."""
    opt = {
        "response": {"primary": {"metric": "m", "direction": surface.direction}},
        "factors": [dict(f) for f in surface.factors],
        "design": {"screen": {"resolution": 5, "center_points": 4},
                   "refine": {"kind": "central_composite", "center_points": 4},
                   "confirm": {"replicates": 3}},
    }
    opt.update(overrides)
    return {
        "kind": "optimization",
        "run_id": f"synthetic-{surface.name}",
        "research_question": f"where is the optimum of {surface.name}?",
        "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
        "target_system": {"name": "synthetic", "description": f"synthetic surface {surface.name}"},
        "optimization": opt,
    }


def _all_pass(campaign: dict) -> dict[str, bool]:
    return {r["native_test"]: True
            for f in campaign["optimization"]["factors"] for r in f["relations"]}


def _read_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _latest_iter_dirs(work_dir: Path) -> list[Path]:
    runs = work_dir / "runs"
    if not runs.exists():
        return []
    dirs = [d for d in runs.iterdir() if d.name.startswith("iter-")]
    return sorted(dirs, key=lambda d: int(d.name.split("-")[1]))


def run_synthetic_campaign(surface: Surface, *, seed: int, parent_dir: Path,
                           campaign_overrides: dict | None = None,
                           max_iterations: int = 8) -> SyntheticResult:
    import os

    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage

    os.environ["NOUS_CAMPAIGN_PARENT"] = str(parent_dir)
    campaign = synthetic_campaign(surface, **(campaign_overrides or {}))
    work_dir = setup_work_dir(campaign["run_id"] + f"-{seed}", repo_path=None, campaign=campaign)
    runner = make_synthetic_runner(surface, seed=seed)

    path: list[str] = []
    for i in range(1, max_iterations + 1):
        try:
            outcome = run_stage(campaign, work_dir, iteration=i, config_runner=runner,
                                test_results=_all_pass(campaign), auto_approve=True)
        except OptimizationAborted as exc:
            path.append(f"aborted:{exc}")
            break
        # Task 6 records transitions.jsonl; before that, reconstruct the path
        # from which artifact each iteration wrote.
        it = work_dir / "runs" / f"iter-{i}"
        if (it / "confirmation.json").exists():
            path.append("confirm")
        elif (it / "effects.json").exists():
            path.append(json.loads((it / "effects.json").read_text()).get("stage", "screen"))
        else:
            path.append("verify")
        if outcome == IterationOutcome.COMPLETED:
            break
    trans = work_dir / "transitions.jsonl"
    if trans.exists():
        path = [json.loads(l)["from"] for l in trans.read_text().splitlines() if l.strip()]
        last = json.loads(trans.read_text().splitlines()[-1])
        path.append(last["to"])

    report = _read_json(work_dir / "report.json") or {}
    rec = (report.get("recommendation") or {}).get("levels")
    basis = (report.get("recommendation") or {}).get("basis", "")
    if rec is None:
        for it in reversed(_latest_iter_dirs(work_dir)):
            conf = _read_json(it / "confirmation.json")
            if conf and conf.get("confirmed_at_levels"):
                rec, basis = conf["confirmed_at_levels"], "confirmation.json"
                break
    rec = rec or {}
    opt, best = true_optimum(surface)
    gap = (best - surface.fn(rec)) if rec else float("inf")
    if surface.direction == "minimize":
        gap = -gap
    return SyntheticResult(
        recommendation=rec, basis=basis,
        residual_regret=report.get("residual_regret_model"),
        residual_regret_terminal=report.get("residual_regret_terminal"),
        true_optimum=opt, true_best=best, true_gap=gap, path=path,
        work_dir=work_dir, report=report,
    )
```

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_harness.py -q -p no:randomly` → the two non-xfail tests PASS, the xfails XFAIL. If `test_bowl_surface…` fails, inspect `confirmation.json`; the legacy path (refine → stationary point in hull → confirm) should reproduce (9, 11) within grid 1. If it does not, that is a real bug on the branch: record it in the test's docstring and mark it `xfail(strict=True, reason="Task 7")` rather than weakening the assertion.

- [ ] **Step 5: Commit** — `git add orchestrator/optimize/harness.py tests/test_optimize_harness.py && git commit -m "test(optimize): synthetic end-to-end harness with strict xfails naming the paper gaps"`.

---

## Phase 2 — The policy is data (spec-correct over old-behaviour-preserving; see spec §2.7)

### Task 4: `policy.json` — schema, compiler, hash, structural checks

**Files:**
- Create: `orchestrator/schemas/policy.schema.json`
- Create: `orchestrator/optimize/policy.py`
- Test: `tests/test_optimize_policy.py`

**Interfaces:**
- Consumes: `factors.parse_factors`, `factors.is_refinable`, `design.is_tabulated`, `design.min_runs_for`.
- Produces: `OBSERVATION_KEYS`, `compile_policy`, `policy_hash`, `write_policy`, `read_policy`, `check_policy`, `pre_epoch_stages`, `POLICY_SCHEMA_PATH`. (`step`, `enumerate_paths`, `longest_path`, transitions I/O come in Task 5 but live in the same module.)

Semantics of the compiled default policy (spec §3.2, §3.3):

- `pre_epoch_stages(campaign)`: the leading run of `build`/`verify` in `optimization.stages` (default `["verify"]`).
- Enabled epoch states: `screen` always; `refine` iff listed in `stages` (or no `stages`) **and** at least one factor `is_refinable`; `confirm` iff listed (or no `stages`); `report`, `exception` always.
- Transitions emitted (in order; first match wins; `default` last):
  - `screen`: `correctness_failed==true → exception`; `nan_response==true → exception`; `refinable_survivors>0 → refine` (if refine enabled); `default → confirm` (or `report` if confirm disabled).
  - `refine`: `correctness_failed==true → exception`; `nan_response==true → exception`; `default → confirm` (or `report`). (Task 11 adds the out-of-hull → exception rule; Task 10 adds `screen → foldover`.)
  - `confirm`: `correctness_failed==true → exception`; `certified==true → report`; `round >= max_rounds → report`; `budget_remaining < runs_needed_confirm → report`; `default → confirm` (accounting `bonferroni_over_registered_rounds`).
- Every `when` transition names `accounting`. Every `when` key ∈ `OBSERVATION_KEYS`.

- [ ] **Step 1: Write the failing tests**

```python
"""policy.json is DATA: compiled by pure Python, schema-validated, hashed.

Behavioural: assert the compiled object, its schema conformance, its hash
stability, and the structural checks — never how compile_policy is written.
"""
from __future__ import annotations

import json

import jsonschema
import pytest

from orchestrator.optimize.policy import (
    OBSERVATION_KEYS, POLICY_SCHEMA_PATH, check_policy, compile_policy,
    policy_hash, pre_epoch_stages, read_policy, write_policy,
)
from orchestrator.optimize.synthetic import SURFACES
from orchestrator.optimize.harness import synthetic_campaign


def _campaign(**over):
    return synthetic_campaign(SURFACES["additive"](), **over)


def test_compiled_policy_validates_against_its_schema():
    pol = compile_policy(_campaign())
    schema = json.loads(POLICY_SCHEMA_PATH.read_text())
    jsonschema.validate(pol, schema)


def test_default_policy_has_the_documented_states_and_initial():
    pol = compile_policy(_campaign())
    assert pol["initial"] == "screen"
    assert set(pol["states"]) == {"screen", "refine", "confirm", "report", "exception"}
    assert pol["states"]["report"]["terminal"] and not pol["states"]["report"]["spends"]
    assert pol["states"]["exception"]["ends_epoch"] is True


def test_refine_is_omitted_when_no_factor_is_refinable():
    s = SURFACES["interaction_only"]()          # all two-level numerics
    pol = compile_policy(synthetic_campaign(s))
    assert "refine" not in pol["states"]
    default = [t for t in pol["transitions"] if t["from"] == "screen" and "default" in t]
    assert default and default[0]["default"] == "confirm"


def test_legacy_stages_list_controls_pre_epoch_and_enabled_states():
    c = _campaign(stages=["build", "verify", "screen"])
    assert pre_epoch_stages(c) == ["build", "verify"]
    pol = compile_policy(c)
    assert "confirm" not in pol["states"] and "refine" not in pol["states"]
    default = [t for t in pol["transitions"] if t["from"] == "screen" and "default" in t]
    assert default[0]["default"] == "report"


def test_every_conditional_transition_names_accounting_and_known_keys():
    pol = compile_policy(_campaign())
    for t in pol["transitions"]:
        if "when" in t:
            assert t.get("accounting"), t
            assert set(t["when"]) <= OBSERVATION_KEYS, t


def test_hash_is_stable_and_changes_with_the_mechanism_patch():
    a = compile_policy(_campaign(), mechanism_patch_hash="abc")
    b = compile_policy(_campaign(), mechanism_patch_hash="abc")
    c = compile_policy(_campaign(), mechanism_patch_hash="def")
    assert policy_hash(a) == policy_hash(b) != policy_hash(c)


def test_write_and_read_round_trip_with_sidecar_hash(tmp_path):
    pol = compile_policy(_campaign())
    p = write_policy(tmp_path, pol)
    assert p.name == "policy.json"
    assert (tmp_path / "policy.sha256").read_text().strip() == policy_hash(pol)
    assert read_policy(tmp_path) == pol
    assert read_policy(tmp_path / "nowhere") is None


def test_check_policy_rejects_structural_defects():
    pol = compile_policy(_campaign())
    bad = json.loads(json.dumps(pol))
    bad["transitions"].append({"from": "screen", "when": {"unicorn": True}, "to": "report"})
    errs = check_policy(bad)
    assert any("unicorn" in e for e in errs)
    assert any("accounting" in e for e in errs)
    bad2 = json.loads(json.dumps(pol))
    bad2["transitions"] = [t for t in bad2["transitions"] if not (t["from"] == "screen" and "default" in t)]
    assert any("no default" in e for e in check_policy(bad2))
    assert check_policy(pol) == []
```

- [ ] **Step 2: Run** → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `orchestrator/schemas/policy.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Nous compiled experimental policy",
  "type": "object",
  "required": ["policy_version", "epoch", "compiled_from", "objective", "budget", "initial", "states", "transitions"],
  "additionalProperties": false,
  "properties": {
    "policy_version": {"const": 1},
    "epoch": {"type": "integer", "minimum": 1},
    "compiled_from": {
      "type": "object", "required": ["campaign_hash", "mechanism_patch_hash", "factor_ids", "pre_epoch"],
      "properties": {
        "campaign_hash": {"type": "string"},
        "mechanism_patch_hash": {"type": "string"},
        "factor_ids": {"type": "array", "items": {"type": "string"}},
        "pre_epoch": {"type": "array", "items": {"enum": ["build", "verify"]}}
      }
    },
    "objective": {
      "type": "object", "required": ["metric", "direction", "epsilon", "delta_screen", "delta_terminal"],
      "properties": {
        "metric": {"type": "string"},
        "direction": {"enum": ["maximize", "minimize"]},
        "epsilon": {"type": "object", "oneOf": [
          {"required": ["abs"], "properties": {"abs": {"type": "number", "minimum": 0}}, "additionalProperties": false},
          {"required": ["pct"], "properties": {"pct": {"type": "number", "minimum": 0}}, "additionalProperties": false}]},
        "delta_screen": {"type": "number", "exclusiveMinimum": 0, "maximum": 0.5},
        "delta_terminal": {"type": "number", "exclusiveMinimum": 0, "maximum": 0.5}
      }
    },
    "budget": {"type": "object", "required": ["max_runs"], "properties": {"max_runs": {"type": ["integer", "null"]}}},
    "known_valid_baseline": {"type": ["object", "null"]},
    "workload": {"type": ["object", "null"]},
    "initial": {"type": "string"},
    "states": {
      "type": "object",
      "additionalProperties": {
        "type": "object", "required": ["spends"],
        "properties": {
          "spends": {"type": "boolean"},
          "terminal": {"type": "boolean"},
          "ends_epoch": {"type": "boolean"},
          "design": {"type": "object"},
          "estimator": {"type": "string"},
          "accounting": {"type": "string"}
        }
      }
    },
    "transitions": {
      "type": "array",
      "items": {
        "type": "object", "required": ["from"],
        "properties": {
          "from": {"type": "string"},
          "to": {"type": "string"},
          "default": {"type": "string"},
          "when": {"type": "object"},
          "accounting": {"type": "string"}
        },
        "oneOf": [{"required": ["when", "to"]}, {"required": ["default"]}]
      }
    }
  }
}
```

- [ ] **Step 4: Implement `orchestrator/optimize/policy.py` (compile half)**

```python
"""The compiled experimental policy: data, not code.

Spec §3.1. ``compile_policy`` is a PURE function of the campaign's
``optimization`` block plus the mechanism patch hash and epoch index; it makes
no model call and reads no measurement. Its output is written once at the end
of ``verify`` (stage_runner), hashed, and cited by every design_matrix.json
materialised inside the epoch. ``step`` (below, Task 5) interprets it over a
CLOSED observation vocabulary — no free-form expressions, no generated code.

Why data: a JSON document with a sha256 written before the first benchmark
run IS a pre-registration; path fidelity against it is checkable exactly like
``matrix.check_fidelity`` checks rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestrator.optimize.factors import is_refinable, parse_factors

POLICY_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "policy.schema.json"

OBSERVATION_KEYS: frozenset[str] = frozenset({
    "correctness_failed", "nan_response", "all_within_noise", "lack_of_fit",
    "refinable_survivors", "alias_consequential", "stationary_in_hull",
    "model_adequate", "certified", "round", "budget_remaining",
    "runs_needed_foldover", "runs_needed_confirm", "residual_regret", "epsilon",
    "behavioral_violation",
})

_PRE = ("build", "verify")
_DEFAULT_STAGES = ("verify", "screen", "refine", "confirm")


def pre_epoch_stages(campaign: dict) -> list[str]:
    stages = ((campaign.get("optimization") or {}).get("stages")) or list(_DEFAULT_STAGES)
    out: list[str] = []
    for s in stages:
        s = getattr(s, "value", None) or str(s)
        if s in _PRE:
            out.append(s)
        else:
            break
    return out


def _enabled(campaign: dict) -> set[str]:
    stages = ((campaign.get("optimization") or {}).get("stages")) or list(_DEFAULT_STAGES)
    return {getattr(s, "value", None) or str(s) for s in stages} - set(_PRE)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compile_policy(campaign: dict, *, mechanism_patch_hash: str = "", epoch: int = 1) -> dict:
    opt = campaign.get("optimization") or {}
    factors = parse_factors(opt["factors"])
    design = opt.get("design") or {}
    pol_cfg = opt.get("policy") or {}
    enabled = _enabled(campaign)
    refine_on = "refine" in enabled and any(is_refinable(f) for f in factors)
    confirm_on = "confirm" in enabled
    primary = (opt.get("response") or {}).get("primary") or {}
    confirm_cfg = design.get("confirm") or {}

    states: dict = {
        "screen": {
            "spends": True,
            "design": {"kind": "screen",
                       "resolution": int((design.get("screen") or {}).get("resolution", 5)),
                       "center_points": int((design.get("screen") or {}).get("center_points", 4))},
            "estimator": "ols_orthogonal_closed_form",
            "accounting": "per_term_t_on_pure_error",
        },
        "report": {"spends": False, "terminal": True},
        "exception": {"spends": False, "terminal": True, "ends_epoch": True},
    }
    if refine_on:
        states["refine"] = {
            "spends": True,
            "design": {"kind": "central_composite",
                       "center_points": int((design.get("refine") or {}).get("center_points", 4))},
            "estimator": "ols_normal_equations",
            "accounting": "per_term_t_on_pure_error",
        }
    if confirm_on:
        states["confirm"] = {
            "spends": True,
            "design": {"kind": "shortlist_replicate",
                       "shortlist_size": int(confirm_cfg.get("shortlist_size", 1)),
                       "replicates": max(1, int(confirm_cfg.get("replicates", 3))),
                       "max_rounds": int(pol_cfg.get("confirm_max_rounds", 1))},
            "estimator": "sample_means",
            "accounting": "holm_one_sided_t",
        }

    after_refine = "confirm" if confirm_on else "report"
    sem = "none: semantic exception ends the epoch, no inference is drawn"
    transitions: list[dict] = [
        {"from": "screen", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
        {"from": "screen", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
    ]
    if refine_on:
        transitions.append({"from": "screen", "when": {"refinable_survivors": {">": 0}}, "to": "refine",
                            "accounting": "screen selection at alpha=0.05 per main effect (Task 8 adds regret)"})
    transitions.append({"from": "screen", "default": ("confirm" if confirm_on else "report")})
    if refine_on:
        transitions += [
            {"from": "refine", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "refine", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
            {"from": "refine", "default": after_refine},
        ]
    if confirm_on:
        transitions += [
            {"from": "confirm", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "confirm", "when": {"certified": True}, "to": "report",
             "accounting": "holm_one_sided_t at delta_terminal over |S|-1 finalists"},
            {"from": "confirm", "when": {"round": {">=": states["confirm"]["design"]["max_rounds"]}},
             "to": "report", "accounting": "registered round cap; report uncertified"},
            {"from": "confirm", "when": {"budget_remaining": {"<": 1}}, "to": "report",
             "accounting": "budget exhausted; report uncertified"},
            {"from": "confirm", "default": "confirm"},
        ]

    policy = {
        "policy_version": 1,
        "epoch": int(epoch),
        "compiled_from": {
            "campaign_hash": hashlib.sha256(_canonical(opt).encode()).hexdigest(),
            "mechanism_patch_hash": mechanism_patch_hash or "",
            "factor_ids": [f.id for f in factors],
            "pre_epoch": pre_epoch_stages(campaign),
        },
        "objective": {
            "metric": primary.get("metric", ""),
            "direction": primary.get("direction", "maximize"),
            "epsilon": dict(pol_cfg.get("epsilon") or {"pct": 2.0}),
            "delta_screen": float(pol_cfg.get("delta_screen", 0.05)),
            "delta_terminal": float(pol_cfg.get("delta_terminal", 0.05)),
        },
        "budget": {"max_runs": design.get("max_runs")},
        "known_valid_baseline": opt.get("known_valid_baseline"),
        "workload": opt.get("workload"),
        "initial": "screen",
        "states": states,
        "transitions": transitions,
    }
    _sanity = {t["from"] for t in transitions if "default" in t}
    assert {s for s, v in states.items() if not v.get("terminal")} <= _sanity
    return policy


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(_canonical(policy).encode()).hexdigest()


def write_policy(work_dir: Path, policy: dict) -> Path:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / "policy.json"
    p.write_text(json.dumps(policy, indent=2, sort_keys=True))
    (work_dir / "policy.sha256").write_text(policy_hash(policy) + "\n")
    return p


def read_policy(work_dir: Path) -> dict | None:
    p = Path(work_dir) / "policy.json"
    return json.loads(p.read_text()) if p.exists() else None


def check_policy(policy: dict) -> list[str]:
    """Structural rules a valid compiled policy must satisfy (spec §3.1, §3.5)."""
    errs: list[str] = []
    states = policy.get("states") or {}
    if policy.get("initial") not in states:
        errs.append(f"initial state {policy.get('initial')!r} is not a declared state")
    elif not states[policy["initial"]].get("spends"):
        errs.append("initial state must be a spending state")
    by_from: dict[str, list[dict]] = {}
    for t in policy.get("transitions") or []:
        by_from.setdefault(t.get("from"), []).append(t)
        if t.get("from") not in states:
            errs.append(f"transition from unknown state {t.get('from')!r}")
        target = t.get("to") or t.get("default")
        if target not in states:
            errs.append(f"transition to unknown state {target!r}")
        if "when" in t:
            unknown = set(t["when"]) - OBSERVATION_KEYS
            if unknown:
                errs.append(f"transition {t.get('from')}->{t.get('to')} uses unknown observation key(s) {sorted(unknown)}")
            if not t.get("accounting"):
                errs.append(f"conditional transition {t.get('from')}->{t.get('to')} names no accounting rule")
    for name, st in states.items():
        if st.get("terminal"):
            continue
        outs = by_from.get(name, [])
        if not any("default" in t for t in outs):
            errs.append(f"state {name!r} has no default transition")
        if st.get("spends") and "exception" in states and not any(t.get("to") == "exception" for t in outs):
            errs.append(f"spending state {name!r} cannot reach exception")
    return errs
```

- [ ] **Step 5: Run** `python -m pytest tests/test_optimize_policy.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add orchestrator/schemas/policy.schema.json orchestrator/optimize/policy.py tests/test_optimize_policy.py && git commit -m "feat(optimize): compile the experimental policy to policy.json (pure Python, hashed)"`.

### Task 5: `step()` interpreter, path enumeration, transition log, property tests

**Files:**
- Modify: `orchestrator/optimize/policy.py` (append)
- Modify: `orchestrator/optimize/stage.py` (add `observations_from_decision`)
- Test: `tests/test_optimize_policy.py` (append)

**Interfaces:**
- Consumes: `predicates.OPS`; `stage.StageDecision`, `Trigger`, `Fit`.
- Produces: `step`, `enumerate_paths`, `longest_path`, `append_transition`, `read_transitions`, `current_state`, `is_terminal(policy, state)`, `stage.observations_from_decision(decision, fit) -> dict`.

- [ ] **Step 1: Append failing tests**

```python
from orchestrator.optimize.policy import (
    append_transition, current_state, enumerate_paths, is_terminal, longest_path,
    read_transitions, step,
)


def test_step_takes_the_first_matching_rule_then_the_default():
    pol = compile_policy(_campaign())
    nxt, rule = step(pol, "screen", {"correctness_failed": False, "nan_response": False,
                                     "refinable_survivors": 2})
    assert nxt == "refine" and rule["to"] == "refine"
    nxt, rule = step(pol, "screen", {"correctness_failed": False, "nan_response": False,
                                     "refinable_survivors": 0})
    assert nxt == "confirm" and "default" in rule
    nxt, _ = step(pol, "screen", {"correctness_failed": True})
    assert nxt == "exception"


def test_step_treats_a_missing_observation_as_not_matching():
    pol = compile_policy(_campaign())
    nxt, _ = step(pol, "screen", {})            # nothing known -> default
    assert nxt == "confirm"


def test_step_supports_comparator_dicts_and_none_never_matches():
    pol = compile_policy(_campaign())
    nxt, _ = step(pol, "confirm", {"correctness_failed": False, "certified": None,
                                   "round": 1, "budget_remaining": 50})
    assert nxt == "report"                       # round >= max_rounds(1)


def test_every_enumerated_path_terminates_and_exception_is_reachable_everywhere():
    pol = compile_policy(_campaign())
    paths = enumerate_paths(pol)
    assert paths and all(is_terminal(pol, p[-1]) for p in paths)
    spending = {s for s, v in pol["states"].items() if v["spends"]}
    for s in spending:
        assert any(s in p and p[-1] == "exception" for p in paths), s
    assert longest_path(pol) >= 3               # screen, refine, confirm


def test_transitions_log_round_trips_and_current_state_follows_it(tmp_path):
    pol = compile_policy(_campaign())
    assert current_state(pol, tmp_path) == "screen"
    append_transition(tmp_path, {"iteration": 2, "from": "screen", "to": "refine",
                                 "rule": {"to": "refine"}, "observations": {}})
    assert read_transitions(tmp_path)[0]["to"] == "refine"
    assert current_state(pol, tmp_path) == "refine"


def test_observations_from_decision_maps_triggers_to_the_closed_vocabulary():
    from orchestrator.optimize.stage import (
        Stage, StageDecision, Trigger, observations_from_decision,
    )
    from orchestrator.optimize.effects import Fit
    d = StageDecision(next_stage=Stage.REFINE, triggers=(Trigger.LACK_OF_FIT,),
                      surviving=("A", "B"), dropped=("C",), rationale="x")
    obs = observations_from_decision(d, Fit(intercept=0.0, effects=(), n_runs=8), refinable_survivors=1)
    assert obs["lack_of_fit"] is True and obs["all_within_noise"] is False
    assert obs["refinable_survivors"] == 1 and obs["stationary_in_hull"] is None
    assert set(obs) <= OBSERVATION_KEYS
```

- [ ] **Step 2: Run** → FAIL (`ImportError`).

- [ ] **Step 3: Append to `policy.py`**

```python
from orchestrator.optimize.predicates import OPS as _OPS  # noqa: E402  (same vocabulary as manipulation checks)


def _match_one(spec, value) -> bool:
    if isinstance(spec, dict):
        return all(op in _OPS and value is not None and _OPS[op](value, want)
                   for op, want in spec.items())
    return value is not None and value == spec


def _matches(when: dict, obs: dict) -> bool:
    return all(k in obs and _match_one(spec, obs[k]) for k, spec in when.items())


def step(policy: dict, state: str, observations: dict) -> tuple[str, dict]:
    """Next state under ``policy`` from ``state`` given ``observations``.

    First conditional rule (in registration order) whose every key is present
    in ``observations`` and matches wins; otherwise the state's default. A
    missing or ``None`` observation never matches — unknown is not a fact.
    """
    default = None
    for t in policy.get("transitions") or []:
        if t.get("from") != state:
            continue
        if "when" in t:
            if _matches(t["when"], observations):
                return t["to"], t
        elif "default" in t and default is None:
            default = t
    if default is None:
        raise ValueError(f"policy has no default transition from {state!r}")
    return default["default"], default


def is_terminal(policy: dict, state: str) -> bool:
    return bool((policy.get("states") or {}).get(state, {}).get("terminal"))


def enumerate_paths(policy: dict, *, max_len: int = 12) -> list[list[str]]:
    """All simple paths (each transition used at most once) from initial to a terminal."""
    out: list[list[str]] = []
    trans = policy.get("transitions") or []

    def walk(state, path, used):
        if is_terminal(policy, state) or len(path) >= max_len:
            out.append(path)
            return
        for i, t in enumerate(trans):
            if t.get("from") != state or i in used:
                continue
            walk(t.get("to") or t.get("default"), path + [t.get("to") or t.get("default")], used | {i})
    walk(policy["initial"], [policy["initial"]], frozenset())
    return out


def longest_path(policy: dict) -> int:
    """Iterations an epoch can take: longest simple path plus registered self-loop rounds."""
    base = max((len(p) for p in enumerate_paths(policy)), default=1)
    extra = sum(max(0, int((v.get("design") or {}).get("max_rounds", 1)) - 1)
                for v in (policy.get("states") or {}).values() if v.get("spends"))
    return base + extra


def append_transition(work_dir: Path, row: dict) -> None:
    with (Path(work_dir) / "transitions.jsonl").open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def read_transitions(work_dir: Path) -> list[dict]:
    p = Path(work_dir) / "transitions.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def current_state(policy: dict, work_dir: Path) -> str:
    rows = read_transitions(work_dir)
    return rows[-1]["to"] if rows else policy["initial"]
```

And in `stage.py`, after `decide_after_refine`:

```python
def observations_from_decision(decision: StageDecision, fit: Fit, *,
                               refinable_survivors: int | None = None,
                               stationary_in_hull: bool | None = None) -> dict:
    """Project a StageDecision onto the policy's closed observation vocabulary.

    Pure. ``stationary_in_hull`` is None at screen (no stationary point yet).
    """
    trig = set(decision.triggers)
    return {
        "all_within_noise": Trigger.ALL_WITHIN_NOISE in trig,
        "lack_of_fit": Trigger.LACK_OF_FIT in trig,
        "behavioral_violation": Trigger.BEHAVIORAL_VIOLATION in trig,
        "refinable_survivors": (len(decision.surviving) if refinable_survivors is None
                                else int(refinable_survivors)),
        "stationary_in_hull": (False if Trigger.OPTIMUM_OUTSIDE_HULL in trig
                               else stationary_in_hull),
        "model_adequate": Trigger.LACK_OF_FIT not in trig,
    }
```

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_policy.py tests/test_optimize_stage.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): pure step() interpreter, path enumeration and transition log for policy.json"`.

### Task 6: Wire the interpreter into `run_stage` (spec-correct over old-behaviour-preserving; see spec §2.7)

**Files:**
- Modify: `orchestrator/optimize/stage_runner.py` (stage resolution ~L262-266 and ~L318; verify branch ~L340-352; the tail after `decision = ...` ~L560-620; `_finish_confirm` ~L933; `_terminal_outcome`/`_is_final_stage` ~L698-727)
- Modify: `orchestrator/campaign.py` (`run_campaign`, before the iteration loop ~L400)
- Modify: `orchestrator/optimize/harness.py` (nothing — it already prefers `transitions.jsonl`)
- Test: `tests/test_optimize_iteration.py` (append), `tests/test_optimize_harness.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 4–5.
- Produces: `stage_runner._resolve_state(campaign, work_dir, iteration, stage) -> tuple[str, dict | None]`; `stage_runner._record_transition(...)`; `stage_runner._run_report(engine, campaign, work_dir, iteration, policy, reason) -> None` (minimal in this task; Task 9 fills it); `policy_hash` in `design_matrix.json`; `transitions.jsonl` at work_dir root; `report.json` at work_dir root.

Rules for this task:
1. **Stage resolution.** `stage` argument (tests) wins. Else if `iteration <= len(pre_epoch_stages(campaign))` → that pre-epoch stage. Else `policy = read_policy(work_dir)`; if `None`, compile lazily (`compile_policy(campaign, mechanism_patch_hash=_read_mechanism_hash(work_dir))`) and write it; state = `current_state(policy, work_dir)`.
2. **Compile at verify.** In the verify branch, after `correctness_failures` is empty and before the human gates, `write_policy(work_dir, compile_policy(...))` and log the hash. Also `check_policy` must return `[]` else `OptimizationAborted`.
3. **Provenance.** `payload["policy_hash"] = policy_hash(policy)` before `write_design_matrix`. In the epoch, if `read_policy` returns a policy whose hash differs from `policy.sha256` → `OptimizationAborted("policy.json was edited after compilation")`.
4. **Transition.** After the fit + decision (screen/refine) or after `_finish_confirm` builds its summary: `obs = observations_from_decision(...) | {"correctness_failed": False, "nan_response": <any NaN among complete rows>, "budget_remaining": <max_runs - rows so far, or 10**9>, "round": <count of prior confirm iterations>, "certified": <Task 9; False for now>}`; `nxt, rule = step(policy, state, obs)`; `append_transition(work_dir, {"iteration", "from": state, "to": nxt, "rule": rule, "observations": obs, "policy_hash"})`.
5. **Terminal handling.** If `nxt == "report"` → `_run_report(...)` writes `report.json` = `{"recommendation": {"levels": <confirmation levels if confirm ran else best observed valid>, "basis": "measured"}, "path": [...], "epoch": ..., "policy_hash": ...}`, `engine.transition("DONE")`, return `COMPLETED`. If `nxt == "exception"` → this task: raise `OptimizationAborted(f"policy routed to exception: {rule}")` (Task 11 replaces with `epoch_end.json`). Else return `CONTINUE`.
6. **Remove index-based finality**: `_terminal_outcome`/`_is_final_stage` are replaced by rule 5. Delete `_is_final_stage`; keep `_terminal_outcome(engine, completed: bool)`.
7. **`campaign.py`**: for `kind: optimization`, `max_iterations = max(max_iterations, len(pre_epoch_stages(campaign)) + longest_path(compile_policy(campaign)))` before `_persist_max_iterations`, with a log line saying the floor was applied.
8. **NaN**: `nan_response` = any complete row whose primary metric is NaN (today `_fitting_responses` raises `OptimizationAborted` on NaN — keep that behaviour for now; set the observation before it raises so Task 11 can route it).

- [ ] **Step 1: Append failing tests to `tests/test_optimize_iteration.py`**

```python
def test_verify_compiles_and_writes_the_policy(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    pol = json.loads((wd / "policy.json").read_text())
    assert pol["initial"] == "screen"
    assert (wd / "policy.sha256").exists()


def test_epoch_iterations_follow_transitions_not_the_iteration_index(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    out2 = run_stage(c, wd, iteration=2, config_runner=_runner(), test_results=_all_tests_pass(c))
    trans = [json.loads(l) for l in (wd / "transitions.jsonl").read_text().splitlines()]
    assert trans[0]["from"] == "screen" and trans[0]["to"] in ("refine", "confirm")
    assert "policy_hash" in json.loads((wd / "runs" / "iter-2" / "design_matrix.json").read_text())
    # keep going until the policy reports; the harness does the same
    it, outcome = 3, out2
    from orchestrator.iteration import IterationOutcome
    while outcome != IterationOutcome.COMPLETED and it < 8:
        outcome = run_stage(c, wd, iteration=it, config_runner=_runner(), test_results=_all_tests_pass(c))
        it += 1
    assert outcome == IterationOutcome.COMPLETED
    assert (wd / "report.json").exists()
    trans = [json.loads(l) for l in (wd / "transitions.jsonl").read_text().splitlines()]
    assert trans[-1]["to"] == "report"


def test_editing_policy_json_after_compilation_hard_fails(tmp_path, work_dir):
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    p = wd / "policy.json"
    pol = json.loads(p.read_text()); pol["objective"]["delta_terminal"] = 0.4
    p.write_text(json.dumps(pol))
    with pytest.raises(OptimizationAborted, match="edited after compilation"):
        run_stage(c, wd, iteration=2, config_runner=_runner(), test_results=_all_tests_pass(c))


def test_explicit_confirm_stage_still_reports_completed(tmp_path, work_dir):
    # legacy calling convention used throughout this file
    c = _campaign()
    wd = _init_work_dir(tmp_path, c)
    from orchestrator.iteration import IterationOutcome
    assert _run(c, wd, stage="confirm", iteration=4) == IterationOutcome.COMPLETED
    assert (wd / "report.json").exists()
```

And to `tests/test_optimize_harness.py`:

```python
def test_harness_path_comes_from_transitions_log(tmp_path):
    res = run_synthetic_campaign(SURFACES["additive"](), seed=11, parent_dir=tmp_path)
    assert res.path[0] == "screen" and res.path[-1] == "report"
    assert (res.work_dir / "transitions.jsonl").exists()
```

- [ ] **Step 2: Run** `python -m pytest tests/test_optimize_iteration.py -q -k "policy or transitions or explicit_confirm"` → FAIL.

- [ ] **Step 3: Implement.** In `stage_runner.py` add near the top:

```python
from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.factors import is_refinable
from orchestrator.optimize.stage import observations_from_decision
```

Replace the two `stage_for_iteration` resolutions with one helper and call it once:

```python
def _resolve_state(campaign: dict, work_dir: Path, iteration: int, stage) -> tuple[str, dict | None]:
    """Which state this iteration runs, and the policy (None before compile).

    An explicit ``stage`` (tests) wins. Pre-epoch stages are index-driven; from
    the first epoch iteration onward the state is whatever the last recorded
    transition says (spec §3.2). A missing policy at an epoch iteration is
    compiled lazily so unit tests that jump straight to ``stage="screen"``
    keep working; a real campaign always compiles at verify.
    """
    pre = policy_mod.pre_epoch_stages(campaign)
    if stage is not None:
        name = getattr(stage, "value", None) or str(stage)
        pol = None if name in pre else _load_or_compile_policy(campaign, work_dir)
        return name, pol
    if iteration <= len(pre):
        return pre[iteration - 1], None
    pol = _load_or_compile_policy(campaign, work_dir)
    return policy_mod.current_state(pol, work_dir), pol


def _read_mechanism_hash(work_dir: Path) -> str:
    p = Path(work_dir) / "mechanism.sha256"
    return p.read_text().strip() if p.exists() else ""


def _epoch_index(work_dir: Path) -> int:
    return 1 + len(list(Path(work_dir).glob("epoch_end*.json")))


def _load_or_compile_policy(campaign: dict, work_dir: Path) -> dict:
    pol = policy_mod.read_policy(work_dir)
    if pol is None:
        pol = policy_mod.compile_policy(
            campaign, mechanism_patch_hash=_read_mechanism_hash(work_dir),
            epoch=_epoch_index(work_dir),
        )
        errs = policy_mod.check_policy(pol)
        if errs:
            raise OptimizationAborted("compiled policy is structurally invalid:\n  " + "\n  ".join(errs))
        policy_mod.write_policy(work_dir, pol)
        return pol
    recorded = (Path(work_dir) / "policy.sha256")
    if recorded.exists() and recorded.read_text().strip() != policy_mod.policy_hash(pol):
        raise OptimizationAborted(
            "policy.json was edited after compilation (hash mismatch with policy.sha256); "
            "a pre-registered policy cannot change inside an epoch",
        )
    return pol
```

In the verify branch, after `if correctness_failures: raise …`:

```python
        pol = policy_mod.compile_policy(
            campaign, mechanism_patch_hash=_read_mechanism_hash(work_dir),
            epoch=_epoch_index(work_dir),
        )
        errs = policy_mod.check_policy(pol)
        if errs:
            raise OptimizationAborted("compiled policy is structurally invalid:\n  " + "\n  ".join(errs))
        policy_mod.write_policy(work_dir, pol)
        logger.info("verify: compiled experimental policy %s (epoch %d)",
                    policy_mod.policy_hash(pol)[:12], pol["epoch"])
```

Before `write_design_matrix`: `payload["policy_hash"] = policy_mod.policy_hash(pol)`. Replace the tail (from `decision_summary = …` through the final `return _terminal_outcome(...)`) and `_finish_confirm`'s tail with a shared closer:

```python
def _close_iteration(engine, campaign, work_dir, iter_dir, iteration, state, pol,
                     observations: dict, *, recommendation_levels: dict | None):
    """Record the transition and run inline terminals. Returns IterationOutcome."""
    from orchestrator.iteration import IterationOutcome, _enter_phase, finalize_iteration
    from orchestrator.ledger import append_ledger_row

    nxt, rule = policy_mod.step(pol, state, observations)
    policy_mod.append_transition(work_dir, {
        "iteration": iteration, "from": state, "to": nxt, "rule": rule,
        "observations": observations, "policy_hash": policy_mod.policy_hash(pol),
    })
    _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
    finalize_iteration(work_dir=work_dir, iter_dir=iter_dir, iteration=iteration, campaign=campaign)
    append_ledger_row(work_dir, iteration)
    if nxt == "report":
        _run_report(engine, campaign, work_dir, iteration, pol,
                    recommendation_levels=recommendation_levels)
        return IterationOutcome.COMPLETED
    if nxt == "exception":
        raise OptimizationAborted(f"policy routed {state} -> exception: {rule.get('when')}")
    return IterationOutcome.CONTINUE


def _run_report(engine, campaign, work_dir, iteration, pol, *, recommendation_levels):
    primary = (((campaign.get("optimization") or {}).get("response") or {}).get("primary") or {})
    metric = primary.get("metric") or ""
    levels, basis = recommendation_levels, "terminal_best"
    if not levels:
        best = _best_observed(work_dir, metric) if metric else None
        levels, basis = (dict(best["levels"]) if best else {}), "measured"
    if not levels and pol.get("known_valid_baseline"):
        levels, basis = dict(pol["known_valid_baseline"]), "baseline"
    trans = policy_mod.read_transitions(work_dir)
    _write_json(Path(work_dir) / "report.json", {
        "recommendation": {"levels": levels, "basis": basis},
        "path": [t["from"] for t in trans] + ([trans[-1]["to"]] if trans else []),
        "epoch": pol["epoch"], "policy_hash": policy_mod.policy_hash(pol),
        "iteration": iteration,
    })
    engine.transition("DONE")
```

Observations for screen/refine (replace the block that computed `decision_summary`; keep the findings/principles writes above it):

```python
    fitted_ids_set = set(fitted_ids)
    obs = observations_from_decision(
        decision, fit,
        refinable_survivors=sum(1 for fid in decision.surviving
                                if is_refinable(next(f for f in factors if f.id == fid))),
        stationary_in_hull=(None if stage_name != Stage.REFINE.value else
                            (stationary is not None and all(-1.0 <= v <= 1.0 for v in stationary.values()))),
    )
    obs.update({
        "correctness_failed": False,
        "nan_response": any(v != v for v in ys),
        "budget_remaining": _budget_remaining(pol, work_dir),
        "round": 0, "certified": False,
    })
    return _close_iteration(engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
                            recommendation_levels=None)
```

with

```python
def _budget_remaining(pol: dict, work_dir: Path) -> int:
    cap = (pol.get("budget") or {}).get("max_runs")
    if not cap:
        return 10 ** 9
    spent = sum(len(artifacts.read_runs(d)) for d in (Path(work_dir) / "runs").glob("iter-*"))
    return int(cap) - spent
```

`_finish_confirm` ends with `return _close_iteration(..., "confirm", pol, obs, recommendation_levels=levels)` where `obs = {"correctness_failed": False, "nan_response": not usable, "certified": False, "round": <1 + number of earlier confirm transitions>, "budget_remaining": _budget_remaining(pol, work_dir)}` — the `round` count is `sum(1 for t in read_transitions(work_dir) if t["from"] == "confirm") + 1`.

Build/verify branches: replace `return _terminal_outcome(engine, campaign, stage_name, IterationOutcome)` with `return IterationOutcome.CONTINUE` (a pre-epoch stage is never terminal). Delete `_terminal_outcome` and `_is_final_stage`.

`campaign.py` before `_persist_max_iterations(work_dir, max_iterations)`:

```python
    from orchestrator.validate import campaign_kind
    if campaign_kind(campaign) == "optimization":
        from orchestrator.optimize import policy as _policy
        floor = len(_policy.pre_epoch_stages(campaign)) + _policy.longest_path(_policy.compile_policy(campaign))
        if floor > max_iterations:
            logger.info("optimization kind: raising max_iterations %d -> %d (longest registered path)",
                        max_iterations, floor)
            max_iterations = floor
```

- [ ] **Step 4: Run the whole suite** `python -m pytest tests/ -q -x`. Existing tests to expect and how to fix:
  - `test_the_final_stage_transitions_to_done_and_reports_completed` / `test_an_explicit_stages_list_decides_which_stage_is_terminal`: pass under rule 5 (confirm→report; `stages: [verify, screen]` → screen default → report). If the second one asserts `screen` returns COMPLETED and it does not, check `_enabled` in `compile_policy`.
  - `test_a_non_final_stage_reports_continue`: screen → refine/confirm → CONTINUE. Pass.
  - Any test asserting the absence of `report.json` or exact file sets: add `transitions.jsonl`/`report.json` to the expected set.
  - `tests/test_optimize_no_regression.py` must be untouched and green.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): run_stage interprets policy.json; transitions.jsonl and report.json replace index-based finality"`.

---

## Phase 3 — The paper's machinery

### Task 7: `recommend()` — argmax over $\mathcal X_{valid}$ replaces the stationary point

**Files:**
- Create: `orchestrator/optimize/decide.py`
- Modify: `orchestrator/optimize/stage_runner.py` (screen/refine tail; refine held-fixed block ~L370-405; confirm-target resolution `_read_confirm_at` ~L1102 → `_read_recommendation`)
- Test: `tests/test_optimize_decide.py`; modify `tests/test_optimize_iteration.py` (three `confirm_at` tests → `recommendation.json`); modify `tests/test_optimize_harness.py` (remove xfail from `saddle` and `choice_x_numeric` tests)

**Interfaces:**
- Consumes: `effects.Fit/Effect`, `factors.Factor/decode_coded/is_refinable/snap_to_grid`.
- Produces: `Candidate`, `predict`, `candidates`, `recommend`; artifact `runs/iter-N/recommendation.json` = `{"stage", "levels", "coded", "predicted", "fitted_ids", "held_fixed", "top_candidates": [{levels, coded, predicted}...≤5], "stationary_point": <dict|None, diagnostic only>, "excluded_measured_infeasible": [levels...]}`; `stage_runner._read_recommendation(work_dir) -> dict | None` (latest by iteration number); `stage_runner._measured_infeasible(work_dir) -> list[dict]`.

Rules (spec §3.3):
- Candidate axis per fitted factor: `choice` → its screen pair (coded ±1); numeric with exactly two levels → screen pair; refinable numeric → up to 9 evenly spaced coded points in [-1, 1] decoded through `decode_coded` (snap + clamp), de-duplicated by decoded level, re-encoded as `(level - mid)/half`.
- Held-fixed factors (not in `fitted_ids`) enter every candidate's `levels` at their held level; they contribute nothing to `predicted`.
- **Refine's held-fixed level is the screen recommendation's level for that factor**, not `levels[0]` (this is what fixes `choice_x_numeric`). Fallback to `levels[0]` only when no screen recommendation exists.
- Exclude any candidate whose `levels` agree on every shared key with a measured `infeasible`/`rejected` row.
- Confirm's target is `_read_recommendation(work_dir)["levels"]`; `confirm_at.json` is no longer written or read. The stationary point stays in `recommendation.json` as `stationary_point` (diagnostic; `OPTIMUM_OUTSIDE_HULL` still fires from it).

- [ ] **Step 1: Write the failing tests** (`tests/test_optimize_decide.py`)

```python
"""recommend() is the paper's x-hat: argmax of the fitted response over X_valid.

Built on real Fit objects from fit_effects over synthetic designs, so these
tests assert the ANSWER against a known surface, not the arithmetic.
"""
from __future__ import annotations

from orchestrator.optimize.decide import candidates, predict, recommend
from orchestrator.optimize.design import central_composite, full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import expand
from orchestrator.optimize.synthetic import SURFACES


def _fit(surface, design, ids):
    factors = parse_factors(list(surface.factors))
    ys = [surface.fn(r.levels) for r in expand(design, factors)]     # noiseless
    return fit_effects(design, ys, factor_ids=ids), factors


def test_predict_reproduces_the_fitted_corners_of_an_additive_surface():
    s = SURFACES["additive"]()
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "B", "C"])
    assert predict(fit, {"A": 1.0, "B": 1.0, "C": 1.0}) == pytest.approx(s.fn({"A": 16, "B": 16, "C": "on"}), abs=1e-6)


def test_saddle_recommendation_is_a_corner_and_beats_the_stationary_point():
    s = SURFACES["saddle"]()
    d = central_composite(["A", "B"], center_points=4)
    fit, factors = _fit(s, d, ["A", "B"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "B"], held_fixed={})
    assert rec.levels["A"] in (2, 16)
    assert s.fn(rec.levels) > s.fn({"A": 9, "B": 11})


def test_choice_factor_is_part_of_the_argmax():
    s = SURFACES["choice_x_numeric"]()
    d = with_center_points(full_factorial(["A", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "C"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "C"], held_fixed={})
    assert rec.levels == {"A": 16, "C": "on"}


def test_held_fixed_levels_are_carried_into_every_candidate():
    s = SURFACES["choice_x_numeric"]()
    d = central_composite(["A"], center_points=4)
    fit, factors = _fit(s, d, ["A"])            # C held fixed, not fitted
    cands = candidates(["A"], factors, held_fixed={"C": "on"})
    assert all(c.levels["C"] == "on" for c in cands)
    assert any(c.levels["A"] == 9 for c in cands)          # interior grid point present


def test_measured_infeasible_levels_are_excluded():
    s = SURFACES["sla"]()
    d = with_center_points(full_factorial(["A", "B"]), 4)
    fit, factors = _fit(s, d, ["A", "B"])
    rec = recommend(fit, factors, direction="maximize", fitted_ids=["A", "B"], held_fixed={},
                    exclude_levels=[{"A": 16, "B": 16}])
    assert rec.levels != {"A": 16, "B": 16}


def test_minimize_direction_picks_the_smallest_prediction():
    s = SURFACES["additive"]()
    d = with_center_points(full_factorial(["A", "B", "C"]), 4)
    fit, factors = _fit(s, d, ["A", "B", "C"])
    rec = recommend(fit, factors, direction="minimize", fitted_ids=["A", "B", "C"], held_fixed={})
    assert rec.levels == {"A": 16, "B": 2, "C": "off"}
```

(add `import pytest` at the top.)

- [ ] **Step 2: Run** → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `orchestrator/optimize/decide.py`**

```python
"""The recommendation: x-hat = argmax over X_valid of the fitted response.

Spec §3.3. A stationary point of a quadratic is where the gradient vanishes —
which is a saddle or a minimum as readily as a maximum, and which ignores
choice factors entirely. Observed on a live campaign: the confirmed
"optimum" was 38% below a corner the screen had already measured. The paper's
recommendation is enumeration over the valid space instead; for the small
spaces this kind handles that is exact and needs no model judgement.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from orchestrator.optimize.effects import Fit
from orchestrator.optimize.factors import Factor, decode_coded, is_refinable


@dataclass(frozen=True)
class Candidate:
    levels: dict
    coded: dict
    predicted: float


def predict(fit: Fit, coded: dict) -> float:
    """intercept + sum over every fitted term of estimate * product(coded)."""
    y = float(fit.intercept)
    for e in list(fit.effects) + list(fit.quadratic):
        y += e.estimate * math.prod(float(coded[t]) for t in e.terms)
    return y


def _axis(f: Factor, *, max_points: int = 9) -> list[tuple[float, object]]:
    low, high = f.screen_levels
    if f.type == "choice" or not is_refinable(f):
        return [(-1.0, low), (1.0, high)]
    mid = (float(low) + float(high)) / 2.0
    half = (float(high) - float(low)) / 2.0 or 1.0
    seen: dict = {}
    for i in range(max_points):
        coded = -1.0 + 2.0 * i / (max_points - 1)
        level = decode_coded(f, coded)
        seen.setdefault(level, (float(level) - mid) / half)
    return sorted(((c, lv) for lv, c in seen.items()), key=lambda p: p[0])


def _excluded(levels: dict, exclude_levels) -> bool:
    for ex in exclude_levels or ():
        shared = set(ex) & set(levels)
        if shared and all(levels[k] == ex[k] for k in shared):
            return True
    return False


def candidates(fit_ids, factors, *, held_fixed: dict, exclude_levels=()) -> list[Candidate]:
    by_id = {f.id: f for f in factors}
    ids = list(fit_ids)
    axes = [_axis(by_id[fid]) for fid in ids]
    out: list[Candidate] = []
    for combo in itertools.product(*axes):
        coded = {fid: c for fid, (c, _) in zip(ids, combo)}
        levels = {**dict(held_fixed), **{fid: lv for fid, (_, lv) in zip(ids, combo)}}
        if _excluded(levels, exclude_levels):
            continue
        out.append(Candidate(levels=levels, coded=coded, predicted=float("nan")))
    return out


def recommend(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
              exclude_levels=()) -> Candidate:
    sign = 1.0 if direction != "minimize" else -1.0
    best = None
    for c in candidates(fitted_ids, factors, held_fixed=held_fixed, exclude_levels=exclude_levels):
        p = predict(fit, c.coded)
        c = Candidate(levels=c.levels, coded=c.coded, predicted=p)
        if best is None or sign * p > sign * best.predicted:
            best = c
    if best is None:
        raise ValueError("no valid candidate remains after exclusions")
    return best


def ranked(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
           exclude_levels=(), top: int = 5) -> list[Candidate]:
    sign = 1.0 if direction != "minimize" else -1.0
    scored = [Candidate(c.levels, c.coded, predict(fit, c.coded))
              for c in candidates(fitted_ids, factors, held_fixed=held_fixed, exclude_levels=exclude_levels)]
    return sorted(scored, key=lambda c: -sign * c.predicted)[:top]
```

- [ ] **Step 4: Wire into `stage_runner.py`.** Add `from orchestrator.optimize import decide` (Task 8 adds `certificate`) and `from orchestrator.optimize.stage import observations_from_decision` at the top. **First, fix the infeasible-row fit** — today `_fitting_responses` returns NaN for `infeasible`/`rejected` rows and `fit_effects` receives them, so one constraint-violating corner NaN-poisons every coefficient while `effects.json` stays schema-valid (verified by reading `_fitting_responses` and `fit_effects`; `tests/test_optimize_iteration.py::test_infeasible_and_rejected_rows_do_not_block_the_fit` only checks the NaN is *carried*, not what the fit does with it). Replace the single `fit_effects(design, ys, ...)` call with:

```python
    keep = [i for i, y in enumerate(ys) if y == y]
    excluded_rows = [i for i in range(len(ys)) if i not in keep]
    if excluded_rows:
        from orchestrator.optimize.design import Design as _Design
        design_fit = _Design(points=tuple(design.points[i] for i in keep), factor_ids=design.factor_ids,
                             kind=design.kind, resolution=design.resolution, generators=design.generators)
        ys_fit = [ys[i] for i in keep]
        logger.info("%s: fitting on %d of %d rows; %d infeasible/rejected row(s) excluded: %s",
                    stage_name, len(keep), len(ys), len(excluded_rows), excluded_rows)
    else:
        design_fit, ys_fit = design, ys
    try:
        fit = fit_effects(design_fit, ys_fit, factor_ids=fitted_ids)
    except ValueError as exc:      # singular after exclusions
        raise OptimizationAborted(
            f"{stage_name}: after excluding {len(excluded_rows)} infeasible/rejected row(s) the "
            f"remaining {len(keep)} runs cannot estimate the model ({exc}); widen the constraint or "
            f"the design") from exc
```

and record `"excluded_rows": excluded_rows` in `effects.json` (`artifacts.write_effects` accepts a `**extra` mapping — add it). Then, after `write_effects`:

```python
    direction = (response_spec.get("primary") or {}).get("direction", "maximize")
    prev = _read_recommendation(work_dir) if stage_name == Stage.REFINE.value else None
    held_now = dict(payload.get("held_fixed") or {})
    excluded = _measured_infeasible(work_dir)
    top = decide.ranked(fit, factors, direction=direction, fitted_ids=fitted_ids,
                        held_fixed=held_now, exclude_levels=excluded, top=5)
    rec = top[0]
    stationary = solve_stationary_point(fit, fitted_ids) if stage_name == Stage.REFINE.value else None
    _write_json(iter_dir / "recommendation.json", {
        "stage": stage_name, "iteration": iteration,
        "levels": rec.levels, "coded": rec.coded, "predicted": rec.predicted,
        "fitted_ids": list(fitted_ids), "held_fixed": held_now,
        "top_candidates": [{"levels": c.levels, "coded": c.coded, "predicted": c.predicted} for c in top],
        "stationary_point": stationary, "excluded_measured_infeasible": excluded,
    })
```

Change the refine held-fixed block: `fixed = {f.id: (prev_levels.get(f.id) if prev_levels and f.id in prev_levels else f.levels[0]) for f in held if getattr(f, "levels", None)}` where `prev_levels = (_read_recommendation(work_dir) or {}).get("levels")`; keep writing `payload["held_fixed"]`. Replace `_read_confirm_at` with:

```python
def _read_recommendation(work_dir) -> dict | None:
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return None
    def _iter_index(path: Path) -> int:
        try:
            return int(path.name.split("-", 1)[1])
        except (IndexError, ValueError):
            return -1
    for d in sorted((p for p in runs.iterdir() if p.is_dir()), key=_iter_index, reverse=True):
        p = d / "recommendation.json"
        if p.exists():
            return json.loads(p.read_text())
    return None


def _measured_infeasible(work_dir) -> list[dict]:
    out: list[dict] = []
    for d in (Path(work_dir) / "runs").glob("iter-*"):
        for row in artifacts.read_runs(d):
            if row.get("status") in ("infeasible", "rejected") and row.get("levels"):
                out.append(dict(row["levels"]))
    return out
```

Confirm target: where `_build_design` reads `confirm_at`, read `(_read_recommendation(work_dir) or {}).get("levels")` and build rows directly at those levels via `matrix.render_apply` (the same way the `best_observed` path already does); coded coordinates are no longer needed for confirm. Delete `_write_json(iter_dir / "confirm_at.json", …)`, `_read_confirm_at`, and the `confirm_at` design-config lookup.

- [ ] **Step 5: Update tests.** In `tests/test_optimize_iteration.py`: `test_confirm_honours_the_refine_stages_solved_optimum` → assert confirm ran at `recommendation.json["levels"]` of the refine iteration; `test_confirm_at_is_read_from_the_latest_iteration_numerically` / `…survives_a_non_numeric_iteration_directory` → same tests against `_read_recommendation` with `recommendation.json` files. In `tests/test_optimize_harness.py` remove the `xfail` decorators from `test_saddle_surface_recommends_a_corner_not_the_saddle_point` and `test_choice_x_numeric_recommends_the_on_branch`.

- [ ] **Step 6: Run** `python -m pytest tests/ -q -x` → PASS (strict xfails for `sla`, `bowl_out_of_hull`, `nan_at_corner` still XFAIL).

- [ ] **Step 7: Commit** — `git commit -am "feat(optimize): recommend() = argmax over X_valid; refine holds non-designed factors at the screen recommendation"`.

### Task 8: `certificate.py` — model-based residual-regret bound with a coverage test

**Files:**
- Create: `orchestrator/optimize/certificate.py`
- Modify: `orchestrator/optimize/stage_runner.py` (add `residual_regret_model` to `recommendation.json`)
- Test: `tests/test_optimize_certificate.py`

**Interfaces:**
- Consumes: `decide.Candidate/predict/ranked`, `Fit`.
- Produces: `RegretBound`, `model_regret_bound`, `resolve_epsilon`; `recommendation.json["residual_regret_model"] = {"value", "challenger", "delta", "method", "detail"}`.

$U_\delta(z,\widehat x)=\text{sign}\cdot(\widehat f(z)-\widehat f(\widehat x)) + t_{1-\delta/M,\,df}\sqrt{\sum_e se_e^2\,(\prod_t z_t-\prod_t x_t)^2}$; $R=\max_z U$ over all candidates (including $\widehat x$, so $R\ge 0$). No pure-error df ⇒ `value=None`, `method="none"`. Method name is honest: `"bonferroni_one_sided_t"`.

- [ ] **Step 1: Write the failing tests**

```python
"""The certificate must COVER: over many replays the true gap exceeds R at
most a delta fraction of the time (paper eq. 2). Monte-Carlo on a correctly
specified synthetic surface; no work_dir, no LLM — fits are milliseconds.
"""
from __future__ import annotations

import random

import pytest

from orchestrator.optimize.certificate import RegretBound, model_regret_bound, resolve_epsilon
from orchestrator.optimize.decide import ranked
from orchestrator.optimize.design import full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import expand
from orchestrator.optimize.synthetic import SURFACES, true_optimum


def _replay(surface, seed, delta):
    factors = parse_factors(list(surface.factors))
    ids = [f.id for f in factors]
    d = with_center_points(full_factorial(ids), 4)
    rng = random.Random(seed)
    rows = expand(d, factors)
    ys = [surface.fn(r.levels) + rng.gauss(0, surface.noise_sd) for r in rows]
    fit = fit_effects(d, ys, factor_ids=ids)
    top = ranked(fit, factors, direction="maximize", fitted_ids=ids, held_fixed={}, top=10 ** 6)
    xhat = top[0]
    bound = model_regret_bound(fit, top, xhat, delta=delta, direction="maximize")
    _, best = true_optimum(surface)
    true_gap = best - surface.fn(xhat.levels)
    return bound, true_gap


def test_bound_is_none_without_a_pure_error_estimate():
    s = SURFACES["additive"]()
    factors = parse_factors(list(s.factors)); ids = [f.id for f in factors]
    d = full_factorial(ids)                                     # no centre points
    fit = fit_effects(d, [s.fn(r.levels) for r in expand(d, factors)], factor_ids=ids)
    top = ranked(fit, factors, direction="maximize", fitted_ids=ids, held_fixed={})
    b = model_regret_bound(fit, top, top[0], delta=0.05, direction="maximize")
    assert b.value is None and b.method == "none"


def test_coverage_on_a_correctly_specified_surface():
    s = SURFACES["additive"]()
    delta, misses, n = 0.10, 0, 300
    for seed in range(n):
        bound, gap = _replay(s, seed, delta)
        assert bound.value is not None and bound.value >= 0
        if gap > bound.value + 1e-12:
            misses += 1
    assert misses / n <= delta + 0.03, misses


def test_bound_shrinks_with_less_noise():
    import dataclasses
    s = SURFACES["additive"]()
    loud, _ = _replay(dataclasses.replace(s, noise_sd=0.5), 1, 0.05)
    quiet, _ = _replay(dataclasses.replace(s, noise_sd=0.01), 1, 0.05)
    assert quiet.value < loud.value


def test_resolve_epsilon_abs_and_pct():
    assert resolve_epsilon({"abs": 0.5}, 100.0) == 0.5
    assert resolve_epsilon({"pct": 2.0}, 50.0) == pytest.approx(1.0)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement `orchestrator/optimize/certificate.py`**

```python
"""Residual-regret certificates: how much better could any challenger still be?

Spec §3.3, paper eq. (2). Two flavours: MODEL-based (screen/refine — depends
on the registered response class; exact for orthogonal main/2fi columns,
optimistic for quadratic terms per effects.py) and TERMINAL (Task 9 — model
free, from fresh replicates of the finalists). Bonferroni over the M
challengers is conservative and honest; the method string says so.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, variance

from scipy.stats import t as student_t

from orchestrator.optimize.decide import Candidate, predict
from orchestrator.optimize.effects import Fit


@dataclass(frozen=True)
class RegretBound:
    value: float | None
    challenger: dict | None
    delta: float
    method: str
    detail: str


def _to_dict(b: RegretBound) -> dict:
    return {"value": b.value, "challenger": b.challenger, "delta": b.delta,
            "method": b.method, "detail": b.detail}


def model_regret_bound(fit: Fit, cands: list[Candidate], xhat: Candidate, *,
                       delta: float, direction: str) -> RegretBound:
    terms = list(fit.effects) + list(fit.quadratic)
    if fit.pure_error_df <= 0 or any(e.se is None for e in terms):
        return RegretBound(None, None, delta, "none",
                           "no pure-error estimate (no replicated centre points) — unknown is not zero")
    sign = 1.0 if direction != "minimize" else -1.0
    others = [c for c in cands if c.levels != xhat.levels]
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single candidate")
    tcrit = float(student_t.ppf(1 - delta / len(others), fit.pure_error_df))
    fx = predict(fit, xhat.coded)
    best_u, best_z = 0.0, None
    for z in others:
        est = sign * (predict(fit, z.coded) - fx)
        var = 0.0
        for e in terms:
            dz = math.prod(float(z.coded[t]) for t in e.terms) - math.prod(float(xhat.coded[t]) for t in e.terms)
            var += (e.se or 0.0) ** 2 * dz * dz
        u = est + tcrit * math.sqrt(var)
        if u > best_u:
            best_u, best_z = u, z.levels
    return RegretBound(best_u, best_z, delta, "bonferroni_one_sided_t",
                       f"M={len(others)} challengers, df={fit.pure_error_df}, t={tcrit:.3f}")


def resolve_epsilon(spec: dict, reference: float) -> float:
    if "abs" in spec:
        return float(spec["abs"])
    return abs(float(reference)) * float(spec.get("pct", 2.0)) / 100.0
```

- [ ] **Step 4: Wire.** In the Task 7 block of `stage_runner.py`, after `top = decide.ranked(...)`: `rb = certificate.model_regret_bound(fit, decide.ranked(..., top=10**6), rec, delta=pol["objective"]["delta_screen"], direction=direction)` and add `"residual_regret_model": certificate._to_dict(rb)` to `recommendation.json`; add `"residual_regret": rb.value` and `"epsilon": certificate.resolve_epsilon(pol["objective"]["epsilon"], rec.predicted)` to the observations dict.

- [ ] **Step 5: Run** `python -m pytest tests/test_optimize_certificate.py tests/test_optimize_iteration.py -q` → PASS. The coverage test should take < 5 s; if slower, drop `n` to 200.

- [ ] **Step 6: Commit** — `git commit -am "feat(optimize): model-based residual-regret bound with Monte-Carlo coverage test"`.

### Task 9: Terminal discrimination — `confirm` over a shortlist, terminal bound, `report.json`, baseline

**Files:**
- Modify: `orchestrator/optimize/certificate.py` (add `terminal_regret_bound`)
- Modify: `orchestrator/optimize/stage_runner.py` (`_finish_confirm`, confirm row construction, `_run_report`)
- Modify: `orchestrator/schemas/campaign.schema.yaml` (`design.confirm.shortlist_size`; new `optimization.policy`, `optimization.known_valid_baseline`)
- Modify: `orchestrator/validate.py` (rule 13: baseline inside declared levels; rule 14: `policy` ranges)
- Modify: `orchestrator/optimize/policy.py` (`shortlist_size` default 3)
- Test: `tests/test_optimize_certificate.py` (append), `tests/test_optimize_iteration.py` (append + adjust), `tests/test_optimize_harness.py` (remove `sla` xfail), `tests/test_optimize_campaign_schema.py` (append)

**Interfaces:**
- Produces: `terminal_regret_bound(samples, best, *, delta, direction, paired) -> RegretBound`; `confirmation.json` = `{"stage": "confirm", "iteration", "round", "finalists": [{"key", "levels", "samples", "mean", "n", "status"}], "best": key, "bounds": {key: U}, "epsilon", "residual_regret_terminal", "certified", "paired", "excluded_infeasible": [...]}`; `report.json` = `{"recommendation": {"levels", "basis", "predicted"|"mean"}, "residual_regret_model", "residual_regret_terminal", "epsilon", "delta_screen", "delta_terminal", "certified", "finalists", "known_valid_baseline", "path", "epoch", "policy_hash", "iteration"}`.

Rules (spec §3.2 confirm, §3.3 ladder):
- Round 1 finalists (dedup by levels, in this priority): latest `recommendation.json.levels`; best measured valid `complete` row; then `top_candidates` in order; stop at `shortlist_size`. Round $r>1$: previous round's best plus every finalist whose bound exceeded ε.
- Rows: for replicate `i` in `range(replicates)`: every finalist once, order within the block randomized with seed `iteration*1000+i`; `role="confirm"`, `replicate=i`, `payload["finalists"]`.
- After execution: a finalist with any `infeasible`/`rejected`/`failed` replicate is excluded (`status: "excluded"`) — measured invalidity trumps prediction. Best = best mean by direction among remaining. `paired=False` in this task (Task 14 makes it `True` under CRN).
- `terminal_regret_bound`: Bonferroni one-sided Welch t over the $M=|S|-1$ challengers; `None` if any finalist has $n<2$.
- ε = `resolve_epsilon(objective.epsilon, |best mean|)`; `certified = R is not None and R <= ε`.
- Observations: `certified, round, budget_remaining, runs_needed_confirm=len(S)*replicates, residual_regret, epsilon, correctness_failed=False, nan_response`.
- Report basis ladder: `certified` → `terminal_best` → `model` (a recommendation.json exists, terminal never ran) → `measured` → `baseline`.
- `optimization.known_valid_baseline` (map factor id → level): validator rule 13 hard-fails a baseline naming an unknown factor or a level outside `levels`; rule 14 hard-fails `policy.delta_* ∉ (0, 0.5]`, `epsilon` with both/neither of `abs`/`pct`, `confirm_max_rounds < 1`.
- Default `shortlist_size` becomes **3**. Legacy single-point tests set `shortlist_size: 1` explicitly (see Step 5).

- [ ] **Step 1: Failing tests** — append to `tests/test_optimize_certificate.py`:

```python
from orchestrator.optimize.certificate import terminal_regret_bound


def test_terminal_bound_is_none_with_fewer_than_two_replicates():
    b = terminal_regret_bound({"x": [1.0], "y": [2.0]}, "y", delta=0.05, direction="maximize", paired=False)
    assert b.value is None


def test_terminal_bound_certifies_a_clear_winner_and_not_a_close_race():
    clear = terminal_regret_bound({"x": [1.0, 1.1, 0.9, 1.0], "y": [5.0, 5.1, 4.9, 5.0]}, "y",
                                  delta=0.05, direction="maximize", paired=False)
    close = terminal_regret_bound({"x": [4.9, 5.2, 4.8, 5.1], "y": [5.0, 5.1, 4.9, 5.0]}, "y",
                                  delta=0.05, direction="maximize", paired=False)
    assert clear.value < 0.5 and close.value > 0.2 and clear.challenger == "x"


def test_terminal_bound_respects_minimize():
    b = terminal_regret_bound({"x": [1.0, 1.1, 0.9], "y": [5.0, 5.1, 4.9]}, "x",
                              delta=0.05, direction="minimize", paired=False)
    assert b.value < 0.5


def test_terminal_coverage_over_replays():
    import random
    from statistics import mean
    delta, misses, n = 0.10, 0, 400
    truth = {"a": 10.0, "b": 10.3, "c": 9.5}
    for seed in range(n):
        rng = random.Random(seed)
        samples = {k: [v + rng.gauss(0, 0.3) for _ in range(4)] for k, v in truth.items()}
        best = max(samples, key=lambda k: mean(samples[k]))
        b = terminal_regret_bound(samples, best, delta=delta, direction="maximize", paired=False)
        if max(truth.values()) - truth[best] > b.value:
            misses += 1
    assert misses / n <= delta + 0.03
```

Append to `tests/test_optimize_iteration.py`:

```python
def test_confirm_compares_a_shortlist_of_finalists_with_fresh_replicates(tmp_path, work_dir):
    c = _campaign()
    c["optimization"]["design"]["confirm"] = {"replicates": 3, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _run(c, wd, stage="screen", iteration=2)
    _run(c, wd, stage="confirm", iteration=3)
    conf = json.loads((wd / "runs" / "iter-3" / "confirmation.json").read_text())
    assert len(conf["finalists"]) == 3 and all(f["n"] == 3 for f in conf["finalists"])
    assert conf["residual_regret_terminal"] is not None
    rep = json.loads((wd / "report.json").read_text())
    assert rep["recommendation"]["basis"] in ("certified", "terminal_best")
    assert rep["residual_regret_terminal"] == conf["residual_regret_terminal"]


def test_a_finalist_measured_infeasible_is_excluded_from_the_recommendation(tmp_path, work_dir):
    c = _campaign()
    c["optimization"]["response"]["constraints"] = [{"metric": "m", "op": "<", "value": 13.4}]
    c["optimization"]["design"]["confirm"] = {"replicates": 2, "shortlist_size": 3}
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _run(c, wd, stage="screen", iteration=2)
    _run(c, wd, stage="confirm", iteration=3)
    conf = json.loads((wd / "runs" / "iter-3" / "confirmation.json").read_text())
    assert any(f["status"] == "excluded" for f in conf["finalists"])
    rep = json.loads((wd / "report.json").read_text())
    assert _runner()(type("R", (), {"levels": rep["recommendation"]["levels"]})())["m"] < 13.4


def test_report_falls_back_to_the_known_valid_baseline_when_nothing_measured_is_valid(tmp_path, work_dir):
    c = _campaign()
    c["optimization"]["known_valid_baseline"] = {"A": 2, "B": 2, "C": 2}
    c["optimization"]["response"]["constraints"] = [{"metric": "m", "op": "<", "value": -1}]  # nothing valid
    wd = _init_work_dir(tmp_path, c)
    _run(c, wd, stage="verify", iteration=1)
    _run(c, wd, stage="screen", iteration=2)
    _run(c, wd, stage="confirm", iteration=3)
    rep = json.loads((wd / "report.json").read_text())
    assert rep["recommendation"] == {"levels": {"A": 2, "B": 2, "C": 2}, "basis": "baseline"}
```

Append to `tests/test_optimize_campaign_schema.py` (use that file's existing `validate`/campaign helpers):

```python
def test_known_valid_baseline_outside_declared_levels_is_rejected(valid_optimization_campaign):
    c = valid_optimization_campaign
    c["optimization"]["known_valid_baseline"] = {"L1": 999}
    errs = validate_optimization_campaign(c)
    assert any("known_valid_baseline" in e for e in errs)


def test_policy_block_ranges_are_validated(valid_optimization_campaign):
    c = valid_optimization_campaign
    c["optimization"]["policy"] = {"delta_terminal": 0.9}
    assert any("delta_terminal" in e for e in validate_optimization_campaign(c))
```

(If the file has no `valid_optimization_campaign` fixture, build the campaign from `synthetic_campaign(SURFACES["additive"]())`.)

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement `terminal_regret_bound`** (append to `certificate.py`):

```python
def terminal_regret_bound(samples: dict[str, list[float]], best: str, *, delta: float,
                          direction: str, paired: bool) -> RegretBound:
    """Model-free one-sided upper bounds on each finalist's improvement over
    ``best`` from fresh replicates; Bonferroni over the M challengers.
    Paired differences under common random numbers, Welch otherwise."""
    others = [k for k in samples if k != best]
    if not others:
        return RegretBound(0.0, None, delta, "trivial", "single finalist")
    if any(len(v) < 2 for v in samples.values()):
        return RegretBound(None, None, delta, "none", "need >= 2 replicates per finalist")
    sign = 1.0 if direction != "minimize" else -1.0
    xb = samples[best]
    best_u, best_z = 0.0, None
    for k in others:
        xk = samples[k]
        if paired and len(xk) == len(xb):
            d = [sign * (b - a) for a, b in zip(xb, xk)]
            n = len(d); m = mean(d); se = math.sqrt(variance(d) / n) if n > 1 else 0.0; df = n - 1
        else:
            m = sign * (mean(xk) - mean(xb))
            vk, vb = variance(xk) / len(xk), variance(xb) / len(xb)
            se = math.sqrt(vk + vb)
            df = ((vk + vb) ** 2 / ((vk ** 2) / (len(xk) - 1) + (vb ** 2) / (len(xb) - 1))
                  if (vk + vb) > 0 else 1.0)
        tcrit = float(student_t.ppf(1 - delta / len(others), max(df, 1.0)))
        u = m + tcrit * se
        if u > best_u:
            best_u, best_z = u, k
    return RegretBound(best_u, best_z, delta,
                       "bonferroni_one_sided_t_paired" if paired else "bonferroni_one_sided_welch_t",
                       f"M={len(others)} challengers")
```

- [ ] **Step 4: Implement the confirm state in `stage_runner.py`.** Replace the confirm branch of `_build_design` and the confirm-specific row rewriting in `run_stage` with a helper called before `write_design_matrix`:

```python
def _confirm_rows(pol: dict, work_dir: Path, factors, primary: str, direction: str,
                  iteration: int) -> tuple[list, dict]:
    """Finalists × replicates as ConfigRows plus the design_matrix payload."""
    import dataclasses
    from orchestrator.optimize.matrix import ConfigRow, randomized_run_order, render_apply

    cfg = pol["states"]["confirm"]["design"]
    k, r = int(cfg["shortlist_size"]), int(cfg["replicates"])
    prev_confirms = [t for t in policy_mod.read_transitions(work_dir) if t["from"] == "confirm"]
    rnd = len(prev_confirms) + 1
    finalists: list[dict] = []

    def _add(levels):
        if levels and all(levels != f for f in finalists) and len(finalists) < k:
            finalists.append(dict(levels))

    if rnd > 1:
        prev = _latest_confirmation(work_dir)
        eps = prev["epsilon"]
        _add(next(f["levels"] for f in prev["finalists"] if f["key"] == prev["best"]))
        for f in prev["finalists"]:
            if f["status"] == "ok" and prev["bounds"].get(f["key"], 0.0) > eps:
                _add(f["levels"])
    else:
        rec = _read_recommendation(work_dir) or {}
        _add(rec.get("levels"))
        best = _best_observed(work_dir, primary)
        if best is not None:
            _add(best["levels"])
        for c in rec.get("top_candidates") or []:
            _add(c["levels"])
        if not finalists and pol.get("known_valid_baseline"):
            _add(pol["known_valid_baseline"])
    if not finalists:
        raise OptimizationAborted("confirm has no finalist: no recommendation, no measured row, no baseline")

    rows: list[ConfigRow] = []
    idx = 0
    for i in range(r):
        order = randomized_run_order(len(finalists), seed=iteration * 1000 + i)
        for j in order:
            lv = finalists[j]
            rows.append(ConfigRow(row_index=idx, levels=dict(lv), role="confirm", replicate=i,
                                  apply={**render_apply(factors, lv), "finalist": j}))
            idx += 1
    payload = {
        "factor_ids": [f.id for f in factors], "kind": "shortlist_replicate", "resolution": None,
        "generators": [], "aliases": [], "run_order": list(range(len(rows))),
        "run_order_seed": iteration, "round": rnd,
        "finalists": [{"key": f"f{j}", "levels": lv} for j, lv in enumerate(finalists)],
        "rows": [{"row_index": x.row_index, "levels": dict(x.levels), "role": x.role,
                  "replicate": x.replicate, "apply": x.apply} for x in rows],
    }
    return rows, payload
```

`_finish_confirm` becomes:

```python
def _finish_confirm(engine, campaign, stage_name, iteration, iter_dir, work_dir,
                    rows, outcomes, ys, factors, test_results, pol, payload):
    from statistics import mean
    direction = pol["objective"]["direction"]
    fin = payload["finalists"]
    by_idx = {r.row_index: r for r in rows}
    samples: dict[str, list[float]] = {f["key"]: [] for f in fin}
    status: dict[str, str] = {f["key"]: "ok" for f in fin}
    for o, y in zip(outcomes, ys):
        key = f"f{by_idx[o.row_index].apply['finalist']}"
        if o.status != "complete" or y != y:
            status[key] = "excluded"
        else:
            samples[key].append(float(y))
    ok = {k: v for k, v in samples.items() if status[k] == "ok" and v}
    sign = 1.0 if direction != "minimize" else -1.0
    best = max(ok, key=lambda k: sign * mean(ok[k])) if ok else None
    bound = (certificate.terminal_regret_bound(ok, best, delta=pol["objective"]["delta_terminal"],
                                               direction=direction, paired=bool(payload.get("paired")))
             if best else certificate.RegretBound(None, None, pol["objective"]["delta_terminal"], "none", "no valid finalist"))
    eps = certificate.resolve_epsilon(pol["objective"]["epsilon"], mean(ok[best]) if best else 0.0)
    certified = bound.value is not None and bound.value <= eps
    bounds = {}
    for k in ok:
        if k != best:
            bounds[k] = certificate.terminal_regret_bound({best: ok[best], k: ok[k]}, best,
                                                          delta=pol["objective"]["delta_terminal"],
                                                          direction=direction, paired=bool(payload.get("paired"))).value
    summary = {
        "stage": stage_name, "iteration": iteration, "round": payload["round"],
        "finalists": [{"key": f["key"], "levels": f["levels"], "samples": samples[f["key"]],
                       "mean": mean(samples[f["key"]]) if samples[f["key"]] else None,
                       "n": len(samples[f["key"]]), "status": status[f["key"]]} for f in fin],
        "best": best, "bounds": bounds, "epsilon": eps,
        "residual_regret_terminal": bound.value, "certified": certified,
        "paired": bool(payload.get("paired")),
        "excluded_infeasible": [f["levels"] for f in fin if status[f["key"]] == "excluded"],
        # legacy fields kept for readers of the old single-point record
        "confirmed_at_levels": next((f["levels"] for f in fin if f["key"] == best), {}),
        "replicates": len(outcomes), "usable_replicates": sum(len(v) for v in ok.values()),
        "mean": mean(ok[best]) if best else None,
    }
    _write_json(iter_dir / "confirmation.json", summary)
    _write_json(iter_dir / "findings.json", _confirm_findings(summary, iteration))
    _write_json(iter_dir / "principle_updates.json", [])
    artifacts.write_relations(iter_dir, relations.reconcile(factors, test_results or {}))
    obs = {"correctness_failed": False, "nan_response": any(y != y for y in ys),
           "certified": certified, "round": payload["round"],
           "budget_remaining": _budget_remaining(pol, work_dir),
           "runs_needed_confirm": len(fin) * int(pol["states"]["confirm"]["design"]["replicates"]),
           "residual_regret": bound.value, "epsilon": eps}
    return _close_iteration(engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
                            recommendation_levels=summary["confirmed_at_levels"] or None)
```

`_confirm_findings`: read `summary["best"]`/`["certified"]`; `status = "CONFIRMED" if certified else ("PARTIALLY_CONFIRMED" if summary["best"] else "REFUTED")`; observed string names best, mean, R, ε. `_latest_confirmation(work_dir)` mirrors `_read_recommendation` for `confirmation.json`.

`_run_report` (replace Task 6's minimal version):

```python
def _run_report(engine, campaign, work_dir, iteration, pol, *, recommendation_levels):
    metric = pol["objective"]["metric"]
    conf = _latest_confirmation(work_dir)
    rec = _read_recommendation(work_dir) or {}
    if conf and conf.get("best"):
        basis = "certified" if conf["certified"] else "terminal_best"
        levels, value = conf["confirmed_at_levels"], conf["mean"]
    elif rec.get("levels") and not _measured_infeasible_contains(work_dir, rec["levels"]):
        basis, levels, value = "model", rec["levels"], rec.get("predicted")
    else:
        best = _best_observed(work_dir, metric) if metric else None
        if best:
            basis, levels, value = "measured", dict(best["levels"]), best.get(metric)
        elif pol.get("known_valid_baseline"):
            basis, levels, value = "baseline", dict(pol["known_valid_baseline"]), None
        else:
            basis, levels, value = "none", {}, None
    trans = policy_mod.read_transitions(work_dir)
    _write_json(Path(work_dir) / "report.json", {
        "recommendation": {"levels": levels, "basis": basis, **({"value": value} if value is not None else {})},
        "residual_regret_model": (rec.get("residual_regret_model") or {}).get("value"),
        "residual_regret_terminal": conf.get("residual_regret_terminal") if conf else None,
        "epsilon": conf.get("epsilon") if conf else None,
        "delta_screen": pol["objective"]["delta_screen"], "delta_terminal": pol["objective"]["delta_terminal"],
        "certified": bool(conf and conf.get("certified")),
        "finalists": conf.get("finalists") if conf else [],
        "known_valid_baseline": pol.get("known_valid_baseline"),
        "path": [t["from"] for t in trans] + ([trans[-1]["to"]] if trans else []),
        "epoch": pol["epoch"], "policy_hash": policy_mod.policy_hash(pol), "iteration": iteration,
    })
    engine.transition("DONE")
```

Note the third test: `_best_observed` must only consider `status == "complete"` rows (check its implementation; if it does not filter, add the filter — an infeasible row is not a valid answer). `recommendation.json` from screen also exists in that test, so `_measured_infeasible_contains` must return True when the recommended levels were measured infeasible — under a `<-1` constraint every screen row is infeasible, so `_best_observed` is None and `rec` is excluded → baseline.

- [ ] **Step 5: Schema + validator + defaults.** In `campaign.schema.yaml` add under `design.confirm.properties`: `shortlist_size: {type: integer, minimum: 1, description: "Finalists compared with fresh replicates at confirm (paper: terminal discrimination). Default 3; 1 reproduces single-point confirmation."}`; under `optimization.properties`: `known_valid_baseline: {type: object, additionalProperties: true, description: "Factor id -> level of a configuration known to be valid; the bottom rung of the report's fallback ladder. Required when build is declared."}` and `policy: {type: object, additionalProperties: false, properties: {epsilon: {type: object}, delta_screen: {type: number}, delta_terminal: {type: number}, confirm_max_rounds: {type: integer, minimum: 1}}}`. In `validate.py` add `_rule13_known_valid_baseline` and `_rule14_policy_ranges` and call them from `validate_optimization_campaign`. In `policy.py` change the default `shortlist_size` to 3.
  Update legacy tests that assumed one configuration at confirm: in `tests/test_optimize_iteration.py::_campaign` set `"confirm": {"replicates": 3, "shortlist_size": 1}` (so `test_confirm_replicates_one_configuration…`, `…writes_a_confirmation_record_and_no_effects`, `…findings_validate_and_report_reproduction`, `test_confirm_honours_the_refine_stages_solved_optimum` keep their meaning); the two new tests above override it to 3. In `tests/test_optimize_harness.py` remove the xfail from `test_sla_surface_never_recommends_an_invalid_point`. Update `docs/optimization-campaign-guide.md` examples if `test_optimize_guide_examples.py` complains about `shortlist_size` (it should not — the field is optional).

- [ ] **Step 6: Run** `python -m pytest tests/ -q -x` → PASS.

- [ ] **Step 7: Commit** — `git commit -am "feat(optimize): terminal discrimination over finalists, terminal regret bound, report.json with fallback ladder and known_valid_baseline"`.

### Task 10: Foldover when aliasing is consequential (and an alias-aware fit)

**Pre-existing defect this task fixes first:** `fit_effects` builds one column per two-factor interaction, so on any resolution-III/IV screen two columns coincide and `_solve_normal_equations` raises `design matrix is singular`. Resolution < 5 is validator-permitted (rule 7 only warns) but has been unrunnable. Verified on the branch:
`with_center_points(fractional_factorial("ABCD", 4), 4)` → `alias_pairs = [(AB,CD),(AC,BD),(AD,BC)]` and `fit_effects` raises.

**Files:**
- Modify: `orchestrator/optimize/effects.py` (`Effect.aliased_with`, alias-aware column build)
- Modify: `orchestrator/optimize/design.py` (`Design.folded_on`, `foldover`, `combine`)
- Modify: `orchestrator/optimize/decide.py` (`alias_consequential`)
- Modify: `orchestrator/optimize/policy.py` (`foldover` state + rules; `policy.foldover` opt-out)
- Modify: `orchestrator/optimize/stage.py` (`Stage.FOLDOVER = "foldover"`)
- Modify: `orchestrator/optimize/stage_runner.py` (foldover state execution; `alias_consequential`/`runs_needed_foldover` observations)
- Test: `tests/test_optimize_foldover.py`; `tests/test_optimize_effects.py` (append)

**Interfaces:**
- `Effect.aliased_with: tuple[tuple[str, ...], ...] = ()` — term tuples whose design column coincided with (or negated) this effect's column and were therefore not fitted separately.
- `design.foldover(design: Design, *, on: str | None = None) -> Design` — corners with every column negated (`on=None`, full foldover: res III → IV) or only column `on` negated (single-factor foldover: separates every 2fi containing `on` from its alias); centre points replicated with the same count; `kind="foldover"`, `folded_on=on`.
- `design.combine(a: Design, b: Design) -> Design` — points concatenated; `kind="combined"`; `resolution=None`; `generators=a.generators`.
- `decide.alias_consequential(fit, factors, *, direction, fitted_ids, held_fixed) -> list[tuple[str, str]]` — pairs `(kept_label, alt_label)` where re-attributing the shared estimate to the alternative term changes `recommend()`.
- Policy: state `foldover` `{spends: true, design: {kind: "foldover_of", state: "screen"}, accounting: "combined OLS over screen ∪ foldover runs; per-term t on pooled pure error"}`; rules `screen: alias_consequential==true & budget_remaining >= runs_needed_foldover → foldover` (before the refine rule); `foldover` has screen's rules minus the foldover rule. `optimization.policy.foldover: false` disables the state.
- Artifacts: `runs/iter-N/recommendation.json["alias_consequential"] = [[kept, alt], ...]`; foldover iteration's `design_matrix.json` has `kind: "foldover"`, `folded_on`, `screen_iteration`; its `effects.json` is the **combined** fit.

- [ ] **Step 1: Failing tests** — `tests/test_optimize_foldover.py`:

```python
"""Aliasing is a resource decision: fold over only when it can change the answer.

Surface interaction_only has a strong AB effect and null mains. At resolution
IV (8 runs) AB is aliased with CD; attributing the shared estimate to CD gives
a different recommendation, so the alias is consequential and the policy must
spend the foldover. On additive (no interactions) it must not.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize.design import (
    alias_pairs, combine, foldover, fractional_factorial, with_center_points,
)
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def test_resolution_iv_screen_fits_instead_of_raising_singular():
    d = with_center_points(fractional_factorial(list("ABCD"), resolution=4), 4)
    fit = fit_effects(d, [float(i) for i in range(len(d.points))], factor_ids=list("ABCD"))
    labels = {e.label: e for e in fit.effects}
    assert "AB" in labels and "CD" not in labels
    assert labels["AB"].aliased_with == (("C", "D"),)


def test_single_factor_foldover_separates_ab_from_cd():
    base = fractional_factorial(list("ABCD"), resolution=4)
    both = combine(base, foldover(base, on="A"))
    assert ("AB", "CD") not in alias_pairs(both)
    assert ("AC", "BD") not in alias_pairs(both)


def test_full_foldover_of_resolution_iii_clears_mains():
    base = fractional_factorial(list("ABCDEFG"), resolution=3)
    both = combine(base, foldover(base))
    assert not any(len(b) == 1 for _, b in alias_pairs(both))   # no 2fi aliased to a main


def test_interaction_only_surface_triggers_foldover_and_lands_on_truth(tmp_path):
    res = run_synthetic_campaign(
        SURFACES["interaction_only"](), seed=21, parent_dir=tmp_path,
        campaign_overrides={"design": {"screen": {"resolution": 4, "center_points": 4},
                                       "confirm": {"replicates": 3, "shortlist_size": 3}}},
    )
    assert "foldover" in res.path, res.path
    assert abs(res.true_gap) / abs(res.true_best) <= 0.02, (res.recommendation, res.true_optimum)
    fold_iter = [json.loads(l) for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                 if json.loads(l)["from"] == "foldover"][0]["iteration"]
    dm = json.loads((res.work_dir / "runs" / f"iter-{fold_iter}" / "design_matrix.json").read_text())
    assert dm["kind"] == "foldover" and dm["folded_on"] in list("ABCD")


def test_additive_surface_at_resolution_iv_does_not_fold_over(tmp_path):
    s = SURFACES["additive"]()
    import dataclasses
    from orchestrator.optimize.synthetic import _numeric
    s4 = dataclasses.replace(s, factors=tuple(_numeric(f, levels=(2, 16)) for f in "ABCD"),
                             fn=lambda lv: 10 + 0.1 * lv["A"] + 0.2 * lv["B"] - 0.05 * lv["C"])
    res = run_synthetic_campaign(
        s4, seed=22, parent_dir=tmp_path,
        campaign_overrides={"design": {"screen": {"resolution": 4, "center_points": 4},
                                       "confirm": {"replicates": 3, "shortlist_size": 3}}},
    )
    assert "foldover" not in res.path, res.path


def test_policy_foldover_false_removes_the_state():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy
    pol = compile_policy(synthetic_campaign(SURFACES["additive"](), policy={"foldover": False}))
    assert "foldover" not in pol["states"]
```

- [ ] **Step 2: Run** → FAIL (singular / ImportError).

- [ ] **Step 3: Implement.**

`effects.py`: add `aliased_with: tuple[tuple[str, ...], ...] = ()` to `Effect`. In `fit_effects`, when adding a 2fi column, compare (over **corner points only**, as `alias_pairs` does) against every existing main/2fi column; if identical or exactly negated, do not append a column — record `(ids[i], ids[j])` in `alias_of[existing_index]` (a dict from column index to list of term tuples; a negated alias records the term tuple too, and the estimate sign convention is documented as "attributed to the kept term's column"). When building `Effect`s, pass `aliased_with=tuple(alias_of.get(idx, []))`. Keep `Fit.aliases = alias_pairs(design)` unchanged. On resolution-III designs a 2fi identical to a *main* column is recorded on the main effect (`aliased_with=(("B","C"),)` on `A`); `dropped_factors` is unaffected.

`design.py`:

```python
@dataclass(frozen=True)
class Design:
    ...
    folded_on: str | None = None


def foldover(design: Design, *, on: str | None = None) -> Design:
    """Add the fold-over runs: negate every corner column (full) or only ``on``."""
    ids = design.factor_ids
    j = None if on is None else ids.index(on)
    corners = tuple(
        DesignPoint(coded=tuple(-c if (j is None or k == j) else c for k, c in enumerate(p.coded)),
                    role="corner")
        for p in design.corners
    )
    centres = tuple(p for p in design.points if p.role == "center")
    return Design(points=corners + centres, factor_ids=ids, kind="foldover", resolution=None,
                  generators=design.generators, folded_on=on)


def combine(a: Design, b: Design) -> Design:
    assert a.factor_ids == b.factor_ids
    return Design(points=a.points + b.points, factor_ids=a.factor_ids, kind="combined",
                  resolution=None, generators=a.generators, folded_on=b.folded_on)
```

`decide.py`:

```python
def alias_consequential(fit: Fit, factors, *, direction, fitted_ids, held_fixed) -> list[tuple[str, str]]:
    import dataclasses
    base = recommend(fit, factors, direction=direction, fitted_ids=fitted_ids, held_fixed=held_fixed)
    out: list[tuple[str, str]] = []
    for i, e in enumerate(fit.effects):
        for alt in e.aliased_with:
            swapped = list(fit.effects)
            swapped[i] = dataclasses.replace(e, terms=tuple(alt), label="".join(alt), aliased_with=())
            alt_fit = dataclasses.replace(fit, effects=tuple(swapped))
            if recommend(alt_fit, factors, direction=direction, fitted_ids=fitted_ids,
                         held_fixed=held_fixed).levels != base.levels:
                out.append((e.label, "".join(alt)))
    return out
```

`policy.py` (`compile_policy`): `fold_on = bool(pol_cfg.get("foldover", True))`; when true add the `foldover` state and insert `{"from": "screen", "when": {"alias_consequential": True, "budget_remaining": {">=": 0}}, "to": "foldover", "accounting": "combined OLS over screen ∪ foldover runs; per-term t on pooled pure error"}` **before** the refine rule (the runtime supplies `budget_remaining - runs_needed_foldover` semantics by putting `budget_remaining` = remaining minus needed into the observation when computing for this rule — simpler: add observation key `foldover_affordable` to `OBSERVATION_KEYS` and use `{"alias_consequential": True, "foldover_affordable": True}`); add foldover's rules = screen's rules without the foldover rule, and its default = screen's default.

`stage.py`: add `FOLDOVER = "foldover"` to `Stage`.

`stage_runner.py`: in `_build_design`, `if stage_name == Stage.FOLDOVER.value:` — rebuild the screen design, choose `on`: read screen's `recommendation.json["alias_consequential"]`; if the screen design's resolution is 3 → `on=None`; else `on` = first factor id (in `factor_ids` order) appearing in the first consequential pair's kept label — parse by trying factor ids as prefixes of the label. Return `foldover(screen_design, on=on)`. In `run_stage` after execution for foldover: `screen_iter = <iteration of the transition with from=="screen">`, `screen_ys = [row["response"][primary] for row in sorted(read_runs(screen_dir), key=row_index)]` (complete rows only; a NaN/incomplete screen row → `nan_response`), `design = combine(screen_design, fold_design)`, `ys = screen_ys + ys`; then the normal fit/recommend/observations path with `fitted_ids = all`. Payload extras: `folded_on`, `screen_iteration`. Screen observations: `alias_consequential = bool(pairs)`, `foldover_affordable = budget_remaining >= len(fold rows)` (compute the fold design size = number of screen corners + centres). Write `alias_consequential` pairs to `recommendation.json`.

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_foldover.py tests/test_optimize_effects.py tests/test_optimize_design.py tests/ -q -x` → PASS. `tests/test_optimize_effects.py` may contain a test asserting the singular error for aliased designs — if so, change it to assert `aliased_with` instead (the old assertion encoded the defect).

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): alias-aware fit and foldover-when-consequential"`.

### Task 11: Semantic exceptions end the epoch (and the campaign still returns an action)

**Files:**
- Modify: `orchestrator/optimize/policy.py` (rules: refine `stationary_in_hull==false → exception`; `current_state` filters transitions by epoch; `_load_or_compile_policy` recompiles when a newer epoch has begun)
- Modify: `orchestrator/optimize/stage_runner.py` (`_close_iteration` exception branch; NaN routing; measured-only finalists after lack-of-fit)
- Modify: `orchestrator/optimize/stage.py` (`Stage.REPORT`, `Stage.EXCEPTION`)
- Test: `tests/test_optimize_epoch.py`; `tests/test_optimize_harness.py` (remove the last two xfails)

**Interfaces:**
- `epoch_end-<epoch>.json` = `{"epoch", "iteration", "state", "rule", "observations", "reason"}`; `report.json["epoch_ended"] = reason` when the epoch ended by exception; transition rows carry `"epoch"`.
- Observations added: none new (`nan_response`, `stationary_in_hull`, `model_adequate` already exist).

Rules (spec §3.2 exception, §3.3 fallback):
- Refine: `stationary_in_hull == False → exception` ("declared ranges do not contain the optimum; widen the ranges and recompile"). Note the recommendation from `recommend()` is still written first, so the report's ladder can offer `model`/`measured`.
- Any spending state: a NaN primary metric on a `complete` row → `nan_response` → exception, **without fitting** (today `_fitting_responses` raises; route instead). Write a minimal schema-valid `findings.json` (`experiment_valid: false`, one arm `REFUTED`, diagnostic note naming the row) and `principle_updates.json = []` before closing.
- Refine `lack_of_fit == True` (model inadequate): still `→ confirm` (the registered augmentation is confirm's fresh measurements) but `recommendation.json["model_adequate"] = false`; `_confirm_rows` then builds finalists from **measured** valid rows only (`_top_measured(work_dir, primary, direction, k)`), never from the model — paper: "remeasures the leading *measured* valid candidates rather than choosing the largest noisy observation".
- `_close_iteration` on `exception`: write `epoch_end-<epoch>.json`; call `_run_report(...)` (ladder skips `model` when the epoch ended by exception; basis is `measured` or `baseline`) with `epoch_ended=reason`; `engine.transition("DONE")`; return `COMPLETED`.
- Epoch bookkeeping: `append_transition` rows include `"epoch": pol["epoch"]`; `current_state` uses only rows with `epoch == policy["epoch"]`; `_load_or_compile_policy` recompiles (overwriting `policy.json`/`.sha256`) when `_epoch_index(work_dir) > policy["epoch"]` — a follow-up `nous run --resume` after a manual/agent fix starts epoch $e+1$ cleanly.

- [ ] **Step 1: Failing tests** — `tests/test_optimize_epoch.py`:

```python
"""A semantic exception ENDS the epoch; it does not cross the boundary and it
does not prevent a decision (paper: 'uncertainty weakens the claim; it need
not prevent a decision')."""
from __future__ import annotations

import json

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def test_out_of_hull_optimum_ends_the_epoch_and_still_reports_an_action(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl_out_of_hull"](), seed=31, parent_dir=tmp_path)
    assert res.path[-1] == "exception"
    ends = list(res.work_dir.glob("epoch_end-*.json"))
    assert len(ends) == 1 and json.loads(ends[0].read_text())["state"] == "refine"
    assert res.report["epoch_ended"]
    assert res.report["recommendation"]["basis"] in ("measured", "baseline")
    assert res.recommendation                                   # an action was still returned


def test_nan_response_ends_the_epoch_without_fitting(tmp_path):
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=32, parent_dir=tmp_path)
    assert res.path == ["screen", "exception"], res.path
    it = res.work_dir / "runs" / "iter-2"
    assert not (it / "effects.json").exists()
    assert json.loads((it / "findings.json").read_text())["experiment_valid"] is False


def test_next_epoch_recompiles_and_restarts_from_initial(tmp_path):
    from orchestrator.optimize.policy import current_state, read_policy
    from orchestrator.optimize.stage_runner import _load_or_compile_policy
    from orchestrator.optimize.harness import synthetic_campaign
    res = run_synthetic_campaign(SURFACES["nan_at_corner"](), seed=33, parent_dir=tmp_path)
    assert read_policy(res.work_dir)["epoch"] == 1
    # a fix happened out of band; the next run sees epoch_end-1.json and starts epoch 2
    pol2 = _load_or_compile_policy(synthetic_campaign(SURFACES["nan_at_corner"]()), res.work_dir)
    assert pol2["epoch"] == 2 and current_state(pol2, res.work_dir) == "screen"


def test_lack_of_fit_sends_confirm_measured_candidates_only(tmp_path):
    # a saddle fitted with a plane at screen: refine's quadratic fits, but force
    # inadequacy by giving refine too few centre points to test LOF -> the rule
    # must not fire; instead assert the flag round-trips when set by hand.
    from orchestrator.optimize.stage_runner import _confirm_rows
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.harness import synthetic_campaign
    s = SURFACES["additive"]()
    c = synthetic_campaign(s)
    pol = compile_policy(c)
    wd = tmp_path / "wd"; (wd / "runs" / "iter-2").mkdir(parents=True)
    (wd / "runs" / "iter-2" / "recommendation.json").write_text(json.dumps(
        {"levels": {"A": 2, "B": 16, "C": "on"}, "model_adequate": False, "top_candidates": []}))
    (wd / "runs" / "iter-2" / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"row_index": 0, "status": "complete", "levels": {"A": 16, "B": 16, "C": "on"}, "response": {"m": 20.0}},
        {"row_index": 1, "status": "complete", "levels": {"A": 2, "B": 2, "C": "off"}, "response": {"m": 1.0}},
    ]))
    rows, payload = _confirm_rows(pol, wd, parse_factors(c["optimization"]["factors"]), "m", "maximize", 3)
    keys = [f["levels"] for f in payload["finalists"]]
    assert {"A": 2, "B": 16, "C": "on"} not in keys          # the model's pick is not trusted
    assert {"A": 16, "B": 16, "C": "on"} in keys              # measured leaders are
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** per the rules above. Concretely in `_close_iteration`:

```python
    if nxt == "exception":
        reason = f"{state}: {json.dumps(rule.get('when'), sort_keys=True)}"
        _write_json(Path(work_dir) / f"epoch_end-{pol['epoch']}.json", {
            "epoch": pol["epoch"], "iteration": iteration, "state": state, "rule": rule,
            "observations": observations, "reason": reason,
        })
        _run_report(engine, campaign, work_dir, iteration, pol,
                    recommendation_levels=None, epoch_ended=reason)
        return IterationOutcome.COMPLETED
```

and `_run_report(..., epoch_ended: str | None = None)` skips the `model` rung when `epoch_ended` and writes `"epoch_ended": epoch_ended`. In `policy.py`: `compile_policy` adds `{"from": "refine", "when": {"stationary_in_hull": False}, "to": "exception", "accounting": sem}` before refine's default; `append_transition` callers include `"epoch"`; `current_state` filters `[r for r in rows if r.get("epoch", 1) == policy["epoch"]]`. In `_load_or_compile_policy`: `if pol is not None and pol["epoch"] < _epoch_index(work_dir): pol = None` before the compile branch (and log "starting epoch N"). NaN routing: in `run_stage`, right after `outcomes` are restored to design order and fidelity is checked: `if any(o.status == "complete" and _primary_of(o) != _primary_of(o) for o in outcomes): write findings/principles; obs = {"correctness_failed": False, "nan_response": True, "budget_remaining": ...}; return _close_iteration(...)`. Add `"model_adequate": Trigger.LACK_OF_FIT not in decision.triggers` into `recommendation.json` (already computed by `observations_from_decision`); `_confirm_rows` checks `rec.get("model_adequate", True)`.

- [ ] **Step 4: Remove the xfails** from `test_bowl_out_of_hull_ends_the_epoch` and `test_nan_corner_ends_the_epoch` in `tests/test_optimize_harness.py`. Run `python -m pytest tests/ -q -x` → PASS with **zero** xfails remaining in `test_optimize_harness.py`.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): semantic exceptions end the epoch, report still returns an action, epochs recompile"`.

---

## Phase 4 — Build-stage oracles

### Task 12: Mechanism patch hash and drift check

**Files:**
- Modify: `orchestrator/optimize/build.py` (`snapshot_mechanism(repo, work_dir) -> str`)
- Modify: `orchestrator/optimize/stage_runner.py` (call after `run_build`; drift check at every epoch iteration)
- Test: `tests/test_optimize_build_oracles.py`

**Interfaces:**
- `build.snapshot_mechanism(repo: Path, work_dir: Path) -> str` — writes `mechanism.patch` (`git diff HEAD` + `git ls-files --others --exclude-standard` contents appended as `+++ untracked: <path>` sections) and `mechanism.sha256`; returns the hash. Returns `""` and writes nothing when `repo` is not a git work tree.
- `build.current_mechanism_hash(repo: Path) -> str` — same computation without writing.
- `stage_runner`: at every epoch iteration with a real `repo`, if `mechanism.sha256` exists and `current_mechanism_hash(repo) != recorded` → `OptimizationAborted("mechanism drifted since compile: …")`.
- `compile_policy(..., mechanism_patch_hash=<recorded>)` already consumes it (Task 6).

- [ ] **Step 1: Failing tests**

```python
"""Build oracles (spec §3.5, oracle 2). Real git repos in tmp_path; no LLM —
the build agent is a fake sdk_runner that edits files."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orchestrator.optimize.build import current_mechanism_hash, snapshot_mechanism


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"; repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "mech.py").write_text("X = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_snapshot_records_the_diff_and_untracked_files_and_hash_changes_on_edit(tmp_path):
    repo = _git_repo(tmp_path); wd = tmp_path / "wd"; wd.mkdir()
    (repo / "mech.py").write_text("X = 2\n"); (repo / "new.py").write_text("Y = 1\n")
    h1 = snapshot_mechanism(repo, wd)
    patch = (wd / "mechanism.patch").read_text()
    assert "X = 2" in patch and "untracked: new.py" in patch
    assert (wd / "mechanism.sha256").read_text().strip() == h1 == current_mechanism_hash(repo)
    (repo / "mech.py").write_text("X = 3\n")
    assert current_mechanism_hash(repo) != h1


def test_non_git_target_yields_empty_hash_and_no_files(tmp_path):
    d = tmp_path / "plain"; d.mkdir(); wd = tmp_path / "wd"; wd.mkdir()
    assert snapshot_mechanism(d, wd) == "" and not (wd / "mechanism.patch").exists()


def test_epoch_iteration_hard_fails_when_the_mechanism_drifted(tmp_path, monkeypatch):
    import json
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    from orchestrator.iteration import setup_work_dir
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s); c["target_system"]["repo_path"] = str(repo)
    wd = setup_work_dir("drift", repo_path=str(repo), campaign=c)
    (repo / "mech.py").write_text("X = 2\n")
    snapshot_mechanism(repo, wd)
    tests_ok = {r["native_test"]: True for f in c["optimization"]["factors"] for r in f["relations"]}
    run_stage(c, wd, iteration=1, stage="verify", config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
    (repo / "mech.py").write_text("X = 99\n")            # drift after compile
    with pytest.raises(OptimizationAborted, match="drifted since compile"):
        run_stage(c, wd, iteration=2, config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** in `build.py`:

```python
def _mechanism_text(repo: Path) -> str | None:
    import subprocess
    try:
        diff = subprocess.run(["git", "diff", "HEAD", "--no-color"], cwd=str(repo),
                              capture_output=True, text=True, timeout=120)
        if diff.returncode != 0:
            return None
        others = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                cwd=str(repo), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = [diff.stdout]
    for rel in sorted(p for p in others.stdout.splitlines() if p.strip()):
        try:
            parts.append(f"+++ untracked: {rel}\n" + (repo / rel).read_text())
        except (OSError, UnicodeDecodeError):
            parts.append(f"+++ untracked: {rel}\n<binary or unreadable>\n")
    return "".join(parts)


def current_mechanism_hash(repo: Path) -> str:
    import hashlib
    text = _mechanism_text(Path(repo))
    return "" if text is None else hashlib.sha256(text.encode()).hexdigest()


def snapshot_mechanism(repo: Path, work_dir: Path) -> str:
    """Record the target's post-build diff and its hash next to the campaign."""
    text = _mechanism_text(Path(repo))
    if text is None:
        return ""
    import hashlib
    h = hashlib.sha256(text.encode()).hexdigest()
    (Path(work_dir) / "mechanism.patch").write_text(text)
    (Path(work_dir) / "mechanism.sha256").write_text(h + "\n")
    return h
```

In `stage_runner.run_stage`: after `build_mod.run_build(...)`: `build_mod.snapshot_mechanism(Path(repo), work_dir)` when `repo`. In `_resolve_state`'s epoch branch (or right after it in `run_stage`): if `repo` and `(work_dir/"mechanism.sha256").exists()` and `build_mod.current_mechanism_hash(Path(repo)) != recorded` → raise `OptimizationAborted("mechanism drifted since compile: the target's working tree no longer matches mechanism.patch; measurements would describe a different system")`. Note the test's verify does not run `build`; it snapshots by hand — the check keys on the file's presence, not on whether build ran.

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_build_oracles.py tests/test_optimize_build.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): record mechanism.patch at build and hard-fail on drift inside the epoch"`.

### Task 13: Tests-must-fail-before-build and control ≡ baseline

**Files:**
- Modify: `orchestrator/optimize/stage_runner.py` (build path: pre-build snapshot; verify path: the two checks)
- Modify: `orchestrator/optimize/build.py` (`baseline_runs(config_runner, factors, baseline, n) -> list[float]`)
- Modify: `orchestrator/validate.py` (rule 15: `build` declared ⇒ `known_valid_baseline` required)
- Modify: `orchestrator/schemas/campaign.schema.yaml` (`optimization.build_checks: {allow_preexisting_tests: bool, baseline_replicates: int, baseline_tolerance_pct: number}`)
- Test: `tests/test_optimize_build_oracles.py` (append)

**Interfaces:**
- `pre_build_tests.json` = `{"passed": [native_test ids that passed BEFORE build], "ran": [...]}` written by the build iteration before `run_build`.
- `baseline_equivalence.json` = `{"levels", "pre": [floats], "post": [floats], "pre_mean", "post_mean", "tolerance_pct", "ok"}`; `pre` measured in the build iteration before `run_build`, `post` at verify.
- Verify hard-fails: (a) any `correctness` relation whose `native_test ∈ pre_build_tests.passed` unless `build_checks.allow_preexisting_tests`; (b) `|post_mean − pre_mean| / |pre_mean| > tolerance_pct/100` (default `tolerance_pct = 3 × response.noise_estimate_pct` or 5.0).

- [ ] **Step 1: Failing tests** (append):

```python
def _build_campaign(tmp_path, repo):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    s = SURFACES["additive"]()
    c = synthetic_campaign(s, stages=["build", "verify", "screen", "confirm"],
                           known_valid_baseline={"A": 2, "B": 2, "C": "off"})
    c["target_system"]["repo_path"] = str(repo)
    return s, c


def _fake_build(writes: dict):
    from orchestrator.sdk_dispatch import SDKResult
    def runner(**kw):
        for rel, text in writes.items():
            Path(kw["cwd"]).joinpath(rel).write_text(text) if "cwd" in kw else None
        return SDKResult(text="built", session_id="s", cost_usd=0.0, num_turns=1)
    return runner


def test_a_test_that_passed_before_build_fails_verify(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    from orchestrator.iteration import setup_work_dir
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("prebuilt", repo_path=str(repo), campaign=c)
    ids = [r["native_test"] for f in c["optimization"]["factors"] for r in f["relations"]]
    all_pass = {t: True for t in ids}
    run_stage(c, wd, iteration=1, stage="build", config_runner=make_synthetic_runner(s, seed=1),
              test_results=all_pass, sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    assert set(json.loads((wd / "pre_build_tests.json").read_text())["passed"]) == set(ids)
    with pytest.raises(OptimizationAborted, match="passed before the mechanism existed"):
        run_stage(c, wd, iteration=2, stage="verify", config_runner=make_synthetic_runner(s, seed=1),
                  test_results=all_pass)


def test_baseline_equivalence_hard_fails_when_build_changed_the_control(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    from orchestrator.iteration import setup_work_dir
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("shifted", repo_path=str(repo), campaign=c)
    ids = [r["native_test"] for f in c["optimization"]["factors"] for r in f["relations"]]
    pre = {t: False for t in ids}; post = {t: True for t in ids}
    run_stage(c, wd, iteration=1, stage="build", config_runner=make_synthetic_runner(s, seed=1),
              test_results=pre, sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    shifted = make_synthetic_runner(s, seed=1)
    def post_runner(row):
        obs = shifted(row); obs["m"] += 5.0; return obs             # build broke the control
    with pytest.raises(OptimizationAborted, match="baseline"):
        run_stage(c, wd, iteration=2, stage="verify", config_runner=post_runner, test_results=post)
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["ok"] is False and len(be["pre"]) == len(be["post"]) == 3


def test_build_without_known_valid_baseline_is_rejected_by_the_validator():
    from orchestrator.validate import validate_optimization_campaign
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    c = synthetic_campaign(SURFACES["additive"](), stages=["build", "verify", "screen", "confirm"])
    assert any("known_valid_baseline" in e for e in validate_optimization_campaign(c))
```

Note: `test_results` on the build iteration stands in for the pre-build `test_command` run (production runs `run_test_command` before `run_build` when `test_command` and `repo` are set; the injected `test_results` is the seam, exactly as verify uses it).

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** In `run_stage`'s build branch **before** `run_build`: `_write_json(work_dir / "pre_build_tests.json", {"passed": [t for t, ok in (test_results or {}).items() if ok], "ran": sorted(test_results or {})})` (when `test_results is None` and `test_command`+`repo` exist, run the test command first — the docstring rationale about "no tests to run" exits 0 no longer applies because we now *want* the pre-build outcome); and if `pol_baseline := opt.get("known_valid_baseline")` and a `config_runner` is available: `pre = build_mod.baseline_runs(config_runner, factors, pol_baseline, n=<build_checks.baseline_replicates or 3>, metric=primary)` → write `baseline_equivalence.json` with `pre` only. In the verify branch after relations pass: (a) `pre = read pre_build_tests.json`; `bad = [v for v in relations.reconcile(...) if v.kind == "correctness" and v.native_test in pre["passed"]]`; if `bad and not allow_preexisting` → `OptimizationAborted(f"native test(s) {ids} passed before the mechanism existed — a test that passes without the mechanism does not test it; set optimization.build_checks.allow_preexisting_tests: true only if the test genuinely covers pre-existing behaviour")`; (b) if `baseline_equivalence.json` has `pre` and `config_runner`: `post = baseline_runs(...)`; write full record; if not ok → `OptimizationAborted("build changed the baseline: control configuration moved from … to … (>tol%) — the mechanism is not inert at its control level")`.

`build.baseline_runs`:

```python
def baseline_runs(config_runner, factors, baseline: dict, *, n: int, metric: str) -> list[float]:
    from orchestrator.optimize.matrix import ConfigRow, render_apply
    out: list[float] = []
    for i in range(n):
        row = ConfigRow(row_index=-1 - i, levels=dict(baseline), role="baseline", replicate=i,
                        apply=render_apply(factors, baseline))
        obs = config_runner(row)
        out.append(float(obs.get(metric, float("nan"))))
    return out
```

Validator rule 15 in `validate.py`: if `"build" in (opt.get("stages") or [])` and not `opt.get("known_valid_baseline")` → error `"optimization.known_valid_baseline is required when the build stage is declared: it is the control the build must leave unchanged (baseline equivalence) and the report's last-resort action"`. Schema: add `build_checks` object.

- [ ] **Step 4: Run** `python -m pytest tests/ -q -x` → PASS. `tests/test_optimize_build.py` tests that declare `build` in `stages` now need `known_valid_baseline` — add it to their campaign fixtures.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): build oracles — tests must fail before build, control must equal baseline after"`.

---

### Task 13.5: Drift oracle scoped to mechanism paths (fixes a live Task 12 defect)

**Inserted mid-plan, not in the original brief set.** Task 12's `build.snapshot_mechanism`/`current_mechanism_hash` hash the target's *entire* working tree — `git diff HEAD` plus every untracked-but-not-gitignored file, by content, with no allowlist. Two independent task reviews (Task 12's own, and Task 13's, which read Task 12's code directly) reproduced end-to-end that this false-aborts a live campaign on Nous's *own* pre-existing machinery: `run_test_command`/`make_config_runner` execute the target's `test_command`/`run_command` with the target repo as `cwd`, so any non-gitignored artifact those commands leave behind (a `.pytest_cache/`, a `run.log`, a coverage file) changes the hash, and the very next epoch iteration's drift check (built in Task 12) aborts with "mechanism drifted since compile" — a false positive that reads as a genuine mechanism problem, the worst available misdiagnosis. Reproduced with **zero** `build` stage and **zero** Task 13 code involved — this is a Task 12 defect, exposed further (not caused) by Task 13's added `config_runner` invocations at the same stage.

Both reviewers' recommendation: narrow the drift hash to a declared allowlist (paths the campaign's `factors`/`relations` actually reference, plus an optional explicit `mechanism_paths` override) rather than "document that authors must gitignore everything" — the documentation route puts the burden on AI campaign authors to anticipate every artifact a test runner emits, and its failure mode is the worst one available. Bundle in the already-carried Task 12 finding: `mechanism.patch` is written but never cross-checked against `mechanism.sha256`, and a mid-epoch `build` re-run (test-seam only, not production-reachable) can re-stamp `mechanism.sha256` without updating `policy.json`'s recorded `mechanism_patch_hash` — both close with one comparison against `policy["compiled_from"]["mechanism_patch_hash"]` where a policy already exists.

**Files:**
- Modify: `orchestrator/optimize/build.py` (`_mechanism_text`, `snapshot_mechanism`, `current_mechanism_hash`)
- Modify: `orchestrator/optimize/stage_runner.py` (the drift `elif` branch; `_load_or_compile_policy`/`_compile_and_write_policy` cross-check)
- Modify: `orchestrator/schemas/campaign.schema.yaml` (`optimization.build_checks.mechanism_paths: list[str]`, optional)
- Test: `tests/test_optimize_build_oracles.py` (append)

**Interfaces:**
- `_mechanism_text(repo, *, allowlist: list[str] | None = None) -> str | None` — when `allowlist` is given, untracked files are filtered to those matching a path in it (prefix or glob match, author's choice — document which); tracked diff (`git diff HEAD`) is filtered the same way via `git diff HEAD -- <allowlist paths>` when an allowlist is present, unfiltered otherwise. `allowlist=None` preserves Task 12's exact current behavior (whole-tree) — **this is the default, so no existing campaign's semantics change without an explicit opt-in**.
- `snapshot_mechanism`/`current_mechanism_hash` gain the same `allowlist` parameter, threaded from `optimization.build_checks.mechanism_paths` when declared, else derived from `factors`' `manipulation`/`relations` file references if those name paths, else `None` (whole-tree, backward-compatible).
- `stage_runner`'s drift `elif` branch and `_load_or_compile_policy`: add one comparison — when a compiled `policy.json` exists, its `compiled_from.mechanism_patch_hash` must equal the on-disk `mechanism.sha256`'s recorded value; mismatch is the same class of hard-fail as today's drift check, with a message distinguishing "the policy's registered hash and the sidecar hash disagree" from "the tree drifted from the sidecar hash."

- [ ] **Step 1: Failing tests** — extend `tests/test_optimize_build_oracles.py` with:
  1. A test reproducing the false-abort directly (a `test_command` that leaves a non-gitignored file behind; no `mechanism_paths` declared; confirm today's whole-tree behavior still aborts — this PINS the backward-compatible default, it does not remove the hazard by itself).
  2. A test that declares `optimization.build_checks.mechanism_paths` naming only the mechanism's actual file; the same test-command artifact must NOT trigger a drift abort, because it falls outside the allowlist.
  3. A test for the `policy.json` vs `mechanism.sha256` cross-check: hand-write a `policy.json` whose `compiled_from.mechanism_patch_hash` disagrees with a freshly-written `mechanism.sha256`, and confirm `_load_or_compile_policy` (or the drift branch, whichever owns the check) raises with a message distinguishing this case from ordinary tree drift.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** Thread the `allowlist` parameter through `_mechanism_text`/`snapshot_mechanism`/`current_mechanism_hash` as described above, defaulting to `None` (today's behavior). Resolve `mechanism_paths` in `stage_runner.py` at the same two call sites Task 12 established (`snapshot_mechanism` in the build branch, `current_mechanism_hash` in the drift `elif`), reading `optimization.build_checks.mechanism_paths` from the campaign. Add the `compiled_from.mechanism_patch_hash` vs. `mechanism.sha256` cross-check in `_load_or_compile_policy`, since that is the function that already reads both `policy.json` (via `read_policy`) and is called at every epoch iteration — the natural, single-owner home both prior reviews pointed at. Do **not** change the default behavior for a campaign that declares no `mechanism_paths` — Task 12's whole-tree hash remains the fallback, since a wrong default (silently narrowing every existing campaign's oracle) would be worse than the status quo bug, per the standing pre-GA principle that behavior may change but only when named and argued, never silently.

- [ ] **Step 4: Run** `python -m pytest tests/test_optimize_build_oracles.py tests/test_optimize_build.py tests/ -q -x` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "fix(optimize): scope the drift oracle to declared mechanism paths; cross-check policy.json against mechanism.sha256"`.

---

## Phase 5 — Systems-target readiness

### Task 14: Workload seeds and common random numbers

**Files:**
- Modify: `orchestrator/schemas/campaign.schema.yaml` (`optimization.workload`)
- Modify: `orchestrator/validate.py` (rule 16: `seed_env` matches `^[A-Z_][A-Z0-9_]*$`)
- Modify: `orchestrator/optimize/stage_runner.py` (assign seeds; `paired=True` at confirm)
- Modify: `orchestrator/optimize/synthetic.py` (`make_synthetic_runner(..., seed_env=None)` reseeds noise per row from `row.apply["env"][seed_env]`)
- Test: `tests/test_optimize_workload.py`

**Interfaces:**
- `optimization.workload: {seed_env: "NOUS_WORKLOAD_SEED", seeds: [int, ...] | null}`.
- Spending states set `row.apply["env"][seed_env]`: screen/foldover/refine → `seeds[row_index % len]` if `seeds` else `(run_order_seed * 7919 + row_index) % 2**31`; confirm → per **replicate index** (`seeds[i % len]` or `(iteration * 7919 + i) % 2**31`) so every finalist's replicate *i* shares a seed → `payload["paired"] = True`, `payload["workload_seeds"] = {row_index: seed}`.
- `runner.make_config_runner` already exports `apply.env` into the subprocess environment — no change.

- [ ] **Step 1: Failing tests**

```python
"""Stochastic workloads: seeded, recorded, and paired at the terminal stage."""
from __future__ import annotations

import json

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


def _run(tmp_path, seed):
    return run_synthetic_campaign(
        SURFACES["additive"](), seed=seed, parent_dir=tmp_path,
        campaign_overrides={"workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
                            "design": {"screen": {"resolution": 5, "center_points": 4},
                                       "refine": {"kind": "central_composite", "center_points": 4},
                                       "confirm": {"replicates": 4, "shortlist_size": 3}}},
    )


def test_every_row_records_its_workload_seed(tmp_path):
    res = _run(tmp_path, 41)
    dm = json.loads((res.work_dir / "runs" / "iter-2" / "design_matrix.json").read_text())
    assert len(dm["workload_seeds"]) == len(dm["rows"])
    assert all("NOUS_WORKLOAD_SEED" in r["apply"]["env"] for r in dm["rows"])


def test_confirm_uses_common_random_numbers_and_a_paired_bound(tmp_path):
    res = _run(tmp_path, 42)
    conf_iters = [json.loads(l)["iteration"] for l in (res.work_dir / "transitions.jsonl").read_text().splitlines()
                  if json.loads(l)["from"] == "confirm"]
    dm = json.loads((res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "design_matrix.json").read_text())
    by_rep = {}
    for r in dm["rows"]:
        by_rep.setdefault(r["replicate"], set()).add(r["apply"]["env"]["NOUS_WORKLOAD_SEED"])
    assert all(len(seeds) == 1 for seeds in by_rep.values())        # CRN within a replicate block
    conf = json.loads((res.work_dir / "runs" / f"iter-{conf_iters[0]}" / "confirmation.json").read_text())
    assert conf["paired"] is True


def test_seed_env_name_is_validated():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](), workload={"seed_env": "bad name"})
    assert any("seed_env" in e for e in validate_optimization_campaign(c))
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** Schema: `workload: {type: object, additionalProperties: false, required: [seed_env], properties: {seed_env: {type: string}, seeds: {type: array, items: {type: integer}}}}`. Validator rule 16 (regex). In `run_stage`, after rows are final and before `write_design_matrix`, a helper:

```python
def _assign_workload_seeds(rows, payload, pol, *, iteration: int, confirm: bool):
    wl = pol.get("workload") or {}
    env_name = wl.get("seed_env")
    if not env_name:
        return rows, payload
    import dataclasses
    seeds = wl.get("seeds") or None
    def _seed(i: int, base: int) -> int:
        return int(seeds[i % len(seeds)]) if seeds else (base * 7919 + i) % (2 ** 31)
    out, rec = [], {}
    for r in rows:
        i = r.replicate if confirm else r.row_index
        sd = _seed(i, iteration if confirm else int(payload.get("run_order_seed", iteration)))
        env = {**((r.apply or {}).get("env") or {}), env_name: sd}
        out.append(dataclasses.replace(r, apply={**(r.apply or {}), "env": env}))
        rec[str(r.row_index)] = sd
    payload = dict(payload)
    payload["workload_seeds"] = rec
    payload["rows"] = [{**row, "apply": {**row["apply"], "env": {**(row["apply"].get("env") or {}), env_name: rec[str(row["row_index"])]}}}
                       for row in payload["rows"]]
    if confirm:
        payload["paired"] = True
    return out, payload
```

`synthetic.make_synthetic_runner(surface, *, seed, seed_env=None)`: when `seed_env` and the row carries it, `noise = random.Random(row_seed).gauss(0, sd)` instead of the shared stream. Update `harness.run_synthetic_campaign` to pass `seed_env=(campaign_overrides.get("workload") or {}).get("seed_env")`.

- [ ] **Step 4: Run** `python -m pytest tests/ -q -x` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(optimize): seeded workloads per row; common random numbers and paired bounds at confirm"`.

### Task 15: Example campaigns for systems targets and the target contract doc

**Files:**
- Create: `examples/optimization/vllm-batching.yaml`, `examples/optimization/qdrant-hnsw.yaml`, `examples/optimization/knative-autoscale.yaml`
- Create: `docs/targets.md`
- Test: `tests/test_optimize_examples.py`

**Interfaces:** the YAMLs must pass `campaign.schema.yaml` and `validate_optimization_campaign` with zero errors (warnings allowed) and `compile_policy` + `check_policy` must return `[]`. `run_command`/`test_command` reference an adapter script the target owner supplies (`bench/nous_bench.py`, `bench/test_nous_props.py`) whose contract is `docs/targets.md`.

- [ ] **Step 1: Failing test**

```python
"""Every shipped example campaign is a valid, compilable optimization campaign."""
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.optimize.policy import check_policy, compile_policy
from orchestrator.validate import validate_optimization_campaign

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "optimization").glob("*.yaml"))
SCHEMA = yaml.safe_load((ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml").read_text())


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_validates_and_compiles(path):
    c = yaml.safe_load(path.read_text())
    jsonschema.validate(c, SCHEMA)
    errs = [e for e in validate_optimization_campaign(c) if not e.lower().startswith("warning")]
    assert errs == [], errs
    pol = compile_policy(c)
    assert check_policy(pol) == []
    assert c["optimization"].get("known_valid_baseline"), "examples must name a known-valid baseline"
    assert c["optimization"].get("workload", {}).get("seed_env"), "systems examples must seed the workload"


def test_examples_exist():
    assert {p.name for p in EXAMPLES} >= {"vllm-batching.yaml", "qdrant-hnsw.yaml", "knative-autoscale.yaml"}
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `examples/optimization/vllm-batching.yaml`**

```yaml
kind: optimization
run_id: vllm-batching-rsm
research_question: >
  Which combination of scheduler batching knobs maximizes decode throughput
  under a bursty mixed-length trace while keeping p99 TTFT under the SLA?
prompts: {methodology_layer: prompts/methodology, domain_adapter_layer: null}
target_system:
  name: vllm
  repo_path: /path/to/vllm            # adapter lives at bench/ inside this checkout
  description: >
    vLLM OpenAI-compatible server. bench/nous_bench.py starts the server with
    the given flags, replays a seeded trace (NOUS_WORKLOAD_SEED), and prints
    one JSON object: {tokens_per_s, p99_ttft_ms, oom, cfg:{...}}.
optimization:
  run_command: "python bench/nous_bench.py --model meta-llama/Llama-3.1-8B-Instruct --requests 400"
  test_command: "python -m pytest bench/test_nous_props.py -q --json-report --json-report-file=/dev/stdout"
  known_valid_baseline: {MNS: 256, MBT: 8192, CP: "off", POL: fcfs}
  workload: {seed_env: NOUS_WORKLOAD_SEED}
  policy: {epsilon: {pct: 2.0}, delta_screen: 0.05, delta_terminal: 0.05, confirm_max_rounds: 2}
  response:
    primary: {metric: tokens_per_s, direction: maximize}
    constraints:
      - {metric: p99_ttft_ms, op: "<=", value: 500}
      - {metric: oom, op: "==", value: 0}
    noise_estimate_pct: 4.0
  factors:
    - id: MNS
      name: max_num_seqs
      type: numeric
      levels: [64, 128, 256, 512]
      grid: 32
      apply: "--max-num-seqs={level}"
      manipulation: {observable: cfg.max_num_seqs, op: "==", value: "{level}"}
      relations:
        - {id: R_MNS, kind: correctness, statement: "outputs are token-identical to baseline at greedy decoding for any max_num_seqs", native_test: "bench/test_nous_props.py::test_greedy_outputs_invariant_to_max_num_seqs"}
    - id: MBT
      name: max_num_batched_tokens
      type: numeric
      levels: [2048, 4096, 8192, 16384]
      grid: 512
      apply: "--max-num-batched-tokens={level}"
      manipulation: {observable: cfg.max_num_batched_tokens, op: "==", value: "{level}"}
      relations:
        - {id: R_MBT, kind: correctness, statement: "no request is truncated: emitted tokens equal requested max_tokens or stop", native_test: "bench/test_nous_props.py::test_no_truncation_under_batched_token_cap"}
    - id: CP
      name: chunked_prefill
      type: choice
      levels: ["off", "on"]
      apply: {kind: cli_flag, template: "--enable-chunked-prefill={level}"}
      manipulation: {observable: cfg.chunked_prefill, op: "==", value: "{level}"}
      relations:
        - {id: R_CP, kind: correctness, statement: "chunked prefill off is byte-identical to baseline", native_test: "bench/test_nous_props.py::test_chunked_prefill_off_is_baseline"}
        - {id: B_CP, kind: behavioral, statement: "TTFT is non-increasing when chunked prefill is on under long prompts", native_test: "bench/test_nous_props.py::test_ttft_monotone_chunked_prefill"}
    - id: POL
      name: scheduling_policy
      type: choice
      levels: [fcfs, priority]
      apply: "--scheduling-policy={level}"
      manipulation: {observable: cfg.scheduling_policy, op: "==", value: "{level}"}
      relations:
        - {id: R_POL, kind: correctness, statement: "every request completes exactly once under either policy", native_test: "bench/test_nous_props.py::test_every_request_completes_once"}
  design:
    screen: {resolution: 5, center_points: 4}
    refine: {kind: central_composite, center_points: 4}
    confirm: {replicates: 4, shortlist_size: 3}
    max_runs: 90
  design_space:
    invariants:
      - {id: I_MEM, statement: "GPU memory utilisation stays under the configured cap", observable: gpu_mem_util, op: "<=", value: 0.95}
```

`qdrant-hnsw.yaml`: factors `M` numeric `[8,16,32,64]` grid 8 (`--m={level}`), `EFC` numeric `[64,128,256,512]` grid 32 (`--ef-construct={level}`), `Q` choice `[none, scalar]` (`--quantization={level}`), `EFS` numeric `[32,64,128,256]` grid 16 (`--ef-search={level}`); response `qps` maximize; constraints `recall_at_10 >= 0.95`, `index_build_s <= 600`; baseline `{M:16, EFC:128, Q: none, EFS: 64}`; correctness relations: `test_search_results_are_a_subset_of_bruteforce_topk_at_recall_floor`, `test_quantization_none_is_baseline`, `test_ef_search_monotone_recall` (behavioral); invariants `segments_optimized == 1`.

`knative-autoscale.yaml`: factors `TC` (target concurrency) numeric `[10,50,100,200]` grid 10, `PW` (panic window pct) numeric `[5,10,20,50]` grid 5, `SZ` (scale-to-zero grace) numeric `[30,60,120,300]` grid 30, `MODE` choice `[concurrency, rps]`; response `p99_latency_ms` **minimize**; constraints `max_pods <= 20`, `error_rate <= 0.001`; baseline `{TC:100, PW:10, SZ:30, MODE: concurrency}`; correctness relations: `test_no_request_lost_during_scale_events`, `test_scale_to_zero_reached_after_grace`, behavioral `test_pods_monotone_in_load`; workload seed env `NOUS_WORKLOAD_SEED`.

- [ ] **Step 4: Write `docs/targets.md`** — the adapter contract, ~120 lines: (1) `run_command` gets each factor's `apply` appended, must exit 0 and print exactly one JSON object last on stdout containing the primary metric, every constraint metric, every `manipulation` observable (`cfg.*`), and every `design_space.invariants` observable; non-zero exit or missing metric = `failed` row, never a silent zero; (2) `test_command` must emit pytest-json-report or JUnit and every `native_test` id must resolve; (3) `NOUS_WORKLOAD_SEED` must fully determine the trace; (4) SLA constraints define validity — violating configurations are `infeasible`, not penalized; (5) long benchmarks: keep `max_runs` honest, `noise_estimate_pct` from a 5-replicate pilot, `known_valid_baseline` = production config; (6) per-target notes for vLLM/Triton, Milvus/Qdrant, ClickHouse, Knative, Cilium (what to seed, what to constrain, which knobs need `build`); (7) run `nous validate campaign FILE --smoke` first.

- [ ] **Step 5: Run** `python -m pytest tests/test_optimize_examples.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add examples docs/targets.md tests/test_optimize_examples.py && git commit -m "docs(optimize): systems-target example campaigns and the adapter contract"`.

### Task 16: Documentation of the compiled policy

**Files:**
- Modify: `docs/optimization-campaign-guide.md` (new section "The compiled policy": `policy` block, `known_valid_baseline`, `workload`, `design.confirm.shortlist_size`, states/transitions table, artifacts, how to read `report.json`, what a semantic exception means and how to start epoch 2)
- Modify: `docs/data-model.md` (artifact table from spec §5)
- Modify: `CLAUDE.md` (optimization section: policy is compiled at verify; artifacts; "never edit policy.json"; `nous validate --smoke` still first)
- Modify: `docs/superpowers/specs/2026-08-13-optimization-campaign-kind-design.md` (top note pointing to the 2026-08-16 spec as the superseding design for §6.3 stage transitions and §5.5 artifacts)
- Test: `tests/test_optimize_guide_examples.py` (existing — every YAML block in the guide must still validate; the new section's example must include `policy`, `known_valid_baseline`, `workload`)

- [ ] **Step 1:** Add to `tests/test_optimize_guide_examples.py`:

```python
def test_guide_documents_the_compiled_policy():
    text = (ROOT / "docs" / "optimization-campaign-guide.md").read_text()
    for needle in ("## The compiled policy", "policy.json", "known_valid_baseline", "shortlist_size",
                   "residual_regret", "epoch_end", "transitions.jsonl"):
        assert needle in text, needle
```

- [ ] **Step 2:** Run → FAIL. Write the section (with one complete example campaign YAML block using every new field, so the extraction test exercises it). Include the states/transitions table from spec §3.2 and the fallback ladder from §3.3. Update `docs/data-model.md` and `CLAUDE.md`.

- [ ] **Step 3:** Run `python -m pytest tests/ -q` → PASS (full suite, no `-x`, and confirm **zero xfail** in `tests/test_optimize_harness.py`).

- [ ] **Step 4: Commit** — `git commit -am "docs(optimize): the compiled policy — states, artifacts, report, epochs"`.

---

## Self-review (run before handing back)

**Spec coverage** (spec §3.x → task): §3.1 policy-as-data → T4/T5/T6; §3.2 states (`foldover` T10, `confirm` T9, `report`/`exception` T6/T11) ; §3.3 recommend T7, model bound T8, terminal bound + ε + ladder + baseline T9; §3.4 aliasing T10; §3.5 oracle 1 T2/T3, oracle 2 T12/T13, oracle 3 T5 (`check_policy`, `enumerate_paths` tests); §3.6 workload/CRN T14, SLA validity T7/T9, examples + targets doc T15; §1 docs overclaim T1; §5 artifacts T6–T11, documented T16.

**Consistency checklist for the executor:**
- `Candidate`, `RegretBound`, `SyntheticResult`, `Surface` field names are used identically in Tasks 3, 7, 8, 9, 14.
- Observation keys used by `compile_policy` rules must all appear in `OBSERVATION_KEYS`: `correctness_failed, nan_response, refinable_survivors, certified, round, budget_remaining, alias_consequential, foldover_affordable (T10), stationary_in_hull (T11)`. Add `foldover_affordable` to `OBSERVATION_KEYS` in T10.
- `stage_runner._close_iteration` signature is fixed in T6 and reused in T9/T10/T11 (`recommendation_levels=` keyword; T11 adds `epoch_ended` to `_run_report`, not to `_close_iteration`).
- `_read_recommendation` replaces `_read_confirm_at` in T7; T9's `_confirm_rows` and T11 read `model_adequate` from the same file.
- Every hard-fail is `OptimizationAborted` and fires regardless of `auto_approve`.

**Definition of done:** full suite green; `tests/test_optimize_harness.py` has no xfail left; `git log main..nousko` shows one commit per task; `nous validate campaign examples/optimization/vllm-batching.yaml` (static) passes; a `run_synthetic_campaign(SURFACES["interaction_only"](), …)` at resolution 4 shows `path = ["screen", "foldover", "confirm", "report"]` and a certified or terminal-best recommendation within 2% of truth.
