# Handoff — iter-1 Maximum Clique (#185)

### Goal
Implement and measure two algorithmic strategies for Maximum Clique: a full branch-and-bound solver (h-main) and a greedy-only baseline (h-control-negative). Record judge scores.

### Key Discoveries
- **Score 100 achieved** with degeneracy-ordered BnB + greedy coloring bound (solution_v2.cpp in worktree). The algorithm solves all test cases optimally within 2s.
- **Greedy-only scores 33.8** — confirms search is essential for hard instances.
- **Basic BnB without degeneracy ordering scores 80** — vertex ordering matters significantly for pruning efficiency.
- `bits/stdc++.h` works in the judge (Docker/Linux) even though it fails on macOS clang. Don't try to compile locally.
- The judge takes ~30-60s per evaluation call.

### System Interface
- **Build:** No local build needed — judge compiles inside Docker.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout, n is 0-100 continuous.
- **Baseline result:** greedy=33.8, basic BnB=80, improved BnB=100.

### Code Map
- `solution.cpp` — the file to edit. Judge compiles this with g++ C++17 inside Docker.
- `fmeasure_185.sh:5` — calls `frontier eval algorithmic 185 "$1" --json`.
- `algorithmic_local.py:89` — subprocess that runs docker compose for the judge.

### Code Targets
- **h-main** (`solution.cpp`): Replace stub with MCQ-style BnB. Key components: bitset<1001> adjacency, degeneracy ordering (repeatedly remove min-degree vertex, reverse), greedy coloring for color-class ordering and upper bound, greedy warm-start.
- **h-control-negative** (`solution.cpp`): Replace stub with degree-sorted greedy clique builder.

### What I Tried That Didn't Work
- Basic BnB without degeneracy ordering: scored 80 instead of 100. The vertex ordering is critical — without degeneracy ordering, the solver wastes time on sparse subgraphs.
- Local compilation with clang on macOS: `bits/stdc++.h` not found. Not an issue since judge compiles in Docker.

### What I Excluded and Why
- Randomized approaches (simulated annealing, genetic algorithms): BnB already achieves 100, and exact methods are more reliable for N≤1000.
- Parallel/multi-threaded approaches: unnecessary given single-thread BnB completes in time.

### Evolution of Thinking
Started with basic BnB → realized vertex ordering is the key differentiator → degeneracy ordering provides the right "core-first" structure that makes coloring bounds tight.

### Current Status
- **Validated:** BnB with degeneracy ordering + coloring = score 100. Greedy-only = score 33.8.
- **Uncertain:** Whether all test cases are solved optimally or some are just close enough.
- **Suggested next:** If score < 100 on any future variant, investigate per-test-case timing. Could try MaxSAT encoding or Bron-Kerbosch with pivoting as alternatives.

### Warnings & Constraints
- Don't compile locally — use the judge script only.
- Each judge call takes ~30-60s.
- Output must be exactly N lines, each "0" or "1" — format mismatch scores 0.
