"""v8: the orchestrator's own use of the official measure command, and results rebuilt from official measures.

Zero LLM tokens. Two jobs:

1. ``run_measure``: run the campaign's sanctioned measure command (``v8.measure_command``, else the
   command the target description names after "MEASURE only with this command:") on a directory and
   parse ``SCORE: <n>``. The orchestrator runs inside the same sandbox as the agents, so the command
   works exactly as it does for them. Tests point ``v8.measure_command`` at a local fake script.
2. ``recover_result``: when a session ended without a usable ``result.json``, build one from the
   official measures recorded during that session's time window (``v8.official_log``) and put the best
   measured solution (from ``v8.measured_archive``, matched by sha256) into the arm's worktree and patch.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_DESC_CMD = re.compile(r"MEASURE only with this command:\s*(.+?)(?:\s{2,}|\s+\(|\n|$)")
_SCORE = re.compile(r"SCORE:\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_PWD_FILE = re.compile(r"\$(?:PWD|\{PWD\})/(\S+)")
ORCHESTRATOR_NOTE = "Written by the orchestrator from the official measures recorded during this arm's sessions;"


def measure_command(campaign: dict) -> str | None:
    """The sanctioned official measure command, or None when the campaign names none."""
    cfg = (campaign or {}).get("v8") or {}
    if str(cfg.get("measure_command") or "").strip():
        return str(cfg["measure_command"]).strip()
    m = _DESC_CMD.search(str(((campaign or {}).get("target_system") or {}).get("description") or ""))
    return m.group(1).strip() if m else None


def solution_file(campaign: dict) -> str | None:
    """Path of the solution file relative to a worktree (``v8.solution_file`` or ``$PWD/<file>`` in the command)."""
    cfg = (campaign or {}).get("v8") or {}
    if str(cfg.get("solution_file") or "").strip():
        return str(cfg["solution_file"]).strip()
    m = _PWD_FILE.search(measure_command(campaign) or "")
    return m.group(1).strip("'\"") if m else None


def parse_score(text: str) -> float | None:
    found = _SCORE.findall(text or "")
    return float(found[-1]) if found else None


def run_measure(campaign: dict, cwd: Path, timeout_s: float | None = None) -> float | None:
    """One official measure of the solution in ``cwd``; None when the command is missing or fails."""
    cmd = measure_command(campaign)
    if not cmd:
        return None
    if timeout_s is None:
        timeout_s = float(((campaign or {}).get("v8") or {}).get("measure_timeout_s") or 1500)
    env = dict(os.environ)
    env["PWD"] = str(Path(cwd).resolve())  # the command names the solution as $PWD/<file>
    t0 = time.time()
    try:
        res = subprocess.run(["/bin/bash", "-c", cmd], cwd=str(cwd), env=env, capture_output=True,
                             text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("v8: official measure failed: %s", exc)
        return None
    # The measure script prints "SCORE: 0.0" when the judge never answered within its wait; that is
    # not a score.
    wait_s = float(((campaign or {}).get("v8") or {}).get("measure_wait_s") or 1200)
    if time.time() - t0 >= wait_s - 15:
        logger.warning("v8: official measure waited %.0f s for the judge; treated as no score", time.time() - t0)
        return None
    score = parse_score(res.stdout + "\n" + res.stderr)
    if score is None:
        logger.warning("v8: official measure printed no score (exit %s): %s", res.returncode,
                       (res.stdout + res.stderr).strip()[-300:])
    return score


# ─── results from official measures ─────────────────────────────────────────────────────────

def measures_in(campaign: dict, work_dir: Path, windows) -> list[dict]:
    """Official measures whose ``ts`` falls in any of ``windows`` (dicts with ``start``/``end``)."""
    from orchestrator.judge_profile import _num, official_measures
    spans = []
    for w in windows or ():
        start = _num((w or {}).get("start"))
        if start is not None:
            spans.append((start, _num(w.get("end"))))
    if not spans:
        return []
    out = []
    for r in official_measures(campaign, work_dir):
        ts = _num(r.get("submitted_ts")) or _num(r.get("ts"))  # attribute a measure to who submitted it
        if ts is not None and any(ts >= s and (e is None or ts <= e) for s, e in spans):
            out.append(r)
    return out


def best_measure(rows: list[dict]) -> dict | None:
    """Highest score; among equal scores the latest one."""
    best = None
    for r in rows:
        if best is None or float(r["score"]) >= float(best["score"]):
            best = r
    return best


def find_code(campaign: dict, sha: str, extra_files=()) -> bytes | None:
    """The measured solution whose sha256 is ``sha``, from the measured archive or ``extra_files``."""
    if not sha:
        return None
    cfg = (campaign or {}).get("v8") or {}
    files = [Path(f) for f in extra_files]
    archive = cfg.get("measured_archive")
    if archive and Path(archive).expanduser().is_dir():
        files += sorted(p for p in Path(archive).expanduser().iterdir() if p.is_file())
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(data).hexdigest() == sha:
            return data
    return None


def _base_solution_sha(campaign: dict, worktree: Path | None, base: str | None) -> str | None:
    """sha256 of the solution file (named in the measure command as $PWD/<file>) at the arm's base commit."""
    m = re.search(r"\$PWD/(\S+)", measure_command(campaign) or "")
    if not (m and worktree and base and Path(worktree).is_dir()):
        return None
    res = subprocess.run(["git", "show", f"{base}:{m.group(1)}"], cwd=str(worktree), capture_output=True)
    return hashlib.sha256(res.stdout).hexdigest() if res.returncode == 0 else None


