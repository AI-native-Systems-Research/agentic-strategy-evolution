"""Identical macOS sandbox (sandbox-exec) for every arm.

- Network: only localhost (the per-run LLM proxy). No internet, so no `git clone` of the public repo, no web search.
- File reads denied: answer keys, oracle, other runs, the original BLIS checkouts (they contain the fix in git history),
  the paper folders, the user's Claude config/transcripts, other agent repos.
- File writes allowed only in this run's directory, the Go/pip caches, and temp dirs.
"""
import os

HOME = os.path.expanduser("~")
RUNS = os.path.join(HOME, "mlsys_runs")
PAPER = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
NOUS_SRC = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
NOUS = os.path.join(RUNS, "nous")  # pinned Nous runtime (copy of the mlsys-exp commit), outside denied folders

DENY_READ = [
    os.path.join(RUNS, "keys"),
    os.path.join(RUNS, "repos", "blis-dbg-fixed"),
    os.path.join(RUNS, "repos", "blis-dbg-base"),
    os.path.join(NOUS, "experiments"),
    NOUS_SRC,
    PAPER,                                   # paper folder: campaigns, keys, oracle, other checkouts
    os.path.join(HOME, "Desktop"),
    os.path.join(HOME, "Downloads"),
    os.path.join(HOME, "Documents"),
    os.path.join(HOME, ".claude"),
    os.path.join(HOME, "nous_repo"),
    os.path.join(HOME, "engram_repo"),
    os.path.join(HOME, "frontier"),
]


def _other_runs(run_dir):
    """Deny every task/arm/rep dir that is not on the path to this run. Parents stay traversable (git needs them)."""
    root = os.path.realpath(os.path.join(RUNS, "runs"))
    rel = os.path.relpath(os.path.realpath(run_dir), root).split(os.sep)  # [task, arm, rep]
    out, cur = [], root
    for part in rel:
        if os.path.isdir(cur):
            out += [os.path.join(cur, d) for d in os.listdir(cur) if d != part]
        cur = os.path.join(cur, part)
    return out


def profile(run_dir, allow_read_extra=()):
    rr = os.path.realpath
    lines = ["(version 1)", "(allow default)",
             "(deny network*)",
             '(allow network* (remote ip "localhost:*"))',
             '(allow network* (remote unix-socket))',
             '(allow network-bind (local ip "localhost:*"))']
    lines += [f'(deny file-read* (subpath "{rr(p)}"))' for p in DENY_READ if os.path.exists(p)]
    lines += [f'(deny file-read* (subpath "{p}"))' for p in _other_runs(run_dir)]
    # re-allow what the arm legitimately needs (later rules win in SBPL)
    allow = [run_dir, NOUS + "/.venv", NOUS + "/orchestrator", NOUS + "/prompts", NOUS + "/bin", NOUS + "/plugin",
             NOUS + "/pyproject.toml", NOUS + "/CLAUDE.md", RUNS + "/harness", "/opt/anaconda3", "/opt/homebrew",
             os.path.join(HOME, "go"), os.path.join(HOME, "Library", "Caches", "go-build"), *allow_read_extra]
    lines += [f'(allow file-read* (subpath "{rr(p)}"))' for p in allow if os.path.exists(p)]
    lines += ["(deny file-write*)"]
    writable = [run_dir, os.path.join(HOME, "go"), os.path.join(HOME, "Library", "Caches"), "/private/tmp",
                "/private/var/folders", "/dev"]
    lines += [f'(allow file-write* (subpath "{rr(p)}"))' for p in writable if os.path.exists(p)]
    return "\n".join(lines) + "\n"
