# Task: does the P/D disaggregation latency model hold in BLIS?

This repository is BLIS, a discrete-event simulator for LLM inference serving (Go; build with `go build -o blis main.go`,
run `./blis run --help`). It models prefill/decode (P/D) disaggregation with separate prefill and decode instance pools.
The `--pd-decider` flag selects routing: `never` (always-local, AL) or `always` (always-disaggregate, AD).

The paper `docs/pd-disagg.pdf` ("When to Disaggregate") gives a closed-form model of P/D serving under continuous
batching. Among other things it predicts mean inter-token latency (ITL) of the form ITL = alpha / (1 - lambda * W), where
lambda is the arrival rate and W a per-request work term, and it predicts how TTFT and ITL compare between AL and AD.

Research question: do the paper's ITL and TTFT predictions for AL and AD hold inside BLIS, over what range of arrival
rates, and where and why do they break down?

Use this setup for every measurement (it is fixed and must not change):
`--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300
--prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded`.
You may vary `--pd-decider`, `--rate` (1 to 150 req/s) and `--seed`.

Report: how accurately the ITL formula fits and over which rates; whether and where it breaks, with the size and sign of
the error; how TTFT and ITL compare between AL and AD; and the mechanism behind any breakdown.
