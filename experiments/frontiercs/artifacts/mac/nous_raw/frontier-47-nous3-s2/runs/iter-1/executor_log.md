Now let me implement the MaxRects solution. The designer validated a v5 achieving 94.46. I'll write a strong implementation with all the features described.Now let me save the patch and run the judge:Score is 87.93, below the designer's 94.46. The designer's v5 likely had more optimizations. Let me improve the solution — the key issue is probably that the permutation search and packer need to be more aggressive. Let me look at what could be improved:

1. The `v` field can be up to 10^9, so I need `long long` for profit comparisons
2. The permutation cap of 20000 is too low for M≤10 (only 3.6M perms for M=10, but 40320 for M=8)
3. Need to be smarter about time budgeting94.45 — very close to the designer's 94.46. Let me try to improve further. The key areas to optimize:

1. Better handling of JSON parsing (the `"h"` key could match incorrectly with `"th"` in type names)
2. More aggressive search — try interleaved greedy (pick best item at each step, not just type-by-type)
3. Try smarter rotation decisions

Let me try a version with some algorithmic improvements:Same score at 94.45. The interleaved greedy didn't help — the permutation search is the dominant strategy. Let me try to squeeze more points by improving the packer itself or using a different strategy entirely. The issue might be that for M=11 or M=12 test cases, we can't do full permutation and random search doesn't find enough good orderings.

Let me try a different approach: instead of just trying all permutations of type order, try a **beam search** or **genetic algorithm** over orderings, and also try **skyline packing** as an alternative to MaxRects.Hmm, dropped to 88.48. The reduced heuristic count in random search (only 2 instead of 4) hurt. Let me think about what's different...

The key insight is that using fewer heuristics per permutation lets you try more permutations, but some test cases need specific heuristics. Let me go back to the approach that scored 94.45 and try to improve it differently — perhaps with better time allocation or a smarter search strategy.94.45 — consistent. Now let me try to push higher. The key improvement opportunities:

1. **Smarter permutation seeding** — start random search from good permutations (near density-sorted) rather than fully random
2. **Adjacent swap neighborhood** — local search around best-found permutation
3. **Skyline-based packing** as alternative to MaxRects for some cases

Let me try a **local search** approach — start from the best permutation found so far, then do adjacent swaps:94.83 — up from 94.45! The local search helped. Let me see if I can push further. The local search is doing pairwise swaps which is good. Let me try to also:

1. Use the local search result as starting point for more random perturbations
2. Try 3-opt moves (insert one element at different positions)
3. Allocate more time to local search vs exhaustive permutation94.84 — slightly better than 94.83. The insertion moves in local search help marginally. Let me try a different angle — the local search with the insertion neighborhood has a bug where restarting causes issues. Let me also try to **combine local search with random restarts** and fix the insertion code:Same 94.84. The random perturbation didn't help beyond the local search. The local search is already finding the local optimum for each heuristic. Let me try a fundamentally different approach — use **nlohmann-style JSON parsing** (actually just use the simpler approach of reading with a proper parser), and try a **different packing algorithm**: Skyline bottom-left packing, which is faster and allows more search iterations.

Actually, let me think about what's limiting the score. The scoring is `(V-B)/(K-B)` averaged over 15 tests. K is an upper bound (fractional relaxation). On some tests we might be close to K, on others far. The tests where we lose the most are likely the ones with M=11-12 where permutation exhaustion is impossible.

Let me try a more aggressive local search — **simulated annealing** over orderings:Still 94.84. The score seems plateau'd. Let me try a fundamentally different approach to squeeze more out. The issue might be that the MaxRects packer itself is suboptimal, not just the ordering. Let me try:

1. A **guillotine packing** approach as an alternative
2. Or **skyline packing** which is simpler but potentially faster, allowing more orderings to be tested

Actually, let me think about this differently. The scoring is averaged over 15 tests. I'm probably getting close to 100 on some tests and far on others. The hard tests are likely the ones with near-prime dimensions or rotation disabled. Let me try to improve the packer's core algorithm by adding a **contact perimeter** heuristic (place items that maximize touching with bin walls and other items):Dropped to 88.56! The contact perimeter heuristic is too slow (O(n²) per placement) and eats into search time. The `usedRects` tracking makes the packer much slower. Let me revert to the approach without contact perimeter and focus on what actually worked (v7/v8 at 94.84).

The key insight is: **the hill climbing + good initial orderings is what gets us to 94.84, and the contact perimeter is too slow**. Let me go back to the 4-heuristic version and try to improve by being smarter about how we use the time budget:Good, back to 94.84. This is our best. Let me now save this as the final version and record the score. Let me update the patch and write all artifacts.Now let me save the score result and write all artifacts:Now write the experiment plan, findings, and principle updates:Now validate:Validation passes.

**Summary:** Score **94.84/100** — CONFIRMED. MaxRects bin packing with 4 heuristics (BSSF, BAF, BL, BLSF), 9 sorting strategies, global greedy packing, permutation exhaustion for M≤8, and hill-climbing local search (swap + insert neighborhoods) over item orderings. The hill-climbing added ~0.4 points over pure permutation exhaustion (94.45 → 94.84). All artifacts validated.