"""Benchmark-faithful access rule shared by every agent's sandbox and prompt.

Visible (read-only): the task README and its resources/ dir, as the task statement intends.
Hidden: the evaluator, test datasets (resources/datasets), reference solutions, every other run's
artifacts/logs/transcripts, other agents' repos. Web tools are disabled separately.
"""
import os
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
HIDDEN_IN_RESOURCES = ["datasets"]


def probdir(pid):
    return Path(FRONTIER) / "research" / "problems" / str(pid)


def visible_paths(pid):
    pd = os.path.realpath(probdir(pid))
    return [f"{pd}/readme", f"{pd}/resources"]


def sbpl_task_access(pid):
    """SBPL lines to append AFTER the deny rules: re-allow the task's visible files, keep test data hidden."""
    pd = os.path.realpath(probdir(pid))
    lines = [f'(allow file-read* (literal "{pd}/readme"))\n', f'(allow file-read* (subpath "{pd}/resources"))\n']
    lines += [f'(deny file-read* (subpath "{pd}/resources/{h}"))\n' for h in HIDDEN_IN_RESOURCES]
    return "".join(lines)


def prompt_rules(pid):
    pd = os.path.realpath(probdir(pid))
    return (f"ACCESS: the task README and its resources are available read-only at {pd}/readme and "
            f"{pd}/resources/ -- explore them freely. The evaluator, test datasets ({pd}/resources/datasets/), "
            f"reference solutions, and any other runs' files are hidden; do not try to access them. "
            f"Solve legitimately: do NOT use import hooks / sys.meta_path, do NOT read test/label data, and do "
            f"NOT tamper with what the evaluator measures; such solutions are rejected and score 0.")
