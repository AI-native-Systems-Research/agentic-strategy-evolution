"""LLM-based agent dispatch for the Nous orchestrator.

Calls an OpenAI-compatible LLM API, loads prompt templates, parses
structured output from code fences, validates against JSON Schema,
and writes artifacts atomically.

Works with any OpenAI-compatible endpoint (OpenAI, Anthropic via proxy,
LiteLLM proxy, etc.).  Set OPENAI_API_KEY and OPENAI_BASE_URL environment
variables to configure.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Callable

import jsonschema
import openai
import yaml

from orchestrator.prompt_loader import PromptLoader
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

_FENCE_RE = {
    "yaml": re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
    "json": re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
}

# Schema cache: schema_name -> parsed schema dict
_schema_cache: dict[str, dict] = {}


class LLMDispatcher:
    """Dispatch agent roles to an LLM and produce schema-conformant artifacts."""

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "aws/claude-sonnet-4-5",
        api_base: str | None = None,
        api_key: str | None = None,
        prompts_dir: Path | None = None,
        completion_fn: Callable | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self._validate_campaign(campaign)
        self.campaign = campaign
        self.model = model
        self.loader = PromptLoader(
            prompts_dir
            or Path(__file__).parent.parent / "prompts" / "methodology"
        )
        if completion_fn:
            self._completion = completion_fn
        else:
            client = openai.OpenAI(
                api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                base_url=api_base or os.environ.get("OPENAI_BASE_URL"),
            )
            self._completion = client.chat.completions.create
        dal = campaign.get("prompts", {}).get("domain_adapter_layer")
        if dal is not None:
            logger.warning(
                "domain_adapter_layer is set to %r but is not yet supported. "
                "Only the methodology layer will be used.",
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
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

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
        ("planner", "frame"): ("frame", None, None),
        ("planner", "design"): ("design", "yaml", "bundle.schema.yaml"),
        ("executor", "plan-execution"): ("run_plan", "yaml", "experiment_plan.schema.yaml"),
        ("executor", "analyze"): ("run_analyze", "json", "findings.schema.json"),
        ("reviewer", "review-design"): ("review_design", None, None),
        ("reviewer", "review-findings"): ("review_findings", None, None),
        ("extractor", "extract"): ("extract", "json", "principles.schema.json"),
        ("extractor", "summarize"): ("summarize", "json", "investigation_summary.schema.json"),
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

        if phase in ("frame", "design"):
            ctx["research_question"] = self._read_research_question(phase, iteration)

        if phase == "design":
            if iteration > 1:
                prev_summary_path = (
                    self.work_dir / "runs" / f"iter-{iteration - 1}"
                    / "investigation_summary.json"
                )
                if prev_summary_path.exists():
                    ctx["investigation_summary"] = prev_summary_path.read_text()
                else:
                    logger.warning(
                        "Investigation summary for iteration %d not found at %s. "
                        "Design prompt will proceed without prior learning context.",
                        iteration - 1, prev_summary_path,
                    )
                    ctx["investigation_summary"] = (
                        "No investigation summary available from the previous iteration."
                    )
            else:
                ctx["investigation_summary"] = (
                    "This is the first iteration. No prior investigation summary."
                )

        if phase in ("design", "review-design", "plan-execution", "analyze", "summarize"):
            bundle_path = self.work_dir / "runs" / f"iter-{iteration}" / "bundle.yaml"
            if phase == "design" and not bundle_path.exists():
                pass  # bundle doesn't exist yet during design — template ignores it
            elif not bundle_path.exists():
                raise FileNotFoundError(
                    f"Cannot run '{phase}' phase: {bundle_path} not found. "
                    f"Ensure the design phase completed for iteration {iteration}."
                )
            else:
                ctx["bundle_yaml"] = bundle_path.read_text()

        if phase in ("frame", "plan-execution"):
            # Pre-inject repo context so claude -p doesn't waste turns exploring
            repo_path = self.campaign.get("target_system", {}).get("repo_path")
            if repo_path:
                from orchestrator.repo_context import gather_repo_context
                ctx["repo_context"] = gather_repo_context(Path(repo_path))
            else:
                ctx["repo_context"] = "(no repo_path configured)"

        if phase in ("plan-execution", "analyze"):
            # Inject problem.md so executor/analyzer has full framing context
            problem_path = self.work_dir / "runs" / f"iter-{iteration}" / "problem.md"
            if not problem_path.exists() and iteration > 1:
                problem_path = self.work_dir / "runs" / "iter-1" / "problem.md"
            if problem_path.exists():
                ctx["problem_md"] = problem_path.read_text()
            else:
                ctx["problem_md"] = "No problem framing available."

        if phase == "analyze":
            results_path = (
                self.work_dir / "runs" / f"iter-{iteration}" / "execution_results.json"
            )
            if not results_path.exists():
                raise FileNotFoundError(
                    f"Cannot run 'analyze' phase: {results_path} not found. "
                    f"Ensure the EXECUTING phase completed for iteration {iteration}."
                )
            ctx["experiment_results"] = results_path.read_text()

        if phase in ("review-findings", "extract", "summarize"):
            findings_path = (
                self.work_dir / "runs" / f"iter-{iteration}" / "findings.json"
            )
            if not findings_path.exists():
                raise FileNotFoundError(
                    f"Cannot run '{phase}' phase: {findings_path} not found. "
                    f"Ensure the executor completed for iteration {iteration}."
                )
            ctx["findings_json"] = findings_path.read_text()

        if phase == "extract":
            principles_path = self.work_dir / "principles.json"
            if principles_path.exists():
                ctx["current_principles_json"] = principles_path.read_text()
            else:
                ctx["current_principles_json"] = json.dumps({"principles": []}, indent=2)

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
                summary_path = (
                    self.work_dir / "runs" / f"iter-{iteration}"
                    / "investigation_summary.json"
                )
                if summary_path.exists():
                    ctx["gate_context"] = f"Investigation summary:\n```json\n{summary_path.read_text()}\n```"
                else:
                    ctx["gate_context"] = "Investigation summary not available."
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

        return ctx

    def _read_research_question(self, phase: str, iteration: int) -> str:
        """Read the research question for frame/design phases."""
        if phase == "frame":
            return self.campaign["research_question"]
        # For design, read from the problem.md produced by framing.
        # In multi-iteration campaigns, framing only runs for iteration 1;
        # subsequent iterations reuse iter-1's problem.md.
        problem_path = self.work_dir / "runs" / f"iter-{iteration}" / "problem.md"
        if not problem_path.exists() and iteration > 1:
            problem_path = self.work_dir / "runs" / "iter-1" / "problem.md"
        if not problem_path.exists():
            raise FileNotFoundError(
                f"Expected {problem_path} for design phase. "
                f"Was the framing phase completed for iteration {iteration}?"
            )
        text = problem_path.read_text()
        in_section = False
        lines: list[str] = []
        for line in text.splitlines():
            if line.strip().startswith("## Research Question"):
                in_section = True
                continue
            if in_section and line.strip().startswith("##"):
                break
            if in_section and line.strip():
                lines.append(line.strip())
        if lines:
            return "\n".join(lines)
        logger.warning(
            "Could not extract research question from %s; "
            "using full problem.md content as context.",
            problem_path,
        )
        return text[:500]

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

    def _call_llm(
        self, system_prompt: str, user_message: str | None = None
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message or "Please proceed."},
        ]
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed (model={self.model}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
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
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed during parse retry "
                f"(model={self.model}): {type(exc).__name__}: {exc}"
            ) from exc
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
        try:
            response = self._completion(
                model=self.model, messages=messages, max_tokens=16384,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed during schema-validation retry "
                f"(model={self.model}): {type(exc).__name__}: {exc}"
            ) from exc
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
            schema_path = Path(__file__).parent.parent / "schemas" / schema_name
            raw = schema_path.read_text()
            if schema_name.endswith(".yaml"):
                _schema_cache[schema_name] = yaml.safe_load(raw)
            else:
                _schema_cache[schema_name] = json.loads(raw)
        jsonschema.validate(data, _schema_cache[schema_name])
