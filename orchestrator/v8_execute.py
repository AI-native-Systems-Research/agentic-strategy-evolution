"""EXECUTE for ``design_profile: v8``: v7 screening, then the winner keeps its own session.

Differences from v7 (``orchestrator.v7_execute``, whose helpers this module reuses):

1. The evaluator session first gets an official score: when the seed scores 0 it writes the simplest
   valid solution (``patches/baseline.patch``), which is committed to the target so arms start from it.
2. Screening sessions keep their worktree and session id. An arm that crashed, failed its validity
   check, or scored 0 gets one small repair turn in the same session before it is ranked.
3. The winner continues in its own session (resumed by id, same worktree) with the rest of the
   iteration budget; at least ``v8.winner_share`` of the iteration is reserved for it.
4. No LLM writes protocol artifacts: findings, principles, plan and the designer update come from the
   arms' result files and patches on disk.
5. From iteration 2, an iteration whose predecessor improved the best judged score by more than the
   noise runs one ``h-main`` that deepens the incumbent (exploit); a plateau runs the full screening.
   When the incumbent arm left a ``next_step``, the orchestrator writes that bundle without a design call.
6. Any exception in a session marks it failed instead of stopping the campaign; a hung session (no
   reply while only API errors arrive) restarts once in a fresh worktree from its last saved patch.

Every v8 session sees the judge profile (``orchestrator.judge_profile``).
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import yaml

from orchestrator.design_profile import EVALUATOR_DIR, V7Settings, V8Settings, is_v8, v7_settings, v8_settings
from orchestrator.instrument import add_to_handoff, check_instrument
from orchestrator.judge_profile import (
    SUMMARY_FILE, best_official, judge_summary, local_log_path, noise_spread, watch_session,
)
from orchestrator.util import atomic_write
from orchestrator.v7_execute import (
    ARMS_DIR, ASSUMED_ARMS, EVALUATOR_KEY, MIN_SESSION_USD, STATE_FILE, _arm_entry, _git, _load_bundle,
    _load_json, _passed, _save_state, _valid, arm_score, fill_missing_artifacts, iteration_spent,
    mark_iteration_start, mechanism_arms, pick_winner, record_screened_arms, save_worktree_diff,
    session_context,
)

logger = logging.getLogger(__name__)

BASELINE_PATCH = "baseline.patch"
MAX_HANG_RESTARTS = 1
WINNER_LABEL = "winner"
EXPLOIT, EXPLORE = "exploit", "explore"


# ─── budget ──────────────────────────────────────────────────────────────────────────────────

def winner_reserve(s: V7Settings, s8: V8Settings) -> float:
    """What screening must leave for the winner's continuation."""
    return max(s.winner_min_usd, s8.winner_share * s.iteration_budget_usd)


def v8_screening_cap(s: V7Settings, s8: V8Settings, remaining: float, sessions_left: int) -> float:
    share = (remaining - winner_reserve(s, s8)) / max(1, sessions_left)
    return round(max(MIN_SESSION_USD, min(s.arm_budget_usd, share)), 2)


# ─── best judged score and the exploit / explore decision ────────────────────────────────────

def _best_found_score(work_dir: Path) -> float | None:
    try:
        top = (json.loads((Path(work_dir) / "best_found.json").read_text()).get("top_k") or [])[0]
        return float(top.get("score"))
    except (OSError, ValueError, IndexError, AttributeError, TypeError):
        return None


def best_judged(campaign: dict, work_dir: Path, extra=()) -> float | None:
    vals = [v for v in (best_official(campaign, work_dir), _best_found_score(work_dir), *extra) if v is not None]
    return max(vals) if vals else None


def _state(iter_dir: Path) -> dict:
    state = _load_json(Path(iter_dir) / ARMS_DIR / STATE_FILE, {})
    state.setdefault("sessions", {})
    return state


def _iter_dir(work_dir: Path, iteration: int) -> Path:
    return Path(work_dir) / "runs" / f"iter-{iteration}"


