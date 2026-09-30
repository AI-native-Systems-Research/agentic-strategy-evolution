Now let me measure the clean baseline:Good, baseline is ~42.2s. Now let me apply the iter-3 patch and measure:Good — iter-3 gives ~0.85ms harness mean. Now let me profile what's actually consuming time with the iter-3 patch applied:Excellent. The profile shows after iter-3: `sqrt_mod` takes ~21% (0.007s), `divisors`/`factorint` takes ~6% (0.002s+0.002s), and the core `diop_DN` takes ~65% (0.022s, the inlined PQa loop + overhead). Let me understand what values flow through:Now let me see the full current state with iter-3 patch and understand the remaining overhead. Let me craft the iter-4 optimization — pure integer replacements for `divisors`, `sqrt_mod`, `divisible`:Now I have a clear picture. Let me implement the iter-4 optimization - replace all sympy utility functions with pure-integer implementations in the |N|>1 branch. Let me first create the optimized version and test it:Now let me apply the optimization. I'll replace the entire `|N|>1` branch with pure-integer implementations:Now let me verify correctness and measure:Significant improvement! 0.31ms vs 0.85ms from iter-3 (2.74x harness speedup). Campaign speedup: 57.3288 / 0.00031 ≈ 184,932×.3 unexpected failures. Let me investigate:Ah, the issue is that when called through the sympy equation solver, `D` and `N` might be sympy `Integer` types, not Python `int`. The bitshift `>>` doesn't work on sympy Integers. I need to convert to Python int early:I need to cast `D` and `N` to Python `int` at the entry of the `|N|>1` branch. Let me also check where `D` and `N` enter as sympy types:The `D` and `N` parameters can be sympy Integers when called from the equation solver. I need to convert to Python int at the branch entry. Let me fix:Also need to update the loop body to use `_D` and `_sD`:Now let me also handle the `sqrt_mod` brute-force properly for large moduli — fall back to sympy's sqrt_mod:Only the expected XFAIL `test_fail_holzer` fails. 41 pass. Now let me measure performance:Consistent ~0.31ms. Let me also profile the warm call timing:Excellent! The profile is dramatically simplified — only 24,901 function calls (down from 38,701 with iter-3). The `sqrt_mod`, `divisors`, `factorint`, `sorted` etc. are completely eliminated. Now the function is almost entirely self-contained with only `integer_nthroot` as an external call.

Now let me check: can we also avoid the `integer_nthroot` call? It's computed at line 1074 before the branch:That's fine — `integer_nthroot` is needed and it's fast (0.000s for 100 calls). The bottleneck is now purely the inner loop and set operations.

Let me now check if there's any additional micro-optimization possible — can we eliminate the `set` and use a fixed-size array or something?Let me also check if large-modulus cases exist in the test suite (where brute-force sqrt_mod would be slow):Max `abs_m` in the test suite is 27. Our brute-force `range(abs_m)` loop for sqrt_mod is perfectly fine for small moduli. But for safety and generality, I should add a fallback for large abs_m. Let me update:Now let me verify everything still passes:41 pass, 1 expected XFAIL. Now measure final performance:Consistent ~0.31ms harness mean. Let me now create the patch:Now let me save the patch and verify it against iter-3 to understand the incremental changes:Now let me also measure the iter-3 baseline (without iter-4 changes) for comparison in the same session:Good, the patch includes the compat fixes. Let me verify everything works:Now let me compute the key metrics:

- **Iter-3 harness mean**: ~0.82ms (average of 0.837, 0.844, 0.789)
- **Iter-4 harness mean**: ~0.31ms (average of 0.304, 0.309, 0.304, 0.328, 0.313)
- **Incremental speedup**: 0.82 / 0.31 ≈ 2.65×
- **Campaign speedup (harness)**: 57.3288 / 0.00031 ≈ 184,932×

Now let me write the design artifacts. First, let me check for the `nous` validation command:Good. Now let me write all three artifacts:Now write the handoff:Now write the campaign-level handoff copy:Now let me run the validation:Validation passes. Let me verify the artifacts one last time:Design validation passes. Here's a summary of the iter-4 design:

## Summary

**Iteration 4** builds on three prior confirmed optimizations (loop-invariant hoisting → integer arithmetic → inlined PQa with period detection) by eliminating the remaining sympy utility function overhead in `diop_DN`'s `|N|>1` branch:

### Key Changes (h-main arm)
1. **Pure-integer divisors**: Replace `divisors(N)` + `divisible(N, d²)` with inline trial division
2. **Pure-integer sqrt_mod**: Replace sympy's CRT-based `sqrt_mod` with brute-force enumeration for small moduli (≤100K), with fallback to sympy for large
3. **int() conversion at branch entry**: Convert D, N, sD to Python `int` to eliminate sympy `Integer` dispatch overhead throughout the 234-iteration inner loop
4. **Micro-optimizations**: `r*r` instead of `r**2`, conditional arithmetic instead of `abs()`, lazy caching of `diop_DN(D, -1)`

### Measured Results (during design exploration)
- **Iter-3 baseline harness**: ~0.82ms
- **Iter-4 treatment harness**: ~0.31ms  
- **Incremental speedup**: 2.65×
- **Campaign speedup**: 57.3288s / 0.00031s ≈ **184,932×**
- **Tests**: 41 pass, 1 XFAIL (test_fail_holzer) — all green
- **Function call count**: 387 → 249 per invocation (36% fewer)

A validated draft patch is saved at `runs/iter-4/patches/h-main-draft.patch`.