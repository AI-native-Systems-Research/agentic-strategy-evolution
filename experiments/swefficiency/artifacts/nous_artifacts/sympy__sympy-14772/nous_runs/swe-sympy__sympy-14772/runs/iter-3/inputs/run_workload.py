#!/usr/bin/env python
"""Workload runner that captures structured JSON output for the experiment."""
import subprocess
import sys
import json
import os
import re

def run_workload(seed_label, output_path, worktree_path):
    """Run the workload and capture results as JSON."""
    env = os.environ.copy()
    env['PYTHONPATH'] = worktree_path

    result = subprocess.Popen(
        ['/opt/miniconda3/envs/testbed/bin/python', '/tmp/workload.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=worktree_path
    )
    stdout, stderr = result.communicate()
    stdout = stdout.decode('utf-8')
    stderr = stderr.decode('utf-8')

    if result.returncode != 0:
        data = {
            'seed': seed_label,
            'exit_code': result.returncode,
            'error': stderr,
            'stdout': stdout
        }
    else:
        mean_match = re.search(r'Mean:\s+([\d.eE+-]+)', stdout)
        std_match = re.search(r'Std Dev:\s+([\d.eE+-]+)', stdout)
        mean_val = float(mean_match.group(1)) if mean_match else None
        std_val = float(std_match.group(1)) if std_match else None
        speedup = 0.0743 / mean_val if mean_val and mean_val > 0 else None

        data = {
            'seed': seed_label,
            'exit_code': 0,
            'mean_seconds': mean_val,
            'std_dev_seconds': std_val,
            'speedup': speedup,
            'raw_stdout': stdout.strip()
        }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    return data

if __name__ == '__main__':
    seed = sys.argv[1]
    output = sys.argv[2]
    worktree = sys.argv[3]
    data = run_workload(seed, output, worktree)
    print(json.dumps(data, indent=2))