def decide_mode(campaign: dict, work_dir: Path, iteration: int) -> dict:
    """``{"mode": "exploit"|"explore", "reason": ...}`` for this iteration, decided once and saved."""
    it = _iter_dir(work_dir, iteration)
    state = _state(it)
    if isinstance(state.get("mode"), dict):
        return state["mode"]
    mode = {"mode": EXPLORE, "reason": "first iteration: screen competing families"}
    if iteration >= 2:
        prev = _state(_iter_dir(work_dir, iteration - 1))
        before, after = prev.get("best_before"), prev.get("best_after")
        noise = noise_spread(campaign, work_dir)
        from orchestrator.design_profile import V8_NOISE_UNKNOWN
        thr = noise if noise is not None else V8_NOISE_UNKNOWN
        if before is None or after is None:
            mode = {"mode": EXPLORE, "reason": "no measured progress for the previous iteration"}
        elif after - before > thr:
            mode = {"mode": EXPLOIT, "gain": round(after - before, 4), "threshold": thr,
                    "reason": f"iteration {iteration - 1} improved the best judged score from {before} to "
                              f"{after} (more than the noise {thr})"}
        else:
            mode = {"mode": EXPLORE, "gain": round(after - before, 4), "threshold": thr,
                    "reason": f"plateau: iteration {iteration - 1} moved the best judged score from {before} "
                              f"to {after} (not more than the noise {thr})"}
    state["mode"] = mode
    (it / ARMS_DIR).mkdir(parents=True, exist_ok=True)
    _save_state(it / ARMS_DIR, state)
    return mode


def _previous_winner(work_dir: Path, iteration: int) -> tuple[str, dict, dict] | None:
    """(key, bundle arm, result) of the previous iteration's winner, when it left a result file."""
    prev = _iter_dir(work_dir, iteration - 1)
    key = (_state(prev).get("winner") or {}).get("key")
    if not key:
        return None
    result = _load_json(prev / ARMS_DIR / key / "result.json", None)
    if not isinstance(result, dict):
        return None
    return key, dict(mechanism_arms(_load_bundle(prev))).get(key, {}), result


def v8_design_note(campaign: dict, work_dir: Path, iteration: int | None) -> str:
    """DESIGN context for v8: the judge profile and, in an exploit iteration, the single-arm rule."""
    if not is_v8(campaign):
        return ""
    parts = ["", "", judge_summary(campaign, work_dir).rstrip()]
    if iteration:
        mode = decide_mode(campaign, work_dir, iteration)
        if mode["mode"] == EXPLOIT:
            parts += ["", "## Exploit iteration (v8)", "",
                      f"{mode['reason']}. Write a single `h-main` arm that deepens the incumbent (same "
                      "mechanism family, a concrete next change), no `h-alternative` arms, and set "
                      "`single_family_reason` to say the incumbent is still improving."]
    return "\n".join(parts) + "\n"


