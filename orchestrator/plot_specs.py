"""Declarative figure pipeline (#263 / F18).

Campaigns declare ``plot_specs`` in campaign.yaml; nous invokes each
script after ``findings.json`` is written, passing the per-iter
``results/`` and ``figures/`` paths via environment variables.

Pure-Python orchestration — the figures themselves come from
user-supplied scripts (typically matplotlib-based), so nous stays
domain-agnostic. The script's contract is simple:

* Read JSON files from ``$NOUS_RESULTS_DIR``.
* Write outputs to ``$NOUS_FIGURES_DIR``.
* Exit 0 on success, non-zero on failure (logged but never blocks).

Failures are warnings, not errors: a busted plot script shouldn't
fail the campaign, but the operator wants to see what went wrong.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def invoke_plot_specs(
    campaign: dict, iter_dir: Path, *, campaign_yaml_dir: Path | None = None,
) -> list[dict]:
    """Run every ``campaign.plot_specs`` entry against ``iter_dir/results/``.

    Returns a list of per-spec result dicts:
      ``{id, ok, returncode, outputs_present, error?}``.

    Idempotent: re-invoking on an iter that already has figures
    overwrites — figure scripts are deterministic by convention.
    """
    specs = campaign.get("plot_specs") or []
    if not isinstance(specs, list) or not specs:
        return []

    iter_dir = Path(iter_dir)
    results_dir = iter_dir / "results"
    figures_dir = iter_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    if campaign_yaml_dir is None:
        # Fall back to the work_dir's parent — best-effort. Operators
        # who need a different base can pass ``campaign_yaml_dir``
        # explicitly via ``_generate_report`` plumbing.
        campaign_yaml_dir = iter_dir.parent.parent.parent

    out: list[dict] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        spec_id = spec.get("id", "<unnamed>")
        script_rel = spec.get("script")
        if not script_rel:
            out.append({"id": spec_id, "ok": False, "error": "missing script"})
            continue
        script_path = (Path(campaign_yaml_dir) / script_rel).resolve()
        if not script_path.is_file():
            out.append({
                "id": spec_id, "ok": False,
                "error": f"script not found: {script_path}",
            })
            continue
        env = {
            **os.environ,
            "NOUS_RESULTS_DIR": str(results_dir),
            "NOUS_FIGURES_DIR": str(figures_dir),
            "NOUS_ITER_DIR": str(iter_dir),
        }
        try:
            result = subprocess.run(
                [_pick_interpreter(script_path), str(script_path)],
                env=env, capture_output=True, text=True, check=False,
                timeout=300,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("plot_specs[%s] failed to start: %s", spec_id, exc)
            out.append({"id": spec_id, "ok": False, "error": str(exc)})
            continue

        outputs_declared = spec.get("outputs") or []
        outputs_present = [
            o for o in outputs_declared
            if (figures_dir / o).exists()
            or (iter_dir / o).exists()
        ]
        out.append({
            "id": spec_id,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "outputs_present": outputs_present,
            "stderr_tail": (result.stderr or "")[-500:] if result.returncode != 0 else "",
        })
        if result.returncode != 0:
            logger.warning(
                "plot_specs[%s] returned %d; stderr tail: %s",
                spec_id, result.returncode, (result.stderr or "")[-200:],
            )
    return out


def _pick_interpreter(script_path: Path) -> str:
    """Pick a sensible interpreter for a figure script. Honors
    shebang via direct execution when the file is executable; else
    dispatches by extension. Defaults to ``python3``.
    """
    suffix = script_path.suffix.lower()
    if suffix in (".py",):
        return "python3"
    if suffix in (".sh", ".bash"):
        return "bash"
    if os.access(script_path, os.X_OK):
        return str(script_path)
    return "python3"
