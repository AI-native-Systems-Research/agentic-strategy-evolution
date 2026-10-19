"""One cost ruler for every arm: token counts from Claude Code transcripts x a fixed public price table, per model.

Each run gets its own CLAUDE_CONFIG_DIR, so every Claude Code session of that run (any arm, any cwd, including Nous's
per-iteration worktrees) writes its transcript under <config_dir>/projects/. One assistant reply is written as several
transcript lines that repeat the same usage, so each reply is counted once (by message id, keeping its largest usage).

Nous also makes a few direct LLM API calls (gate summaries, final report) that do not go through Claude Code; those are
read from the campaign's llm_metrics.jsonl (dispatcher "llm") and priced with the same table.

Prices per million tokens (input, output; cache write = 1.25x input, cache read = 0.1x input), matching the
Claude Code CLI's own pricing for these models (checked: our meter reproduces the CLI's total_cost_usd exactly for
claude-opus-4-6 and claude-sonnet-4-6 on the same usage).
"""
import glob
import json
import os

PRICES = {  # $ per 1M tokens: input, output
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def price_for(model):
    m = (model or "").lower()
    for k, v in PRICES.items():
        if k in m:
            return v
    raise ValueError(f"no price for model {model!r}; add it to PRICES")


def usage_cost(u, model):
    pin, pout = price_for(model)
    return (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout +
            u.get("cache_creation_input_tokens", 0) * pin * 1.25 + u.get("cache_read_input_tokens", 0) * pin * 0.1) / 1e6


def transcript_cost(config_dir):
    per_msg, by_model = {}, {}
    for f in glob.glob(os.path.join(config_dir, "projects", "**", "*.jsonl"), recursive=True):
        for ln in open(f, errors="ignore"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d.get("message"), dict) else None
            u = m.get("usage") if m else None
            if not u:
                continue
            k = m.get("id") or f"{f}:{d.get('uuid')}"
            c = usage_cost(u, m.get("model"))
            if c > per_msg.get(k, (0.0, None))[0]:
                per_msg[k] = (c, m.get("model"))
    for c, mdl in per_msg.values():
        by_model[mdl] = by_model.get(mdl, 0.0) + c
    return round(sum(c for c, _ in per_msg.values()), 4), {k: round(v, 4) for k, v in by_model.items()}, len(per_msg)


def direct_llm_cost(campaign_dir):
    """Nous's non-Claude-Code calls (dispatcher=llm), from llm_metrics.jsonl, same price table."""
    tot = 0.0
    for f in glob.glob(os.path.join(campaign_dir, "**", "llm_metrics.jsonl"), recursive=True):
        for ln in open(f, errors="ignore"):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("dispatcher") != "llm":
                continue
            tot += usage_cost(r, r.get("model"))
    return round(tot, 4)


def run_cost(config_dir, campaign_dir=None):
    t, by_model, n = transcript_cost(config_dir)
    d = direct_llm_cost(campaign_dir) if campaign_dir else 0.0
    return dict(total=round(t + d, 4), transcripts=t, direct_llm=d, by_model=by_model, n_replies=n)