def maybe_write_exploit_bundle(campaign: dict, work_dir: Path, iter_dir: Path, iteration: int) -> bool:
    """Exploit iteration whose incumbent arm named a next step: write the design without an LLM call."""
    if not is_v8(campaign) or iteration < 2:
        return False
    mode = decide_mode(campaign, work_dir, iteration)
    if (Path(iter_dir) / "bundle.yaml").exists():
        return bool(mode.get("bundle_by_orchestrator"))  # a resumed run keeps the written design
    if mode["mode"] != EXPLOIT:
        return False
    prev = _previous_winner(work_dir, iteration)
    step = str((prev[2].get("next_step") if prev else "") or "").strip()
    if not step:
        return False
    key, arm, result = prev
    family = str(result.get("mechanism_family") or arm.get("mechanism_family") or key)
    score = arm_score(result, campaign)
    iter_dir, prev_dir = Path(iter_dir), _iter_dir(work_dir, iteration - 1)
    iter_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "metadata": {"iteration": iteration, "family": family,
                     "research_question": str(campaign.get("research_question") or "Improve the score")},
        "single_family_reason": (f"v8 exploit: the incumbent {family} ({key}) improved the best judged score "
                                 "last iteration, so this iteration deepens it."),
        "arms": [{
            "type": "h-main", "mechanism_family": family,
            "prediction": f"The next step raises the score above {score} by more than the noise.",
            "mechanism": step,
            "diagnostic": "If it does not improve, the family has plateaued: screen competing families next.",
            "validity_check": str(arm.get("validity_check") or "The output is valid on a tiny case."),
        }],
    }
    atomic_write(iter_dir / "bundle.yaml", yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True))
    for name, sources in (("problem.md", [prev_dir / "problem.md"]),
                          ("handoff_snapshot.md", [Path(work_dir) / "handoff.md", prev_dir / "handoff_snapshot.md"])):
        src = next((p for p in sources if p.is_file()), None)
        if src is not None:
            shutil.copyfile(src, iter_dir / name)
        else:
            atomic_write(iter_dir / name, f"# {name}\n\nv8 exploit iteration {iteration}: {step}\n")
    state = _state(iter_dir)
    state["mode"] = {**mode, "bundle_by_orchestrator": True}
    _save_state(iter_dir / ARMS_DIR, state)
    logger.info("v8: exploit iteration %d written without a design call (next step of %s)", iteration, key)
    print(f"  v8 exploit: deepening `{key}` ({family}) with its next step; no design call")
    return True


# ─── session context ─────────────────────────────────────────────────────────────────────────

def _notes(state: dict) -> dict:
    return state.setdefault("notes", {})


def screening_lines(campaign: dict, iter_dir: Path) -> str:
    adir = Path(iter_dir) / ARMS_DIR
    lines = ["Screening results:"]
    for key, arm in mechanism_arms(_load_bundle(iter_dir)):
        r = _load_json(adir / key / "result.json", None)
        if r is None:
            lines.append(f"- `{key}` ({arm.get('mechanism_family', '?')}): no result file")
            continue
        lines.append(f"- `{key}` ({r.get('mechanism_family') or arm.get('mechanism_family', '?')}): score "
                     f"{arm_score(r, campaign)}, validity {'failed' if not _valid(r) else 'passed'}")
    return "\n".join(lines)


def v8_session_context(campaign: dict, work_dir: Path, iteration: int, key: str | None, phase: str,
                       budget_usd: float | None = None) -> dict[str, str]:
    """Prompt placeholders for the v8 templates (build_evaluator_v8, execute_arm_v8, continue_arm, repair_arm)."""
    work_dir = Path(work_dir)
    is_eval = phase == "build-evaluator-v8"
    ctx = session_context(campaign, work_dir, iteration, EVALUATOR_KEY if is_eval else key, budget_usd)
    iter_dir = _iter_dir(work_dir, iteration).resolve()
    state = _state(iter_dir)
    note = _notes(state).get(EVALUATOR_KEY if is_eval else str(key)) or ""
    ctx.update({
        "judge_profile": judge_summary(campaign, work_dir),
        "judge_profile_path": str(work_dir.resolve() / SUMMARY_FILE),
        "session_note": f"\n{note}\n" if note else "",
        "local_log": str(local_log_path(work_dir.resolve())),
        "baseline_patch": str(iter_dir / "patches" / BASELINE_PATCH),
        "assumed_time_limit_s": f"{v8_settings(campaign).assumed_time_limit_s:g}",
    })
    if phase == "continue-arm":
        ctx["screening_results"] = screening_lines(campaign, iter_dir)
    if phase == "repair-arm":
        ctx["repair_reason"] = (state["sessions"].get(str(key)) or {}).get("repair_reason") or "a failure"
    return ctx


# ─── sessions ────────────────────────────────────────────────────────────────────────────────

