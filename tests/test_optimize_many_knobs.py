"""Many knobs, end to end: a 12- or 16-knob campaign runs in seconds and
finds the optimum.

Before: the screen fell back to a 2^k full factorial past 8 knobs and the
candidate search enumerated 9^k points, so 7 knobs did not finish in nine
minutes. These drive the real policy end to end on a sparse surface (three
active knobs among k) and judge against the noiseless truth.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import sparse_knobs, true_optimum


def _runs(work_dir) -> int:
    return sum(sum(1 for ln in p.read_text().splitlines() if ln.strip())
               for p in Path(work_dir).glob("runs/iter-*/runs.jsonl"))


def test_the_active_factor_oracle_equals_full_enumeration():
    """The shortcut must be the truth, not an approximation of it."""
    s = sparse_knobs(4)
    full = dataclasses.replace(s, active=())
    assert true_optimum(s) == true_optimum(full)


@pytest.mark.parametrize("k,resolution,screen_corners", [
    (12, 5, 256), (16, 5, 256), (16, 4, 32)])
def test_a_many_knob_campaign_finds_the_optimum_in_seconds(tmp_path, k, resolution,
                                                          screen_corners):
    t = time.monotonic()
    res = run_synthetic_campaign(
        sparse_knobs(k), seed=1, parent_dir=tmp_path,
        campaign_overrides={"design": {
            "screen": {"resolution": resolution, "center_points": 4},
            "refine": {"kind": "central_composite", "center_points": 4},
            "confirm": {"replicates": 3}}})
    elapsed = time.monotonic() - t
    assert res.path[-1] == "report", res.path
    assert res.true_gap == pytest.approx(0.0, abs=1e-9), (res.recommendation,
                                                           res.true_optimum)
    screen = json.loads((Path(res.work_dir) / "runs" / "iter-2" /
                         "design_matrix.json").read_text())
    corners = sum(1 for r in screen["rows"] if r.get("role", "corner") == "corner")
    assert corners == screen_corners, "the screen is a fraction, not 2^k"
    assert _runs(res.work_dir) < 2 ** k
    # Generous: measured 4-9 s; the point is "seconds, not hours".
    assert elapsed < 120, f"{k} knobs took {elapsed:.0f}s"
