# Problem Framing: Iteration 2 — Reducing Per-Iteration Overhead in HRR Formula

## Research Question

After iteration 1 eliminated the O(j^2) bottleneck in `_a` (54.5x speedup, 1.29s → 0.023s), the remaining ~23ms runtime is distributed across `_a` (~63%, 15ms) and `_d` (~28%, 6.6ms). Can we further reduce runtime by (1) precomputing coprime lists and Dedekind sums to eliminate per-iteration gcd and function-call overhead in `_a`, and (2) replacing mpmath's pure-Python arithmetic in `_d` with gmpy2 C-level MPFR operations for low-precision iterations?

**Key source files:**
- `sympy/ntheory/partitions_.py:28-80` — `_a(n, j, prec)`: inner sum function, still the dominant cost at ~15ms (63% of runtime with warm Dedekind cache). The per-iteration overhead comes from `math.gcd` checks (14641 calls, 3ms) and `_d_dedekind` function-call overhead via `@lru_cache` (9028 cache hits, but Python function dispatch overhead adds ~9ms).
- `sympy/ntheory/partitions_.py:83-96` — `_d(n, j, prec, sq23pi, sqrt8)`: sinh term, ~6.6ms (28% of runtime). Uses mpmath's pure-Python `mpf_cosh_sinh` and `mpf_div`, which are slower than gmpy2's C-level equivalents at precisions <= 1000 bits.
- `sympy/ntheory/partitions_.py:99-139` — `npartitions(n)`: main loop, M=244 iterations with dynamic precision reduction.

## System Interface

- **Build command:** None (pure Python).
- **CLI flags:** The workload runs `python /tmp/workload.py` which calls `npartitions(10**6)` 10 times and prints Mean/Std.
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:14-25`: `_d_dedekind` with `@lru_cache` — each cache lookup has Python function-call overhead.
  - `sympy/ntheory/partitions_.py:49-54`: Inner loop with `math.gcd(h, j)` check — 14641 calls per npartitions invocation.
  - `sympy/ntheory/partitions_.py:83-96`: `_d` uses `mpf_cosh_sinh`, `mpf_div`, `mpf_sqrt` — all pure Python.
  - `sympy/ntheory/partitions_.py:130-131`: `_a` and `_d` called per iteration in main loop.
- **Output:** Workload prints `Mean: <float>` and `Std Dev: <float>` to stdout.
- **Tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`

## Baseline Command

```bash
docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"
```

## Baseline Validation

Ran baseline on current iter-1 optimized code:
- Exit code: 0
- Output: `Mean: 0.02294` / `Std Dev: 0.00323`
- Tests pass: 1/1 (test_partitions.py)
- Verified npartitions(10^6) produces correct exact integer.

## Experimental Conditions

### h-main: Precomputed coprimes + gmpy2 _d
Modify `sympy/ntheory/partitions_.py` to:
1. Add `_precompute_coprimes(M)` function that builds per-j lists of (h, D) pairs, eliminating per-iteration `math.gcd` calls and `_d_dedekind` function-dispatch overhead.
2. Rewrite `_a` to accept precomputed coprime data instead of doing gcd+Dedekind lookups per iteration. Handle j=2 unpaired term correctly.
3. In `npartitions`, precompute gmpy2 constants (pi, sqrt(2/3)*pi, sqrt(8), n-1/24) at initial precision.
4. Replace `_d` calls with inline gmpy2 MPFR computation when prec <= 1000, keeping mpmath for prec > 1000 (4 iterations).

Probed performance: 13.4ms mean (1.84x speedup over iter-1 baseline of 24.7ms). Correctness verified for n=0..100000 and n=10^6.

### h-ablation: Precomputed coprimes only (no gmpy2 _d)
Same as h-main change 1-2, but keep original `_d` function unchanged. Isolates the contribution of the coprime precomputation.

Probed performance: 17.6ms mean (1.40x speedup). Correctness verified.

## Success Criteria

- **h-main:** workload_mean_runtime decreases consistently from ~23ms to ~14ms (directional decrease, ~40% reduction).
- **h-ablation:** workload_mean_runtime decreases consistently from ~23ms to ~18ms (directional decrease, ~23% reduction).
- **Both:** All covering tests pass (test_partitions.py).
- **h-main > h-ablation:** The gmpy2 _d optimization provides additional speedup beyond coprime precomputation alone.

## Constraints

- Do NOT edit `/tmp/workload.py` or test files.
- Do NOT change the M factor formula (0.24) or precision formula (1.1x + 100) — RP-2 establishes these are necessary for correctness.
- Do NOT use early termination of the HRR series — RP-2 establishes this is unsafe.
- All optimizations must preserve exact integer correctness for all n.
- gmpy2 _d uses 50 guard bits (prec + 50) to ensure the accumulated numerical difference doesn't affect the final rounded integer.

## Prior Knowledge

- **RP-1:** Iter-1 confirmed that Dedekind reciprocity + Kloosterman symmetry + gmpy2 cos + float path gives 54.5x speedup. The `_a` function went from 90%+ of runtime to ~63%.
- **RP-2:** Early termination is unsafe. M formula must be preserved.
- **Iter-1 handoff suggested:** (1) Precomputed coprime lists, (2) _d function optimization at low precision using gmpy2.
- **New finding (this exploration):** gmpy2 _d is 2x faster than mpmath at prec <= 1000 but 0.7x slower at prec > 1000 (only 4 iterations). Precomputed coprime data gives 2.9x speedup on float path and 1.2x on gmpy2 path, saving ~5.4ms total in _a. Combined optimization: 24.7ms → 13.4ms.
