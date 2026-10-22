"""Secret masking for Nous v2 artifacts (spec 3.14).

Prevents secret values from leaking into answer.json, report.md,
or other REPORT-phase artifacts.
"""

from __future__ import annotations


def mask_secrets(text: str, secrets: dict[str, str]) -> str:
    """Replace each secret value with ``<secret:NAME>``."""
    if not secrets:
        return text
    result = text
    # Sort by length descending so longer values are replaced first,
    # preventing partial matches when one secret is a substring of another.
    for name, value in sorted(secrets.items(), key=lambda kv: -len(kv[1])):
        if value:
            result = result.replace(value, f"<secret:{name}>")
    return result


def check_secrets(text: str, secrets: dict[str, str]) -> list[str]:
    """Return list of secret names whose values appear in *text*."""
    if not secrets:
        return []
    found: list[str] = []
    for name, value in secrets.items():
        if value and value in text:
            found.append(name)
    return sorted(found)
