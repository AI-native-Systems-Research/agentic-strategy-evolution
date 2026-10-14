"""EXECUTE for ``design_profile: v7``: screen each mechanism arm in a fresh capped session, then deepen the winner.

Order within an iteration (all sessions sequential, each in its own worktree branched from the target HEAD,
which carry-forward keeps at the best solution so far):

1. ``build-evaluator`` session, only while ``<work_dir>/evaluator/README.md`` is missing.
2. One ``execute-arm`` session per mechanism arm (``h-main``, ``h-alternative-1``, ...), each capped at
   ``v7.arm_budget_usd`` (shrunk so the winner keeps ``v7.winner_min_usd`` of the iteration budget). Each
   writes ``arms/<key>/result.json`` and ``patches/<key>.patch``.
3. The winner (best valid score) gets a fresh worktree with its patch applied and the rest of the iteration
   budget in one ``execute-analyze`` session, which writes the usual protocol artifacts.
4. Losing arms are appended to ``findings.json`` and ``principle_updates.json`` from their result files.

Spend is measured on the token ruler from ``llm_metrics.jsonl`` against a snapshot taken when the iteration
started (``arms/budget.json``), so the design session counts toward the iteration budget.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import yaml

from orchestrator.design_profile import EVALUATOR_DIR, V7Settings, is_v7, v7_settings
from orchestrator.metrics import spent_usd
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

ARMS_DIR = "arms"
STATE_FILE = "state.json"
BUDGET_FILE = "budget.json"
EVALUATOR_KEY = "evaluator"
MIN_SESSION_USD = 1.0
_STATUSES = ("CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED")
_ERROR_TYPES = ("direction", "magnitude", "regime", "shape_mismatch")


def mechanism_arms(bundle: dict) -> list[tuple[str, dict]]:
    """(key, arm) for each h-main / h-alternative arm in bundle order: h-main, h-alternative-1, ..."""
    out: list[tuple[str, dict]] = []
    counts = {"h-main": 0, "h-alternative": 0}
    for arm in (bundle or {}).get("arms") or []:
        if not isinstance(arm, dict) or arm.get("type") not in counts:
            continue
        t = arm["type"]
        counts[t] += 1
        if t == "h-alternative":
            out.append((f"h-alternative-{counts[t]}", arm))
        else:
            out.append(("h-main" if counts[t] == 1 else f"h-main-{counts[t]}", arm))
    return out


def screening_cap(s: V7Settings, remaining: float, sessions_left: int) -> float:
    """Cap for the next screening session: the arm cap, shrunk so the winner keeps its reserve."""
    share = (remaining - s.winner_min_usd) / max(1, sessions_left)
    return round(max(MIN_SESSION_USD, min(s.arm_budget_usd, share)), 2)


def winner_cap(s: V7Settings, remaining: float) -> float:
    return round(max(s.winner_min_usd, remaining), 2)


def _metrics_path(work_dir: Path) -> Path:
    return Path(work_dir) / "llm_metrics.jsonl"


def mark_iteration_start(campaign: dict, work_dir: Path, iter_dir: Path) -> None:
    """Snapshot campaign spend at the start of the iteration (idempotent)."""
    path = Path(iter_dir) / ARMS_DIR / BUDGET_FILE
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    start = spent_usd(_metrics_path(work_dir), v7_settings(campaign).cost_rates)
    atomic_write(path, json.dumps({"start_spent_usd": round(start, 4)}) + "\n")


def iteration_spent(campaign: dict, work_dir: Path, iter_dir: Path) -> float:
    mark_iteration_start(campaign, work_dir, iter_dir)
    start = json.loads((Path(iter_dir) / ARMS_DIR / BUDGET_FILE).read_text()).get("start_spent_usd", 0.0)
    return spent_usd(_metrics_path(work_dir), v7_settings(campaign).cost_rates) - float(start)


def _load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def _save_state(adir: Path, state: dict) -> None:
    atomic_write(adir / STATE_FILE, json.dumps(state, indent=2) + "\n")


def _metric_keys(campaign: dict) -> list[str]:
    weights = (campaign.get("objective") or {}).get("weights") or {}
    return list(weights) or list(campaign.get("target_system", {}).get("observable_metrics") or ["score"])


def arm_score(result: dict | None, campaign: dict) -> float | None:
    """Objective value of a screened arm, or None when it reports none of the objective's metrics."""
    if not isinstance(result, dict) or not isinstance(result.get("metrics"), dict):
        return None
    metrics = result["metrics"]
    from orchestrator.iteration import _resolve_objective
    objective = _resolve_objective(campaign)
    if objective is None:
        try:
            return float(metrics[_metric_keys(campaign)[0]])
        except (KeyError, TypeError, ValueError, IndexError):
            return None
    present = [k for k in objective.weights if isinstance(metrics.get(k), (int, float))]
    if not present:
        return None
    from orchestrator.composite_score import compute_score
    return compute_score(metrics, objective)


