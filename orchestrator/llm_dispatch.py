"""LLM-based agent dispatch for the Nous orchestrator.

Calls an OpenAI-compatible LLM API, loads prompt templates, parses
structured output from code fences, validates against JSON Schema,
and writes artifacts atomically.

Works with any OpenAI-compatible endpoint (OpenAI, Anthropic via proxy,
LiteLLM proxy, etc.).  Optionally set OPENAI_API_KEY and OPENAI_BASE_URL
environment variables.  If no API key is available, the dispatcher is
created in disabled mode and dispatch() raises RuntimeError when called.
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable

import jsonschema
import openai
import yaml

from orchestrator.metrics import log_metrics
from orchestrator.prompt_loader import PromptLoader
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_FENCE_RE = {
    "yaml": re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
    "json": re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
}

# Schema cache: schema_name -> parsed schema dict
_schema_cache: dict[str, dict] = {}


def _format_campaign_ground_truth(gt: dict | None) -> str:
    """Render a top-level campaign.ground_truth block as Markdown for the
    DESIGN prompt (#185). Returns the empty string when the block is absent
    so templates that don't reference it stay clean.

    Authors who pre-register a direction claim and pass condition want
    those visible to the agent verbatim — this surfaces them next to
    target_system.description rather than burying them in prose.
    """
    if not gt or not isinstance(gt, dict):
        return ""
    lines: list[str] = ["## Pre-registered ground truth"]
    if gt.get("pre_registered"):
        lines.append("This ground truth was committed before any data was collected.")
    field_order = (
        ("workload", "Workload"),
        ("baselines", "Baselines"),
        ("primary_metric", "Primary metric"),
        ("direction_claim", "Direction claim"),
        ("pass_condition", "Pass condition"),
        ("seeds", "Seeds"),
    )
    for key, label in field_order:
        val = gt.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            rendered = ", ".join(str(x) for x in val)
        else:
            rendered = str(val)
        lines.append(f"- **{label}:** {rendered}")
    return "\n".join(lines)


def _normalize_theory_references(refs) -> list[dict]:
    """Normalize theory_references items to object form (#185).

    Schema accepts either string or object items; downstream consumers
    should always see ``[{"name": ..., ...}, ...]``. String entries
    become ``{"name": <string>}`` with empty other fields.
    """
    if not refs:
        return []
    out: list[dict] = []
    for entry in refs:
        if isinstance(entry, str):
            out.append({"name": entry})
        elif isinstance(entry, dict):
            out.append(entry)
    return out


def _format_results_summary(work_dir: Path) -> str:
    """#214: enumerate per-iteration result files for the REPORT extractor.

    Walks ``runs/iter-*/results/`` and produces a structured listing the
    extractor can engage with directly. Without this, a campaign that
    completed 4/5 policies × 10 seeds (40 valid arms) but failed on the
    5th policy can have its report dismiss all 40 results as "no data"
    — a search-orientation violation. Pre-rendering the file inventory
    forces the extractor to acknowledge what's on disk.

    Pure deterministic Python — no LLM, no I/O beyond directory walks.
    """
    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return "No iteration directories found."
    lines: list[str] = []
    iter_dirs = sorted(
        (d for d in runs_dir.iterdir()
         if d.is_dir() and d.name.startswith("iter-")),
        key=lambda d: d.name,
    )
    if not iter_dirs:
        return "No iteration directories found."
    for iter_dir in iter_dirs:
        results_dir = iter_dir / "results"
        if not results_dir.is_dir():
            lines.append(f"- {iter_dir.name}: results/ directory absent")
            continue
        files = sorted(p for p in results_dir.iterdir() if p.is_file())
        if not files:
            lines.append(f"- {iter_dir.name}: 0 result files in {results_dir}")
            continue
        lines.append(
            f"- {iter_dir.name}: {len(files)} result file(s) "
            f"under {results_dir}"
        )
        # Cap per-iter listing to keep prompts bounded.
        cap = 50
        for f in files[:cap]:
            lines.append(f"  - {f.name}")
        if len(files) > cap:
            lines.append(f"  - ... and {len(files) - cap} more")
    return "\n".join(lines)


def _format_brief_amendments_summary(work_dir: Path) -> str:
    """#223: surface structured ``brief_amendments.jsonl`` entries to
    the REPORT extractor.

    Each amendment is a JSON object with required fields
    ``id, brief_section, problem, fix, priority``. Optional
    ``evidence``, ``impact``. The schema lives at
    ``orchestrator/schemas/brief_amendments.schema.json`` and is
    enforced by the agent that *writes* the file (per methodology) —
    this renderer JSON-decodes each row and surfaces a count of
    lines that failed to parse so the operator sees corruption,
    but does not itself re-validate against the schema.

    Walks ``runs/iter-*/inputs/brief_amendments.jsonl`` and renders a
    per-iter listing grouped by priority. The REPORT extractor can use
    this to: (a) cite which amendments shaped the iteration's findings,
    (b) flag which BLOCKING amendments still need applying to the
    upstream brief (the cross-run learning loop).
    """
    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return "(no iteration directories — no brief amendments to report.)"
    iter_dirs = sorted(
        (d for d in runs_dir.iterdir()
         if d.is_dir() and d.name.startswith("iter-")),
        key=lambda d: d.name,
    )
    sections: list[str] = []
    total = 0
    for iter_dir in iter_dirs:
        log = iter_dir / "inputs" / "brief_amendments.jsonl"
        if not log.exists():
            continue
        try:
            text = log.read_text()
        except OSError as exc:
            sections.append(
                f"- {iter_dir.name}: brief_amendments.jsonl unreadable "
                f"({type(exc).__name__})"
            )
            continue
        rows: list[dict] = []
        skipped_malformed = 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                skipped_malformed += 1
        if not rows and skipped_malformed == 0:
            continue
        # Group by priority for at-a-glance triage. BLOCKING first, then
        # HIGH / MEDIUM / LOW / INFO. Unknown priorities sort last.
        priority_order = {
            "BLOCKING": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4,
        }
        rows_sorted = sorted(
            rows,
            key=lambda r: priority_order.get(
                str(r.get("priority", "")).upper(), 99
            ),
        )
        header = f"- {iter_dir.name}: {len(rows)} amendment(s)"
        if skipped_malformed:
            header += f" + {skipped_malformed} malformed line(s) skipped"
        sections.append(header)
        total += len(rows)
        cap = 20
        for r in rows_sorted[:cap]:
            aid = r.get("id", "?")
            prio = r.get("priority", "?")
            section = r.get("brief_section", "?")
            problem = r.get("problem", "")
            sections.append(
                f"  - [{prio}] {aid} (target: {section}) — "
                + (problem[:160] + "..." if len(problem) > 160 else problem)
            )
        if len(rows_sorted) > cap:
            sections.append(f"  - ... and {len(rows_sorted) - cap} more")
    if not sections:
        return (
            "(no brief_amendments.jsonl entries — the campaign brief was "
            "consistent with the agent's runs; no amendments queued.)"
        )
    return "\n".join(sections)


def _format_bundle_amendments_summary(work_dir: Path) -> str:
    """#211: surface bundle_amendments.jsonl entries to the REPORT extractor.

    EXECUTE_ANALYZE writes one entry per parameter override during
    smoke/validation cycles (e.g. kv_blocks 1100 → 1200 because smoke
    showed dropped_unservable). Without this, the silent drift becomes
    invisible in the report — and the next campaign run re-discovers
    the same friction.

    Walks ``runs/iter-*/inputs/bundle_amendments.jsonl`` and produces
    a per-iter listing. Pure deterministic Python.
    """
    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return "(no iteration directories — no amendments to report.)"
    iter_dirs = sorted(
        (d for d in runs_dir.iterdir()
         if d.is_dir() and d.name.startswith("iter-")),
        key=lambda d: d.name,
    )
    sections: list[str] = []
    total = 0
    for iter_dir in iter_dirs:
        log = iter_dir / "inputs" / "bundle_amendments.jsonl"
        if not log.exists():
            continue
        try:
            text = log.read_text()
        except OSError as exc:
            sections.append(
                f"- {iter_dir.name}: bundle_amendments.jsonl unreadable "
                f"({type(exc).__name__})"
            )
            continue
        rows: list[dict] = []
        skipped_malformed = 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                skipped_malformed += 1
        if not rows and skipped_malformed == 0:
            continue
        # Header for this iter — single line whether or not malformed
        # rows were skipped; the skip count is appended in-line so the
        # operator sees both the valid count and the corruption count.
        if skipped_malformed:
            sections.append(
                f"- {iter_dir.name}: {len(rows)} amendment(s) + "
                f"{skipped_malformed} malformed line(s) skipped"
            )
            if not rows:
                continue
        else:
            sections.append(f"- {iter_dir.name}: {len(rows)} amendment(s)")
        total += len(rows)
        for r in rows[:20]:
            param = r.get("parameter", "?")
            prescribed = r.get("prescribed_value", "?")
            actual = r.get("actual_value", "?")
            reason = r.get("reason", "")
            sections.append(
                f"  - {param}: {prescribed!r} → {actual!r}"
                + (f" — {reason}" if reason else "")
            )
        if len(rows) > 20:
            sections.append(f"  - ... and {len(rows) - 20} more")
    if not sections:
        return (
            "(no bundle_amendments.jsonl entries — DESIGN's experiment_spec "
            "ran unmodified through EXECUTE_ANALYZE.)"
        )
    return "\n".join(sections)


def _format_retry_log_summary(work_dir: Path) -> str:
    """#214: surface retry_log entries to the REPORT extractor so it can
    distinguish 'no data because iteration failed cleanly' from 'no data
    because the apparatus broke mid-run'. Empty when the log is missing
    or empty.
    """
    log = work_dir / "retry_log.jsonl"
    if not log.exists():
        return "(retry_log.jsonl not present — no dispatcher-level retries.)"
    rows: list[dict] = []
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return "(retry_log.jsonl is empty — no dispatcher-level retries.)"
    by_type: dict[str, int] = {}
    for r in rows:
        ft = r.get("failure_type") or "unknown"
        by_type[ft] = by_type.get(ft, 0) + 1
    parts = [f"{len(rows)} entry/entries by failure_type:"]
    for ft, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        parts.append(f"  - {ft}: {n}")
    return "\n".join(parts)


def _format_theory_references(refs) -> str:
    """Render theory_references as a Markdown bullet list for the DESIGN
    prompt. Empty when no references are declared.
    """
    norm = _normalize_theory_references(refs)
    if not norm:
        return ""
    lines: list[str] = ["## External theory anchors"]
    for ref in norm:
        name = ref.get("name", "?")
        statement = ref.get("statement")
        if statement:
            lines.append(f"- **{name}** — {statement}")
        else:
            lines.append(f"- **{name}**")
        how = ref.get("how")
        if how:
            lines.append(f"  - How to apply: {how}")
    return "\n".join(lines)


class LLMDispatcher:
    """Dispatch agent roles to an LLM and produce schema-conformant artifacts."""

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "claude-sonnet-4-6",
        api_base: str | None = None,
        api_key: str | None = None,
        prompts_dir: Path | None = None,
        completion_fn: Callable | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self._validate_campaign(campaign)
        self.campaign = campaign
        self.model = model
        # PromptLoader prefers <template>_thin.md when CLAUDE.md exists
        # at work_dir/CLAUDE.md (#131 Phase B): the thin variants carry
        # only per-iteration context and reference CLAUDE.md for the
        # methodology, dropping ~400 lines per call when warm.
        self.loader = PromptLoader(
            prompts_dir
            or Path(__file__).parent.parent / "prompts" / "methodology",
            claude_md_at=Path(work_dir) / "CLAUDE.md",
        )
        if completion_fn:
            self._completion = completion_fn
        else:
            resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
            resolved_base = api_base or os.environ.get("OPENAI_BASE_URL")
            if resolved_key:
                client = openai.OpenAI(
                    api_key=resolved_key, base_url=resolved_base,
                )
                self._completion = client.chat.completions.create
            else:
                logger.warning(
                    "No OPENAI_API_KEY found. LLM dispatch will fail at "
                    "call time. Set OPENAI_API_KEY to enable LLM features."
                )
                self._completion = None
        self._metrics_path = self.work_dir / "llm_metrics.jsonl"
        self._current_role: str = "unknown"
        self._current_phase: str = "unknown"
        dal = campaign.get("prompts", {}).get("domain_adapter_layer")
        if dal is not None:
            # Issue #89: this field looks like the right place for domain
            # context but is NOT YET IMPLEMENTED. Authors hit this trap
            # silently — their carefully-prepared notes never reach the LLM.
            # The warning is loud and points at the migration path: put
            # the content in target_system.description (which IS substituted
            # into agent prompts) and run `nous create-campaign` for guidance.
            logger.warning(
                "⚠️  prompts.domain_adapter_layer is set to %r but is NOT YET "
                "IMPLEMENTED (issue #89). The value will be IGNORED. The LLM "
                "agents will not see any context from this file. To fix: "
                "migrate that content into `target_system.description` "
                "(which IS substituted into the agent's prompts), then set "
                "domain_adapter_layer to null. The `nous create-campaign` "
                "skill / CLI walks through the correct structure.",
                dal,
            )

    @staticmethod
    def _validate_campaign(campaign: dict) -> None:
        ts = campaign.get("target_system")
        if not isinstance(ts, dict):
            raise ValueError(
                "Campaign config missing 'target_system' section. "
                "See examples/campaign.yaml for the expected format."
            )
        required = ["name", "description"]
        missing = [k for k in required if k not in ts]
        if missing:
            raise ValueError(
                f"Campaign 'target_system' missing required keys: {missing}. "
                f"See examples/campaign.yaml for the expected format."
            )
        for field in ("observable_metrics", "controllable_knobs"):
            val = ts.get(field)
            if val is not None:
                if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                    raise ValueError(
                        f"Campaign 'target_system.{field}' must be a list of strings. "
                        f"Got: {val!r}"
                    )

    # ------------------------------------------------------------------
    # Public interface (satisfies Dispatcher protocol)
    # ------------------------------------------------------------------

    def dispatch(
        self,
        role: str,
        phase: str,
        *,
        output_path: Path,
        iteration: int,
        perspective: str | None = None,
        h_main_result: str = "CONFIRMED",
    ) -> None:
        """Dispatch an LLM agent to produce an artifact.

        *h_main_result* is ignored — kept for protocol compatibility with
        StubDispatcher.  The executor determines results from its own analysis.
        """
        if self._completion is None:
            raise RuntimeError(
                f"Cannot dispatch {role}/{phase}: no API key available. "
                f"Pass api_key= to LLMDispatcher or set the "
                f"OPENAI_API_KEY environment variable."
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._current_role = role
        self._current_phase = phase

        template, fmt, schema_name = self._route(role, phase)
        context = self._build_context(role, phase, iteration, perspective)
        prompt = self.loader.load(template, context)

        response = self._call_llm(prompt)

        if fmt is None:
            # Plain markdown output — no parsing or validation needed.
            atomic_write(output_path, response)
        else:
            try:
                data = self._extract_fenced_content(response, fmt)
            except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
                logger.warning(
                    "Parse failed for %s/%s (%s), retrying with feedback.",
                    role, phase, exc,
                )
                data = self._retry_parse(prompt, response, exc, fmt)
            if schema_name is not None:
                try:
                    self._validate(data, schema_name)
                except jsonschema.ValidationError as exc:
                    logger.warning(
                        "Schema validation failed for %s/%s, retrying: %s",
                        role, phase, exc.message,
                    )
                    data = self._retry_with_feedback(
                        prompt, response, exc, fmt, schema_name
                    )

            if fmt == "yaml":
                atomic_write(
                    output_path,
                    yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                )
            else:
                atomic_write(output_path, json.dumps(data, indent=2) + "\n")

        logger.info("Dispatched role=%s phase=%s -> %s", role, phase, output_path)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    _ROUTES: dict[tuple[str, str], tuple[str, str | None, str | None]] = {
        # (role, phase) -> (template_name, output_format, schema_name)
        ("planner", "design"): ("design", None, None),
        ("executor", "execute-analyze"): ("execute_analyze", "json", "execute_analyze.schema.json"),
        ("summarizer", "summarize-gate"): ("summarize_gate", "json", "gate_summary.schema.json"),
        ("extractor", "report"): ("report", None, None),
    }

    def _route(
        self, role: str, phase: str
    ) -> tuple[str, str | None, str | None]:
        key = (role, phase)
        if key not in self._ROUTES:
            raise ValueError(f"Unknown role/phase combination: {role}/{phase}")
        return self._ROUTES[key]

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_context(
        self,
        role: str,
        phase: str,
        iteration: int,
        perspective: str | None,
    ) -> dict[str, str]:
        ts = self.campaign["target_system"]
        ctx: dict[str, str] = {
            "target_system": ts["name"],
            "system_description": ts["description"],
            "observable_metrics": ", ".join(ts["observable_metrics"]) if ts.get("observable_metrics") else "Not specified — planner should discover from code",
            "controllable_knobs": ", ".join(ts["controllable_knobs"]) if ts.get("controllable_knobs") else "Not specified — planner should discover from code",
            "active_principles": self._format_principles(),
            "iteration": str(iteration),
        }

        if phase == "design":
            ctx["research_question"] = self.campaign["research_question"]
            iter_dir = self.work_dir / "runs" / f"iter-{iteration}"
            ctx["iter_dir"] = str(iter_dir.resolve())
            ctx["nous_dir"] = str(Path(__file__).resolve().parent.parent)
            # #212: per-iteration mode (rehearsal | real). Default = real
            # for backward compat. Mode-specific guidance is rendered into
            # the prompt directly so the design template doesn't need
            # conditional logic.
            from orchestrator.iteration_mode import (
                iteration_mode_for, mode_guidance_for,
            )
            mode = iteration_mode_for(self.campaign, iteration)
            ctx["iteration_mode"] = mode
            ctx["mode_guidance"] = mode_guidance_for(mode)
            # #185: surface a top-level pre-registered ground_truth block
            # to the designer so the immutable direction-claim and pass
            # condition reach the LLM directly. When absent, the
            # placeholder stays empty and templates that don't reference
            # it remain unaffected.
            ctx["ground_truth"] = _format_campaign_ground_truth(
                self.campaign.get("ground_truth"),
            )
            ctx["theory_references"] = _format_theory_references(
                self.campaign.get("theory_references"),
            )

        if phase == "design":
            # Campaign-level handoff — the living document updated each iteration
            handoff_path = self.work_dir / "handoff.md"
            if handoff_path.exists():
                ctx["previous_handoff"] = handoff_path.read_text()
            else:
                ctx["previous_handoff"] = (
                    "This is the first iteration. No prior handoff."
                )

            if iteration > 1:
                prev_findings_path = (
                    self.work_dir / "runs" / f"iter-{iteration - 1}"
                    / "findings.json"
                )
                if prev_findings_path.exists():
                    ctx["previous_findings"] = prev_findings_path.read_text()
                else:
                    logger.warning(
                        "findings.json for iteration %d not found at %s.",
                        iteration - 1, prev_findings_path,
                    )
                    ctx["previous_findings"] = (
                        "No findings available from the previous iteration."
                    )
            else:
                ctx["previous_findings"] = (
                    "This is the first iteration. No prior findings."
                )

        if phase in ("design", "execute-analyze"):
            fb_path = self.work_dir / "runs" / f"iter-{iteration}" / "human_feedback.json"
            if fb_path.exists():
                try:
                    store = json.loads(fb_path.read_text())
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Corrupt human_feedback.json at %s: %s. "
                        "Human feedback will not be injected.",
                        fb_path, exc,
                    )
                    store = {}
                if not isinstance(store, dict):
                    logger.warning(
                        "human_feedback.json at %s has unexpected type %s. "
                        "Human feedback will not be injected.",
                        fb_path, type(store).__name__,
                    )
                    store = {}
                phase_to_key = {"design": "design", "execute-analyze": "findings"}
                fb_key = phase_to_key.get(phase, "")
                entries = store.get(fb_key, [])
                if entries:
                    latest = entries[-1]
                    attempt = latest.get("attempt", "?")
                    reason = latest.get("reason", "(no reason recorded)")
                    ctx["human_feedback"] = (
                        f"## Human Feedback (attempt {attempt})\n\n{reason}"
                    )
                else:
                    ctx["human_feedback"] = ""
            else:
                ctx["human_feedback"] = ""

        if phase in ("design", "execute-analyze"):
            bundle_path = self.work_dir / "runs" / f"iter-{iteration}" / "bundle.yaml"
            if phase == "design" and not bundle_path.exists():
                pass
            elif not bundle_path.exists():
                raise FileNotFoundError(
                    f"Cannot run '{phase}' phase: {bundle_path} not found. "
                    f"Ensure the design phase completed for iteration {iteration}."
                )
            else:
                ctx["bundle_yaml"] = bundle_path.read_text()

        if phase in ("design", "execute-analyze"):
            ctx["repo_context"] = "(You have full shell access — explore the repo directly.)"
            ctx["max_turns"] = str(self._max_turns_for_phase(phase))

        if phase == "execute-analyze":
            problem_path = self.work_dir / "runs" / f"iter-{iteration}" / "problem.md"
            if not problem_path.exists() and iteration > 1:
                problem_path = self.work_dir / "runs" / "iter-1" / "problem.md"
            if problem_path.exists():
                ctx["problem_md"] = problem_path.read_text()
            else:
                ctx["problem_md"] = "No problem framing available."

            iter_dir = self.work_dir / "runs" / f"iter-{iteration}"
            ctx["iter_dir"] = str(iter_dir.resolve())
            ctx["nous_dir"] = str(Path(__file__).resolve().parent.parent)

            # Campaign-level handoff — the living document
            handoff_path = self.work_dir / "handoff.md"
            if handoff_path.exists():
                ctx["design_handoff"] = handoff_path.read_text()
            else:
                logger.warning(
                    "handoff.md not found for campaign. "
                    "Executor will proceed without designer context.",
                )
                ctx["design_handoff"] = (
                    "No design handoff available — explore the system directly."
                )

            # #221: per-iteration mode signal in EXECUTE_ANALYZE too. The
            # post-#212 paper-burst rerun observed the DESIGN agent
            # honoring rehearsal scope-shrink while EXECUTE_ANALYZE
            # dutifully fanned out the full bundle anyway — because the
            # mode signal only flowed to DESIGN. Rendering it in execute
            # too closes that gap.
            from orchestrator.iteration_mode import (
                iteration_mode_for, execute_mode_guidance_for,
            )
            mode = iteration_mode_for(self.campaign, iteration)
            ctx["iteration_mode"] = mode
            ctx["mode_guidance"] = execute_mode_guidance_for(mode)

        if perspective is not None:
            ctx["perspective_name"] = perspective

        if phase == "summarize-gate":
            gate_type = perspective or "design"
            ctx["gate_type"] = gate_type
            # Build context based on gate type
            if gate_type == "design":
                bundle_path = self.work_dir / "runs" / f"iter-{iteration}" / "bundle.yaml"
                if bundle_path.exists():
                    ctx["gate_context"] = f"Hypothesis bundle:\n```yaml\n{bundle_path.read_text()}\n```"
                else:
                    ctx["gate_context"] = "Bundle not available."
            elif gate_type == "findings":
                findings_path = self.work_dir / "runs" / f"iter-{iteration}" / "findings.json"
                if findings_path.exists():
                    ctx["gate_context"] = f"Findings:\n```json\n{findings_path.read_text()}\n```"
                else:
                    ctx["gate_context"] = "Findings not available."
            elif gate_type in ("continue", "end_of_campaign"):
                parts = []
                findings_path = (
                    self.work_dir / "runs" / f"iter-{iteration}"
                    / "findings.json"
                )
                if findings_path.exists():
                    parts.append(f"Findings:\n```json\n{findings_path.read_text()}\n```")
                handoff_path = self.work_dir / "handoff.md"
                if handoff_path.exists():
                    parts.append(f"Designer handoff:\n{handoff_path.read_text()}")
                ctx["gate_context"] = "\n\n".join(parts) if parts else "No context available."
            else:
                ctx["gate_context"] = "No additional context."

        if phase == "report":
            ctx["research_question"] = self.campaign["research_question"]
            # Ledger summary
            ledger_path = self.work_dir / "ledger.json"
            if ledger_path.exists():
                ctx["ledger_summary"] = ledger_path.read_text()
            else:
                ctx["ledger_summary"] = "No ledger entries."
            # Final principles
            principles_path = self.work_dir / "principles.json"
            if principles_path.exists():
                ctx["final_principles"] = principles_path.read_text()
            else:
                ctx["final_principles"] = "No principles extracted."
            # #214: Pre-render an enumeration of per-iteration result
            # files so the extractor surfaces partial data EVEN WHEN an
            # iteration failed mid-execute. Without this, the extractor
            # has no way to know what's on disk and frequently dismisses
            # 80% data as "no data" — search-orientation violation.
            ctx["results_summary"] = _format_results_summary(self.work_dir)
            ctx["retry_log_summary"] = _format_retry_log_summary(self.work_dir)
            # #211: surface any silent parameter overrides EXECUTE_ANALYZE
            # logged during smoke / validation, so the report doesn't
            # describe the prescribed bundle when the actual run used
            # different values.
            ctx["bundle_amendments_summary"] = (
                _format_bundle_amendments_summary(self.work_dir)
            )
            # #223: structured brief_amendments — propagate to REPORT
            # so the extractor can cite which amendments shaped the
            # iteration's findings AND surface BLOCKING amendments
            # that haven't been applied to the upstream brief yet
            # (cross-run learning loop).
            ctx["brief_amendments_summary"] = (
                _format_brief_amendments_summary(self.work_dir)
            )

        return ctx


    def _max_turns_for_phase(self, phase: str) -> int:
        """Return the max_turns limit for a CLI-dispatched phase."""
        defaults_path = Path(__file__).parent / "defaults.yaml"
        if defaults_path.exists():
            defaults = yaml.safe_load(defaults_path.read_text()) or {}
            max_turns = defaults.get("max_turns", {})
            phase_key = phase.replace("-", "_")
            if phase_key in max_turns:
                return max_turns[phase_key]
        return 25

    def _format_principles(self) -> str:
        """Read principles.json and format active ones for prompt injection."""
        path = self.work_dir / "principles.json"
        if not path.exists():
            return "No principles extracted yet."
        try:
            store = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            logger.error("principles.json contains invalid JSON: %s", exc)
            raise RuntimeError(
                f"Cannot read principles.json: corrupt JSON. {exc}"
            ) from exc
        principles_list = store.get("principles")
        if principles_list is None:
            logger.warning(
                "principles.json has no 'principles' key — treating as empty. "
                "File may be corrupt."
            )
            return "No principles extracted yet."
        active = [
            p for p in principles_list if p.get("status") == "active"
        ]
        if not active:
            return "No principles extracted yet."
        lines = [
            f"- {p.get('id', '?')}: {p.get('statement', '?')} "
            f"[confidence: {p.get('confidence', '?')}]"
            for p in active
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    def _log_llm_metrics(self, response, t0: float, phase_suffix: str = "") -> None:
        """Log token usage from an LLM API response. Silent no-op if usage absent."""
        duration_ms = int((time.time() - t0) * 1000)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        if not isinstance(prompt_tokens, int):
            logger.debug(
                "LLM response has no usable usage info (usage=%r); metrics not recorded.",
                usage,
            )
            return
        phase = self._current_phase
        if phase_suffix:
            phase = f"{phase}/{phase_suffix}"
        log_metrics(self._metrics_path, {
            "dispatcher": "llm",
            "role": self._current_role,
            "phase": phase,
            "model": self.model,
            "input_tokens": prompt_tokens,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cost_usd": None,
            "duration_ms": duration_ms,
            "num_turns": 1,
        })

    def _call_llm(
        self, system_prompt: str, user_message: str | None = None
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message or "Please proceed."},
        ]
        t0 = time.time()
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed (model={self.model}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        self._log_llm_metrics(response, t0)

        if not response.choices:
            raise RuntimeError("LLM returned empty choices list.")
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned None content.")

        return content

    def _retry_parse(
        self,
        original_prompt: str,
        original_response: str,
        error: Exception,
        fmt: str,
    ) -> dict:
        """Retry when the LLM response couldn't be parsed (missing fence, bad JSON/YAML)."""
        feedback = (
            f"Your previous response could not be parsed.\n\n"
            f"Error: {error}\n\n"
            f"Please output ONLY a ```{fmt}``` code fence with valid {fmt.upper()} inside. "
            f"No explanation outside the fence."
        )
        messages = [
            {"role": "system", "content": original_prompt},
            {"role": "assistant", "content": original_response},
            {"role": "user", "content": feedback},
        ]
        t0 = time.time()
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed during parse retry "
                f"(model={self.model}): {type(exc).__name__}: {exc}"
            ) from exc
        self._log_llm_metrics(response, t0, "retry-parse")
        if not response.choices:
            raise RuntimeError("LLM returned empty choices list during parse retry.")
        retry_text = response.choices[0].message.content
        if retry_text is None:
            raise RuntimeError("LLM returned None content during parse retry.")
        try:
            return self._extract_fenced_content(retry_text, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"LLM retry response could not be parsed as {fmt}: {exc}"
            ) from exc

    def _retry_with_feedback(
        self,
        original_prompt: str,
        first_response: str,
        error: jsonschema.ValidationError,
        fmt: str,
        schema_name: str,
    ) -> dict:
        """Retry the LLM call with validation error feedback."""
        feedback = (
            f"Your output failed schema validation:\n{error.message}\n\n"
            f"Please fix the issue and return only the corrected "
            f"{fmt} in a code fence."
        )
        messages = [
            {"role": "system", "content": original_prompt},
            {"role": "user", "content": "Please proceed."},
            {"role": "assistant", "content": first_response},
            {"role": "user", "content": feedback},
        ]
        t0 = time.time()
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed during schema-validation retry "
                f"(model={self.model}): {type(exc).__name__}: {exc}"
            ) from exc
        self._log_llm_metrics(response, t0, "retry-validation")
        if not response.choices:
            raise RuntimeError(
                "LLM returned empty choices list during retry."
            )
        retry_text = response.choices[0].message.content
        if retry_text is None:
            raise RuntimeError(
                "LLM returned None content during retry."
            )
        try:
            data = self._extract_fenced_content(retry_text, fmt)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            raise RuntimeError(
                f"LLM retry response could not be parsed as {fmt}: {exc}"
            ) from exc
        try:
            self._validate(data, schema_name)
        except jsonschema.ValidationError as exc:
            raise RuntimeError(
                f"LLM output failed schema validation after retry: {exc.message}"
            ) from exc
        return data

    # ------------------------------------------------------------------
    # Parsing & validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fenced_content(text: str, fmt: str) -> dict:
        """Extract and parse content from a code-fenced block.

        If the response contains multiple fences, uses the last one
        (LLMs often explain before giving the final answer).
        Raises ValueError if no code fence is found — callers handle retry.
        """
        pattern = _FENCE_RE.get(fmt)
        if pattern is None:
            raise ValueError(f"Unsupported format: {fmt}")

        matches = pattern.findall(text)
        if matches:
            raw = matches[-1]  # use last fence
        else:
            raise ValueError(
                f"No ```{fmt}``` code fence found in LLM response ({len(text)} chars). "
                f"Expected the LLM to wrap its output in a ```{fmt}``` block."
            )

        parsed = yaml.safe_load(raw) if fmt == "yaml" else json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected a {fmt} object from LLM, got {type(parsed).__name__}"
            )
        return parsed

    @staticmethod
    def _validate(data: dict, schema_name: str) -> None:
        """Validate *data* against the named schema file."""
        if schema_name not in _schema_cache:
            schema_path = Path(__file__).parent / "schemas" / schema_name
            raw = schema_path.read_text()
            if schema_name.endswith(".yaml"):
                _schema_cache[schema_name] = yaml.safe_load(raw)
            else:
                _schema_cache[schema_name] = json.loads(raw)
        jsonschema.validate(data, _schema_cache[schema_name])
