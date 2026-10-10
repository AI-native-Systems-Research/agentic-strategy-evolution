I'll start by understanding the current state of the system and exploring what optimization opportunities remain beyond what previous iterations have found.Good. Now let me understand the workload deeply and look for optimization opportunities beyond the single line change that previous iterations focused on.Interesting! Sympy already has `legendre_symbol` and `jacobi_symbol` in `ntheory`. Let me examine their implementations:Let me probe the optimized performance to understand the headroom:Now let me probe some genuinely new optimization approaches:Let me check the campaign configuration and prior findings for complete context:Let me check the other `pow` call sites in the crypto module to find a good control-negative:Good. Now let me verify the baseline and both planned code changes work correctly:Baseline confirmed: Mean 0.069s, 38/38 tests pass. Now let me smoke-test the h-main change:h-main validated: 15.5μs mean (speedup ~4,787x), 38/38 tests pass. Now reset and test the control-negative:Control-negative validated: Mean 0.069s (no speedup), 38/38 tests pass. Now reset code to original:Now let me verify the code is back to original state:Good, clean. Now I have all the evidence I need. Let me write the three design artifacts.Now let me write the handoff document:Now copy the handoff to the campaign-level living document:Now let's validate:Validation passes. Let me provide a summary of the design.

---

## Design Summary — Iteration 4

**Research question:** Does the confirmed three-arg `pow()` optimization in `_legendre()` produce consistent ~3,500–4,500× speedup, and is the speedup mechanism-specific?

**Bundle family:** `legendre-modpow-optimization` (tier 1)

**Two arms:**

1. **h-main** — Replace `pow(a%p, (p-1)//2) % p` with `pow(a, (p-1)//2, p)` at line 2075 of `crypto.py`. This eliminates construction of a ~1.1M-bit intermediate integer. Smoke-tested: 15.5μs mean (speedup ≈ 4,787×), 38/38 tests pass. Prediction: consistent ~3,500–4,500× speedup across all 5 seeds.

2. **h-control-negative** (new for this iteration) — Apply the same *class* of optimization to `encipher_gm` at line 2221 (`pow(a, b) % N` → `pow(a, b, N) % N`), which is NOT in the workload's call graph. Smoke-tested: 0.069s mean (speedup ≈ 1.08×, within baseline noise), 38/38 tests pass. Prediction: no measurable speedup, validating that h-main's effect is path-specific.

**What's new vs prior iterations:**
- Iters 1–3 focused on the `_legendre` function exclusively (confirmation, ablation, algorithmic alternative)
- Iter 4 adds mechanism-specificity validation via a control-negative arm that applies the same optimization class to an unrelated code path
- Also explored and ruled out: delegation to `sympy.ntheory.jacobi_symbol` (6.4μs, no improvement over three-arg pow), combined micro-optimizations (no measurable effect), bitshift exponent (no effect)

**All three artifacts written and validated:**
- `problem.md` — full problem framing with baseline validation
- `bundle.yaml` — hypothesis bundle with experiment_spec
- `handoff_snapshot.md` — accumulated exploration context for executor/next designer