# Task: find and fix a metrics bug in BLIS

This repository is BLIS, a discrete-event simulator for LLM inference serving (Go; build with `go build -o blis main.go`,
test with `go test ./...`, run `./blis run --help`).

A user reports: "When the KV cache is small enough that requests get preempted, `total_output_tokens` and
`tokens_per_sec` in the metrics output look too high. For example
`./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600` reports more output
tokens than the same command with a large KV cache, even though every request completes in both runs and the requests
are identical."

Research question: is this a real bug? If so, what is the root cause, and what is the correct fix?

Find the root cause, fix it in the source code, and add a regression test. Keep the change minimal and do not break
existing behavior or tests. Report the root cause (file and function), the evidence that it is the cause, and the
evidence that your fix is correct. `deliverable` in `final/answer.json` must be the path to a patch file of your change
(`git diff > final/fix.patch`).
