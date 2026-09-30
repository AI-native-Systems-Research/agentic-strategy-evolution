Now I see the key issue. The `_legendre` function at line 2075 does `pow(a%p, (p - 1)//2) % p` — computing a full integer power before taking mod, instead of using Python's 3-argument `pow(base, exp, mod)` which does modular exponentiation efficiently.

Let me verify the baseline and confirm the optimization:Good — baseline runs with the testbed Python 3.6 environment. Mean ~0.069s. Now let me verify the optimization will work, and run the tests:Now let me apply the fix and test:Extraordinary results. The optimization gives ~4,000x speedup and all 38 tests pass. Let me save the patch and reset:Now let me read the patch to confirm its contents, then write all three artifacts:Now let me write all three artifacts. Starting with problem.md:Now write the handoff:Now validate:Validation passes. Let me provide a brief summary.

---

## Summary

**Iteration 1 — Design complete. Validation: PASS.**

### What I found
The workload benchmarks `_legendre(87389, 131071)` in `sympy/crypto/crypto.py:2075`. The implementation uses `pow(a%p, (p-1)//2) % p` — Python's **two-argument** `pow`, which computes the full integer `87389^65535` (~1.1 million bits) before taking mod. This is the classic modular exponentiation anti-pattern.

### The fix (h-main)
Replace with `pow(a % p, (p - 1) // 2, p)` — Python's **three-argument** `pow`, which performs modular exponentiation in C using square-and-multiply, keeping all intermediates bounded by `p` (~17 bits).

### Validated results
| Metric | Baseline | Optimized |
|--------|----------|-----------|
| Mean runtime | 0.069s | 0.000016s |
| Speedup | 1.0x | **~4,225x** |
| Tests | 38/38 pass | 38/38 pass |

### Artifacts written
- `/tmp/nous_runs/swe-sympy__sympy-14772/runs/iter-1/problem.md` — problem framing
- `/tmp/nous_runs/swe-sympy__sympy-14772/runs/iter-1/bundle.yaml` — hypothesis bundle (tier 1, single arm)
- `/tmp/nous_runs/swe-sympy__sympy-14772/runs/iter-1/handoff_snapshot.md` — executor/next-iter handoff
- `/tmp/nous_runs/swe-sympy__sympy-14772/runs/iter-1/patches/h-main.patch` — validated git patch