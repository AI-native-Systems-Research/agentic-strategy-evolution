"""EXECUTE for ``design_profile: v8``: v7 screening, then the winner keeps its own session.

Differences from v7 (``orchestrator.v7_execute``, whose helpers this module reuses):

1. The evaluator session only gets an official score: when the seed scores 0 it writes the simplest
   valid solution (``patches/baseline.patch``), which is committed to the target so arms start from it.
   The orchestrator then measures that baseline officially 3 times and writes ``instrument.json``.
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
7. Bundles have ``h-main`` and at most one ``h-alternative``; every screening target is at least
   ``v8.arm_floor_usd``, and an arm the iteration cannot fund at that floor is skipped, not starved.
8. A session that ends without a scored ``result.json`` gets one written by the orchestrator from the
   official measures in its time window, with the best measured solution as its patch
   (``orchestrator.official_measure``). The repair turn runs only when no official score > 0 exists.

Every v8 session sees the judge profile (``orchestrator.judge_profile``).
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

import yaml

from orchestrator.design_profile import EVALUATOR_DIR, V7Settings, V8Settings, is_v8, v7_settings, v8_settings
from orchestrator.instrument import INSTRUMENT_FILE, add_to_handoff, check_instrument
from orchestrator.judge_profile import (
    SUMMARY_FILE, best_official, judge_summary, local_log_path, noise_spread, stated_time_limit, watch_session,
)
from orchestrator.official_measure import measure_command, recover_result, run_measure
from orchestrator.util import atomic_write
from orchestrator.v7_execute import (
    ARMS_DIR, EVALUATOR_KEY, MIN_SESSION_USD, STATE_FILE, _arm_entry, _git, _load_bundle,
    _load_json, _passed, _save_state, _valid, arm_score, fill_missing_artifacts, iteration_spent,
    mark_iteration_start, mechanism_arms, pick_winner, record_screened_arms, save_worktree_diff,
    session_context,
)

logger = logging.getLogger(__name__)

BASELINE_PATCH = "baseline.patch"
CAP_OVERSHOOT_USD = 1.0  # a cap stops after the reply that crosses it
MAX_HANG_RESTARTS = 1
NOISE_RUNS = 3  # official measures of the baseline that the orchestrator takes for instrument.json
MAX_NOISE_ATTEMPTS = NOISE_RUNS + 2
SKIPPED = "skipped"
# Live p58: with no scored solution, sessions tried to prove a construction correct in their thinking
# until the 64k output limit cut the reply; replies that ended in writing something did not get cut.
ACT_FIRST_NOTE = (
    "No solution has an official score above 0 yet. Act before analysing: first write the simplest "
    "correct solution (and, if it is cheap, a brute-force checker for small cases), run it, and measure "
    "it officially. Check ideas by running code, not by tracing cases in your head. Improve after that."
)
WINNER_LABEL = "winner"
EXPLOIT, EXPLORE = "exploit", "explore"


# ─── budget ──────────────────────────────────────────────────────────────────────────────────

def winner_reserve(s: V7Settings, s8: V8Settings) -> float:
    """What screening must leave for the winner's continuation."""
    return max(s.winner_min_usd, s8.winner_share * s.iteration_budget_usd)


def v8_screening_cap(s: V7Settings, s8: V8Settings, remaining: float, sessions_left: int) -> float:
    """Target for the next screening session: its share above the winner's reserve, never below the floor."""
    share = (remaining - winner_reserve(s, s8)) / max(1, sessions_left)
    return round(max(MIN_SESSION_USD, s8.arm_floor_usd, min(s.arm_budget_usd, share)), 2)


def screening_hard_cap(s: V7Settings, s8: V8Settings, cap: float, remaining: float, waiting: int) -> float:
    """Hard stop for a screening arm: whatever is above the winner's reserve and the floor of each arm still
    waiting. A cap trips after the reply that crosses it, so a margin covers that overshoot
    (live p5: $0.30 over left $3.86, under the $4 floor, and the second family was skipped). The arm's own
    repair turn is set aside too (live p26/p0/p58: a $1.11 repair left $0.26 too little for the second family)."""
    room = (remaining - winner_reserve(s, s8) - waiting * (s8.arm_floor_usd + CAP_OVERSHOOT_USD)
            - (s8.repair_budget_usd + CAP_OVERSHOOT_USD if s8.repair_budget_usd > 0 else 0.0))
    # The target stays the arm's share; the hard stop is everything the reserves do not need. Live p5 s1:
    # arms stopped at 2x a $4 target ran 2-7 turns and never got past a first version; v7 arms (whose caps
    # undercounted) ran 15+ turns.
    return round(max(min(cap, s8.arm_floor_usd), room), 2)