def _repair_reason(outcome: str, result: dict | None, campaign: dict) -> str | None:
    """Why a screened arm needs its one repair turn, or None."""
    if outcome == "failed":
        return "the session crashed or failed"
    if not isinstance(result, dict):
        return "no result file was written (a crash or an early stop)"
    if not _valid(result):
        detail = (result.get("validity_check") or {}).get("detail")
        return f"its validity check failed ({detail or 'no detail'})"
    score = arm_score(result, campaign)
    if score is None:
        return "the result reports no score"
    if score == 0:
        return "the official judge scored it 0 (a crash, invalid output, or a timeout)"
    return None


def _ensure_patch(worktree: Path, patch: Path, base: str, extras) -> None:
    """Keep the session's own patch; if it wrote none, save the worktree's full change (new files too)."""
    if patch.is_file() and patch.stat().st_size > 0:
        return
    save_worktree_diff(worktree, base, patch, exclude=extras or [])
    if patch.is_file() and not patch.read_text().strip():
        patch.unlink()


def _fresh_worktree_from_patch(repo: Path, iteration: int, patch: Path, extras) -> tuple[Path, str]:
    from orchestrator.worktree import create_experiment_worktree
    wt, eid = create_experiment_worktree(repo, iteration, extras=extras or [])
    if patch.is_file() and patch.stat().st_size > 0:
        if _git(wt, "apply", str(patch.resolve())).returncode != 0:
            logger.warning("v8: could not apply %s after a hang; the restart begins from the incumbent", patch)
    return wt, eid


def _dispatch(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int, repo: Path,
              state: dict, key: str, phase: str, *, label: str, target: float, hard: float,
              resume: str | None, extras, patch: Path) -> str:
    """One v8 session with hang recovery; ``"done"`` or ``"failed"``. Never raises an ``Exception``.

    Updates ``state["sessions"][key]`` (worktree, session id) so a crash can resume.
    """
    from orchestrator.sdk_dispatch import SDKHangError
    from orchestrator.worktree import _EXPERIMENTS_DIRNAME, remove_experiment_worktree
    adir = Path(iter_dir) / ARMS_DIR
    rec = state["sessions"][key]
    log = adir / key / f"{label}_log.md"
    spent0 = iteration_spent(campaign, work_dir, iter_dir)
    restarts = 0
    while True:
        wt = Path(repo) / _EXPERIMENTS_DIRNAME / rec["experiment_id"]
        left = round(hard - (iteration_spent(campaign, work_dir, iter_dir) - spent0), 2)
        if left < MIN_SESSION_USD and restarts:
            return "failed"
        dispatcher.last_session_id = None
        try:
            with watch_session(campaign, work_dir, label), dispatcher.override_cwd(wt), \
                    dispatcher.session_budget(left, label=label, target_usd=min(target, left)), \
                    dispatcher.resume_session(resume):
                dispatcher.dispatch("executor", phase, output_path=log, iteration=iteration, perspective=key)
            if dispatcher.last_session_id:
                rec["session_id"] = dispatcher.last_session_id
            _notes(state).pop(key, None)
            _save_state(adir, state)
            return "done"
        except SDKHangError as exc:
            restarts += 1
            logger.warning("v8 session %s (%s) hung: %s", key, label, exc)
            if restarts > MAX_HANG_RESTARTS:
                return "failed"
            # Restart from the last saved patch in a fresh worktree and a fresh session.
            old = rec["experiment_id"]
            new_wt, new_eid = _fresh_worktree_from_patch(repo, iteration, patch, extras)
            remove_experiment_worktree(repo, old)
            rec.update({"experiment_id": new_eid, "base": _git(new_wt, "rev-parse", "HEAD").stdout.strip(),
                        "hang_restarts": restarts, "session_id": None})
            _notes(state)[key] = ("Note: your previous session hung on API timeouts and was restarted. Your "
                                  "worktree holds your last saved patch; check the files you wrote and "
                                  "continue from them.")
            _save_state(adir, state)
            resume = None
        except Exception as exc:  # noqa: BLE001 - one failed session must not stop the campaign
            logger.warning("v8 session %s (%s) failed: %s", key, label, exc)
            if dispatcher.last_session_id:
                rec["session_id"] = dispatcher.last_session_id
            _save_state(adir, state)
            return "failed"


