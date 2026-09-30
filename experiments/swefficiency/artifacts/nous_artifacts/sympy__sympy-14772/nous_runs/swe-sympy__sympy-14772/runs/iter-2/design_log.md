Now let me explore for additional optimization opportunities and verify the current state:Let me probe the micro-optimization opportunity and verify the mechanism:Now let me apply and verify the optimized code:Let me now apply the main fix and smoke-test it with the workload and tests:Now test variant 2 (no pre-reduction):Good, code is clean. Now let me also verify the baseline one more time for accurate reference:Now I have all the exploration data. Let me write the three artifacts.Now write the handoff:Now copy the handoff to the campaign-level location:Now run validation:Validation passes. Let me verify the artifacts are complete:All artifacts are written and validation passes. Here's a summary of the iter-2 design:

## Summary

**Iteration 2** of `sympy__sympy-14772` — `legendre-modpow-optimization` family, complexity tier 2.

### Arms designed:
1. **h-main**: Replace `pow(a%p, (p-1)//2) % p` with `pow(a%p, (p-1)//2, p)` at `crypto.py:2075`. This is the confirmed RP-1 mechanism from iter-1, delivering ~3,900x speedup by eliminating construction of a ~1.1M-bit intermediate integer.

2. **h-ablation**: Same three-arg pow fix but additionally removes the redundant `a%p` pre-reduction → `pow(a, (p-1)//2, p)`. Tests whether this arithmetic step contributes measurable overhead. Probes show it adds ~0.1μs (~3%), well within workload noise.

### Key findings from exploration:
- Baseline verified at 0.0686s (consistent with campaign reference of 0.0743s)
- h-main smoke-test: 18.5μs mean, all 38 tests green → ~4,016x speedup
- h-ablation smoke-test: 19.6μs mean, all 38 tests green → ~3,801x speedup
- Both variants are functionally identical for all edge cases (negative `a`, zero, `a > p`)
- All other `pow()` calls in crypto.py already use three-arg form; only line 2075 has the anti-pattern

**Validation: PASS** ✅