def repair_funded(s: V7Settings, s8: V8Settings, remaining: float, waiting: int) -> bool:
    """True when a repair turn still leaves the winner's reserve and every waiting arm its floor."""
    return (s8.repair_budget_usd > 0 and remaining - s8.repair_budget_usd - CAP_OVERSHOOT_USD
            >= winner_reserve(s, s8) + waiting * s8.arm_floor_usd - 1e-9)


def arm_funded(s: V7Settings, s8: V8Settings, remaining: float) -> bool:
    """True when what is left above the winner's reserve still funds one arm at the floor."""
    return remaining - winner_reserve(s, s8) >= s8.arm_floor_usd - 1e-9


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


def close_open_windows(state: dict, now: float | None = None) -> bool:
    """End the time windows a killed run left open, so later measures are not credited to that session.

    Sessions run one at a time, so nothing ran between the kill and this resume.
    """
    now = time.time() if now is None else now
    changed = False
    for rec in state.get("sessions", {}).values():
        for w in (rec or {}).get("windows") or []:
            if isinstance(w, dict) and w.get("end") is None:
                w["end"], w["closed_on_resume"] = now, True
                changed = True
    return changed


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
        thr = max(noise, V8_NOISE_UNKNOWN) if noise is not None else V8_NOISE_UNKNOWN
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
    sessions = _state(iter_dir)["sessions"]
    lines = ["Screening results:"]
    for key, arm in mechanism_arms(_load_bundle(iter_dir)):
        r = _load_json(adir / key / "result.json", None)
        if (sessions.get(key) or {}).get("outcome") == SKIPPED:
            lines.append(f"- `{key}` ({arm.get('mechanism_family', '?')}): skipped, "
                         f"{sessions[key].get('skip_reason') or 'not funded'}")
            continue
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
    if (best_official(campaign, work_dir) or 0.0) <= 0 and phase in ("build-evaluator-v8", "execute-arm-v8"):
        note = (note + "\n" if note else "") + ACT_FIRST_NOTE
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
        # The session's time window: official measures inside it belong to this arm (result recovery).
        window = {"label": label, "start": time.time(), "end": None}
        rec.setdefault("windows", []).append(window)
        _save_state(adir, state)
        try:
            try:
                with watch_session(campaign, work_dir, label), dispatcher.override_cwd(wt), \
                        dispatcher.session_budget(left, label=label, target_usd=min(target, left)), \
                        dispatcher.resume_session(resume):
                    dispatcher.dispatch("executor", phase, output_path=log, iteration=iteration,
                                        perspective=key)
            finally:
                window["end"] = time.time()
                _save_state(adir, state)
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
            # Restart from the session's current work in a fresh worktree and a fresh session.
            old = rec["experiment_id"]
            if wt.is_dir():  # keep the session's latest edits, but never replace a saved patch with nothing
                tmp = patch.with_name(patch.name + ".hang")
                save_worktree_diff(wt, rec.get("base") or "HEAD", tmp, exclude=extras or [])
                if tmp.is_file() and tmp.read_text().strip():
                    tmp.replace(patch)
                tmp.unlink(missing_ok=True)
            new_wt, new_eid = _fresh_worktree_from_patch(repo, iteration, patch, extras)
            remove_experiment_worktree(repo, old)
            rec.update({"experiment_id": new_eid, "base": _git(new_wt, "rev-parse", "HEAD").stdout.strip(),
                        "hang_restarts": restarts, "session_id": None})
            cut = sorted((Path(work_dir) / "cut_reasoning").glob(f"{label}-*.md"))
            _notes(state)[key] = ("Note: your previous session hung on API timeouts and was restarted. Your "
                                  "worktree holds your last saved patch; check the files you wrote and "
                                  "continue from them."
                                  + (f" Your last cut reasoning is saved in `{cut[-1]}`: read its end and act on "
                                     "it rather than re-deriving." if cut else ""))
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
    if rec.get("windows"):  # an interrupted attempt's official measures still count for this arm
        state["sessions"][key]["windows"] = rec["windows"]
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


