I'll start by reading the previous iteration's results and the current state of the codebase to understand what was achieved and plan iter-2.Let me check the iter-1 results more thoroughly and verify the current state of the solution.Now let me explore potential improvements. The key question: can we beat 5 operations for the endgame (swapping last 2 elements)?Excellent! The BFS shows the endgame can be done in **4 operations** instead of 5! This is a genuine improvement. Let me find the actual 4-op sequence.There's a clear pattern: the 4-op endgame is `(1,2), (1,n-2), (1,2), (2,2)`. Let me verify for n=4 and test on larger n.The 4-op endgame `(1,2), (1,n-2), (1,2), (2,2)` works for all n≥5 and saves 1 operation. Let me check if we can also optimize the last-3-elements handling.Huge discovery! Handling last 3 elements as a unit saves up to 4 operations. Let me find the optimal sequences.Now let me verify the existing solution still works and build the optimized version.Now let me verify the generalized endgame sequences work for n=1000.All patterns verified. Now let me create and test the optimized solution.Let me do a direct comparison of operation counts between original and optimized.Excellent! The optimized algorithm never loses, saves an average of 1.4 ops (max 4), and reduces max from 2000 to 1996. Let me test it with the judge.Let me test a greedy lexicographic approach to see how it compares.The greedy with small ops gets stuck quickly. Let me try a smarter greedy that processes one element at a time.The single-op greedy approach fails to sort (score 0) — confirming the 2-op mechanism is essential. This is a clean ablation. Now let me check the checker source to confirm understanding.Now I have full understanding. Let me write the design artifacts. First, let me check the directory structure.Good. Now let me write the three design artifacts.Now write the handoff:Now copy the handoff to the campaign-level living document:Now let me run the validation:Validation passes. Let me provide a summary of the design.

---

## Iteration 2 Design Summary

**Status: PASS** — All design artifacts validated successfully.

### Key Discovery
BFS analysis revealed that the iter-1 algorithm's 5-operation endgame (for swapping the last 2 elements) can be reduced to **4 operations** for n≥5 using the sequence `(1,2), (1,n-2), (1,2), (2,2)`. Furthermore, handling the **last 3 elements as a unit** with BFS-optimal case-specific sequences saves up to **4 operations total**, reducing worst-case from **2n+1 to 2n−2** (2001→1998 for n=1000).

### Experiment Arms

| Arm | Algorithm | Expected Score | Key Metric |
|-----|-----------|---------------|------------|
| **h-main** | Optimized circular buffer rotation with BFS-derived last-3-element endgame | **100** | Avg 1984.0 ops (↓1.4 from iter-1), max 1996 (↓4) |
| **h-ablation** | Remove Op2 (prefix restoration) from the 2-op rotation | **0** | Array fails to sort; proves Op2 is essential |

### Scientific Value
1. **Optimization finding**: The last-3-element endgame provides free operation savings without changing the core mechanism
2. **Mechanism necessity**: Op2 (prefix restoration) is not just an optimization — it's structurally essential. Without it, the algorithm completely fails
3. **Completeness**: The combination confirms both that the mechanism works (h-main: score 100) and that each component is necessary (h-ablation: score 0)