def _start_session(repo: Path, iteration: int, state: dict, key: str, cap: float, extras) -> Path:
    from orchestrator.worktree import create_experiment_worktree, remove_experiment_worktree
    rec = state["sessions"].get(key) or {}
    if rec.get("experiment_id"):  # interrupted earlier: start this session over
        remove_experiment_worktree(repo, rec["experiment_id"])
    wt, eid = create_experiment_worktree(repo, iteration, extras=extras or [])
    state["sessions"][key] = {"status": "running", "experiment_id": eid, "budget_usd": cap,
                              "base": _git(wt, "rev-parse", "HEAD").stdout.strip()}
    return wt


def commit_baseline(repo: Path, patch: Path, state: dict) -> bool:
    """Commit the evaluator's measured baseline to the target so every arm starts from it (once)."""
    if state.get("baseline") or not (patch.is_file() and patch.stat().st_size > 0):
        return False
    ok = _git(repo, "apply", "--check", str(patch.resolve())).returncode == 0
    if ok:
        ok = _git(repo, "apply", "--index", str(patch.resolve())).returncode == 0
    if ok:
        res = _git(repo, "-c", "user.email=nous@local", "-c", "user.name=nous", "-c", "commit.gpgsign=false",
                   "commit", "-q", "--no-verify", "-m", "nous v8: measured baseline from the evaluator session")
        ok = res.returncode == 0
        if not ok:
            _git(repo, "apply", "-R", "--index", str(patch.resolve()))
    state["baseline"] = {"patch": str(patch), "committed": ok}
    (logger.info if ok else logger.warning)("v8: baseline %s %s", patch, "committed" if ok else "did not apply")
    return ok


def _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, cap, extras) -> None:
    from orchestrator.worktree import remove_experiment_worktree
    adir = Path(iter_dir) / ARMS_DIR
    _start_session(repo, iteration, state, EVALUATOR_KEY, cap, extras)
    _save_state(adir, state)
    hard = round(cap * 2.0, 2)
    print(f"  v8 build-evaluator (target ${cap:.2f}, hard cap ${hard:.2f})")
    patch = Path(iter_dir) / "patches" / BASELINE_PATCH
    outcome = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, EVALUATOR_KEY,
                        "build-evaluator-v8", label=EVALUATOR_KEY, target=cap, hard=hard, resume=None,
                        extras=extras, patch=patch)
    rec = state["sessions"][EVALUATOR_KEY]
    remove_experiment_worktree(repo, rec["experiment_id"])
    state["sessions"][EVALUATOR_KEY] = {"status": "done", "outcome": outcome, "budget_usd": cap,
                                        "instrument": check_instrument(iter_dir)}
    commit_baseline(repo, patch, state)
    _save_state(adir, state)
    add_to_handoff(campaign, work_dir, iter_dir, iteration)


def run_v8_evaluator(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int,
                     repo_path, *, extras=None) -> None:
    """Pre-design evaluator session (iteration 1), as in v7 but with the v8 prompt and baseline."""
    from orchestrator.v7_execute import evaluator_before_design
    work_dir, iter_dir = Path(work_dir), Path(iter_dir)
    if not evaluator_before_design(campaign, work_dir, iter_dir):
        return
    s, s8 = v7_settings(campaign), v8_settings(campaign)
    (iter_dir / ARMS_DIR).mkdir(parents=True, exist_ok=True)
    (iter_dir / "patches").mkdir(parents=True, exist_ok=True)
    mark_iteration_start(campaign, work_dir, iter_dir)
    state = _state(iter_dir)
    left = s.iteration_budget_usd - iteration_spent(campaign, work_dir, iter_dir) - s.design_budget_usd
    cap = v8_screening_cap(s, s8, left, 1 + ASSUMED_ARMS)
    _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, Path(repo_path), state, cap, extras)