def _write_evaluator_readme(campaign: dict, work_dir: Path, runs: list[float]) -> None:
    """A short evaluator README when the session left none, so later iterations do not rebuild it."""
    readme = Path(work_dir) / EVALUATOR_DIR / "README.md"
    if readme.is_file() and readme.read_text().strip():
        return
    limit = stated_time_limit(campaign)
    lines = ["# Evaluator (v8, written by the orchestrator)", "",
             "No local evaluator was kept. Decide on the official measure command:", "",
             f"`{measure_command(campaign) or '(none found in the campaign)'}`", "",
             f"Time limit from the statement: {f'{limit:g} s' if limit else 'none given'}."]
    if runs:
        lines += ["", f"Baseline (what every arm starts from), {len(runs)} official measures: "
                      + ", ".join(f"{r:g}" for r in runs) + "."]
    else:
        lines += ["", "The orchestrator could not measure the baseline officially."]
    readme.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(readme, "\n".join(lines) + "\n")


def write_orchestrator_instrument(campaign: dict, work_dir: Path, iter_dir: Path, iteration: int, repo: Path,
                                  state: dict, extras) -> str:
    """Measure the committed baseline officially ``NOISE_RUNS`` times and write ``instrument.json``.

    Zero LLM tokens. Each measure is saved in the state as it finishes, so a crash resumes the count.
    """
    from orchestrator.worktree import create_experiment_worktree, remove_experiment_worktree
    adir = Path(iter_dir) / ARMS_DIR
    rec = state["sessions"][EVALUATOR_KEY]
    runs = [float(r) for r in rec.get("noise_runs") or []]
    cmd = measure_command(campaign)
    if cmd and len(runs) < NOISE_RUNS and int(rec.get("measure_attempts") or 0) < MAX_NOISE_ATTEMPTS:
        wt, eid = create_experiment_worktree(repo, iteration, extras=extras or [])
        print(f"  v8 orchestrator: {NOISE_RUNS} official measures of the baseline (no LLM)")
        try:
            while len(runs) < NOISE_RUNS and int(rec.get("measure_attempts") or 0) < MAX_NOISE_ATTEMPTS:
                score = run_measure(campaign, wt)
                rec["measure_attempts"] = int(rec.get("measure_attempts") or 0) + 1
                if score is not None:
                    runs.append(score)
                    rec["noise_runs"] = runs
                _save_state(adir, state)
        finally:
            remove_experiment_worktree(repo, eid)
    _write_evaluator_readme(campaign, work_dir, runs)
    if not cmd:
        logger.warning("v8: no official measure command in the campaign; instrument.json not written")
        return "missing: no official measure command"
    if len(runs) < NOISE_RUNS:
        logger.warning("v8: only %d of %d official baseline measures returned a score", len(runs), NOISE_RUNS)
        return f"missing: {len(runs)} of {NOISE_RUNS} official measures returned a score"
    limit = stated_time_limit(campaign)
    noise = {"runs": runs, "min": min(runs), "max": max(runs), "spread": round(max(runs) - min(runs), 6),
             "command": cmd}
    if max(runs) <= 0:  # a 0-score baseline says nothing about the judge's noise
        noise["note"] = "unknown: the baseline scored 0"
    data = {"max_cpu_s": None, "time_limit_s": limit,
            "time_limit_source": "statement" if limit else "none in the statement",
            "speed_first": False,
            "noise": noise,
            "knobs": [], "written_by": "orchestrator"}
    atomic_write(Path(iter_dir) / INSTRUMENT_FILE, json.dumps(data, indent=2) + "\n")
    print(f"  v8 orchestrator: baseline official scores {', '.join(f'{r:g}' for r in runs)}")
    return check_instrument(iter_dir)


def _baseline_from_official(campaign, work_dir, repo, rec, patch, extras) -> None:
    """The baseline is the evaluator's best official measure (> 0), whatever patch it saved.

    Live p0: the evaluator saved a 45.98 version while its best official measure was 63.51; live p5: 26
    saved, 40 measured. The saved patch is kept only when nothing scored above 0.
    """
    from orchestrator.official_measure import _write_best_code, best_measure, measures_in
    from orchestrator.v7_execute import save_worktree_diff
    rows = [r for r in measures_in(campaign, work_dir, rec.get("windows")) if float(r.get("score") or 0) > 0]
    best = best_measure(rows)
    if best is None:
        return
    note = _write_best_code(campaign, best, _worktree(repo, rec), patch, rec.get("base"), extras,
                            save_worktree_diff)
    logger.warning("v8: baseline = the evaluator's best official measure %s. %s", best.get("score"), note)


