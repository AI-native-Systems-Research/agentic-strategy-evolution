"""Shared iso-cost ruler for every Claude-Code-based agent (Nous and the Claude baseline).

Cost = tokens x fixed $15 in / $75 out / $18.75 cache-write / $1.50 cache-read per M, model-independent.
Usage comes from the Claude Code transcripts the CLI writes live under <config>/projects/<cwd-key>*.
One assistant reply is written as several transcript lines that repeat the same usage, so each reply is
counted once (by message id, keeping its largest usage). Summing every line double-counts.
"""
import glob, json, os, re
from pathlib import Path

R_IN, R_OUT, R_CW, R_CR = 15 / 1e6, 75 / 1e6, 18.75 / 1e6, 1.5 / 1e6


def usage_cost(u):
    return (u.get("input_tokens", 0) * R_IN + u.get("output_tokens", 0) * R_OUT
            + u.get("cache_creation_input_tokens", 0) * R_CW + u.get("cache_read_input_tokens", 0) * R_CR)


def project_key(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cwd)))


def transcript_cost(cwd, config_dir=None, since=0.0):
    """Cost of every transcript whose session cwd is `cwd` or a dir below it (worktrees included)."""
    root = Path(config_dir or os.path.expanduser("~/.claude")) / "projects"
    per_msg = {}
    for f in glob.glob(str(root / f"{project_key(cwd)}*" / "**" / "*.jsonl"), recursive=True):
        if os.path.getmtime(f) < since: continue
        for ln in open(f, errors="ignore"):
            try: d = json.loads(ln)
            except ValueError: continue
            m = d.get("message") if isinstance(d.get("message"), dict) else None
            u = m.get("usage") if m else None
            if not u: continue
            k = m.get("id") or f"{f}:{d.get('uuid')}"
            per_msg[k] = max(per_msg.get(k, 0.0), usage_cost(u))
    return round(sum(per_msg.values()), 4)
