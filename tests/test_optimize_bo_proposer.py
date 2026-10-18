"""WP-D D3: the optional BO proposer (bo_proposer.py, the nous[bo] extra).

No live LLM; Optuna's Study.optimize is blocked by conftest. The proposer only
uses ask/tell over an in-memory study rebuilt from rows, which is the contract
under test.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.optimize import bo_proposer
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import synthetic_campaign
from orchestrator.optimize.policy import compile_policy, policy_hash
from orchestrator.optimize.synthetic import SURFACES, _choice, _numeric

ROOT = Path(__file__).resolve().parents[1]
FACTORS = parse_factors([_numeric("A"), _numeric("B", levels=(1, 2, 4, 8)), _choice("C")])
OBJ = [{"metric": "m", "direction": "maximize"}]


def _rows():
    out = []
    for i, (a, b, c) in enumerate([(2, 1, "off"), (16, 8, "on"), (8, 4, "on"),
                                   (4, 2, "off"), (12, 6, "on"), (99, 1, "on")]):
        out.append({"row_index": i, "levels": {"A": a, "B": b, "C": c},
                    "response": {"m": float(a + b + (3 if c == "on" else 0))}})
    out.append({"row_index": 9, "levels": {"A": 2, "B": 1, "C": "on"},
                "response": {"m": float("nan")}})
    return out


def test_a_fake_sampler_at_the_seam_runs_without_optuna():
    """CI-able with no optuna installed. The seam receives the trials rebuilt
    from rows (out-of-space and NaN rows skipped and counted). Proposals are
    snapped onto the declared grid, held factors are merged in, and measured
    duplicates are dropped."""
    seen = {}

    def fake(trials, space, objectives, config, n):
        seen["trials"], seen["config"] = trials, config
        return [{"A": 16.4, "B": 8, "C": "on"},          # measured once snapped -> dropped
                {"A": 9.6, "B": 3, "C": "off"},
                {"A": 9.6, "B": 3, "C": "off"}]          # duplicate -> dropped

    props, prov = bo_proposer.propose(_rows(), factors=FACTORS, objectives=OBJ,
                                      config={"seed": 7}, n=3, held_fixed={"D": "x"},
                                      sampler=fake)
    assert len(seen["trials"]) == 5 and prov["rows_skipped"] == 2
    assert seen["config"] == {"sampler": "tpe", "n_startup": 10, "seed": 7}
    assert [p["levels"] for p in props] == [{"D": "x", "A": 10, "B": 3, "C": "off"}]
    assert props[0]["source"] == "bo_proposal"
    p = props[0]["provenance"]
    assert p["seed"] == 7 and p["n_trials_from_rows"] == 5 and p["n_proposed"] == 1
    assert p["sampler"] == "fake" and "nothing persisted" in p["storage"]


def test_same_seed_and_rows_give_identical_proposals_and_a_new_seed_differs():
    pytest.importorskip("optuna")
    kw = dict(factors=FACTORS, objectives=OBJ, n=4)
    a, pa = bo_proposer.propose(_rows(), config={"seed": 3, "n_startup": 2}, **kw)
    b, pb = bo_proposer.propose(_rows(), config={"seed": 3, "n_startup": 2}, **kw)
    assert a and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert pa["optuna_version"] and pa["sampler"] == "TPESampler"
    c, _ = bo_proposer.propose(_rows(), config={"seed": 4, "n_startup": 2}, **kw)
    assert [x["levels"] for x in c] != [x["levels"] for x in a]
    for x in a:
        assert x["levels"]["A"] in range(2, 17) and x["levels"]["C"] in ("on", "off")


def test_optuna_proposals_are_identical_across_processes():
    """No hidden state: a fresh interpreter, given the same rows and seed,
    proposes the same configurations."""
    pytest.importorskip("optuna")
    code = (
        "import json,sys;from tests.test_optimize_bo_proposer import _rows,FACTORS,OBJ;"
        "from orchestrator.optimize.bo_proposer import propose;"
        "p,_=propose(_rows(),factors=FACTORS,objectives=OBJ,n=3,config={'seed':5,'n_startup':2});"
        "print(json.dumps([x['levels'] for x in p],sort_keys=True))")
    outs = [subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout for _ in range(2)]
    here, _ = bo_proposer.propose(_rows(), factors=FACTORS, objectives=OBJ, n=3,
                                  config={"seed": 5, "n_startup": 2})
    assert outs[0] == outs[1] == json.dumps([x["levels"] for x in here], sort_keys=True) + "\n"


def test_the_bo_configuration_is_compiled_into_the_policy_and_hashed():
    base = synthetic_campaign(SURFACES["bowl"]())
    with_bo = synthetic_campaign(SURFACES["bowl"](), planner={"bo": {"seed": 11}})
    p0, p1 = compile_policy(base), compile_policy(with_bo)
    assert "planner" not in p0
    assert p1["planner"] == {"bo": {"sampler": "tpe", "n_startup": 10, "seed": 11}}
    assert bo_proposer.bo_config(p1) == {"sampler": "tpe", "n_startup": 10, "seed": 11}
    assert bo_proposer.bo_config(p0) is None
    p2 = compile_policy(synthetic_campaign(SURFACES["bowl"](), planner={"bo": {"seed": 12}}))
    assert len({policy_hash(p0), policy_hash(p1), policy_hash(p2)}) == 3


def test_a_policy_with_planner_bo_validates_against_the_schemas(tmp_path):
    import jsonschema
    import yaml

    from orchestrator.optimize.policy import write_policy

    c = synthetic_campaign(SURFACES["bowl"](), planner={"bo": {"seed": 1, "n_startup": 4}})
    write_policy(tmp_path, compile_policy(c))
    schema = yaml.safe_load((ROOT / "orchestrator/schemas/campaign.schema.yaml").read_text())
    jsonschema.validate(c, schema)
    bad = synthetic_campaign(SURFACES["bowl"](), planner={"bo": {"sampler": "cmaes"}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods |= {f"{node.module}.{a.name}" for a in node.names}
    return mods


INFERENCE_MODULES = ("certificate", "decide", "effects", "adequacy", "constraint_models",
                     "pareto", "pareto_stage", "stage", "stage_runner", "policy",
                     "reanalyze", "provenance")


@pytest.mark.parametrize("name", INFERENCE_MODULES)
def test_optuna_and_the_proposer_never_reach_an_inference_module(name):
    """Static: no inference or certification module imports the proposer or
    optuna, at any depth of the module (function-level imports included)."""
    mods = _imports(ROOT / "orchestrator" / "optimize" / f"{name}.py")
    assert not any(m.startswith("optuna") or m.endswith("bo_proposer")
                   or m == "orchestrator.optimize.allocate" or m.endswith("planner")
                   for m in mods), sorted(mods)


def test_importing_the_inference_path_loads_no_optuna():
    """Dynamic: a fresh interpreter that imports the whole inference path,
    and allocate, has neither optuna nor the proposer in sys.modules."""
    code = ("import sys;"
            + "".join(f"import orchestrator.optimize.{m};" for m in INFERENCE_MODULES)
            + "import orchestrator.optimize.allocate;"
            "print(sorted(m for m in sys.modules if m.startswith('optuna') or "
            "m.endswith('bo_proposer')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == "[]"


def test_the_proposer_imports_optuna_lazily():
    tree = ast.parse((ROOT / "orchestrator/optimize/bo_proposer.py").read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("optuna" in ast.dump(n) for n in top)


def test_an_off_step_measured_level_is_snapped_not_refused():
    """A row at A=5 with grid 2 starting at 2 (off the low + k*step grid)."""
    pytest.importorskip("optuna")
    f = parse_factors([_numeric("A", levels=(2, 4, 8, 16), grid=2), _numeric("B")])
    rows = [{"levels": {"A": a, "B": b}, "response": {"m": float(a + b)}}
            for a, b in [(2, 2), (5, 16), (16, 4), (8, 8)]]
    props, prov = bo_proposer.propose(rows, factors=f, objectives=OBJ, n=2,
                                      config={"seed": 1, "n_startup": 2})
    assert prov["n_trials_from_rows"] == 4 and props
