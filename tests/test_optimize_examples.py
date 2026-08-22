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
    errs = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN:")]
    assert errs == [], errs
    pol = compile_policy(c)
    assert check_policy(pol) == []
    assert c["optimization"].get("known_valid_baseline"), "examples must name a known-valid baseline"
    assert c["optimization"].get("workload", {}).get("seed_env"), "systems examples must seed the workload"


def test_examples_exist():
    assert {p.name for p in EXAMPLES} >= {
        "vllm-batching.yaml",
        "qdrant-hnsw.yaml",
        "knative-autoscale.yaml",
    }
