Now let me examine the current state of the container and code to understand what's already applied and where the remaining bottlenecks are.Let me profile more granularly to understand where the remaining time goes:Now let me understand the breakdown better and test prototype optimizations:Let me try a more aggressively optimized version with better mpfr conversion and constant sharing:Now let me explore the CRT (Chinese Remainder Theorem) factorization of Kloosterman sums - this could significantly reduce the number of expensive gmpy2.cos calls for composite j:The CRT factorization doesn't apply directly to HRR's Dedekind-weighted sums. Let me explore a different approach - using ctypes to push the inner cos loop to C:The C float path is 5x faster. Now let me try a more ambitious approach - compile a C helper that handles both float AND MPFR paths:The MPFR C path gives only 7% over gmpy2 (both call MPFR), but the float C path gives 5x. Let me now test a full combined prototype with the C float helper + all micro-optimizations:Good progress - 24% improvement. Let me run a more careful benchmark and also try pushing the gmpy2 _a loop to C:Now I have a solid understanding of the optimization landscape. Let me also run the covering tests to confirm the current code passes:Now let me check the iter-3 directory structure and the nous validation tool:Good. Now let me also check the existing principles.json for any refuted mechanisms:No refuted mechanisms — all 4 principles are active and confirmed. Now let me write the experiment artifacts. Let me start with the problem framing:Now the bundle.yaml:Now the handoff:Now copy the handoff to the campaign-level location:Now let me run validation:Validation passes. Let me verify the files are all in order:Validation passes with `{"status": "pass", "warnings": []}`. Here's a summary of the iteration 3 design:

## Summary — Iter-3 Design: npartitions Loop Overhead Elimination

**Context:** After iter-1's 54.5x algorithmic speedup and iter-2's 1.6x overhead reduction (both CONFIRMED), the remaining runtime (~14ms for npartitions(10^6)) is split between irreducible MPFR computation (53%) and addressable Python interpreter overhead (45%).

**Hypothesis (h-main):** Six combined micro-optimizations will reduce runtime by ~20%:
1. **C float-path helper** — A compiled C function for the hardware-cos loop (5x on float path: 2.1ms → 0.33ms)
2. **Inlined _a/_d** — Eliminate 243 function calls, share gmpy2 context
3. **Precomputed division factor** — Save one mpfr division per gmpy2.cos call (0.57ms)
4. **Precomputed _d constants** — `sqrt(n-1/24)` computed once instead of 239 times
5. **as_mantissa_exp()** — Faster mpfr→mpf conversion (avoids temporary 2^wp multiplication)
6. **Local attribute caching** — Module lookups moved to local variables

**Ablation (h-ablation):** Same as h-main but WITHOUT the C float-path helper. Isolates whether the C helper or the Python-level optimizations drive the gain.

**Validated prototypes:** h-main: 11.3ms (21% improvement), h-ablation: 12.0ms (14% improvement). All correctness tests pass for both. The C helper accounts for ~30-40% of the total improvement.

**Key dead ends explored:** CRT Kloosterman factorization (wrong formula), C MPFR inner loop (only 7% over gmpy2), NumPy vectorization (1.85x vs C's 5x), extending float path beyond prec=53 (unsafe — corrupts final integer).