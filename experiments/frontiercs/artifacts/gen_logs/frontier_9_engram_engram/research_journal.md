# Research Journal — Frontier-CS #9

## Agent 0 handoff (global best so far: 5)
## Summary for Next Agent

**Best Result** — Score of 5 (out of unknown max). Greedy edge-swap matching approach that iteratively finds beneficial transpositions to sort a permutation, selecting swaps that maximize displacement reduction.

**What I Tried**

1. **Greedy maximum-benefit matching approach**: Computed edge swap benefits (displacement reduction) for all possible transpositions, greedily selected a maximum matching of beneficial swaps, applied them simultaneously as one "round," repeated until the permutation becomes identity. Capped iterations to avoid infinite loops. **Result: 5**

2. **Two additional attempts (no explicit plan changes noted)**: Appeared to be the same or very similar approach. **Result: 5 each**

All three attempts scored identically at 5, suggesting the basic greedy matching strategy hits a ceiling.

**Key Insights**

- This is a permutation sorting problem where the goal is to decompose a permutation into a minimum number of "rounds," where each round is a set of disjoint transpositions (a matching) applied simultaneously.
- Score of 5 likely means 5 rounds were used. The optimal might be fewer rounds (lower = better, or the scoring might reward fewer rounds).
- Greedy displacement-reduction doesn't necessarily minimize the number of rounds — it's a local heuristic that may not find the globally optimal decomposition.
- The theoretical minimum number of rounds relates to the cycle structure of the permutation: a cycle of length k can be sorted in ⌈log₂(k)⌉ rounds using parallel transpositions (this is related to sorting networks / parallel sorting by transpositions).

**Approaches That Didn't Work (and Why)**

- **Greedy displacement-based matching**: Consistently gets 5 but doesn't improve beyond that. The greedy heuristic doesn't account for the global structure of cycles in the permutation, so it likely wastes rounds on suboptimal swap selections.

**Recommended Next Steps**

1. **Cycle-based decomposition**: Analyze the permutation's cycle structure. For each cycle of length k, use an optimal parallel transposition strategy (e.g., odd-even merge / binary splitting) to sort it in ⌈log₂(k)⌉ rounds. Combine across cycles, packing transpositions from different cycles into the same round.
2. **Exact optimization**: If the permutation is small enough, try BFS/DFS over the space of possible matchings to find the minimum number of rounds (minimum factorization into involutions).
3. **Look at the scoring function carefully**: Determine whether lower rounds = higher score or if there's a different objective (maybe maximizing the number of elements sorted per round, or minimizing total swaps, etc.). Understanding the exact scoring is critical before optimizing further.

---

## Agent 1 handoff (global best so far: 5)
## Summary for Next Agent

**Best Result** — Score of 5 (lower is better — this is the number of rounds to sort). Achieved by finding "happy swaps" (edges where both endpoints benefit from swapping) as a maximum matching each round, repeated until sorted.

**What I Tried** — Three attempts, all scoring 5:
1. **Happy-edge matching**: For each edge (u,v), check if swapping values moves both closer to their targets (i.e., each value's target is on the other side of the edge). Find a maximum matching among such "happy" edges each round, apply all swaps simultaneously, repeat. Result: 5 rounds.
2. **Variant 2** (no plan stated): Also scored 5 — likely a similar greedy/matching approach.
3. **Variant 3** (no plan stated): Also scored 5 — same result.

**Key Insights**
- The problem is about parallel sorting on a graph: each round you pick a matching (set of non-adjacent edges), swap values along those edges, goal is to sort in minimum rounds.
- "Happy swaps" (both endpoints benefit) is a natural greedy heuristic but may not be globally optimal — it might miss swaps that are temporarily bad for one value but enable faster overall sorting.
- The graph structure and initial permutation matter enormously. Need to look at the specific instance in the archive to find a better schedule.

**Approaches That Didn't Work (and Why)**
- Pure greedy happy-edge matching: Gets stuck at 5 rounds. The greedy criterion is too local — it only considers immediate benefit for both endpoints and may miss sequences where a "sacrifice" swap in one round enables faster completion.

**Recommended Next Steps**
- **BFS/DFS over round schedules**: Since the answer is likely 3-4 rounds, enumerate possible matchings more aggressively. Use backtracking search: at each round, try different maximal matchings (not just happy-edge ones), and find the schedule that sorts in fewest rounds.
- **Look at the specific instance**: Read the archive to understand the graph topology and initial permutation. For small instances, exact search (even brute force over matchings) may be feasible.
- **Allow "unhappy" swaps**: Permit swaps where only one side benefits, or even where neither benefits immediately, if it creates a better configuration for subsequent rounds. This is the key limitation of the greedy approach.
- **Cycle-based analysis**: Decompose the permutation into cycles relative to the target, then plan swap sequences that break cycles efficiently using available edges.

---

## Agent 2 handoff (global best so far: 5)
## Summary for Next Agent

**Best Result** — Score of 5 (lower is better; this is the number of swap rounds needed). The approach computes for each round which edges would beneficially swap values toward their targets using tree path analysis, then finds a maximum matching of such edges.

**What I Tried** — Three attempts, all scoring 5:

1. **Tree-path greedy matching**: For each round, compute for every edge whether swapping its endpoint values moves them closer to their targets (by checking if values need to cross that edge on their path to destination). Find a maximum matching prioritizing edges where both endpoints benefit. Repeat until sorted. Score: 5.

2. **Variant of approach 1** (no explicit plan change noted): Same core logic, still scored 5.

3. **Another variant**: Same framework, scored 5.

All three attempts used essentially the same strategy and got the same result. No meaningful variation was explored.

**Key Insights**:
- This is a problem about sorting values on a tree using parallel swaps (a matching per round) along edges. The minimum number of rounds is the key metric.
- Tree path analysis (determining which edges each value needs to "cross" to reach its target) is the right foundation.
- A score of 5 means 5 rounds were needed. The theoretical lower bound is related to the maximum number of edges any single value must traverse, but parallelism can help.
- Simply doing greedy beneficial swaps each round may not be optimal — the order/selection of swaps matters for minimizing total rounds.

**Approaches That Didn't Work (and Why)**:
- Pure greedy "swap if both values benefit" matching: Gets stuck at 5 rounds. Likely because greedy local decisions don't account for future round interactions. Sometimes you need to make a swap that doesn't immediately help one value in order to unblock a shorter global schedule.

**Recommended Next Steps**:
- **BFS/DFS over round schedules**: Try more sophisticated planning — e.g., look ahead 2+ rounds when choosing matchings, or use a priority system that accounts for bottleneck values (those with the longest remaining path).
- **Cycle-based analysis**: Decompose the permutation into cycles on the tree and reason about how many rounds each cycle requires; try to schedule swaps to resolve long cycles first.
- **Odd/even or coloring-based parallel scheduling**: Color the tree edges and use structured round-robin swap schedules rather than greedy selection.
- **Simulated annealing / random restarts on matching choices**: When multiple valid matchings exist per round, explore different choices to find sequences that converge in fewer rounds.
- **Lower bound analysis**: Compute the theoretical minimum rounds (max over all values of their path length, or based on permutation cycle structure on the tree) to know how much room for improvement exists beyond 5.

---
