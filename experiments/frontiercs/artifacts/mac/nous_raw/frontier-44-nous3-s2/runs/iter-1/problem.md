# Problem Framing — Iter 1

## Research Question

What algorithm maximizes the judge score for problem #44 (Traveling Santa with Carrot Constraint)? The problem is a TSP variant where every 10th step incurs a 10% distance penalty unless the source city is prime-numbered. Cities are given sorted by x-coordinate, making the sequential tour a strong baseline. The scoring system (`fmeasure_44.sh`) calls `frontier eval algorithmic 44` and reports a continuous score 0–100.

Key files: `solution.cpp` (the only file we edit).

## System Interface

- **Build command:** Compilation is handled internally by the `frontier eval` judge — no explicit build needed.
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Code evidence:** `fmeasure_44.sh:5` — calls `frontier eval algorithmic 44 "$1" --json`
- **Output format:** Single line `SCORE: <n>` on stdout, n ∈ [0, 100].

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation

- Sequential tour (0→1→2→...→N-1→0): SCORE: 0 (this IS the baseline the judge compares against)
- Nearest-neighbor + limited SA 2-opt: SCORE: 33.456
- Exit code 0 in both cases, output printed to stdout.

## Experimental Conditions

### h-main: Advanced SA with Or-opt + Prime Scheduling

Replace `solution.cpp` with a high-performance simulated annealing solution combining:

1. **Fast construction**: Grid-based nearest-neighbor (O(N log N) via spatial bucketing instead of O(N²) brute-force NN) to build a good initial tour quickly even for N=200,000.
2. **Efficient SA with mixed moves**: Use Or-opt (relocate single city or chain of 2-3 cities) and small-segment 2-opt. Or-opt delta computation is O(1) — only 3 edges change, plus at most a few penalty positions to recheck. This allows millions of move evaluations in 2 seconds.
3. **Penalty-aware prime scheduling**: After the main SA phase, do a targeted optimization pass that specifically swaps prime cities into penalty positions (tour indices 9, 19, 29, ...) and non-primes out, accepting swaps that reduce total penalized cost. With ~18K primes and ~N/10 penalty positions, many penalty positions can be covered.
4. **Adaptive temperature**: Start temperature from initial tour cost / N, cool exponentially, with a reheat if stalled.

Changes from baseline: complete rewrite of solution.cpp algorithmic logic.

## Success Criteria

- h-main achieves score > 33.5 (beating the validated NN+limited-SA probe), targeting 50+ with the improved approach.
- Score is recorded in findings metadata under key 'score'.

## Constraints

- Time limit: 2 seconds per test case
- Memory limit: 512 MB
- N up to 200,000 cities
- Must output valid tour (start/end at 0, visit all cities exactly once)
- Output format: K on first line, then K city IDs one per line

## Prior Knowledge

This is iteration 1. No prior principles.

Key numerical context:
- Primes < 200,000: 17,984. Penalty positions for N=200K: 20,000. Ratio ≈ 0.90 — not all penalty positions can be covered by primes.
- Sequential tour scores 0 (it's the comparison baseline).
- NN + naive SA with segment-capped 2-opt scored 33.5, suggesting substantial room for improvement with better SA implementation.
