#!/bin/bash
# Iteration 3 validation sweep: run key rate points for AL and AD
# Also run with different seeds at rate=100 to measure routing distribution effects

BASE="./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded"

mkdir -p final/data/iter3

# Core validation: key rates for AL and AD
for RATE in 1 10 50 100 150; do
  for MODE in never always; do
    echo "Running rate=$RATE mode=$MODE seed=42..."
    $BASE --pd-decider $MODE --rate $RATE --seed 42 >final/data/iter3/r${RATE}_${MODE}_s42.txt 2>/dev/null
  done
done

# Multi-seed at rate=100 to check routing effects
for SEED in 42 43 44 45 46 47 48 49 50 51; do
  echo "Running rate=100 mode=never seed=$SEED..."
  $BASE --pd-decider never --rate 100 --seed $SEED >final/data/iter3/r100_never_s${SEED}.txt 2>/dev/null
done

# Per-instance data: run rate=100 and extract per-instance metrics
echo "Running rate=100 for per-instance analysis..."
$BASE --pd-decider never --rate 100 --seed 42 >final/data/iter3/r100_full.txt 2>/dev/null

echo "Done."