def _valid(result: dict | None) -> bool:
    check = (result or {}).get("validity_check")
    return not (isinstance(check, dict) and check.get("passed") is False)


def pick_winner(arms: list[tuple[str, dict]], results: dict, campaign: dict) -> str | None:
    """Best valid score; ties go to the earlier arm. None when no arm has a valid score."""
    best_key, best = None, None
    for key, _arm in arms:
        r = results.get(key)
        score = arm_score(r, campaign)
        if score is None or not _valid(r):
            continue
        if best is None or score > best:
            best_key, best = key, score
    return best_key


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _ensure_patch(worktree: Path, patch: Path) -> None:
    """Keep the session's patch; if it wrote none, save the worktree's tracked diff instead."""
    if patch.is_file() and patch.stat().st_size > 0:
        return
    diff = _git(worktree, "diff").stdout
    if diff.strip():
        patch.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(patch, diff)


def session_context(campaign: dict, work_dir: Path, iteration: int, key: str | None,
                    budget_usd: float | None = None) -> dict[str, str]:
    """Prompt placeholders for the execute-arm and build-evaluator templates."""
    work_dir = Path(work_dir)
    iter_dir = (work_dir / "runs" / f"iter-{iteration}").resolve()
    ctx = {
        "iter_dir": str(iter_dir),
        "evaluator_dir": str(work_dir.resolve() / EVALUATOR_DIR),
        "budget_usd": f"{budget_usd:.2f}" if budget_usd is not None else "(uncapped)",
        "metric_keys": ", ".join(_metric_keys(campaign)),
    }
    if key and key != EVALUATOR_KEY:
        arm = dict(mechanism_arms(_load_bundle(iter_dir))).get(key, {})
        ctx.update({
            "arm_key": key,
            "arm_yaml": yaml.safe_dump(arm, sort_keys=False).strip(),
            "result_path": str(iter_dir / ARMS_DIR / key / "result.json"),
            "patch_path": str(iter_dir / "patches" / f"{key}.patch"),
        })
    return ctx


