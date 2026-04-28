# Running Nous on BLIS

This example shows how to run Nous on [BLIS](https://github.com/inference-sim/inference-sim), a discrete-event simulator for LLM inference serving systems.

## Prerequisites

- Python 3.11+
- Claude Code CLI (`claude`) installed and authenticated
- An LLM API key: `export OPENAI_API_KEY=...` (and `OPENAI_BASE_URL` if using a proxy)
- Nous installed: `pip install -e ".[dev]"`

## Setup

1. Clone BLIS locally and build it:
   ```bash
   git clone https://github.com/inference-sim/inference-sim.git blis
   cd blis && go build -o blis .
   ```

2. Edit `campaign.yaml` — set `repo_path` to your BLIS checkout:
   ```yaml
   repo_path: /path/to/your/blis
   ```

## Running a campaign

```bash
python run_campaign.py examples/blis/campaign.yaml --max-iterations 3
```

The script will loop through iterations. Each iteration:

1. **Framing** — planner explores the BLIS codebase and frames the problem
2. **Design** — planner creates a hypothesis bundle with code-level specificity
3. **Design review** — 3 reviewers check the bundle
4. **Human design gate** — shows summary, asks approve/reject/abort
5. **Running** — executor runs the experiment
6. **Findings review** — reviewers check findings
7. **Human findings gate** — shows summary, asks approve/reject/abort
8. **Extraction** — extracts principles for next iteration
9. **Continue gate** — asks whether to proceed to next iteration

Options:

```bash
python run_campaign.py examples/blis/campaign.yaml --max-iterations 5 -v
python run_campaign.py examples/blis/campaign.yaml --model gpt-4o
python run_campaign.py examples/blis/campaign.yaml --run-id my-campaign
python run_campaign.py examples/blis/campaign.yaml --auto-approve  # skip gates
```

You can also set `max_iterations` in `campaign.yaml` (CLI flag overrides it).

## Campaign configuration

The `campaign.yaml` starts minimal — just a research question, system description, and `repo_path`. The planner discovers metrics, knobs, and execution methods from the code.

Optional fields (documented as inline comments in `campaign.yaml`):

| Field | Purpose |
|-------|---------|
| `observable_metrics` | Constrain what agents measure (planner discovers from code if omitted) |
| `controllable_knobs` | Constrain what agents change (planner discovers from code if omitted) |

## Expected output

```
blis-run/
  state.json
  principles.json
  ledger.json
  runs/iter-N/
    problem.md                     # problem framing
    bundle.yaml                    # hypothesis bundle
    findings.json                  # results
    gate_summary_design.json       # human-readable design summary
    gate_summary_findings.json     # human-readable findings summary
    investigation_summary.json     # iteration summary (non-final iterations)
    reviews/
      review-*.md                  # design reviews
      review-findings-*.md         # findings reviews
```

## Customizing

To adapt for a different system:

1. Copy `campaign.yaml`
2. Update `target_system` (name, description, repo_path)
3. Optionally adjust reviewer perspectives in `review`
4. Run: `python run_campaign.py path/to/your/campaign.yaml --max-iterations 3`
