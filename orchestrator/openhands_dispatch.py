"""OpenHands backend for Nous code phases (``--agent openhands``).

Runs DESIGN / EXECUTE_ANALYZE turns with the OpenHands Software Agent SDK
instead of the Claude Agent SDK, so any LiteLLM-reachable model — including
open-weight models such as GLM or Nemotron — can serve as designer or
executor. Model names in ``campaign.models`` are LiteLLM slugs, e.g.
``openrouter/z-ai/glm-5.2``.

OpenHands lives in its own environment; ``OpenHandsRunner`` shells out to
``bin/nous-openhands-driver`` with that environment's interpreter
(``NOUS_OPENHANDS_PYTHON``) and exchanges JSON files, so nous never imports
OpenHands and the two dependency trees never clash.

EXECUTE_ANALYZE completion is meant to be enforced by a Claude Code Stop
hook (``bin/nous-execute-stop``), but that hook is not wired into the SDK
path today. Rather than depend on any harness's hook mechanism (OpenHands
SDK 1.21 does have Stop/PreToolUse hooks), ``OpenHandsDispatcher`` applies
the check from the orchestrator: after the DESIGN and EXECUTE_ANALYZE turns
it runs ``validate_design`` / ``validate_execution`` and, on failure, sends
the errors back for a bounded number of repair turns.

Turn timeout: the Claude SDK path never applies ``--timeout`` to a turn, so
turns are not wall-clock killed at 1800s here either. A separate hang guard
(``NOUS_OPENHANDS_TURN_TIMEOUT``, default 4h) protects against a stuck
driver process.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult, SDKTransientError

logger = logging.getLogger(__name__)

_DRIVER = Path(__file__).resolve().parent.parent / "bin" / "nous-openhands-driver"
_DEFAULT_REPAIR_TURNS = 3
_DEFAULT_TURN_TIMEOUT = 4 * 3600
# OpenHands otherwise requests the model's maximum output (e.g. 131072) on every
# call; per-request credit pre-authorization (OpenRouter) rejects that.
_DEFAULT_MAX_OUTPUT_TOKENS = 16384


# OpenHands' own system prompt (kept: it explains its tools) tells the agent to
# commit with `git commit -a` and to keep notes in AGENTS.md. Both conflict with
# nous: an executor was observed cd-ing to the target repo and committing there.
# This block is appended after nous's methodology and overrides that guidance.
_HARNESS_RULES = """
## Harness rules for this session (override any general guidance above)
- Never run `git commit`, `git push`, `git stash`, `git reset` or `git checkout`
  in any repository. Nous records your code changes itself.
- Only change files in your current working directory and in the nous run
  directory you are told to write artifacts to. Never `cd` into, or modify, the
  main target repository: during EXECUTE_ANALYZE your working directory is an
  isolated experiment worktree; during DESIGN do not modify the target at all.
- Do not create AGENTS.md or other memory files; nous keeps the record.
- Do not read other nous campaigns or runs (sibling directories of your run
  directory): each campaign must be independent unless it declares warm_start.
