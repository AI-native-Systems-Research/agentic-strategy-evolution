# Problem Framing — sympy npartitions Performance Optimization

## Research Question

How can we reduce the runtime of `npartitions(10**6)` in sympy's Hardy-Ramanujan-Rademacher (HRR) formula implementation without changing observable behavior?

The workload calls `npartitions(10**6)` which is implemented in `sympy/ntheory/partitions_.py:55`. The inner sum function `_a()` at line 12 dominates runtime at ~70% of total execution time (1.156s of 1.642s in profiling). The inner k-loop within `_a` performs ~2.9 million iterations of big-integer arithmetic on ~4148-bit fixed-point numbers.

Key source files:
- `sympy/ntheory/partitions_.py:12` — `_a()` function (inner Kloosterman-like sum, the hotspot)
- `sympy/ntheory/partitions_.py:39` — `_d()` function (sinh term, fast, ~0.029s)
- `sympy/ntheory/partitions_.py:55` — `npartitions()` main function
- `sympy/core/numbers.py:142` — `igcd()` function (called 29,403 times, slow due to Python overhead vs C-level `math.gcd`)

## System Interface

- **Build command:** None needed (pure Python). Requires `mpmath` package.
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Output format:** Prints `Mean:` and `Std Dev:` to stdout.
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:7` — `from sympy.core.numbers import igcd` (replaced by `from math import gcd`)
  - `sympy/ntheory/partitions_.py:19` — `if igcd(h, j) != 1:` coprimality check in h-loop
  - `sympy/ntheory/partitions_.py:22-33` — inner k-loop computing fixed-point Dedekind-like sum
  - `sympy/ntheory/partitions_.py:86-87` — outer q-loop calling `_a` and `_d`
  - `sympy/ntheory/partitions_.py:94` — dynamic precision reduction `p = bitcount(abs(to_int(d))) + 50`

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

- Exit code: 0
- Output: `Mean: 1.0413860368993482`, `Std Dev: 0.01629019820219409`
- Reference baseline: 1.3901s (as stated in campaign)
- Tests: 1 passed (test_partitions)

## Experimental Conditions

### Condition: h-main (optimized _a function)

Changes to `sympy/ntheory/partitions_.py`:

1. **Replace `igcd` with `math.gcd`**: The `igcd` function from `sympy.core.numbers` uses a Python-level cache and `as_int()` type checking on every call. `math.gcd` is a C-builtin that is ~9x faster for the integer inputs used here (benchmarked: 0.089s vs 0.010s for 100k calls).

2. **Hoist loop-invariant big-integer constants out of the h-loop**: `one = 1 << prec`, `onemask`, and `half = one >> 1` are currently recomputed for every value of h. These depend only on `prec` which is constant within `_a`. Move them before the h-loop.

3. **Precompute fractional-part lookup table**: The inner k-loop computes `(h*k*one)//j` then extracts its lower `prec` bits. Since `(h*k*one // j) & onemask = ((h*k % j) * one) // j`, and `h*k % j` ranges over 0..j-1, precompute `frac_table[r] = (r * one) // j` for r in 0..j-1 once per call to `_a` (only j entries). This converts each inner-loop iteration from a division of a ~4148-bit integer by a small number + bitmask + subtraction to a single table lookup + multiply by small int + add.

4. **Factor out the half-subtraction**: Instead of subtracting `half` from each `frac` value inside the loop (j-1 big-int subtractions), precompute `half_sum = half * j*(j-1)//2` and subtract once after the loop.

5. **Precompute `2*n*one`**: The expression `2*h*n*one` in the final g computation is split to `h * n2one` where `n2one = 2*n*one` is computed once.

### Condition: baseline (unmodified code)

Run with the original `sympy/ntheory/partitions_.py`.

## Success Criteria

- **Speedup > 1.0**: The optimized code must produce a lower Mean runtime than the baseline, giving speedup = 1.3901 / treatment_mean > 1.0.
- **Correctness**: All covering tests in `test_partitions.py` must pass (exact integer results for npartitions at various inputs).
- **Probe result**: In isolated testing, the optimized `_a` function produces identical results to the original for j=50 and j=200, and the full `npartitions(10**6)` returns the same integer value. End-to-end runtime reduced from ~1.04s to ~0.49s (2.1x speedup on this machine, ~2.8x relative to reference baseline).

## Constraints

- Must not edit `/tmp/workload.py` or any test files.
- Must keep all covering tests green.
- The optimization must produce bit-identical results (npartitions returns exact integer).
- Python 3.11 compatibility fixes (in `sympy/core/basic.py`, `sympy/core/function.py`, `sympy/ntheory/egyptian_fraction.py`, `sympy/plotting/plot.py`) are required for the import chain to work but are NOT part of the experiment — they are infrastructure fixes.

## Prior Knowledge

This is iteration 1. No prior principles exist.

The profiling data shows:
- `_a` function: 1.156s tottime (70% of total 1.642s)
- `mpf_cos`: 0.286s cumulative (18,055 calls within `_a`)
- `igcd`: 0.077s (29,403 calls, reducible to ~0.01s with `math.gcd`)
- Inner k-loop: ~2,915,711 iterations total, each performing 5+ big-integer operations on ~4148-bit numbers
- Dynamic precision reduction means early terms (q=1..~20) use full 4148-bit precision and dominate cost
