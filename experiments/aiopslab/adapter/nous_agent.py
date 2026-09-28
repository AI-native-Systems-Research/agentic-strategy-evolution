"""NousAgent — an AIOpsLab-side agent that delegates investigation to a Nous campaign.

AIOpsLab drives the loop (init_context once, then get_action per step). Nous is itself an
orchestrator with no stepwise action API, so on the first get_action we run ONE Nous campaign
(live_target mode) that investigates the cluster, then return a single submit(...) with its
diagnosis. See DESIGN.md.
"""

import ast
import json
import os
import subprocess
import time
from pathlib import Path

import yaml

# experiments/aiopslab/adapter/nous_agent.py -> repo root is parents[3]
NOUS_REPO = Path(__file__).resolve().parents[3]
METHODOLOGY = NOUS_REPO / "prompts" / "methodology"


class NousAgent:
    def __init__(self, run_dir, task_type, problem_id,
                 model="claude-opus-4-6", max_iterations=1, nous_bin="nous"):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.task_type = task_type            # detection | localization | ...
        self.problem_id = problem_id
        self.model = model
        self.max_iterations = max_iterations
        self.nous_bin = nous_bin
        self.answer_file = self.run_dir / "nous_answer.txt"
        self.workspace = self.run_dir / "workspace"
        self.workspace.mkdir(exist_ok=True)
        self.campaign_path = self.run_dir / "campaign.yaml"
        self._submit = None
        self.meta = {"problem_id": problem_id, "task_type": task_type, "model": model,
                     "max_iterations": max_iterations}

    # ---- AIOpsLab agent contract -------------------------------------------
    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        contract = self._answer_contract()
        rq = (f"Investigate this live AIOpsLab {self.task_type} problem on a Kubernetes cluster "
              f"and determine the answer.\n\n{problem_desc}\n\n{contract}")
        desc = (
            "A live Kubernetes microservice cluster (kind) with an injected fault. "
            "Investigate with kubectl and Prometheus via the shell. "
            + self._observe_only_clause()
            + f"\n\nAIOpsLab task instructions:\n{instructions}\n\n{contract}"
        )
        spec = {
            "research_question": rq,
            "run_id": f"aiopslab-{self.problem_id}",
            "max_iterations": self.max_iterations,
            "target_system": {
                "name": f"AIOpsLab::{self.problem_id}",
                "description": desc,
                "repo_path": str(self.workspace),
                "live_target": True,
                "observable_metrics": ["pod_status", "logs", "latency", "error_rate"],
                "controllable_knobs": ["kubectl", "prometheus_query"],
            },
            "models": {"design": self.model, "execute_analyze": self.model, "report": self.model},
            "prompts": {"methodology_layer": str(METHODOLOGY), "domain_adapter_layer": None},
        }
        self.campaign_path.write_text(yaml.safe_dump(spec, sort_keys=False))
        self.meta["campaign"] = str(self.campaign_path)

    async def get_action(self, input):
        if self._submit is None:
            self._run_campaign()
            self._submit = self._read_answer()
        return self._submit

    # ---- helpers -----------------------------------------------------------
    def _observe_only_clause(self):
        if self.task_type in ("detection", "localization", "analysis"):
            return ("CRITICAL: OBSERVE-ONLY. Do NOT modify, restart, scale, delete, patch, or "
                    "reconfigure any cluster resource. Use only read commands (kubectl "
                    "get/describe/logs/top, prometheus queries). Mutating the cluster invalidates the result.")
        if self.task_type == "mitigation":
            return ("You MUST apply a fix to the LIVE cluster (kubectl edit/patch/scale/apply/rollout/"
                    "delete as appropriate) to mitigate the fault, then VERIFY the affected pods/services "
                    "recover (pods Ready, errors cleared) before finishing.")
        return ""

    def _answer_contract(self):
        if self.task_type == "detection":
            fmt = 'Write EXACTLY one word: Yes (if anomalies/faults present) or No.'
        elif self.task_type == "localization":
            fmt = 'Write a JSON list of faulty component service name(s), e.g. ["geo"], or [] if none.'
        elif self.task_type == "analysis":
            fmt = ('Write a JSON object with keys "system_level" (one of: Hardware, '
                   '"Operating System", Virtualization, Application) and "fault_type" (one of: '
                   'Misconfiguration, "Code Defect", "Authentication Issue", "Network/Storage Issue", '
                   '"Operation Error", "Dependency Problem"). If no fault, write exactly: NONE')
        elif self.task_type == "mitigation":
            fmt = ('After you have APPLIED a fix to the cluster AND verified the affected service '
                   'recovered (pods Ready, errors cleared), write the single word DONE.')
        else:
            fmt = "Write your final answer."
        return ("ANSWER CONTRACT (mandatory terminal step): " + fmt
                + "\nWrite it (and nothing else) to this exact file, overwriting any prior content:\n"
                + str(self.answer_file))

    def _run_campaign(self):
        env = dict(os.environ)
        env["NOUS_CAMPAIGN_PARENT"] = str(self.run_dir / "nous_runs")
        env["NOUS_ANSWER_FILE"] = str(self.answer_file)
        if self.answer_file.exists():
            self.answer_file.unlink()
        log = self.run_dir / "nous_run.log"
        cmd = [self.nous_bin, "run", str(self.campaign_path),
               "--auto-approve", "--agent", "sdk", "--sandbox", "bypass",
               "--max-iterations", str(self.max_iterations)]
        self.meta["nous_cmd"] = " ".join(cmd)
        t0 = time.time()
        with open(log, "w") as lf:
            proc = subprocess.run(cmd, cwd=str(NOUS_REPO), env=env,
                                  stdout=lf, stderr=subprocess.STDOUT, text=True)
        self.meta["nous_seconds"] = round(time.time() - t0, 1)
        self.meta["nous_exit"] = proc.returncode

    _EMPTY = "__EMPTY_SUBMIT__"

    def _read_answer(self):
        if self.task_type == "mitigation":
            raw = self.answer_file.read_text().strip() if self.answer_file.exists() else None
            self.meta["raw_answer"] = raw
            self.meta["answer_valid"] = bool(raw)   # DONE written = agent claims it finished the fix
            return "```\nsubmit()\n```"              # mitigation submit takes no args; eval checks recovery
        raw = self.answer_file.read_text().strip() if self.answer_file.exists() else None
        self.meta["raw_answer"] = raw
        literal = self._to_literal(raw) if raw else None
        self.meta["answer_valid"] = literal is not None
        if literal == self._EMPTY:                      # no-fault submission -> submit()
            return "```\nsubmit()\n```"
        if literal is None:                             # fallback default (marked invalid)
            self.meta["used_default"] = True
            default = {"detection": '"No"', "localization": "[]", "analysis": None}.get(self.task_type, "[]")
            if default is None:
                return "```\nsubmit()\n```"
            literal = default
        # one fenced code block, single call — required by AIOpsLab ResponseParser
        return f"```\nsubmit({literal})\n```"

    def _to_literal(self, raw):
        try:
            if self.task_type == "detection":
                low = raw.lower()
                if "yes" in low and "no" not in low.replace("yes", ""):
                    return '"Yes"'
                val = raw.strip().strip('"').strip("'").capitalize()
                if val in ("Yes", "No"):
                    return json.dumps(val)
                return '"Yes"' if "yes" in low else ('"No"' if "no" in low else None)
            if self.task_type == "localization":
                data = json.loads(raw)
                return json.dumps(data) if isinstance(data, list) else None
            if self.task_type == "analysis":
                if raw.strip().upper() == "NONE":
                    return self._EMPTY
                data = json.loads(raw)
                if isinstance(data, dict) and "system_level" in data and "fault_type" in data:
                    return json.dumps({"system_level": data["system_level"],
                                       "fault_type": data["fault_type"]})
                return None
            return json.dumps(raw)
        except Exception:
            return None

    def _filter_dict(self, d, f):
        return {k: v for k, v in d.items() if f(k, v)}
