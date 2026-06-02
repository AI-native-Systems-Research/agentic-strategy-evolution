#!/usr/bin/env python3
"""Validate a concepts.json file for relationship integrity.

Checks:
  1. Every concept has operates_on (≥1) and parameters (≥0)
  2. Every parameter has parent_concept (exactly 1)
  3. No parameter appears in more than one concept's parameters array
  4. All names in operates_on exist in the entities array
  5. All names in concept.parameters exist in the parameters array
  6. Every parent_concept value matches a concept name
  7. Bidirectional consistency: concept.parameters ↔ parameter.parent_concept
  8. No orphaned parameters (not in any concept's parameters array)
  9. No unreachable entities (not in any concept's operates_on)

Usage:
    python scripts/validate_concepts.py <path-to-concepts.json>
    python scripts/validate_concepts.py ~/.nous/wiki/campaigns/*/concepts.json
"""

import json
import sys
from pathlib import Path


def validate(path: Path) -> list[str]:
    """Return a list of error strings. Empty = valid."""
    with open(path) as f:
        data = json.load(f)

    errors = []

    concept_names = {c["name"] for c in data.get("concepts", [])}
    param_names = {p["name"] for p in data.get("parameters", [])}
    entity_names = {e["name"] for e in data.get("entities", [])}

    # Track which parameters are claimed by concepts
    param_owners = {}  # param_name → list of concept names

    for concept in data.get("concepts", []):
        name = concept["name"]

        # Check operates_on exists and is non-empty
        operates_on = concept.get("operates_on")
        if operates_on is None:
            errors.append(f"concept '{name}': missing operates_on field")
        elif len(operates_on) == 0:
            errors.append(f"concept '{name}': operates_on is empty (need ≥1 entity)")
        else:
            for entity in operates_on:
                if entity not in entity_names:
                    errors.append(f"concept '{name}': operates_on references unknown entity '{entity}'")

        # Check parameters field exists
        params = concept.get("parameters")
        if params is None:
            errors.append(f"concept '{name}': missing parameters field")
        else:
            for p in params:
                if p not in param_names:
                    errors.append(f"concept '{name}': parameters references unknown parameter '{p}'")
                param_owners.setdefault(p, []).append(name)

    # Check for multi-ownership
    for p, owners in param_owners.items():
        if len(owners) > 1:
            errors.append(f"parameter '{p}': owned by multiple concepts: {owners}")

    for param in data.get("parameters", []):
        name = param["name"]

        # Check parent_concept exists
        parent = param.get("parent_concept")
        if parent is None:
            errors.append(f"parameter '{name}': missing parent_concept field")
        elif parent not in concept_names:
            errors.append(f"parameter '{name}': parent_concept '{parent}' not found in concepts")

        # Bidirectional check: parent concept should list this param
        if parent and parent in concept_names:
            parent_concept = next(c for c in data["concepts"] if c["name"] == parent)
            if name not in parent_concept.get("parameters", []):
                errors.append(f"parameter '{name}': parent_concept is '{parent}' but that concept doesn't list it in parameters")

    # Orphaned parameters
    claimed_params = set(param_owners.keys())
    for p in param_names:
        if p not in claimed_params:
            errors.append(f"parameter '{p}': orphaned — not in any concept's parameters array")

    # Unreachable entities
    referenced_entities = set()
    for concept in data.get("concepts", []):
        referenced_entities.update(concept.get("operates_on", []))
    for e in entity_names:
        if e not in referenced_entities:
            errors.append(f"entity '{e}': unreachable — not in any concept's operates_on")

    # Entity source grounding
    repo_path = data.get("repo_path")
    for entity in data.get("entities", []):
        source = entity.get("source")
        if not source:
            errors.append(f"entity '{entity['name']}': missing source field (not grounded to code)")
        elif repo_path:
            # source format: "relative/path/to/file.go::TypeName"
            file_part = source.split("::")[0]
            full_path = Path(repo_path) / file_part
            if not full_path.exists():
                errors.append(f"entity '{entity['name']}': source file not found: {full_path}")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_concepts.py <concepts.json> [...]", file=sys.stderr)
        sys.exit(1)

    all_valid = True
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"SKIP {path} (not found)")
            continue

        errors = validate(path)
        if errors:
            all_valid = False
            print(f"FAIL {path} ({len(errors)} errors):")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK   {path}")

    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