def _load_bundle(iter_dir: Path) -> dict:
    try:
        return yaml.safe_load((Path(iter_dir) / "bundle.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def screening_summary(campaign: dict, iter_dir: Path) -> str:
    """Winner-session note listing every screened arm; empty unless v7 screening ran for this iteration."""
    if not is_v7(campaign):
        return ""
    adir = Path(iter_dir) / ARMS_DIR
    state = _load_json(adir / STATE_FILE, {})
    winner = (state.get("winner") or {}).get("key")
    if not winner:
        return ""
    lines = ["", "", "## Screening results (v7)", ""]
    for key, arm in mechanism_arms(_load_bundle(iter_dir)):
        r = _load_json(adir / key / "result.json", None)
        if r is None:
            lines.append(f"- `{key}` ({arm.get('mechanism_family', '?')}): no result file")
            continue
        check = r.get("validity_check") or {}
        lines.append(f"- `{key}` ({r.get('mechanism_family') or arm.get('mechanism_family', '?')}): score "
                     f"{arm_score(r, campaign)}, validity {'failed' if not _valid(r) else 'passed'}"
                     f"{': ' + str(check.get('detail')) if check.get('detail') else ''}; {r.get('status')}; "
                     f"`{adir / key / 'result.json'}`")
    applied = state["winner"].get("patch_applied")
    lines += ["", f"Winner: `{winner}`. Your worktree "
              + (f"starts from `patches/{winner}.patch`." if applied else
                 "is the unchanged incumbent (no winner patch could be applied).")]
    return "\n".join(lines) + "\n"


def _arm_entry(key: str, arm: dict, result: dict, campaign: dict) -> dict:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    status = result.get("status") if result.get("status") in _STATUSES else "REFUTED"
    if not _valid(result):
        status = "REFUTED"
    error_type = result.get("error_type") if result.get("error_type") in _ERROR_TYPES else None
    return {
        "arm_type": arm.get("type", "h-alternative"),
        "predicted": str(result.get("predicted") or arm.get("prediction") or "(not stated)"),
        "observed": str(result.get("observed") or f"score {arm_score(result, campaign)}"),
        "status": status,
        "error_type": error_type,
        "diagnostic_note": f"Lost the v7 screening; result in arms/{key}/result.json",
        # An invalid mechanism keeps its numbers out of the objective keys so best_found never ranks it.
        "metadata": {**(metrics if _valid(result) else {"screen_metrics": metrics}),
                     "candidate_id": key, "screening": True,
                     "mechanism_family": result.get("mechanism_family") or arm.get("mechanism_family"),
                     "validity_check": result.get("validity_check")},
    }


def _loser_principle(key: str, arm: dict, result: dict, winner: str, winner_result: dict | None,
                     iteration: int, cap: float | None, campaign: dict) -> dict:
    family = result.get("mechanism_family") or arm.get("mechanism_family") or key
    win_family = (winner_result or {}).get("mechanism_family") or winner
    check = result.get("validity_check") or {}
    if not _valid(result):
        why = f"failed its validity check ({check.get('detail') or 'no detail'})"
    else:
        why = (f"scored {arm_score(result, campaign)} vs {arm_score(winner_result, campaign)} for "
               f"{win_family} ({winner})")
    budget = f" at a ${cap:.2f} screening budget" if cap else ""
    return {
        "id": f"iter-{iteration}-{key}-lost",
        "statement": (f"In iteration {iteration} the {family} mechanism ({key}) lost the screening{budget}: "
                      f"it {why}. Its prediction was {result.get('status', 'not met')}: "
                      f"{result.get('predicted') or arm.get('prediction', '')}"),
        "confidence": "low",
        "regime": f"v7 screening{budget}",
        "evidence": [f"iter-{iteration}/{key}: {result.get('observed') or ''}".strip()],
        "contradicts": [],
        "extraction_iteration": iteration,
        "mechanism": str(arm.get("mechanism") or ""),
        "applicability_bounds": "One short screening session; a deeper attempt may score differently.",
        "superseded_by": None,
        "category": "domain",
        "status": "active",
    }


def record_screened_arms(campaign: dict, iter_dir: Path, iteration: int) -> None:
    """Append losing screened arms to findings.json and a principle per loser to principle_updates.json."""
    iter_dir = Path(iter_dir)
    adir = iter_dir / ARMS_DIR
    state = _load_json(adir / STATE_FILE, {})
    winner = (state.get("winner") or {}).get("key")
    findings = _load_json(iter_dir / "findings.json", None)
    updates = _load_json(iter_dir / "principle_updates.json", None)
    if not winner or not isinstance(findings, dict) or not isinstance(findings.get("arms"), list):
        return
    arms = mechanism_arms(_load_bundle(iter_dir))
    results = {k: _load_json(adir / k / "result.json", None) for k, _ in arms}
    seen = {(a.get("metadata") or {}).get("candidate_id") for a in findings["arms"] if isinstance(a, dict)}
    for key, arm in arms:
        r = results.get(key)
        if key == winner or not isinstance(r, dict):
            continue
        if key not in seen:
            findings["arms"].append(_arm_entry(key, arm, r, campaign))
        if isinstance(updates, list):
            pid = f"iter-{iteration}-{key}-lost"
            cited = any(isinstance(p, dict) and (p.get("id") == pid or any(
                f"iter-{iteration}/{key}" in str(e) for e in (p.get("evidence") or []))) for p in updates)
            if not cited:
                cap = (state.get("sessions", {}).get(key) or {}).get("budget_usd")
                updates.append(_loser_principle(key, arm, r, winner, results.get(winner), iteration, cap,
                                                campaign))
    atomic_write(iter_dir / "findings.json", json.dumps(findings, indent=2) + "\n")
    if isinstance(updates, list):
        atomic_write(iter_dir / "principle_updates.json", json.dumps(updates, indent=2) + "\n")


def run_v7_execute(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int,
                   repo_path, *, extras=None) -> tuple[Path, str]:
    """Run screening and the winner session; return the winner's (worktree, experiment_id) for cleanup."""
    from orchestrator.worktree import (
        _EXPERIMENTS_DIRNAME, create_experiment_worktree, remove_experiment_worktree,
    )
    work_dir, iter_dir, repo = Path(work_dir), Path(iter_dir), Path(repo_path)
    s = v7_settings(campaign)
    adir = iter_dir / ARMS_DIR
    adir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "patches").mkdir(parents=True, exist_ok=True)
    mark_iteration_start(campaign, work_dir, iter_dir)
    state = _load_json(adir / STATE_FILE, {})
    state.setdefault("sessions", {})
    arms = mechanism_arms(_load_bundle(iter_dir))
    if not arms:
        raise RuntimeError(f"v7 EXECUTE: {iter_dir / 'bundle.yaml'} has no h-main or h-alternative arm")

    def remaining() -> float:
        return s.iteration_budget_usd - iteration_spent(campaign, work_dir, iter_dir)

    sessions: list[tuple[str, dict | None]] = []
    evaluator_done = (state["sessions"].get(EVALUATOR_KEY) or {}).get("status") == "done"
    if evaluator_done or not (work_dir / EVALUATOR_DIR / "README.md").is_file():
        sessions.append((EVALUATOR_KEY, None))
    sessions += arms
    todo = [k for k, _ in sessions if (state["sessions"].get(k) or {}).get("status") != "done"]
    for key, _arm in sessions:
        rec = state["sessions"].get(key) or {}
        if rec.get("status") == "done":
            continue
        if rec.get("experiment_id"):  # interrupted earlier: start this session over
            remove_experiment_worktree(repo, rec["experiment_id"])
        cap = screening_cap(s, remaining(), len(todo))
        todo.remove(key)
        wt, eid = create_experiment_worktree(repo, iteration, extras=extras or [])
        state["sessions"][key] = {"status": "running", "experiment_id": eid, "budget_usd": cap}
        _save_state(adir, state)
        phase = "build-evaluator" if key == EVALUATOR_KEY else "execute-arm"
        log = adir / key / "session_log.md"
        print(f"  v7 {phase} `{key}` (cap ${cap:.2f}) in {wt}")
        status = "done"
        try:
            with dispatcher.override_cwd(wt), dispatcher.session_budget(cap, label=key):
                dispatcher.dispatch("executor", phase, output_path=log, iteration=iteration, perspective=key)
        except RuntimeError as exc:
            logger.warning("v7 session %s failed: %s", key, exc)
            status = "failed"
        if key != EVALUATOR_KEY:
            _ensure_patch(wt, iter_dir / "patches" / f"{key}.patch")
        remove_experiment_worktree(repo, eid)
        state["sessions"][key] = {"status": "done", "outcome": status, "budget_usd": cap}
        _save_state(adir, state)

    results = {k: _load_json(adir / k / "result.json", None) for k, _ in arms}
    win = state.get("winner") or {}
    if not win.get("key"):
        key = pick_winner(arms, results, campaign)
        if key is None:
            key = arms[0][0]
            logger.warning("v7: no screened arm reported a valid score; continuing with %s", key)
        win = {"key": key, "score": arm_score(results.get(key), campaign)}
    old_wt = repo / _EXPERIMENTS_DIRNAME / str(win.get("experiment_id") or "")
    if win.get("experiment_id") and old_wt.is_dir():
        wt, eid = old_wt, win["experiment_id"]
    else:
        wt, eid = create_experiment_worktree(repo, iteration, extras=extras or [])
        patch = iter_dir / "patches" / f"{win['key']}.patch"
        usable = patch.is_file() and patch.stat().st_size > 0 and _valid(results.get(win["key"]))
        applied = usable and _git(wt, "apply", str(patch.resolve())).returncode == 0
        if usable and not applied:
            logger.warning("v7: could not apply %s; the winner session starts from the incumbent", patch)
        win.update({"experiment_id": eid, "patch_applied": applied})
    state["winner"] = win
    _save_state(adir, state)
    (iter_dir / ".experiment_id").write_text(eid)

    cap = winner_cap(s, remaining())
    print(f"  v7 winner `{win['key']}` (score {win.get('score')}) gets ${cap:.2f} in {wt}")
    with dispatcher.override_cwd(wt), dispatcher.session_budget(cap, label="winner"):
        dispatcher.dispatch("executor", "execute-analyze", output_path=iter_dir / "executor_log.md",
                            iteration=iteration)
    record_screened_arms(campaign, iter_dir, iteration)
    return wt, eid
