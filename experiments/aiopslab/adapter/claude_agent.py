"""ClaudeCodeAgent — the true "plain Claude Code" L0 baseline.

Same base agent Nous wraps (the `claude` agent, same model + tools + API path), driven
headless on the task with NO Nous methodology. Comparing Nous vs this isolates the
*methodology* contribution (base agent held constant), unlike AIOpsLab's own GenericOpenAI
agent which is a different scaffold + API. Reuses NousAgent's answer-contract/parse logic.
"""
import os
import subprocess
import time

from nous_agent import NousAgent


class ClaudeCodeAgent(NousAgent):
    def init_context(self, problem_desc, instructions, apis):
        contract = self._answer_contract()
        parts = [
            "You are an SRE investigating a LIVE Kubernetes cluster to solve an AIOpsLab task.",
            problem_desc,
            "AIOpsLab task instructions (for the expected answer shape):",
            instructions,
            self._observe_only_clause(),
            "Investigate using kubectl and Prometheus via the shell (Bash), then complete the "
            "ANSWER CONTRACT below.",
            contract,
        ]
        self.prompt = "\n\n".join(p for p in parts if p)
        (self.run_dir / "prompt.txt").write_text(self.prompt)
        self.meta["prompt_file"] = str(self.run_dir / "prompt.txt")
        self.meta["agent"] = "plain_claude_code"

    def _run_campaign(self):
        env = dict(os.environ)
        if self.answer_file.exists():
            self.answer_file.unlink()
        log = self.run_dir / "claude_run.log"
        cmd = ["claude", "-p", "--model", self.model,
               "--permission-mode", "bypassPermissions",
               "--allowedTools", "Bash", "--output-format", "text"]
        self.meta["claude_cmd"] = " ".join(cmd) + " (prompt via stdin)"
        t0 = time.time()
        with open(log, "w") as lf:
            proc = subprocess.run(cmd, cwd=str(self.workspace), env=env, input=self.prompt,
                                  stdout=lf, stderr=subprocess.STDOUT, text=True)
        self.meta["claude_seconds"] = round(time.time() - t0, 1)
        self.meta["claude_exit"] = proc.returncode
