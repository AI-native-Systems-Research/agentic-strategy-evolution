# Research Report: Reducing Runtime of the SymPy `_legendre` Workload

## Answer

The runtime of the `_legendre(87389, 131071)` workload in `sympy/crypto/crypto.py` can be reduced by **~3,500×** by replacing the two-argument `pow(a, (p-1)//2) % p` with the three-argument form `pow(a, (p-1)//2, p)` on line 1886. This single-character-class change eliminates construction of a ~1.1 million-bit intermediate integer, keeping all intermediates bounded by ~17 bits. No further micro-optimizations produce statistically significant additional improvement due to measurement harness overhead dominating the remaining computation time.

## Evidence

### Iteration 1 — Initial hypothesis (CONFIRMED)
Replaced `pow(a, (p - 1) // 2) % p` with `pow(a, (p - 1) // 2, p)` in `_legendre()`. The hypothesis was confirmed with a massive speedup. This established the core optimization.

### Iteration 2 — Ablation: pre-reduction redundancy (CONFIRMED)
Tested whether adding an explicit `a % p` pre-reduction before the three-arg `pow` call provides additional benefit. The ablation confirmed it does not — CPython's C-level implementation internally reduces the base before exponentiation, making explicit pre-reduction redundant. The three-arg `pow` alone captures the full benefit.

### Iteration 3 — Alternative algorithm: Jacobi symbol (CONFIRMED, no additional gain)
Tested replacing modular exponentiation entirely with a Jacobi-symbol / quadratic-reciprocity algorithm (~1.7× faster per call in microbenchmark: ~4μs vs ~7μs). The robustness test confirmed this provides no statistically significant improvement in the workload harness because the multiprocessing fork overhead (~16μs) dominates the ~3μs per-call savings.

### Iteration 4 — Control-negative (CONFIRMED)
Applied three-arg `pow` optimization to a *different* call site (`encipher_gm`, line 2221) that is not in the workload's execution path. Measured speedup was 1.06× (noise), versus 3,441× for the `_legendre` optimization. This confirmed the speedup is mechanism-specific to the `_legendre` code path and not an artifact of modifying the module.

### Iteration 5 — Stacked micro-optimizations (CONFIRMED, no additional gain)
Combined the three-arg `pow` with bitshift exponent (`(p-1) >> 1` instead of `(p-1)//2`) and branchless return. Welch's t-test showed no significant difference (t=1.35, df=4.3, p>0.05). Sub-microsecond savings (~0.02μs combined) are invisible against ~16μs fork overhead.

All five iterations achieved 100% prediction accuracy across all experimental arms (12/12 correct predictions).

## Principles Discovered

| ID | Principle | Confidence | Regime |
|----|-----------|------------|--------|
| **RP-1** | Three-arg `pow(base, exp, mod)` eliminates exponentially-large intermediates, yielding ~3,500× speedup for large exponents | High | Any Python path with `pow(a, exp) % mod` where exp is large (~65,535+) |
| **RP-2** | Explicit `a % mod` pre-reduction before three-arg `pow` is redundant — CPython handles it internally | High | All three-arg `pow` usage |
| **RP-3** | Jacobi-symbol algorithm is ~1.7× faster per call but invisible when harness overhead dominates | High | Measurement regimes where fork overhead (~16μs) exceeds computation time (~3–7μs) |
| **RP-4** | Speedup is mechanism-specific to `_legendre` code path, not a side effect of modifying `crypto.py` | High | Workload-path-specific optimizations require path verification |
| **RP-5** | Three-arg `pow` captures the entire practical improvement; stacking micro-optimizations yields no further measurable gain | High | This workload with this measurement harness |

## Limitations & Open Questions

### Scientific Gaps
1. **Measurement ceiling**: The multiprocessing fork overhead (~16μs) constitutes ~80% of measured time after optimization, creating a hard floor that masks further improvements. A tighter harness (batch in-process timing) would reveal whether the Jacobi algorithm's ~1.7× per-call advantage translates to real workload benefit.
2. **Generalization**: Only one `(a, p)` pair was tested. For very large primes (hundreds of digits), the Jacobi algorithm's O(log² p) complexity could meaningfully outperform three-arg pow's O(log p · log² mod) modular exponentiation.
3. **Other hot paths**: The campaign focused exclusively on `_legendre`. Other functions in `crypto.py` (e.g., `encipher_gm`, `decipher_gm`) may contain similar two-arg `pow` patterns that would benefit from the same fix if they appear in other workloads.

### Infrastructure Gaps
- No result files were produced on disk across any iteration, suggesting the experiment harness captured results only through stdout/process return codes rather than file artifacts. This limited post-hoc analysis to ledger entries.
- No dispatcher retries or bundle amendments were needed — the infrastructure was stable throughout all 5 iterations.

### Recommended Next Steps
1. Audit the entire SymPy codebase for `pow(x, y) % z` patterns (potential grep: `pow\(.+\)\s*%`) and convert to three-arg form.
2. Investigate whether a tighter measurement harness would make the Jacobi-symbol replacement worthwhile for number-theoretic workloads.
3. Profile broader SymPy workloads to identify the next highest-impact optimization targets beyond `_legendre`.