def _screen(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, cap, extras,
            remaining) -> None:
    """Screen one arm in a fresh worktree (kept for the winner), then its one repair turn if needed."""
    adir = Path(iter_dir) / ARMS_DIR
    s8 = v8_settings(campaign)
    _start_session(repo, iteration, state, key, cap, extras)
    _save_state(adir, state)
    hard = round(cap * 2.0, 2)
    patch = Path(iter_dir) / "patches" / f"{key}.patch"
    print(f"  v8 execute-arm `{key}` (target ${cap:.2f}, hard cap ${hard:.2f})")
    outcome = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, "execute-arm-v8",
                        label=key, target=cap, hard=hard, resume=None, extras=extras, patch=patch)
    rec = state["sessions"][key]
    from orchestrator.worktree import _EXPERIMENTS_DIRNAME
    wt = Path(repo) / _EXPERIMENTS_DIRNAME / rec["experiment_id"]
    _ensure_patch(wt, patch, rec.get("base") or "HEAD", extras)
    rec["outcome"] = outcome
    reason = _repair_reason(outcome, _load_json(adir / key / "result.json", None), campaign)
    s = v7_settings(campaign)
    if reason and not rec.get("repaired") and s8.repair_budget_usd > 0 \
            and remaining() - s8.repair_budget_usd >= winner_reserve(s, s8):
        rec.update({"repaired": True, "repair_reason": reason})
        _save_state(adir, state)
        print(f"  v8 repair `{key}` ({reason}; ${s8.repair_budget_usd:.2f})")
        rec["repair_outcome"] = _dispatch(
            dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, "repair-arm",
            label=f"{key}-repair", target=s8.repair_budget_usd, hard=s8.repair_budget_usd,
            resume=rec.get("session_id"), extras=extras, patch=patch)
        wt = Path(repo) / _EXPERIMENTS_DIRNAME / rec["experiment_id"]
        _ensure_patch(wt, patch, rec.get("base") or "HEAD", extras)
    rec["status"] = "done"
    _save_state(adir, state)


# ─── orchestrator-written artifacts ──────────────────────────────────────────────────────────

def _handoff_update(campaign: dict, iter_dir: Path, winner: str, result: dict | None) -> str:
    lines = ["# Executor update (v8, written by the orchestrator)", "",
             f"Winner: `{winner}`, score {arm_score(result, campaign)}; patch `patches/{winner}.patch`.", "",
             screening_lines(campaign, iter_dir), ""]
    if isinstance(result, dict):
        if result.get("observed"):
            lines += [f"Observed: {result['observed']}", ""]
        groups = [g for g in result.get("per_group") or [] if isinstance(g, dict)]
        if groups:
            lines.append("Per size group (lowest mean score first):")
            for g in sorted(groups, key=lambda g: g.get("mean_score") if isinstance(g.get("mean_score"),
                                                                                    (int, float)) else 0):
                lines.append(f"- {g.get('group')}: n={g.get('n')}, mean {g.get('mean_score')}, max CPU "
                             f"{g.get('max_cpu_s')} s, timeouts {g.get('timeouts')}")
            lines.append("")
        if result.get("next_step"):
            lines += [f"Next step: {result['next_step']}", ""]
    return "\n".join(lines)