"""

_PRICING_CACHE: dict[str, dict | None] = {}


def resolve_pricing(model: str, fixed: dict | None = None) -> dict | None:
    """Per-million-token USD rates for ``model``, or None if unknown.

    ``fixed`` (campaign ``openhands.pricing``) wins. For ``openrouter/...``
    models the rates come from OpenRouter's per-model endpoint list (one small
    request, cached per process). Several providers can serve one model at
    very different prices (GLM-5.3: $0.055-$2.80/M input) and the serving
    provider isn't known per request, so the median listed rate is used
    (OpenRouter's default routing favours cheaper providers). Treat it as an
    estimate; OpenRouter's billed usage is the ground truth. Network failures
    never fail a turn; they only drop back to OpenHands' own cost figure.
    """
    if fixed:
        return fixed
    if not model.startswith("openrouter/"):
        return None
    if model in _PRICING_CACHE:
        return _PRICING_CACHE[model]
    import urllib.request

    slug = model[len("openrouter/"):]
    rates = None
    try:
        url = f"https://openrouter.ai/api/v1/models/{slug}/endpoints"
        with urllib.request.urlopen(url, timeout=15) as r:
            endpoints = json.load(r)["data"]["endpoints"]
        priced = [e["pricing"] for e in endpoints if e.get("pricing")]
        if priced:
            import statistics

            def median(key: str, fallback: str = "prompt") -> float:
                return statistics.median(
                    float(p.get(key) or p.get(fallback) or 0) for p in priced
                ) * 1e6
            rates = {
                "input_per_million": median("prompt"),
                "output_per_million": median("completion", "completion"),
                "cache_read_per_million": median("input_cache_read"),
                "cache_write_per_million": median("input_cache_write"),
            }
    except Exception as exc:  # noqa: BLE001 — pricing must never break a turn
        logger.warning("OpenRouter price lookup failed for %s (%s); using OpenHands cost", model, exc)
    _PRICING_CACHE[model] = rates
    return rates


def _repo_snapshot(repo: Path) -> dict | None:
    """HEAD + working-tree status of the target repo, ignoring nous's own dirs."""
    if not (repo / ".git").exists():
        return None
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
        ).stdout.strip()
    status = [
        line for line in git("status", "--porcelain").splitlines()
        if not line[3:].startswith((".nous/", ".nous-experiments/"))
    ]
    return {"head": git("rev-parse", "HEAD"), "status": status}


def _is_v7_family(campaign: dict) -> bool:
    from orchestrator.design_profile import is_v7_family
    return is_v7_family(campaign or {})


def _openhands_python() -> str:
    python = os.environ.get("NOUS_OPENHANDS_PYTHON")
    if not python:
        raise RuntimeError(
            "NOUS_OPENHANDS_PYTHON is not set. Point it at the python of an "
            "environment with `openhands` installed (e.g. `uv tool install "
            "openhands` or a dedicated venv)."
        )
    return python


