import argparse
import sys
from pathlib import Path

import yaml


def _find_repo_root(start=None):
    current = Path(start) if start else Path.cwd()
    while True:
        if (current / ".nous").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    print("Could not find .nous/ directory in any parent", file=sys.stderr)
    sys.exit(1)


def resolve_work_dir(target):
    if target.endswith(".yaml") or target.endswith(".yml"):
        p = Path(target)
        if not p.exists():
            print(f"Campaign file not found: {target}", file=sys.stderr)
            sys.exit(1)
        with open(p) as f:
            data = yaml.safe_load(f)
        repo_path = Path(data["target_system"]["repo_path"])
        run_id = data["run_id"]
        work_dir = repo_path / ".nous" / run_id
        return work_dir

    p = Path(target)
    if p.is_dir() and (p / "state.json").exists():
        return p

    run_id = target
    root = _find_repo_root()
    work_dir = root / ".nous" / run_id
    if not work_dir.is_dir():
        print(f"Work directory not found: {work_dir}", file=sys.stderr)
        sys.exit(1)
    return work_dir


def _cmd_run(args):
    pass


def _cmd_resume(args):
    pass


def _cmd_validate(args):
    pass


def _cmd_status(args):
    pass


def _cmd_cost(args):
    pass


def _cmd_report(args):
    pass


def _cmd_replay(args):
    pass


def main():
    parser = argparse.ArgumentParser(prog="nous")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run")
    p_run.add_argument("campaign")
    p_run.add_argument("--max-iterations", type=int)
    p_run.add_argument("--model")
    p_run.add_argument("--run-id")
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument("--timeout", type=int, default=1800)
    p_run.add_argument("--max-cli-retries", type=int, default=10)
    p_run.add_argument("--agent", choices=["inline", "api"], default="api")
    p_run.set_defaults(func=_cmd_run)

    p_resume = subparsers.add_parser("resume")
    p_resume.add_argument("target")
    p_resume.add_argument("--max-iterations", type=int)
    p_resume.add_argument("--model")
    p_resume.add_argument("--auto-approve", action="store_true")
    p_resume.add_argument("--timeout", type=int, default=1800)
    p_resume.add_argument("--max-cli-retries", type=int, default=10)
    p_resume.add_argument("--agent", choices=["inline", "api"], default="api")
    p_resume.set_defaults(func=_cmd_resume)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("phase", choices=["design", "execution"])
    p_validate.add_argument("--dir", required=True, type=Path)
    p_validate.set_defaults(func=_cmd_validate)

    p_status = subparsers.add_parser("status")
    p_status.add_argument("target")
    p_status.set_defaults(func=_cmd_status)

    p_cost = subparsers.add_parser("cost")
    p_cost.add_argument("target")
    p_cost.set_defaults(func=_cmd_cost)

    p_report = subparsers.add_parser("report")
    p_report.add_argument("target")
    p_report.add_argument("--model")
    p_report.add_argument("--timeout", type=int, default=1800)
    p_report.add_argument("--agent", choices=["inline", "api"], default="api")
    p_report.set_defaults(func=_cmd_report)

    p_replay = subparsers.add_parser("replay")
    p_replay.add_argument("target")
    p_replay.add_argument("--iter", required=True, type=int)
    p_replay.add_argument("--model")
    p_replay.add_argument("--timeout", type=int, default=1800)
    p_replay.add_argument("--agent", choices=["inline", "api"], default="api")
    p_replay.set_defaults(func=_cmd_replay)

    args = parser.parse_args()
    if not args.command:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