def write_artifacts(campaign: dict, iter_dir: Path, iteration: int, winner: str) -> None:
    """findings.json, principle_updates.json, experiment_plan.yaml and handoff_update.md from disk."""
    iter_dir = Path(iter_dir)
    adir = iter_dir / ARMS_DIR
    arm = dict(mechanism_arms(_load_bundle(iter_dir))).get(winner, {})
    result = _load_json(adir / winner / "result.json", None)
    if not (iter_dir / "findings.json").exists():
        if isinstance(result, dict):
            entry = _arm_entry(winner, arm, result, campaign)
            entry["diagnostic_note"] = (f"Won the v8 screening and continued in its own session; result in "
                                        f"arms/{winner}/result.json")
        else:
            entry = {"arm_type": arm.get("type", "h-main"),
                     "predicted": str(arm.get("prediction") or "(not stated)"),
                     "observed": "no result file", "status": "REFUTED", "error_type": None,
                     "diagnostic_note": "The winning arm wrote no result file.",
                     "metadata": {"candidate_id": winner, "screening": True}}
        findings = {"iteration": iteration, "bundle_ref": "bundle.yaml", "arms": [entry],
                    "experiment_valid": _passed(result),
                    "discrepancy_analysis": ("Written by the orchestrator from the arms' result files (v8); "
                                             "no LLM wrap-up.")}
        atomic_write(iter_dir / "findings.json", json.dumps(findings, indent=2) + "\n")
    if not (iter_dir / "principle_updates.json").exists():
        atomic_write(iter_dir / "principle_updates.json", "[]\n")
    record_screened_arms(campaign, iter_dir, iteration)
    fill_missing_artifacts(iter_dir, iteration, "v8 screening and winner continuation (written by the orchestrator)")
    upd = iter_dir / "handoff_update.md"
    if not (upd.is_file() and upd.read_text().strip()):
        atomic_write(upd, _handoff_update(campaign, iter_dir, winner, result))


# ─── EXECUTE ─────────────────────────────────────────────────────────────────────────────────

