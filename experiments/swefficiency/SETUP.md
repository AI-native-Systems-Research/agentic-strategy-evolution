# SWE-fficiency setup (reproducible) — Linux x86 VM

SWE-fficiency scores are RUNTIME speedups, so runs need a real x86_64 Docker host with the
**prebuilt amd64 images** (not the M1 — QEMU emulation corrupts timing; local arm64 build also
fails per-task on dependency re-resolution). We use a Linux VM; the agent LLM (Opus 4.6) is
reached from the VM via a reverse SSH tunnel to a Mac that has litellm/VPN access.

## VM (Ubuntu 24.04, x86_64, 8 vCPU / 31GB)
```bash
# docker
sudo apt-get update && sudo apt-get install -y docker.io python3-pip python3-venv git
sudo systemctl enable --now docker && sudo usermod -aG docker $USER   # re-login, or: sudo chmod 666 /var/run/docker.sock
# swefficiency
mkdir -p ~/nous_swe && cd ~/nous_swe && git clone https://github.com/swefficiency/swefficiency
cd swefficiency && python3 -m venv .venv && . .venv/bin/activate && pip install -e .
# agent CLI (for generation)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs
sudo npm install -g @anthropic-ai/claude-code
```

### Required patch (small-machine CPU pinning)
`swefficiency/harness/run_validation.py` hardcodes `allocate_whole_cores(max_workers,
vcpus_per_worker=4, threads_per_core=2, reserve_cores=4)` (tuned for 64-vCPU). On an 8-vCPU
(=4 physical core) box, `reserve_cores=4` leaves 0. Patch:
```bash
sed -i "s/vcpus_per_worker=4,/vcpus_per_worker=2,/; s/reserve_cores=4,/reserve_cores=0,/" \
  swefficiency/harness/run_validation.py
```
Then run with `--num_workers 2` (need 2 cores, have 4).

## litellm reverse tunnel (from the Mac that has VPN)
```bash
# on the VM: map the litellm host to loopback so TLS SNI stays valid through the tunnel
echo "127.0.0.1 ete-litellm.ai-models.vpc-int.res.ibm.com" | sudo tee -a /etc/hosts
# ~/.nous_env on the VM (chmod 600): base_url uses port 8443
#   ANTHROPIC_BASE_URL / OPENAI_BASE_URL = https://ete-litellm.ai-models.vpc-int.res.ibm.com:8443
#   ANTHROPIC_AUTH_TOKEN / OPENAI_API_KEY = <token>
# on the Mac: reverse tunnel VM:8443 -> Mac -> litellm:443
ssh -f -N -R 8443:ete-litellm.ai-models.vpc-int.res.ibm.com:443 -i key ubuntu@<vm>
# verify from VM:
set -a; . ~/.nous_env; set +a
curl -sS "$OPENAI_BASE_URL/v1/models" -H "Authorization: Bearer $OPENAI_API_KEY" | head -c 200
```

## Pipeline (per task)
1. **Gold baseline** (no LLM): `swefficiency eval --run_id gold --num_workers 2 --instances_regex "<id>"`
   → expert speedup denominator (e.g. astropy__astropy-16295 = 25x).
2. **Generation** (agent produces model_patch): `gen/swe_gen.py` starts the prebuilt container
   `ghcr.io/swefficiency/swefficiency-images:<id>`, drives the agent on the HOST to optimize
   `/testbed` via `docker exec` (LLM via tunnel), extracts `git diff` → `preds/<id>.<label>.jsonl`.
   ```bash
   set -a; . ~/.nous_env; set +a
   python ~/nous_swe/swe_gen.py <id> --agent claude --out preds/<id>.plain_claude.jsonl --label plain_claude
   ```
3. **Score**: `swefficiency eval --run_id <label> --num_workers 2 --prediction_path preds/<id>.<label>.jsonl --instances_regex "<id>"`
   then `swefficiency report --gold_run logs/run_evaluation/gold/gold --pred_run logs/run_evaluation/<label>/<label>`.
   Metric = Speedup Ratio (model speedup / expert speedup), correctness-gated.

## Notes
- Gold baseline validated on VM: `astropy__astropy-16295` expert speedup **25x**, tests pass.
- Nous generation reuses the same host-driven docker-exec pattern (Nous campaign, live target = the task container).
