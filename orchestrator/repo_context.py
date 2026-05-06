"""Gather repo context for claude -p prompts (no AI, instant)."""
import subprocess
from pathlib import Path


def gather_repo_context(repo_path: Path) -> str:
    """Run quick shell commands to build context string for prompts.

    Returns formatted string with repo tree, build file, and CLI help.
    """
    parts = []

    # 1. File tree (depth 2, max 80 lines)
    try:
        tree = subprocess.run(
            ["find", ".", "-maxdepth", "2", "-type", "f",
             "-not", "-path", "./.git/*"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        if tree.returncode == 0:
            lines = tree.stdout.strip().split("\n")[:80]
            parts.append(f"## Repo Structure\n```\n{chr(10).join(lines)}\n```")
    except (subprocess.TimeoutExpired, OSError):
        pass

    # 2. Build file (first found)
    for bf in ["Makefile", "go.mod", "package.json", "pyproject.toml", "Cargo.toml"]:
        p = repo_path / bf
        if p.exists():
            content = p.read_text()[:2000]
            parts.append(f"## {bf}\n```\n{content}\n```")
            break

    # 3. CLI help (try common entry points)
    for entry in ["go run main.go", "go run .", "./main", "python -m ."]:
        try:
            result = subprocess.run(
                f"{entry} --help", shell=True, cwd=repo_path,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and len(result.stdout) > 20:
                parts.append(
                    f"## CLI Help (`{entry} --help`)\n```\n{result.stdout[:3000]}\n```"
                )
                break
        except (subprocess.TimeoutExpired, OSError):
            continue

    # 4. Example configs (list files in examples/ or similar dirs)
    for examples_dir in ["examples", "configs", "testdata"]:
        edir = repo_path / examples_dir
        if edir.is_dir():
            try:
                files = sorted(str(p.relative_to(repo_path)) for p in edir.iterdir() if p.is_file())[:20]
                if files:
                    parts.append(f"## Example Files (`{examples_dir}/`)\n```\n{chr(10).join(files)}\n```")
            except OSError:
                pass
            break

    return "\n\n".join(parts) if parts else "(no repo context gathered)"
