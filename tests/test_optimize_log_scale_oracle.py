"""scale: log on a geometric knob -- the oracle that motivated it.

A response that is a smooth bowl in log(level), peaking at the geometric
interior of [1, 64] x [256, 16384]. Coded linearly the design's centre is
(32.5, 8320); coded in log space it is (8, 2048), the optimum.
"""
from __future__ import annotations

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_log_scale_finds_the_geometric_optimum_and_is_never_worse(tmp_path, seed):
    lin = run_synthetic_campaign(SURFACES["geometric_knob"](), seed=seed,
                                 parent_dir=tmp_path / "lin")
    log = run_synthetic_campaign(SURFACES["geometric_knob_log"](), seed=seed,
                                 parent_dir=tmp_path / "log")
    assert log.true_gap <= lin.true_gap + 1e-9
    assert log.report["recommendation"]["levels"] == {"INT": 8, "BUF": 2048}
    assert log.true_gap == pytest.approx(0.0, abs=1e-9)
