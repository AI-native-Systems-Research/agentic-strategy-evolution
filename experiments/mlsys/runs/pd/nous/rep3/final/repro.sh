#!/usr/bin/env bash
set -euo pipefail

# Reproduce the P/D disaggregation latency model validation experiment.
# Runs 48 experiments: 8 rates × 2 modes (AL/AD) × 3 seeds.
# Outputs per-run metrics to final/evidence/runs/ and prints headline ITL/TTFT values.

OUTDIR="final/evidence/runs"
mkdir -p "$OUTDIR"

BASE="--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded"

for rate in 5 10 20 40 60 80 100 130; do
  for seed in 42 43 44; do
    ./blis run $BASE --pd-decider never  --rate "$rate" --seed "$seed" --metrics-path "$OUTDIR/AL_r${rate}_s${seed}.json" 2>/dev/null >/dev/null
    ./blis run $BASE --pd-decider always --rate "$rate" --seed "$seed" --metrics-path "$OUTDIR/AD_r${rate}_s${seed}.json" 2>/dev/null >/dev/null
  done
done

python3 -I -c "
import json, os, glob
outdir = '$OUTDIR'
rates = [5, 10, 20, 40, 60, 80, 100, 130]
seeds = [42, 43, 44]
print('Rate | AL_ITL(ms) | AD_ITL(ms) | Gap(ms) | AL_TTFT(ms) | AD_TTFT(ms)')
print('-----|------------|------------|---------|-------------|------------')
for r in rates:
    al_itls, ad_itls, al_ttfts, ad_ttfts = [], [], [], []
    for s in seeds:
        al = json.load(open(f'{outdir}/AL_r{r}_s{s}.json'))
        ad = json.load(open(f'{outdir}/AD_r{r}_s{s}.json'))
        al_itls.append(al['itl_mean_ms']); ad_itls.append(ad['itl_mean_ms'])
        al_ttfts.append(al['ttft_mean_ms']); ad_ttfts.append(ad['ttft_mean_ms'])
    al_itl = sum(al_itls)/3; ad_itl = sum(ad_itls)/3
    al_ttft = sum(al_ttfts)/3; ad_ttft = sum(ad_ttfts)/3
    print(f'{r:4d} | {al_itl:10.3f} | {ad_itl:10.3f} | {al_itl-ad_itl:7.3f} | {al_ttft:11.3f} | {ad_ttft:10.3f}')
"