def _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, extras) -> None:
    """Evaluator session (official score and baseline only), then the orchestrator's instrument checks.

    State ``running`` -> ``measuring`` (session over, baseline committed) -> ``done``; a crash while
    measuring resumes the measures without another session.
    """
    from orchestrator.worktree import remove_experiment_worktree
    adir = Path(iter_dir) / ARMS_DIR
    patch = Path(iter_dir) / "patches" / BASELINE_PATCH
    rec = state["sessions"].get(EVALUATOR_KEY) or {}
    if rec.get("status") != "measuring":
        cap = v8_settings(campaign).evaluator_budget_usd
        spent_before = iteration_spent(campaign, work_dir, iter_dir)
        _start_session(repo, iteration, state, EVALUATOR_KEY, cap, extras)
        _save_state(adir, state)
        hard = round(cap * 2.0, 2)
        print(f"  v8 build-evaluator (target ${cap:.2f}, hard cap ${hard:.2f})")
        outcome = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, EVALUATOR_KEY,
                            "build-evaluator-v8", label=EVALUATOR_KEY, target=cap, hard=hard, resume=None,
                            extras=extras, patch=patch)
        rec = state["sessions"][EVALUATOR_KEY]
        # A session stopped at its cap may leave a written solution without saving its patch (live p26
        # smoke s4: the code was written, the worktree removed, and only the stub was measured).
        _ensure_patch(_worktree(repo, rec), patch, rec.get("base") or "HEAD", extras)
        _baseline_from_official(campaign, work_dir, repo, rec, patch, extras)
        remove_experiment_worktree(repo, rec["experiment_id"])
        commit_baseline(repo, patch, state)
        state["sessions"][EVALUATOR_KEY] = {
            "status": "measuring", "outcome": outcome, "budget_usd": cap, "noise_runs": [],
            "spent_usd": round(iteration_spent(campaign, work_dir, iter_dir) - spent_before, 4)}
        _save_state(adir, state)
    instrument = write_orchestrator_instrument(campaign, work_dir, iter_dir, iteration, repo, state, extras)
    state["sessions"][EVALUATOR_KEY].update({"status": "done", "instrument": instrument})
    _save_state(adir, state)
    add_to_handoff(campaign, work_dir, iter_dir, iteration)


def run_v8_evaluator(dispatcher, campaign: dict, work_dir: Path, iter_dir: Path, iteration: int,
                     repo_path, *, extras=None) -> None:
    """Pre-design evaluator session (iteration 1), as in v7 but with the v8 prompt and baseline."""
    from orchestrator.v7_execute import evaluator_before_design
    work_dir, iter_dir = Path(work_dir), Path(iter_dir)
    if not evaluator_before_design(campaign, work_dir, iter_dir):
        return
    (iter_dir / ARMS_DIR).mkdir(parents=True, exist_ok=True)
    (iter_dir / "patches").mkdir(parents=True, exist_ok=True)
    mark_iteration_start(campaign, work_dir, iter_dir)
    state = _state(iter_dir)
    _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, Path(repo_path), state, extras)


def _worktree(repo: Path, rec: dict) -> Path | None:
    from orchestrator.worktree import _EXPERIMENTS_DIRNAME
    return Path(repo) / _EXPERIMENTS_DIRNAME / rec["experiment_id"] if rec.get("experiment_id") else None


def _recover(campaign, work_dir, iter_dir, repo, state, key, extras, *, stale_before=None) -> float | None:
    """Rebuild a missing or unscored result (and patch) from official measures; the best score or None."""
    rec = state["sessions"].get(key) or {}
    iter_dir = Path(iter_dir)
    try:
        best = recover_result(
            campaign, work_dir, iter_dir / ARMS_DIR / key / "result.json", arm_key=key,
            arm=dict(mechanism_arms(_load_bundle(iter_dir))).get(key, {}), windows=rec.get("windows"),
            worktree=_worktree(repo, rec), patch=iter_dir / "patches" / f"{key}.patch", base=rec.get("base"),
            extras=extras, stale_before=stale_before)
    except Exception as exc:  # noqa: BLE001 - recovery must never stop the campaign
        logger.warning("v8: could not rebuild the result of %s from official measures: %s", key, exc)
        return None
    if best is None:
        return None
    rec["best_official"] = float(best["score"])
    _save_state(iter_dir / ARMS_DIR, state)
    return float(best["score"])