def _needs_score(result, campaign: dict) -> bool:
    from orchestrator.v7_execute import arm_score
    return not isinstance(result, dict) or arm_score(result, campaign) is None


def recover_result(campaign: dict, work_dir: Path, result_path: Path, *, arm_key: str, arm: dict,
                   windows, worktree: Path | None, patch: Path, base: str | None, extras=(),
                   stale_before: float | None = None) -> dict | None:
    """Write ``result_path`` (and the patch) from the best official measure in ``windows`` when needed.

    Needed when the result is missing or has no score, or (``stale_before``, the winner's session start)
    when the result was not rewritten since then and a measure in the window scored higher. Returns the
    best official measure in the window (or None); writes nothing when no measure fell in the window.
    """
    from orchestrator.v7_execute import _load_json, _metric_keys, arm_score, save_worktree_diff
    rows = measures_in(campaign, work_dir, windows)
    base_sha = _base_solution_sha(campaign, worktree, base)
    if base_sha:  # re-measuring the unchanged incumbent is not the arm's result
        rows = [r for r in rows if str(r.get("sha256") or "") != base_sha]
    best = best_measure(rows)
    if best is None:
        return None
    result = _load_json(result_path, None)
    score = float(best["score"])
    need = _needs_score(result, campaign)
    why = "the session ended without recording a score."
    if not need and score > (arm_score(result, campaign) or 0.0):
        # The judge's record wins over the agent's notes. Live p181: an arm scored 49.55 officially but
        # its result.json still said 12.46, so the wrong arm won the screening.
        need = True
        why = "an official measure in this arm's sessions beat the score its result file records."
    if not need:
        return best
    code_note = _write_best_code(campaign, best, worktree, patch, base, extras, save_worktree_diff)
    keys = _metric_keys(campaign)
    out = dict(result) if isinstance(result, dict) else {}
    out.update({
        "arm_key": arm_key,
        "arm_type": out.get("arm_type") or arm.get("type") or "h-main",
        "mechanism_family": out.get("mechanism_family") or arm.get("mechanism_family") or arm_key,
        "metrics": {**(out.get("metrics") if isinstance(out.get("metrics"), dict) else {}), keys[0]: score},
        "validity_check": ({"passed": True, "detail": f"the official judge scored it {score:g} (> 0)"}
                           if score > 0 else
                           {"passed": None, "detail": "unknown: no official measure scored above 0"}),
        "predicted": out.get("predicted") or str(arm.get("prediction") or "(not stated)"),
        "observed": (f"best official score {score:g} among {len(rows)} official measures in this arm's "
                     "sessions (recorded by the orchestrator)"),
        "written_by": "orchestrator",
        "orchestrator_note": f"{ORCHESTRATOR_NOTE} {why} {code_note}",
    })
    result_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(result_path, json.dumps(out, indent=2) + "\n")
    logger.info("v8: %s result written by the orchestrator (score %s; %s)", arm_key, score, code_note)
    print(f"  v8 `{arm_key}`: result.json written by the orchestrator from the official measures "
          f"(best {score:g})")
    return best


def _write_best_code(campaign, best, worktree, patch, base, extras, save_diff) -> str:
    rel = solution_file(campaign)
    if worktree is None or not Path(worktree).is_dir():
        return "The arm's worktree is gone, so its patch was kept."
    if not rel:
        return "No solution file is known, so the patch was kept."
    target = Path(worktree) / rel
    code = find_code(campaign, str(best.get("sha256") or ""), [target])
    if code is None:
        return "The best measured file was not found, so the patch was kept."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(code)
    save_diff(Path(worktree), base or "HEAD", Path(patch), exclude=list(extras or []))
    return "The patch holds the best measured solution."
