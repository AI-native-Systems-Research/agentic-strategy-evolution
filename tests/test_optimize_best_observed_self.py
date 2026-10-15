"""confirm never calls the winner worse than ITSELF, and respects epsilon.

Found on a real campaign: confirm warned that the winning finalist was "WORSE
than the best configuration already observed ... treat the surface as
mis-specified" -- where the best observation was an earlier row of the SAME
configuration. A single row is an upward-biased read of its configuration; the
comparison only means something against a different configuration, and only
outside the campaign's own indifference width.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


@pytest.mark.parametrize("surface,seed", [("bowl", s) for s in range(1, 7)]
                         + [("sla", 5), ("saddle", 2), ("additive", 1)])
def test_no_regression_is_reported_against_the_winners_own_rows(tmp_path, surface, seed):
    res = run_synthetic_campaign(SURFACES[surface](), seed=seed, parent_dir=tmp_path)
    for conf in Path(res.work_dir).glob("runs/iter-*/confirmation.json"):
        c = json.loads(conf.read_text())
        bo = c.get("best_observed")
        if bo and bo.get("levels") == c.get("confirmed_at_levels"):
            assert c["confirmed_is_best_observed"] is True, conf
            assert "regression_vs_best_observed" not in c, conf
        reg = c.get("regression_vs_best_observed")
        if reg is not None and isinstance(c.get("epsilon"), (int, float)):
            assert reg["within_epsilon"] == (reg["absolute"] <= c["epsilon"]), conf