class OpenHandsRunner:
    """``SDKRunner`` implementation backed by the OpenHands SDK."""

    def __init__(
        self, timeout: int | None = None, base_url: str | None = None,
        pricing: dict | None = None, max_output_tokens: int | None = None,
        request_timeout: int | None = None, context_window: int | None = None,
    ) -> None:
        self.timeout = timeout or int(
            os.environ.get("NOUS_OPENHANDS_TURN_TIMEOUT", _DEFAULT_TURN_TIMEOUT)
        )
        self.base_url = base_url or os.environ.get("NOUS_OPENHANDS_BASE_URL")
        # {"input_per_million": ..., "output_per_million": ...} USD; None lets the
        # driver look prices up (see bin/nous-openhands-driver).
        self.pricing = pricing
        self.max_output_tokens = max_output_tokens or _DEFAULT_MAX_OUTPUT_TOKENS
        # Seconds per model call (OpenHands default 300). Local models (Ollama)
        # can be much slower on long prompts.
        self.request_timeout = request_timeout or (
            int(os.environ["NOUS_OPENHANDS_REQUEST_TIMEOUT"])
            if os.environ.get("NOUS_OPENHANDS_REQUEST_TIMEOUT") else None
        )
        # Context window in tokens for small local models (e.g. Ollama num_ctx).
        self.context_window = context_window

    def __call__(
        self,
        *,
        prompt: str,
        model: str,
        cwd: Path | None,
        max_turns: int,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        event_log_path: Path | None = None,
        permission_mode: Literal["bypassPermissions"] | None = None,
        turn_silence_threshold: float | None = None,
        effort: str | None = None,
        resume: str | None = None,
        max_cost_usd: float | None = None,
        cost_rates: dict | None = None,
        hang_after_s: float | None = None,
        transcript_caps: bool = False,
        stop_on_output_limit: bool = False,
        **_unused,
    ) -> SDKResult:
        # v8 also passes transcript_caps / stop_on_output_limit, which are about
        # Claude Code's transcript and CLI output limit; the driver enforces caps
        # itself. hang_after_s: no agent event for that long -> SDKHangError.
        # resume / max_cost_usd / cost_rates follow the Claude runner: continue a
        # session by id, and stop a session at a token-ruler dollar cap.
        # settings_path / permission_mode / effort are Claude Code concepts
        # with no OpenHands equivalent; headless OpenHands never asks for
        # confirmation, which matches nous's default "bypass" sandbox.
        request = {
            "prompt": prompt,
            "model": model,
            "cwd": str(cwd or Path.cwd()),
            "max_turns": max_turns,
            "system_prompt": (system_prompt or "") + _HARNESS_RULES,
            "base_url": self.base_url,
            "pricing": resolve_pricing(model, self.pricing),
            "max_output_tokens": self.max_output_tokens,
            "request_timeout": self.request_timeout,
            "context_window": self.context_window,
            "max_cost_usd": max_cost_usd,
            "cost_rates": cost_rates,
        }
        env = os.environ.copy()
        # The executor is told to run `nous validate`; make sure the agent's
        # shell finds the same nous install that is driving the campaign.
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        if event_log_path is not None:
            # runs/iter-N/inputs/executor_log.jsonl -> runs/iter-N
            env["NOUS_ITER_DIR"] = str(Path(event_log_path).parent.parent)
            # Live per-event log (same shape as the Claude backend) and the full
            # OpenHands conversation next to it, for audit and replay.
            request["event_log_path"] = str(event_log_path)
            request["persistence_dir"] = str(Path(event_log_path).parent / "openhands")
            if resume:
                request["resume_conversation_id"] = resume

        with tempfile.TemporaryDirectory(prefix="nous-oh-") as tmp:
            req_path, resp_path = Path(tmp) / "request.json", Path(tmp) / "response.json"
            session_file = Path(tmp) / "session_id"
            request["session_file"] = str(session_file)
            req_path.write_text(json.dumps(request))
            stderr_path = Path(tmp) / "stderr.log"
            with open(stderr_path, "w") as stderr:
                proc = subprocess.Popen(
                    [_openhands_python(), "-I", str(_DRIVER), str(req_path), str(resp_path)],
                    cwd=request["cwd"], env=env, stdout=subprocess.DEVNULL, stderr=stderr,
                )
                self._wait(proc, event_log_path, hang_after_s, session_file)
            stderr_tail = stderr_path.read_text(errors="replace")[-4000:]
            if not resp_path.exists():
                raise SDKTransientError(
                    f"OpenHands driver exited {proc.returncode} without a response: {stderr_tail[-2000:]}"
                )
            data = json.loads(resp_path.read_text())
        if event_log_path is not None:
            with open(event_log_path, "a") as log:
                log.write(json.dumps({
                    "type": "OpenHandsTurnEnd", "ts": time.time(), "harness": "openhands",
                    "execution_status": data.get("execution_status"),
                    "is_error": data.get("is_error", False),
                    "subtype": data.get("subtype"),
                    "num_turns": data.get("num_turns"),
                    "conversation_id": data.get("conversation_id"),
                    "resumed": bool(request.get("resume_conversation_id")),
                    "stderr_tail": stderr_tail,
                }) + "\n")

        if data.get("fatal"):
            # Bad key, unknown model, no credits: retrying cannot help, so fail
            # the turn now instead of backing off for an hour.
            raise RuntimeError(f"OpenHands turn failed (not retryable): {data.get('error_message')}")
        status = data.get("execution_status")
        if status and status not in ("finished", "paused") and not data.get("subtype"):
            logger.warning(
                "OpenHands turn ended with status %r (e.g. its stuck detector); "
                "artifacts are checked by validation", status,
            )

        fields = SDKResult.__dataclass_fields__
        return SDKResult(**{k: v for k, v in data.items() if k in fields})


    def _wait(self, proc, event_log_path, hang_after_s, session_file: Path) -> None:
        """Wait for the driver; kill it on the turn timeout or a v8 hang (no events)."""
        from orchestrator.sdk_dispatch import SDKHangError, kill_process_tree

        start = last = time.time()
        seen = event_log_path.stat().st_size if event_log_path and event_log_path.exists() else 0
        while True:
            try:
                proc.wait(timeout=2.0)
                return
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            if event_log_path is not None and event_log_path.exists():
                size = event_log_path.stat().st_size
                if size != seen:
                    seen, last = size, now
            if now - start > self.timeout:
                kill_process_tree(proc.pid)
                proc.wait()
                raise SDKTransientError(f"OpenHands turn timed out after {self.timeout}s")
            if hang_after_s and event_log_path is not None and now - last > hang_after_s:
                kill_process_tree(proc.pid)
                proc.wait()
                exc = SDKHangError(f"OpenHands session sent no events for {now - last:.0f}s")
                exc.session_id = session_file.read_text().strip() if session_file.exists() else None
                exc.usage = {}
                raise exc


