# Problem Framing — Iteration 2

## Research Question

What algorithm maximizes the Frontier-CS judge score for the Traveling Santa with Carrot Constraint problem (#44)? Specifically, does replacing window-based 2-opt with spatial nearest-neighbor-list 2-opt, combined with greedy NN construction, produce a significant score improvement over the strip-based + window 2-opt approach from iteration 1?

Key source files:
- `chk.cc:91-101` — penalized tour cost computation (multiplier 1.1 when t%10==0 and source not prime)
- `chk.cc:133-176` — scoring formula (part1 + part2, tau=1.25, s_full=N^0.6, visibility remap)
- `chk.cc:19-42` — visibility remap anchors (compresses <0.30, expands 0.66-0.90 range)
- `config.yaml` — time limit 2.5s, memory 512MB, 20 test cases

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **CLI flags:** None — solution reads from stdin, writes to stdout.
- **Code evidence:** `config.yaml:3` defines time limit as 2.5s. `chk.cc:48` reads N in range [2, 200000].
- **Output/measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp` — prints `SCORE: <n>` (0-100, average across 20 test cases).

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

The solution.cpp must be edited with the algorithm before running. The stub returns 0 (empty output = invalid = score 0).

## Baseline Validation

Iteration 1 established a baseline score of **55.4535** using strip-based serpentine construction + window 2-opt + carrot optimization. The identity tour scores exactly 0. These baselines are validated and reproducible.

During this iteration's exploration, the following prototypes were tested:
- Strip + NN-list 2-opt (K=10): **71.2** (v4)
- NN construction + NN-list 2-opt (K=15): **76.0** (v5, verified twice)
- NN construction + NN-list 2-opt (K=20): **76.3** (v8)
- NN construction + bidirectional NN 2-opt (K=15): **71.0** (v6, worse due to expensive long reversals)
- NN construction + alternating 2-opt/or-opt mega-loop (K=20): **71.3** (v9, worse due to or-opt disruption)

## Experimental Conditions

### h-main: NN Construction + Spatial NN-list 2-opt

Replace solution.cpp with an algorithm that:
1. **Precomputes K=20 nearest spatial neighbors** per city using dual x-sorted and y-sorted windows (W_nn=35-150 depending on N), with squared-distance comparison.
2. **Constructs initial tour via greedy nearest-neighbor** from city 0 (using NN list + fallback search).
3. **NN-list 2-opt optimization** (~1.7s budget): for each edge in tour, checks if swapping with edges adjacent to spatial neighbors improves tour length. Forward direction only (j > i) to avoid expensive long reversals.
4. **Window-based 2-opt** (~0.3s budget): standard window 2-opt (window=25-300 depending on N) as a cleanup pass.
5. **Carrot optimization** (~0.1s budget): swap prime cities into penalty positions (t%10==0).

### h-ablation: Strip Construction + Spatial NN-list 2-opt

Same algorithm as h-main but with **strip-based serpentine construction** instead of NN construction. This isolates the contribution of the NN construction heuristic vs the NN-list 2-opt optimization.

## Success Criteria

- h-main should score ≥ 70 (significantly above iter-1's 55.4)
- h-main should score higher than h-ablation (demonstrating NN construction's value)
- Both arms should score above iter-1's baseline of 55.4

## Constraints

- Time limit: 2.5s per test case
- Memory limit: 512MB
- 20 test cases with N ranging from 10 to 200,000
- Test case distributions: scattered (unique x per city, N=5K-40K) and grid-like (many shared x values, N=80K-200K)
- Score is averaged across all 20 test cases

## Prior Knowledge

- RP-1: Strip + 2-opt + carrot scores ~55.45 (iter-1)
- RP-2: 2-opt local optimum is robust within window-based search (iter-1)
- RP-3: Carrot constraint contributes only ~1-5% of total cost (iter-1)
- The key limitation from iter-1 was the window-based 2-opt which only checks tour-order neighbors. Spatial NN-list 2-opt finds cross-tour improvements by checking geometrically nearby cities.