def _screen(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, cap, extras,
            remaining, waiting: int = 0) -> None:
    """Screen one arm in a fresh worktree (kept for the winner), then its one repair turn if needed.

    State ``running`` -> ``ended`` (session over, patch saved) -> ``done``; a crash after the session
    resumes at the result recovery instead of screening again.
    """
    adir = Path(iter_dir) / ARMS_DIR
    s, s8 = v7_settings(campaign), v8_settings(campaign)
    patch = Path(iter_dir) / "patches" / f"{key}.patch"
    if (state["sessions"].get(key) or {}).get("status") != "ended":
        hard = screening_hard_cap(s, s8, cap, remaining(), waiting)
        cap = min(cap, hard)
        _start_session(repo, iteration, state, key, cap, extras)
        _save_state(adir, state)
        print(f"  v8 execute-arm `{key}` (target ${cap:.2f}, hard cap ${hard:.2f})")
        outcome = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key,
                            "execute-arm-v8", label=key, target=cap, hard=hard, resume=None, extras=extras,
                            patch=patch)
        rec = state["sessions"][key]
        _ensure_patch(_worktree(repo, rec), patch, rec.get("base") or "HEAD", extras)
        rec.update({"outcome": outcome, "status": "ended"})
        _save_state(adir, state)
    rec = state["sessions"][key]
    best = _recover(campaign, work_dir, iter_dir, repo, state, key, extras)
    reason = _repair_reason(rec.get("outcome") or "failed", _load_json(adir / key / "result.json", None), campaign)
    if reason and best is not None and best > 0:
        logger.info("v8: %s needs no repair: an official measure scored %s", key, best)
        reason = None
    if reason and not rec.get("repaired") and repair_funded(s, s8, remaining(), waiting):
        rec.update({"repaired": True, "repair_reason": reason})
        _save_state(adir, state)
        print(f"  v8 repair `{key}` ({reason}; ${s8.repair_budget_usd:.2f})")
        rec["repair_outcome"] = _dispatch(
            dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, "repair-arm",
            label=f"{key}-repair", target=s8.repair_budget_usd, hard=s8.repair_budget_usd,
            resume=rec.get("session_id"), extras=extras, patch=patch)
        rec = state["sessions"][key]
        _ensure_patch(_worktree(repo, rec), patch, rec.get("base") or "HEAD", extras)
        _recover(campaign, work_dir, iter_dir, repo, state, key, extras)
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
    if close_open_windows(state):
        _save_state(adir, state)
    arms = mechanism_arms(_load_bundle(iter_dir))
    if not arms:
        raise RuntimeError(f"v8 EXECUTE: {iter_dir / 'bundle.yaml'} has no h-main or h-alternative arm")
    if state.get("best_before") is None:
        state["best_before"] = best_judged(campaign, work_dir)
        _save_state(adir, state)

    def remaining() -> float:
        # The iteration-1 evaluator is one-time setup: it does not use up the iteration's screening money.
        setup = float((state["sessions"].get(EVALUATOR_KEY) or {}).get("spent_usd") or 0.0)
        return s.iteration_budget_usd + setup - iteration_spent(campaign, work_dir, iter_dir)

    add_to_handoff(campaign, work_dir, iter_dir, iteration)  # the designer rewrote the handoff
    ev = state["sessions"].get(EVALUATOR_KEY) or {}
    need_eval = ev.get("status") != "done" and (ev.get("status") in ("running", "measuring")
                                                or not (work_dir / EVALUATOR_DIR / "README.md").is_file())
    todo = [k for k, _ in arms if (state["sessions"].get(k) or {}).get("status") != "done"]
    if need_eval:
        _run_evaluator(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, extras)
    for key, _arm in arms:
        rec = state["sessions"].get(key) or {}
        if rec.get("status") == "done":
            continue
        screened = any((state["sessions"].get(k) or {}).get("status") == "done"
                       and (state["sessions"].get(k) or {}).get("outcome") != SKIPPED for k, _ in arms)
        # The first arm always runs; a later one is skipped when the floor no longer fits above the reserve.
        if not rec.get("status") and screened and not arm_funded(s, s8, remaining()):
            left = round(remaining(), 2)
            state["sessions"][key] = {
                "status": "done", "outcome": SKIPPED,
                "skip_reason": (f"${left:.2f} was left in the iteration, below the ${s8.arm_floor_usd:.2f} arm "
                                f"floor on top of the ${winner_reserve(s, s8):.2f} winner reserve")}
            _save_state(adir, state)
            print(f"  v8 skip `{key}`: {state['sessions'][key]['skip_reason']}")
            todo.remove(key)
            continue
        cap = v8_screening_cap(s, s8, remaining(), len(todo))
        todo.remove(key)
        _screen(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key, cap, extras, remaining,
                waiting=len(todo))

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
            # Without a session to resume, the continuation needs the full arm prompt (problem, arm, context).
            phase = "continue-arm" if rec.get("session_id") else "execute-arm-v8"
            win["outcome"] = _dispatch(dispatcher, campaign, work_dir, iter_dir, iteration, repo, state, key,
                                       phase, label=WINNER_LABEL, target=cap, hard=cap,
                                       resume=rec.get("session_id"), extras=extras, patch=patch)
            rec = state["sessions"][key]
            eid = rec["experiment_id"]
            wt = repo / _EXPERIMENTS_DIRNAME / eid
            (iter_dir / ".experiment_id").write_text(eid)
            _ensure_patch(wt, patch, rec.get("base") or "HEAD", extras)
        rec = state["sessions"][key]
        starts = [w.get("start") for w in rec.get("windows") or [] if w.get("label") == WINNER_LABEL]
        _recover(campaign, work_dir, iter_dir, repo, state, key, extras,
                 stale_before=min(starts) if starts else None)
        write_artifacts(campaign, iter_dir, iteration, key)
        final = _load_json(adir / key / "result.json", None)
        scores = [arm_score(r, campaign) for k, r in
                  [(k, _load_json(adir / k / "result.json", None)) for k, _ in arms] if _passed(r)]
        state["best_after"] = best_judged(campaign, work_dir, [v for v in scores if v is not None])
        win.update({"status": "done", "score": arm_score(final, campaign)})
        _save_state(adir, state)
    record_screened_arms(campaign, iter_dir, iteration)
    return wt, eid


