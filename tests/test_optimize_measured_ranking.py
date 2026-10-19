"""The 'best measured' configuration: ranked by mean, scoped to the epoch.

Both found on a real two-epoch Go campaign (gopack): one lucky epoch-1 row
out-ranked a configuration with five replicates, and an epoch-1 configuration
naming a factor epoch 2 no longer declared was seated as an epoch-2 finalist,
claiming a level it did not run at.
"""

from __future__ import annotations

import json

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.stage_runner import _best_observed, _top_measured
from orchestrator.optimize.synthetic import SURFACES


def _row(levels, m, status="complete"):
    return json.dumps({"levels": levels, "status": status, "response": {"m": m}})


def _write_iter(work_dir, n, rows, policy_hash=None):
    it = work_dir / "runs" / f"iter-{n}"
    it.mkdir(parents=True, exist_ok=True)
    (it / "runs.jsonl").write_text("\n".join(rows) + "\n")
    if policy_hash is not None:
        (it / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash}))


def test_one_lucky_row_does_not_outrank_a_replicated_mean(tmp_path):
    lucky, steady = {"A": 1}, {"A": 2}
    _write_iter(tmp_path, 1, [_row(lucky, 140.0), _row(lucky, 100.0), _row(lucky, 104.0)]
                + [_row(steady, v) for v in (124, 126, 125, 127, 123)])
    best = _best_observed(tmp_path, "m", direction="maximize")
    assert best["levels"] == steady and best["n"] == 5
    assert abs(best["m"] - 125.0) < 1e-9


def test_minimize_ranks_by_mean_too(tmp_path):
    _write_iter(tmp_path, 1, [_row({"A": 1}, 1.0), _row({"A": 1}, 50.0),
                              _row({"A": 2}, 10.0), _row({"A": 2}, 12.0)])
    assert _best_observed(tmp_path, "m", direction="minimize")["levels"] == {"A": 2}


def test_a_previous_epochs_configuration_is_never_this_epochs_best(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    before = _top_measured(res.work_dir, "m", k=50)
    # An earlier epoch's iteration: a different policy hash, a factor this
    # epoch does not declare, and a value no current row comes near.
    _write_iter(res.work_dir, 0, [_row({"A": 9, "B": 9, "GONE": 2}, 1e9)],
                policy_hash="0" * 64)
    after = _top_measured(res.work_dir, "m", k=50)
    assert after == before
    assert all("GONE" not in t["levels"] for t in after)


def test_rows_without_a_recorded_epoch_still_count(tmp_path):
    """Pre-field work dirs carry no policy hash; nothing is silently dropped."""
    _write_iter(tmp_path, 1, [_row({"A": 1}, 5.0)])
    assert _best_observed(tmp_path, "m")["levels"] == {"A": 1}
