"""Benchmark-faithful access rule shared by every agent's sandbox and prompt.

Visible (read-only): the task README and its resources/ dir, as the task statement intends.
Hidden: the evaluator, test datasets (resources/datasets), reference solutions, every other run's
artifacts/logs/transcripts, other agents' repos. Web tools are disabled separately.
"""
import os
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
HIDDEN_IN_RESOURCES = ["datasets"]


def is_algo(pid):
    """Algorithmic problem ids are integers; research ids are paths like grammar_fuzzing/seed/sql."""
    return str(pid).isdigit()


def probdir(pid):
    track = "algorithmic" if is_algo(pid) else "research"
    return Path(FRONTIER) / track / "problems" / str(pid)


def statement(pid):
    p = probdir(pid) / ("statement.txt" if is_algo(pid) else "readme")
    return p.read_text() if p.exists() else f"(problem {pid})"


def visible_paths(pid):
    pd = os.path.realpath(probdir(pid))
    return [f"{pd}/readme", f"{pd}/resources"]


def sbpl_task_access(pid):
    """SBPL lines to append AFTER the deny rules: re-allow the task's visible files, keep test data hidden."""
    if is_algo(pid):
        return ""  # the statement is in the prompt; the problem dir holds only judge data
    pd = os.path.realpath(probdir(pid))
    lines = [f'(allow file-read* (literal "{pd}/readme"))\n', f'(allow file-read* (subpath "{pd}/resources"))\n']
    lines += [f'(deny file-read* (subpath "{pd}/resources/{h}"))\n' for h in HIDDEN_IN_RESOURCES]
    return "".join(lines)


def prompt_rules(pid):
    if is_algo(pid):
        return ("ACCESS: the full problem statement is given below. The judge, its test data and answer files, "
                "reference solutions, and any other runs' files are hidden; do not try to access them. Solve it "
                "algorithmically: do NOT hard-code expected outputs or read judge data; such solutions are rejected.")
    pd = os.path.realpath(probdir(pid))
    return (f"ACCESS: the task README and its resources are available read-only at {pd}/readme and "
            f"{pd}/resources/ -- explore them freely. The evaluator, test datasets ({pd}/resources/datasets/), "
            f"reference solutions, and any other runs' files are hidden; do not try to access them. "
            f"Solve legitimately: do NOT use import hooks / sys.meta_path, do NOT read test/label data, and do "
            f"NOT tamper with what the evaluator measures; such solutions are rejected and score 0.")


JUDGE_TMP_ROOTS = ["/tmp/fcs_judge", "/tmp/fcs_rjudge2", "/tmp/fcs_rjudge_csdk"]


def sbpl_judge_tmp(own_root):
    """Deny every run's judge inbox/outbox under /tmp except this run's own (SBPL: last match wins)."""
    lines = [f'(deny file-read* (subpath "{os.path.realpath(r)}"))\n' for r in JUDGE_TMP_ROOTS]
    lines.append(f'(allow file-read* (subpath "{os.path.realpath(own_root)}"))\n')
    return "".join(lines)
