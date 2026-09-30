# Problem Framing: npartitions Performance Optimization

## Research Question

How can we reduce the runtime of `npartitions(10**6)` in `sympy/ntheory/partitions_.py` without changing its numerical output, while keeping the covering tests (`sympy/ntheory/tests/test_partitions.py`) green?

The implementation uses the Hardy-Ramanujan-Rademacher (HRR) formula. Profiling reveals that the `_a` function (`partitions_.py:12`) consumes **80% of total runtime** (1.05s of 1.32s). The bottleneck is a double loop: outer over Euler coprime residues h, inner over k=1..j-1, performing expensive big-integer arithmetic per iteration.

Key source files:
- `sympy/ntheory/partitions_.py:12` — `_a(n, j, prec)`: inner sum (80% of runtime)
- `sympy/ntheory/partitions_.py:39` — `_d(n, j, prec, ...)`: sinh term (1% of runtime)
- `sympy/ntheory/partitions_.py:55` — `npartitions(n)`: main function, outer HRR loop

## System Interface

- **Build command:** None needed (pure Python).
- **Run command:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"`
- **Test command:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python -m pytest -q sympy/ntheory/tests/test_partitions.py"`
- **Code evidence:**
  - `partitions_.py:12-36` — `_a` function with O(j²) inner loop per coprime h
  - `partitions_.py:17` — `igcd(h, j)` call using sympy's slow GCD with type checks
  - `partitions_.py:24-30` — inner k-loop doing per-step big-integer arithmetic (`h*k*one//j`, bitmask, multiply, accumulate)
  - `partitions_.py:55-71` — `npartitions` outer loop with M ≈ 0.24*sqrt(n)+4 iterations
- **Output format:** stdout prints `Mean:` and `Std Dev:` from `timeit.repeat`

## Baseline Command

```bash
docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 1.2468 / Std Dev: 0.0157`
- **Tests:** 1 passed (test_partitions)

## Experimental Conditions

### h-main: Dedekind sum + Kloosterman symmetry + direct cos

Four synergistic optimizations targeting the `_a` function:

1. **Dedekind sum via reciprocity** (`_d_dedekind` function): Replace the O(j) inner k-loop with an O(log j) recursive computation of the Dedekind sum using the reciprocity law: `s(h,k) + s(k,h) = (h²+k²+1)/(12hk) - 1/4`. Memoized with `lru_cache` for reuse across outer-loop iterations.

2. **Kloosterman symmetry**: Exploit the property `D(j-h,j) = -D(h,j)` to show `cos(angle(j-h)) = cos(angle(h))`, halving the coprime iteration range from `range(1, j)` to `range(1, (j-1)//2 + 1)` with a factor-of-2 multiply.

3. **Direct `cos_sin_basecase`**: Bypass the full `mpf_cos` pipeline (which includes redundant normalization, range reduction, and multiprecision overhead) by calling `cos_sin_basecase` directly with manual range reduction via modular arithmetic.

4. **Float path for low precision**: When working precision `prec <= 53` (which applies to most of the 243 outer-loop iterations due to dynamic precision reduction), use hardware `math.cos` instead of any mpmath function.

Additionally: replace `igcd` (sympy wrapper with `as_int` type checking) with `math.gcd` (C builtin).

## Success Criteria

- **Correctness:** All assertions in `test_partitions.py` pass (npartitions values match for n in [0..12, 100, 200, 1000, 2000, 10000, 100000])
- **Performance:** `workload_mean_runtime` decreases from baseline (~1.25s) — directional improvement expected

## Constraints

- Must NOT edit `/tmp/workload.py` or test files
- Must only edit library source under `/testbed`
- All covering tests must pass

## Prior Knowledge

This is the first iteration. No prior principles.