def write_fallback_design(campaign: dict, work_dir: Path, iter_dir: Path, iteration: int) -> bool:
    """A design session that ended without a valid bundle (cap stop mid-reasoning) gets a minimal one.

    Live p58: the designer hit its cap inside a long reasoning turn, wrote nothing, and the whole iteration
    was abandoned. One h-main that builds, measures and improves in short steps keeps the iteration going.
    Returns True when it wrote anything.
    """
    from orchestrator.validate import validate_design
    iter_dir = Path(iter_dir)
    bundle_ok = (iter_dir / "bundle.yaml").is_file() and \
        validate_design(iter_dir, campaign=campaign).get("status") == "pass"
    missing = [n for n in ("problem.md", "handoff_snapshot.md") if not (iter_dir / n).is_file()]
    if bundle_ok and not missing:
        return False
    if not bundle_ok:
        best = best_judged(campaign, work_dir)
        bundle = {
            "metadata": {"iteration": iteration, "family": "direct construction",
                         "research_question": str(campaign.get("research_question") or "Improve the score")},
            "single_family_reason": ("v8 fallback: the design session ended without a bundle, so one arm builds "
                                     "and improves a solution directly."),
            "arms": [{
                "type": "h-main", "mechanism_family": "direct construction from the statement",
                "prediction": f"A working solution built and measured in short steps scores above "
                              f"{best if best is not None else 0}.",
                "mechanism": ("Start from the current solution; work out the problem's structure in short steps, "
                              "writing and measuring code after each step, and keep the best version."),
                "diagnostic": "If it does not beat the incumbent, the next iteration screens competing families.",
                "validity_check": "The output is valid on the smallest case and the official judge scores it above 0.",
            }],
        }
        atomic_write(iter_dir / "bundle.yaml", yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True))
    for name in missing:
        atomic_write(iter_dir / name, f"# {name}\n\nv8 fallback design for iteration {iteration}: the design "
                                      "session ended without this file.\n")
    logger.warning("v8: design ended without a valid bundle%s; wrote a fallback design",
                   f" or {', '.join(missing)}" if missing else "")
    return True


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
            write_fallback_design(campaign, work_dir, iter_dir, iteration)
            return
        except SDKHangError as exc:
            logger.warning("v8 design session hung (attempt %d): %s", attempt + 1, exc)
            if attempt >= MAX_HANG_RESTARTS or left < MIN_SESSION_USD:
                if write_fallback_design(campaign, work_dir, iter_dir, iteration):
                    return
                raise
