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
        # No fallback by design: plot script paths declared in
        # campaign.plot_specs[].script are relative to the
        # campaign.yaml's directory, which is recorded as
        # ``state.json["config_ref"]`` at setup_work_dir time
        # (#263 / F18). The caller must read it via
        # ``orchestrator.iteration._campaign_yaml_dir_from_state``.
        # Returning an empty result is the right answer here —
        # guessing a directory and silently failing to resolve
        # scripts was the bug from review I1.
        logger.warning(
            "invoke_plot_specs called without campaign_yaml_dir; "
            "skipping (script paths cannot be resolved without it)."
        )
        return [
            {"id": (s or {}).get("id", "<unnamed>"), "ok": False,
             "error": "no campaign_yaml_dir available"}
            for s in specs if isinstance(s, dict)
        ]

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
                _build_command(script_path),
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


def _build_command(script_path: Path) -> list[str]:
    """Build the argv list for invoking ``script_path``.

    Dispatch by extension (``.py`` → python3, ``.sh``/``.bash`` →
    bash). For executable files with no recognized extension, invoke
    directly via the shebang (single-element argv) — the previous
    ``_pick_interpreter`` returned the script as both interpreter
    and argv[1], which made the script invoke itself with itself
    as its first argument. Falls back to python3 for unknown
    non-executable suffixes (the most common authoring shape).
    """
    suffix = script_path.suffix.lower()
    if suffix == ".py":
        return ["python3", str(script_path)]
    if suffix in (".sh", ".bash"):
        return ["bash", str(script_path)]
    if os.access(script_path, os.X_OK):
        return [str(script_path)]
    return ["python3", str(script_path)]
