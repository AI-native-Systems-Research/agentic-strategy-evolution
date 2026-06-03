#!/usr/bin/env python3
"""Retrieve structured context from the Nous wiki for a given research intent.

This script implements the deterministic retrieval pipeline for /suggest-next.
The LLM picks campaign names and entity names; this script does direct lookups
on explicit relationship fields in concepts.json to produce a structured context block.

Usage:
    python scripts/retrieve_wiki_context.py \
      --campaigns epp-ttft-slope-detector epp-saturation-detector-archive-20260519-115428 \
      --entities "UtilizationDetector" "GatewayQueue" \
      --intent "improve admission control fairness across priority bands"

Output: A structured markdown context block printed to stdout.
"""

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_cost_context(wiki_dir: Path, campaign_names: list[str]) -> dict:
    """Compute cost stats from llm_metrics.jsonl for each campaign."""
    results = {}
    for name in campaign_names:
        metrics_path = wiki_dir / "campaigns" / name / "llm_metrics.jsonl"
        if not metrics_path.exists():
            continue
        entries = []
        with open(metrics_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        # Only count real cost-bearing entries (planner:design + executor:execute-analyze)
        design_entries = [e for e in entries if e.get("phase") == "design" and e.get("cost_usd")]
        execute_entries = [e for e in entries if e.get("phase") == "execute-analyze" and e.get("cost_usd")]

        design_cost = sum(e["cost_usd"] for e in design_entries)
        execute_cost = sum(e["cost_usd"] for e in execute_entries)
        total_cost = design_cost + execute_cost
        n_iters = max(len(design_entries), len(execute_entries))

        results[name] = {
            "total_cost_usd": round(total_cost, 2),
            "iterations": n_iters,
            "cost_per_iteration": round(total_cost / n_iters, 2) if n_iters else 0,
            "design_cost_usd": round(design_cost, 2),
            "execute_cost_usd": round(execute_cost, 2),
            "design_model": design_entries[0]["model"] if design_entries else None,
            "execute_model": execute_entries[0]["model"] if execute_entries else None,
            "avg_design_turns": round(sum(e["num_turns"] for e in design_entries) / len(design_entries)) if design_entries else 0,
            "avg_execute_turns": round(sum(e["num_turns"] for e in execute_entries) / len(execute_entries)) if execute_entries else 0,
            "total_duration_hours": round(sum(e["duration_ms"] for e in design_entries + execute_entries) / 3_600_000, 1),
        }
    return results


def retrieve_context(
    wiki_dir: Path,
    campaign_names: list[str],
    entity_names: list[str],
    intent: str,
) -> str:
    """Run the retrieval pipeline and return the structured context block.

    Uses explicit relationship fields in concepts.json for direct lookups:
      1. Match entities by name
      2. Find concepts whose operates_on includes matched entities
      3. Find parameters whose parent_concept matches found concepts
      4. Collect scoped principles from all matched items
      5. Filter frontiers/interactions by scoped principles
    """
    entity_names_lower = {n.lower() for n in entity_names}

    all_campaigns_info = []
    all_entities = []
    all_concepts = []
    all_parameters = []
    all_principles = []
    all_dead_ends = []
    all_frontiers = []
    all_interactions = []

    seen_entity_names = set()
    seen_concept_names = set()
    seen_param_names = set()
    seen_principle_ids = set()

    for campaign_name in campaign_names:
        campaign_dir = wiki_dir / "campaigns" / campaign_name

        concepts_data = load_json(campaign_dir / "concepts.json")
        if not concepts_data:
            continue

        all_campaigns_info.append({
            "name": campaign_name,
            "research_question": concepts_data.get("research_question", ""),
            "date": concepts_data.get("date", ""),
        })

        # 1. Match entities by name
        matched_entity_names = set()
        for entity in concepts_data.get("entities", []):
            if entity["name"].lower() in entity_names_lower:
                matched_entity_names.add(entity["name"])
                if entity["name"] not in seen_entity_names:
                    seen_entity_names.add(entity["name"])
                    all_entities.append(entity)

        if not matched_entity_names:
            continue

        # 2. Find concepts that operate on matched entities
        matched_concept_names = set()
        for concept in concepts_data.get("concepts", []):
            operates_on = concept.get("operates_on", [])
            if any(e in matched_entity_names for e in operates_on):
                matched_concept_names.add(concept["name"])
                if concept["name"] not in seen_concept_names:
                    seen_concept_names.add(concept["name"])
                    all_concepts.append(concept)
                # Also include entities referenced by operates_on (neighbors)
                for e_name in operates_on:
                    if e_name not in matched_entity_names and e_name not in seen_entity_names:
                        # Find this entity in the data
                        for ent in concepts_data.get("entities", []):
                            if ent["name"] == e_name:
                                seen_entity_names.add(e_name)
                                all_entities.append(ent)
                                break

        # 3. Find parameters belonging to matched concepts
        for param in concepts_data.get("parameters", []):
            if param.get("parent_concept") in matched_concept_names:
                if param["name"] not in seen_param_names:
                    seen_param_names.add(param["name"])
                    all_parameters.append(param)

        # 4. Collect scoped principle IDs from all matched items
        scoped_principle_ids = set()
        for entity in concepts_data.get("entities", []):
            if entity["name"] in seen_entity_names:
                scoped_principle_ids.update(entity.get("principles", []))
        for concept in concepts_data.get("concepts", []):
            if concept["name"] in matched_concept_names:
                scoped_principle_ids.update(concept.get("principles", []))
        for param in concepts_data.get("parameters", []):
            if param["name"] in seen_param_names:
                scoped_principle_ids.update(param.get("principles", []))

        # Load principles.json, filter to scoped IDs
        principles_data = load_json(campaign_dir / "principles.json")
        if principles_data:
            for p in principles_data.get("principles", []):
                if p["id"] in scoped_principle_ids and p["id"] not in seen_principle_ids:
                    seen_principle_ids.add(p["id"])
                    all_principles.append(p)

        # Load dead-ends (all)
        dead_ends = load_json(campaign_dir / "dead-ends.json")
        if dead_ends and isinstance(dead_ends, list):
            all_dead_ends.extend(dead_ends)

        # Load frontiers (filtered by scoped principles)
        frontiers = load_json(campaign_dir / "frontiers.json")
        if frontiers and isinstance(frontiers, list):
            for f in frontiers:
                related = set(f.get("related_principles", []))
                if related & scoped_principle_ids:
                    all_frontiers.append(f)

        # Load interactions (filtered by scoped principles)
        interactions = load_json(campaign_dir / "interactions.json")
        if interactions and isinstance(interactions, list):
            for i in interactions:
                related = set(i.get("related_principles", []))
                if related & scoped_principle_ids:
                    all_interactions.append(i)

    cost_context = load_cost_context(wiki_dir, campaign_names)

    return _format_context_block(
        intent=intent,
        campaigns=all_campaigns_info,
        entities=all_entities,
        concepts=all_concepts,
        parameters=all_parameters,
        principles=all_principles,
        dead_ends=all_dead_ends,
        frontiers=all_frontiers,
        interactions=all_interactions,
        cost_context=cost_context,
    )


def _format_context_block(
    intent: str,
    campaigns: list,
    entities: list,
    concepts: list,
    parameters: list,
    principles: list,
    dead_ends: list,
    frontiers: list,
    interactions: list,
    cost_context: dict | None = None,
) -> str:
    """Format all retrieved data into the structured context block."""
    lines = []
    lines.append("## Retrieved Context\n")

    # Research Problem
    lines.append("### Research Problem")
    lines.append(intent)
    lines.append("")

    # Selected Campaigns
    lines.append(f"### Selected Campaigns ({len(campaigns)})")
    for c in campaigns:
        lines.append(f"- **{c['name']}**: {c['research_question']} ({c['date']})")
    lines.append("")

    # Matched Entities
    lines.append(f"### Matched Entities ({len(entities)})")
    for e in entities:
        principles_str = ", ".join(e["principles"])
        lines.append(f"- **{e['name']}** — {e['definition']} [principles: {principles_str}]")
    lines.append("")

    # Related Concepts
    lines.append(f"### Related Concepts ({len(concepts)})")
    for c in concepts:
        principles_str = ", ".join(c["principles"])
        lines.append(f"- **{c['name']}** — {c['definition']} [principles: {principles_str}]")
    lines.append("")

    # Related Parameters
    lines.append(f"### Related Parameters ({len(parameters)})")
    for p in parameters:
        principles_str = ", ".join(p["principles"])
        evo_str = ""
        if p.get("evolution"):
            evo_parts = [f"{e['iter']}={e['value']} ({e['outcome']})" for e in p["evolution"]]
            evo_str = f" [evolution: {'; '.join(evo_parts)}]"
        lines.append(f"- **{p['name']}** — {p['definition']} [principles: {principles_str}]{evo_str}")
    lines.append("")

    # Scoped Principles
    lines.append(f"### Scoped Principles ({len(principles)})")
    for p in principles:
        confidence = p.get("confidence", "unknown")
        regime = p.get("regime", "")
        regime_str = f" | regime: {regime}" if regime else ""
        lines.append(f"- **{p['id']}** ({confidence}): {p['statement']}{regime_str}")
    lines.append("")

    # Dead-Ends
    lines.append(f"### Dead-Ends ({len(dead_ends)})")
    for d in dead_ends:
        lines.append(f"- **{d.get('id', '?')}**: {d.get('title', '')} — tried: {d.get('what_was_tried', '')} | failed: {d.get('why_it_failed', '')} | avoid when: {d.get('avoid_when', '')}")
    lines.append("")

    # Frontiers
    lines.append(f"### Frontiers ({len(frontiers)})")
    for f in frontiers:
        lines.append(f"- **{f.get('id', '?')}**: {f.get('title', '')} — untried: {f.get('what_was_left_untried', '')} | try next: {f.get('what_to_try_next', '')}")
    lines.append("")

    # Interactions
    lines.append(f"### Interactions ({len(interactions)})")
    for i in interactions:
        lines.append(f"- **{i.get('id', '?')}**: {i.get('title', '')} — A: {i.get('approach_a', '')} | B: {i.get('approach_b', '')} | why: {i.get('why_combine', '')} | experiment: {i.get('experiment_to_run', '')}")
    lines.append("")

    # Cost Context
    if cost_context:
        lines.append(f"### Cost Context ({len(cost_context)} campaigns with metrics)")
        lines.append("| Campaign | Iters | Total Cost | $/Iter | Design Model | Execute Model |")
        lines.append("|----------|-------|-----------|--------|--------------|---------------|")
        total_cost_all = 0.0
        total_iters_all = 0
        total_design = 0.0
        total_execute = 0.0
        for name, stats in cost_context.items():
            lines.append(
                f"| {name} | {stats['iterations']} | ${stats['total_cost_usd']:.2f} "
                f"| ${stats['cost_per_iteration']:.2f} | {stats['design_model'] or '—'} "
                f"| {stats['execute_model'] or '—'} |"
            )
            total_cost_all += stats["total_cost_usd"]
            total_iters_all += stats["iterations"]
            total_design += stats["design_cost_usd"]
            total_execute += stats["execute_cost_usd"]
        lines.append("")
        avg_per_iter = total_cost_all / total_iters_all if total_iters_all else 0
        design_pct = round(100 * total_design / total_cost_all) if total_cost_all else 0
        execute_pct = 100 - design_pct
        lines.append(f"**Project averages:** ${avg_per_iter:.2f}/iter, {design_pct}% design / {execute_pct}% execute split")
        lines.append(f"**Total project research investment:** ${total_cost_all:.2f} across {total_iters_all} iterations")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve structured context from Nous wiki for research planning"
    )
    parser.add_argument(
        "--campaigns", "-c", nargs="+", required=True,
        help="Campaign names to retrieve from"
    )
    parser.add_argument(
        "--entities", "-e", nargs="+", required=True,
        help="Entity names to seed the graph traversal"
    )
    parser.add_argument(
        "--intent", "-i", default="",
        help="Research intent (included in context block header)"
    )
    parser.add_argument(
        "--wiki-dir", "-w", default=str(Path.home() / ".nous" / "wiki"),
        help="Path to wiki directory (default: ~/.nous/wiki/)"
    )
    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    if not wiki_dir.exists():
        print(f"Error: wiki directory not found: {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    context = retrieve_context(
        wiki_dir=wiki_dir,
        campaign_names=args.campaigns,
        entity_names=args.entities,
        intent=args.intent,
    )
    print(context)


if __name__ == "__main__":
    main()
