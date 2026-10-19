"""Per-reply timeline of a Nous run's Claude Code sessions (zero LLM tokens; reads transcripts only).

For each reply: when it finished, seconds since the previous event, output tokens, tokens/s, stop reason,
what it contained (thinking / text / tool_use), and how often its thinking second-guesses itself
("Actually", "Wait", "Let me recheck"). For each session, how long it has been silent and how many API errors
arrived since its last reply. A long thinking reply streams at a steady ~65 tok/s with no API errors; a gateway
stall shows api_error lines and no reply.

Usage: python gen/reply_timeline.py <slug like p58-v8c50s2> [--min-out 20000]
"""
import glob
import json
import os
import re
import sys
import time
from datetime import datetime

BASE = os.path.expanduser("~/.claude/projects")
SECOND_GUESS = re.compile(r"\b(Actually|Wait|Hmm|Let me reconsider|Let me recheck|Let me verify)\b")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def session(path):
    prev, last_reply, rows, errors_since = None, None, [], 0
    first_prompt = ""
    for line in open(path):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = r.get("timestamp")
        if not t:
            continue
        m = r.get("message")
        if not first_prompt and r.get("type") == "user" and isinstance(m, dict) and isinstance(m.get("content"), str):
            first_prompt = m["content"].split("\n", 1)[0][:60]
        if r.get("type") == "system" and r.get("subtype") == "api_error":
            errors_since += 1
        if r.get("type") == "assistant" and isinstance(m, dict) and m.get("usage"):
            if rows and m.get("id") and rows[-1].get("id") == m.get("id"):  # same reply, next content block
                rows[-1]["kinds"] = sorted(set(rows[-1]["kinds"]) | {b.get("type") for b in m.get("content") or []
                                                                    if isinstance(b, dict)})
                last_reply, errors_since = ts(t), 0
                continue
            blocks = [b for b in m.get("content") or [] if isinstance(b, dict)]
            think = " ".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
            out = int(m["usage"].get("output_tokens", 0) or 0)
            dt = ts(t) - prev if prev else 0.0
            rows.append({"id": m.get("id"), "at": t[11:19], "secs": round(dt), "out": out,
                         "tok_s": round(out / dt) if dt > 5 else None, "stop": m.get("stop_reason"),
                         "kinds": sorted({b.get("type") for b in blocks}),
                         "second_guesses": len(SECOND_GUESS.findall(think))})
            last_reply, errors_since = ts(t), 0
        if r.get("type") in ("user", "assistant"):
            prev = ts(t)
    return first_prompt, rows, last_reply, errors_since


def main():
    slug = sys.argv[1]
    min_out = int(sys.argv[sys.argv.index("--min-out") + 1]) if "--min-out" in sys.argv else 20000
    now = time.time()
    for d in sorted(glob.glob(f"{BASE}/-Users-toslali-frontier-gen-logs-research-{slug}-ws*"),
                    key=os.path.getmtime):
        for f in sorted(glob.glob(d + "/*.jsonl"), key=os.path.getmtime):
            prompt, rows, last, errs = session(f)
            if not rows:
                continue
            silent = round(now - last) if last else None
            big = [r for r in rows if r["out"] >= min_out]
            print(f"{os.path.basename(d)[-24:]} | {prompt} | replies {len(rows)}, big {len(big)}, "
                  f"silent {silent}s, api errors since last reply {errs}")
            for r in big:
                print(f"    {r['at']} {r['secs']:>5}s out {r['out']:>6} {r['tok_s'] or '-':>4} tok/s "
                      f"stop={r['stop']} {','.join(r['kinds'])} second-guesses={r['second_guesses']}")


if __name__ == "__main__":
    main()