def run_v8_execute(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int,
                   repo_path, *, extras=None) -> tuple[Path, str]:
    """Screen (with repairs), continue the winner in its own session, write the artifacts.

    Returns the winner's (worktree, experiment_id) for the caller to clean up.
    """
    from orchestrator.worktree import _EXPERIMENTS_DIRNAME, remove_experiment_worktree
    work_dir, iter_dir, repo = Path(work_dir), Path(iter_dir), Path(repo_path)
    s, s8 = v7_settings(campaign), v8_settings(campaign)
    adir = iter_dir / ARMS_DIR
    adir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "patches").mkdir(parents=True, exist_ok=True)
    mark_iteration_start(campaign, work_dir, iter_dir)
    state = _state(iter_dir)
    arms = mechanism_arms(_load_bundle(iter_dir))
    if not arms:
        raise RuntimeError(f"v8 EXECUTE: {iter_dir / 'bundle.yaml'} has no h-main or h-alternative arm")
    if state.get("best_before") is None:
        state["best_before"] = best_judged(campaign, work_dir)
        _save_state(adir, state)

    def remaining() -> float:
        return s.iteration_budget_usd - iteration_spent(campaign, work_dir, iter_dir)

    add_to_handoff(campaign, work_dir, iter_dir, iteration)  # the designer rewrote the handoff
    ev = state["sessions"].get(EVALUATOR_KEY) or {}
    need_eval = ev.get("status") != "done" and (ev.get("status") == "running"
                                                or not (work_dir / EVALUATOR_DIR / "README.md").is_file())
    todo = [k for k, _ in arms if (state["sessions"].get(k) or {}).get("status") != "done"]
    if need_eval:
        cap = v8_screening_cap(s, s8, remaining(), len(todo) + 1)
        _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, cap, extras)
    for key, _arm in arms:
        if (state["sessions"].get(key) or {}).get("status") == "done":
            continue
        cap = v8_screening_cap(s, s8, remaining(), len(todo))
        todo.remove(key)
        _screen(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, cap, extras, remaining)

    results = {k: _load_json(adir / k / "result.json", None) for k, _ in arms}
    win = state.get("winner") or {}
    if not win.get("key"):
        key = pick_winner(arms, results, campaign)
        if key is None:
            key = arms[0][0]
            logger.warning("v8: no screened arm reported a passing validity check; continuing %s", key)
        win = {"key": key, "score": arm_score(results.get(key), campaign)}
        state["winner"] = win
        _save_state(adir, state)
    key = win["key"]
    for k, _ in arms:  # losers' patches are saved; only the winner's worktree is kept
        rec = state["sessions"].get(k) or {}
        if k != key and rec.get("experiment_id") and not rec.get("removed"):
            remove_experiment_worktree(repo, rec["experiment_id"])
            rec["removed"] = True
    _save_state(adir, state)

    rec = state["sessions"].setdefault(key, {})
    patch = iter_dir / "patches" / f"{key}.patch"
    wt = repo / _EXPERIMENTS_DIRNAME / str(rec.get("experiment_id") or "")
    if not rec.get("experiment_id") or not wt.is_dir():
        wt, eid = _fresh_worktree_from_patch(repo, iteration, patch, extras)
        rec.update({"experiment_id": eid, "base": _git(wt, "rev-parse", "HEAD").stdout.strip(),
                    "session_id": None})
        _save_state(adir, state)
    eid = rec["experiment_id"]
    (iter_dir / ".experiment_id").write_text(eid)

    if win.get("status") != "done":
        cap = round(max(s.winner_min_usd, remaining()), 2) if not win.get("attempts") else round(
            max(0.0, remaining()), 2)
        if (iter_dir / "findings.json").exists():
            pass  # artifacts were written before a crash kept `done` from being saved
        elif win.get("attempts") and cap < MIN_SESSION_USD:
            print(f"  v8 winner `{key}`: the iteration budget is spent; recording what exists")
        else:
            win["attempts"] = int(win.get("attempts") or 0) + 1
            _save_state(adir, state)
            print(f"  v8 winner `{key}` (score {win.get('score')}) continues its session with ${cap:.2f}")
            win["outcome"] = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key,
                                       "continue-arm", label=WINNER_LABEL, target=cap, hard=cap,
                                       resume=rec.get("session_id"), extras=extras, patch=patch)
            rec = state["sessions"][key]
            eid = rec["experiment_id"]
            wt = repo / _EXPERIMENTS_DIRNAME / eid
            (iter_dir / ".experiment_id").write_text(eid)
            _ensure_patch(wt, patch, rec.get("base") or "HEAD", extras)
        write_artifacts(campaign, iter_dir, iteration, key)
        final = _load_json(adir / key / "result.json", None)
        scores = [arm_score(r, campaign) for k, r in
                  [(k, _load_json(adir / k / "result.json", None)) for k, _ in arms] if _passed(r)]
        state["best_after"] = best_judged(campaign, work_dir, [v for v in scores if v is not None])
        win.update({"status": "done", "score": arm_score(final, campaign)})
        _save_state(adir, state)
    record_screened_arms(campaign, iter_dir, iteration)
    return wt, eid


def run_v8_design(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int) -> None:
    """The capped DESIGN session; a hang restarts it once in a fresh session on what is left of its cap.

    The designer writes its files straight to the iteration directory, so a fresh session continues
    from them. Other errors propagate as before (the iteration cannot go on without a design).
    """
    from orchestrator.sdk_dispatch import SDKHangError
    cap = v7_settings(campaign).design_budget_usd
    spent0 = iteration_spent(campaign, work_dir, iter_dir)
    for attempt in range(1 + MAX_HANG_RESTARTS):
        left = round(cap - (iteration_spent(campaign, work_dir, iter_dir) - spent0), 2)
        try:
            with watch_session(campaign, work_dir, "design"), dispatcher.session_budget(left, label="design"):
                dispatcher.dispatch("planner", "design", output_path=Path(iter_dir) / "design_log.md",
                                    iteration=iteration)
            return
        except SDKHangError as exc:
            logger.warning("v8 design session hung (attempt %d): %s", attempt + 1, exc)
            if attempt >= MAX_HANG_RESTARTS or left < MIN_SESSION_USD:
                raise
