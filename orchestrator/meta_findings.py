"""Deterministic emitter for ``meta_findings.json`` (issue #155).

Reads the campaign's on-disk artifacts (ledger.json, principles.json,
findings.json across iterations, retry_log.jsonl, llm_metrics.jsonl)
and emits a structured ``meta_findings.json`` with three streams of
lessons:

  * ``campaign_design_lessons`` — how to structure future campaigns better.
  * ``target_system_asks``      — what the target repo should improve.
  * ``nous_asks``               — what Nous itself should improve.

This is **pure Python** — zero LLM tokens. The bottom-line goal of the
issue (capturing a triagable feedback signal that today lives only in
chat history) is met by deterministic heuristics over artifacts the
orchestrator already writes. Each emitted entry carries a concrete
``evidence`` citation that points at a specific iter-N, file path,
tool name, or error string — never a vague aspirational claim.

This file is also the home of citation enforcement. ``validate_evidence``
classifies an evidence string as concrete or vague; the validator in
``orchestrator.validate`` uses the same classifier so an LLM-emitted
meta_findings.json (a future enhancement) is held to the same floor.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

# ─── Citation enforcement ────────────────────────────────────────────────
#
# An evidence string is "concrete" if it cites a specific moment in the
# campaign. The patterns below are intentionally permissive — descriptive
# long-form text with a number and a name is fine; what we reject is
# pure platitudes ("things were slow", "it didn't work"). The patterns
# match anywhere in the string.

_CITATION_PATTERNS = (
    re.compile(r"\biter[-_ ]?\d+\b", re.IGNORECASE),
    re.compile(r"\b\w+\.(py|yaml|yml|json|md|toml|jsonl|txt|sh|patch)\b"),
    re.compile(r"/[\w./-]{3,}"),
    re.compile(r'"[^"]{4,}"'),
    re.compile(r"\b(Read|Write|Bash|Edit|Glob|Grep|TodoWrite|Task|Skill|"
               r"claude_agent_sdk|subprocess|cli_dispatch|sdk_dispatch|"
               r"llm_dispatch|inline_dispatch|StubDispatcher)\b"),
    re.compile(r"\barm[_-]?(?:id\s*=|\s+)[\w-]+", re.IGNORECASE),
    re.compile(r"\bh-(main|ablation|super-additivity|control-negative|"
               r"robustness|dose-response|tradeoff)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(ms|s|tokens?|%|MB|GB|x)\b"),
    re.compile(r"\b\d{2,}\b"),
)


def evidence_is_concrete(text: str) -> bool:
    """True iff the evidence string carries at least one citation marker.

    Used by both the emitter (to self-check) and the validator (to
    reject vague entries from any source — Python or future LLM).
    """
    if not text or len(text) < 8:
        return False
    return any(p.search(text) for p in _CITATION_PATTERNS)


def validate_evidence(text: str) -> str | None:
    """Return None if evidence passes the citation floor, else an error.

    The error is human-readable so the validator can surface it as
    ``meta_findings.json: <stream>[i].evidence is too vague: ...``.
    """
    if not isinstance(text, str):
        return f"evidence must be a string, got {type(text).__name__}"
    if len(text) < 8:
        return f"evidence too short ({len(text)} chars; need >= 8)"
    if not evidence_is_concrete(text):
        return (
            "evidence is vague: must cite at least one concrete marker "
            "(iter-N, file path, tool name, quoted error, arm id, or "
            "a numeric measurement). Got: "
            + (text[:80] + ("…" if len(text) > 80 else ""))
        )
    return None


# ─── Artifact readers ────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _iter_findings(work_dir: Path) -> Iterable[tuple[int, dict]]:
    runs_dir = work_dir / "runs"
    if not runs_dir.is_dir():
        return
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir() or not child.name.startswith("iter-"):
            continue
        try:
            iteration = int(child.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        f = _read_json(child / "findings.json")
        if isinstance(f, dict):
            yield iteration, f


# ─── Heuristic detectors ─────────────────────────────────────────────────


def _detect_target_system_asks(
    campaign: dict, retry_entries: list[dict],
) -> list[dict]:
    """Find concrete asks of the target repo from retry log and campaign.

    Heuristics:
      * Repeated retries of the same dispatch failure point at flaky
        tooling or missing instrumentation.
      * Empty observable_metrics / controllable_knobs in campaign.yaml
        means the planner had to discover them — a documentation gap.
    """
    asks: list[dict] = []

    if retry_entries:
        # Bucket by phase + failure_type — repeated bucket entries are signal.
        by_bucket: Counter[tuple[str, str]] = Counter()
        sample_error: dict[tuple[str, str], str] = {}
        for entry in retry_entries:
            phase = entry.get("phase") or "unknown"
            kind = entry.get("failure_type") or "unknown"
            key = (phase, kind)
            by_bucket[key] += 1
            if key not in sample_error:
                sample_error[key] = (entry.get("error") or "")[:120]
        for (phase, kind), count in by_bucket.most_common(3):
            if count < 2:
                continue
            err = sample_error.get((phase, kind), "")
            asks.append({
                "ask": (
                    f"Reduce {kind} failures during {phase}: the dispatcher "
                    f"retried {count} times in this campaign."
                ),
                "evidence": (
                    f"retry_log.jsonl: phase={phase} failure_type={kind} "
                    f"count={count} sample=\"{err}\""
                ),
                "kind": "reproducibility",
            })

    target = campaign.get("target_system", {}) if isinstance(campaign, dict) else {}
    if not target.get("observable_metrics"):
        asks.append({
            "ask": (
                "Declare observable_metrics in campaign.yaml so the planner "
                "doesn't have to rediscover them via Explore."
            ),
            "evidence": (
                "campaign.yaml: target_system.observable_metrics is unset; "
                "planner had to infer from code in iter-1 design phase."
            ),
            "kind": "instrumentation",
        })
    if not target.get("controllable_knobs"):
        asks.append({
            "ask": (
                "Declare controllable_knobs in campaign.yaml so the planner "
                "can pick from a known list rather than discovering them."
            ),
            "evidence": (
                "campaign.yaml: target_system.controllable_knobs is unset; "
                "planner had to infer from code in iter-1 design phase."
            ),
            "kind": "documentation",
        })

    return asks


def _detect_nous_asks(
    metrics_entries: list[dict], retry_entries: list[dict],
) -> list[dict]:
    """Find concrete asks of Nous itself from llm_metrics + retry log."""
    asks: list[dict] = []

    if metrics_entries:
        total_in = sum((e.get("input_tokens") or 0) for e in metrics_entries)
        cache_read = sum((e.get("cache_read_input_tokens") or 0) for e in metrics_entries)
        calls = len(metrics_entries)
        if total_in > 0 and calls > 0:
            avg_in = total_in / calls
            cache_ratio = (cache_read / total_in) if total_in else 0.0
            if avg_in > 30000:
                asks.append({
                    "ask": (
                        "Per-call input tokens are high — investigate "
                        "whether more of the system block can be cached "
                        "or whether handoff.md is unbounded."
                    ),
                    "evidence": (
                        f"llm_metrics.jsonl: avg input_tokens per call "
                        f"= {int(avg_in)} across {calls} calls "
                        f"(total_input={total_in})."
                    ),
                    "kind": "token_budget",
                })
            if total_in > 5000 and cache_ratio < 0.30:
                asks.append({
                    "ask": (
                        "Prompt cache hit rate is low — verify the static "
                        "system block is being cached and not perturbed by "
                        "per-call substitution."
                    ),
                    "evidence": (
                        f"llm_metrics.jsonl: cache_read_input_tokens / "
                        f"total_input_tokens = {cache_ratio:.0%} "
                        f"({cache_read}/{total_in}); expected >= 30%."
                    ),
                    "kind": "token_budget",
                })

    if len(retry_entries) >= 5:
        kinds = Counter(e.get("failure_type") or "unknown" for e in retry_entries)
        top_kind, top_count = kinds.most_common(1)[0]
        if top_count >= 3:
            asks.append({
                "ask": (
                    "Investigate root cause of repeated dispatch retries — "
                    "the retry path is masking a recurrent failure."
                ),
                "evidence": (
                    f"retry_log.jsonl: failure_type={top_kind} occurred "
                    f"{top_count} times across the campaign."
                ),
                "kind": "dispatch",
            })

    return asks


def _detect_design_lessons(work_dir: Path) -> list[dict]:
    """Find lessons about campaign design from per-iteration findings."""
    lessons: list[dict] = []

    findings_by_iter: dict[int, dict] = dict(_iter_findings(work_dir))
    if not findings_by_iter:
        return lessons

    h_main_status: dict[int, str] = {}
    invalid_iters: list[int] = []
    for it, f in findings_by_iter.items():
        if not f.get("experiment_valid", True):
            invalid_iters.append(it)
        for arm in f.get("arms", []) or []:
            if arm.get("arm_type") == "h-main":
                h_main_status[it] = arm.get("status", "")
                break

    if invalid_iters:
        lessons.append({
            "lesson": (
                "Tighten experiment_plan validation upstream: at least one "
                "iteration produced findings.json with experiment_valid=false."
            ),
            "evidence": (
                f"findings.json reported experiment_valid=false in "
                f"iter-{','.join(str(i) for i in invalid_iters)}"
            ),
        })

    refuted_then_confirmed = [
        i for i in sorted(h_main_status)
        if h_main_status[i] == "CONFIRMED"
        and any(h_main_status.get(j) == "REFUTED" for j in h_main_status if j < i)
    ]
    if refuted_then_confirmed:
        first_confirm = refuted_then_confirmed[0]
        first_refute = next(
            j for j in sorted(h_main_status)
            if h_main_status[j] == "REFUTED" and j < first_confirm
        )
        lessons.append({
            "lesson": (
                "Initial mechanism hypothesis was wrong — schedule simpler "
                "alternative arms in iter 1 next time."
            ),
            "evidence": (
                f"h-main was REFUTED in iter-{first_refute} and only "
                f"CONFIRMED in iter-{first_confirm}."
            ),
        })

    if h_main_status and all(s == "REFUTED" for s in h_main_status.values()):
        iters_str = ",".join(str(i) for i in sorted(h_main_status))
        lessons.append({
            "lesson": (
                "Every h-main arm was refuted — the family of mechanisms "
                "explored may not be the right one for this research question."
            ),
            "evidence": (
                f"h-main status = REFUTED in iter-{iters_str} (every "
                f"completed iteration)."
            ),
        })

    return lessons


# ─── Top-level emitter ───────────────────────────────────────────────────


def emit_meta_findings(
    work_dir: Path, campaign: dict, *, now: datetime | None = None,
) -> dict:
    """Build the meta_findings.json payload for a completed campaign.

    Pure function — does not write to disk. Caller passes it through
    ``write_meta_findings``. Heuristics are deterministic and depend
    only on the on-disk artifacts already produced by the orchestrator;
    no LLM is consulted.
    """
    work_dir = Path(work_dir)
    metrics = _read_jsonl(work_dir / "llm_metrics.jsonl")
    retries = _read_jsonl(work_dir / "retry_log.jsonl")

    ledger = _read_json(work_dir / "ledger.json")
    iterations_completed = 0
    if isinstance(ledger, dict):
        iterations_completed = sum(
            1 for row in ledger.get("iterations", [])
            if isinstance(row, dict)
            and isinstance(row.get("iteration"), int)
            and row["iteration"] >= 1
        )

    state = _read_json(work_dir / "state.json")
    run_id = (
        state.get("run_id", work_dir.name)
        if isinstance(state, dict) else work_dir.name
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "run_id": run_id,
        "iterations_completed": iterations_completed,
        "campaign_design_lessons": _detect_design_lessons(work_dir),
        "target_system_asks": _detect_target_system_asks(campaign, retries),
        "nous_asks": _detect_nous_asks(metrics, retries),
    }

    if not (
        payload["campaign_design_lessons"]
        or payload["target_system_asks"]
        or payload["nous_asks"]
    ):
        payload["notes"] = (
            "No surprises detected from artifacts. This is rare — typically "
            "indicates a very short campaign (single iteration, no retries, "
            "no token-budget anomalies)."
        )

    return payload


def write_meta_findings(work_dir: Path, payload: dict) -> Path:
    """Atomically write meta_findings.json and return the path."""
    work_dir = Path(work_dir)
    target = work_dir / "meta_findings.json"
    atomic_write(target, json.dumps(payload, indent=2) + "\n")
    return target


def render_meta_findings_markdown(payload: dict) -> str:
    """Render the three streams as a markdown section for nous report."""
    lines = ["## Meta-findings", ""]
    sections = [
        ("Campaign-design lessons", payload.get("campaign_design_lessons") or [], "lesson"),
        ("Target-system asks", payload.get("target_system_asks") or [], "ask"),
        ("Nous asks", payload.get("nous_asks") or [], "ask"),
    ]
    any_content = False
    for title, items, key in sections:
        lines.append(f"### {title}")
        lines.append("")
        if not items:
            lines.append("_None._")
            lines.append("")
            continue
        any_content = True
        for item in items:
            text = item.get(key, "")
            evidence = item.get("evidence", "")
            kind = item.get("kind")
            kind_str = f" _[{kind}]_" if kind else ""
            lines.append(f"- {text}{kind_str}")
            if evidence:
                lines.append(f"  - Evidence: {evidence}")
        lines.append("")
    if not any_content and payload.get("notes"):
        lines.append(f"_{payload['notes']}_")
        lines.append("")
    return "\n".join(lines)