class OpenHandsDispatcher(SDKDispatcher):
    """SDKDispatcher that runs turns through OpenHands and gates EXECUTE_ANALYZE."""

    def __init__(self, *args, repair_turns: int | None = None, **kwargs) -> None:
        campaign = kwargs.get("campaign") if "campaign" in kwargs else args[1]
        oh_cfg = campaign.get("openhands") or {}
        kwargs.setdefault("sdk_runner", OpenHandsRunner(
            pricing=oh_cfg.get("pricing"), max_output_tokens=oh_cfg.get("max_output_tokens"),
            request_timeout=oh_cfg.get("request_timeout"),
            context_window=oh_cfg.get("context_window"),
        ))
        super().__init__(*args, **kwargs)
        configured = oh_cfg.get("repair_turns")
        self.repair_turns = (
            repair_turns if repair_turns is not None
            else configured if configured is not None
            else _DEFAULT_REPAIR_TURNS
        )

    def preflight_check(self) -> None:
        python = _openhands_python()
        proc = subprocess.run(
            [python, "-I", "-c", "import openhands.sdk, openhands.tools"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Pre-flight check failed: {python} cannot import openhands: "
                f"{proc.stderr.strip()[-500:]}"
            )
        logger.info("OpenHands pre-flight check passed (model=%s)", self.model)

    def _check_model(self) -> None:
        """Refuse to run a code phase on nous's built-in Claude defaults.

        Model resolution is campaign.models > defaults.yaml > --model, and
        defaults.yaml pins bare ``claude-*`` names. Under --agent openhands an
        unpinned phase would silently run on Claude instead of the intended
        model. Provider-qualified names (``anthropic/claude-...``) are allowed.
        """
        if "/" not in self.model and self.model.startswith("claude-"):
            raise RuntimeError(
                f"--agent openhands resolved model {self.model!r} from nous's Claude "
                f"defaults. Pin every code phase in campaign.models with a LiteLLM "
                f"name (e.g. openrouter/z-ai/glm-5.3, or anthropic/{self.model} to "
                f"use Claude on purpose)."
            )

    def dispatch(  # type: ignore[override]
        self, role: str, phase: str, *, output_path, iteration: int,
        perspective=None, h_main_result="CONFIRMED",
    ) -> None:
        self._check_model()
        repo = (self.campaign.get("target_system") or {}).get("repo_path")
        self._repo_before = _repo_snapshot(Path(repo)) if repo else None
        super().dispatch(
            role, phase, output_path=output_path, iteration=iteration,
            perspective=perspective, h_main_result=h_main_result,
        )
        phase_key = self._normalize_phase(phase)
        # Classic flow only: v7/v8 campaigns run their own sessions (arms,
        # evaluator, winner) with their own repair and fallback logic.
        gated = not _is_v7_family(self.campaign) and (
            (phase == "design" and role == "planner")
            or (phase in ("execute-analyze", "execute_analyze") and role == "executor")
        )
        iter_dir = self.work_dir / "runs" / f"iter-{iteration}"
        if gated:
            # Parent dispatch clears the event log path on exit; keep repair turns
            # logged (and NOUS_ITER_DIR exported) like the phase turn itself.
            self._event_log_path = iter_dir / "inputs" / "executor_log.jsonl"
            try:
                self._repair_until_valid(iter_dir, phase_key)
            finally:
                self._event_log_path = None
        self._check_target_repo(iter_dir, phase_key)

    def _check_target_repo(self, iter_dir: Path, phase_key: str) -> None:
        """Detect agents that leave their worktree and change the target repo.

        Experiments must run in the per-iteration worktree; the prompt says so,
        but an OpenHands executor was observed cd-ing to the target repo and
        committing there. Nothing is reverted automatically (the operator may
        be committing too); the change is recorded loudly instead.
        """
        repo = (self.campaign.get("target_system") or {}).get("repo_path")
        before = getattr(self, "_repo_before", None)
        if not repo or before is None:
            return
        after = _repo_snapshot(Path(repo))
        if after == before:
            return
        new_commits = subprocess.run(
            ["git", "-C", repo, "log", "--format=%h %an: %s", f"{before['head']}..{after['head']}"],
            capture_output=True, text=True,
        ).stdout.strip().splitlines()
        record = {
            "phase": phase_key, "repo_path": repo, "before": before, "after": after,
            "new_commits": new_commits,
        }
        (iter_dir / "inputs").mkdir(parents=True, exist_ok=True)
        with open(iter_dir / "inputs" / "target_repo_violation.json", "a") as f:
            f.write(json.dumps(record) + "\n")
        with open(self.work_dir / "retry_log.jsonl", "a") as f:
            f.write(json.dumps({"kind": "target_repo_modified", **record}) + "\n")
        logger.error(
            "%s: the agent changed the target repo outside its worktree "
            "(new commits: %s; working-tree changes: %s). Isolation is broken for "
            "this iteration; see inputs/target_repo_violation.json.",
            phase_key.upper(), new_commits or "none", after["status"] or "none",
        )

    def _validation_errors(self, iter_dir: Path, phase_key: str) -> list[str]:
        from orchestrator.validate import validate_design, validate_execution

        if phase_key == "design":
            result = validate_design(iter_dir, campaign=self.campaign)
            return [] if result.get("status") == "pass" else list(result.get("errors", []))
        result = validate_execution(iter_dir, campaign=self.campaign)
        errors = [] if result.get("status") == "pass" else list(result.get("errors", []))
        if not (iter_dir / "principle_updates.json").exists():
            errors.insert(0, "principle_updates.json is missing (write a JSON list, possibly empty)")
        return errors

    def _repair_until_valid(self, iter_dir: Path, phase_key: str = "execute_analyze") -> None:
        """Orchestrator-side self-correction for DESIGN and EXECUTE_ANALYZE.

        Same check the orchestrator runs before advancing (and the
        EXECUTE_ANALYZE Stop hook was meant to run): on failure the errors go
        back to the agent for up to ``repair_turns`` turns. If they remain,
        the orchestrator's own validation fails the phase as before.
        """
        cli_phase = "design" if phase_key == "design" else "execution"
        for attempt in range(1, self.repair_turns + 1):
            errors = self._validation_errors(iter_dir, phase_key)
            if not errors:
                return
            logger.warning(
                "%s artifacts invalid (repair %d/%d): %s",
                phase_key.upper(), attempt, self.repair_turns, errors,
            )
            self._log_repair(iter_dir, attempt, errors, phase_key)
            bullet_list = "\n".join(f"  - {e}" for e in errors)
            # Continue the phase's own conversation so the agent keeps its context.
            with self.resume_session(self.last_session_id):
                self._call_claude(
                    f"The orchestrator validated the {phase_key} artifacts in {iter_dir} and "
                    f"they FAILED ({len(errors)} error(s)):\n{bullet_list}\n\n"
                    f"Fix every error by editing the files in place (do not re-run experiments "
                    f"unless an error requires it), then run "
                    f"`nous validate {cli_phase} --dir {iter_dir}` and stop only when it "
                    f"reports status: pass."
                )

    def _log_repair(
        self, iter_dir: Path, attempt: int, errors: list[str], phase_key: str,
    ) -> None:
        with open(self.work_dir / "retry_log.jsonl", "a") as f:
            f.write(json.dumps({
                "kind": "validation_repair", "phase": phase_key, "iter_dir": str(iter_dir),
                "attempt": attempt, "errors": errors,
            }) + "\n")
