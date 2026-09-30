# Problem Framing — iter-5: Performance Ceiling Confirmation

## Research Question

Can any combination of micro-optimizations (branchless return, bitshift exponent) provide measurable speedup beyond the three-argument `pow()` optimization in `_legendre()` at `sympy/crypto/crypto.py:2075`, or has the optimization space reached its practical ceiling?

Iterations 1–4 established that three-arg `pow(a, (p-1)//2, p)` yields ~3,000–4,000× speedup by eliminating a ~1.1M-bit intermediate integer (RP-1). All alternative approaches — Jacobi algorithm (RP-3), `a%p` pre-reduction ablation (RP-2), combined micro-optimizations, `sympy.ntheory.jacobi_symbol` delegation, bitshift exponent — showed no measurable further improvement. Mechanism specificity was confirmed via control-negative (RP-4).

This final iteration tests the **performance ceiling hypothesis**: that three-arg pow alone captures the entire optimization opportunity, and stacking additional micro-optimizations (branchless conditional, bitshift exponent) cannot produce measurable improvement above the ~16μs multiprocessing fork overhead floor.

### Key source files:
- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition
- `sympy/crypto/crypto.py:2075` — Hot line: `sig = pow(a%p, (p - 1)//2) % p`
- `sympy/crypto/crypto.py:2076-2081` — Return logic (if/elif/else chain)

## System Interface

- **Build command:** None needed (pure Python). Set `PYTHONPATH=$PWD`.
- **Run workload:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Speedup formula:** `0.0743 / measured_mean`

### Code Evidence

- `sympy/crypto/crypto.py:2075` — the hot line where `pow(a%p, (p-1)//2) % p` is computed. This is the only performance-critical line in the workload's call path.
- `sympy/crypto/crypto.py:2076-2081` — the if/elif/else return chain. h-robustness tests replacing this with a branchless expression.
- `/tmp/workload.py:12` — `_ = _legendre(a, p)` — the timed function call.
- `/tmp/workload.py:36-37` — multiprocessing fork context, contributing ~16μs overhead per measurement.

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py
```

## Baseline Validation

Ran baseline on unmodified code:
- **Exit code:** 0
- **Mean:** 0.0695s
- **Std Dev:** 0.0011s
- **Speedup:** 0.0743 / 0.0695 = 1.07× (baseline, within noise of campaign reference)
- **Tests:** 38/38 pass

Ran h-main smoke test (three-arg pow at line 2075):
- **Mean:** 2.06e-05s (20.6μs)
- **Speedup:** 0.0743 / 0.0000206 ≈ 3,607×
- **Tests:** 38/38 pass

Ran h-robustness smoke test (three-arg pow + bitshift + branchless):
- **Mean:** 2.06e-05s (20.6μs)
- **Speedup:** 0.0743 / 0.0000206 ≈ 3,607×
- **Tests:** 38/38 pass

Per-call microbenchmarks (in-process, no fork overhead):
- Raw `pow(87389, 65535, 131071)`: 3.13μs
- Branched `_legendre` with three-arg pow: 3.16μs
- Branchless `_legendre` with three-arg pow + bitshift: 3.22μs
- Empty function call: 0.06μs

Conclusion: function-level overhead is <0.1μs over raw pow; the ~16μs fork overhead completely dominates the measured workload time.

## Experimental Conditions

### h-main: Three-argument pow optimization
**Change:** Line 2075: `pow(a%p, (p-1)//2) % p` → `pow(a, (p - 1) // 2, p)`

This is the canonical optimization (RP-1), confirmed across 15 seeds in iterations 1–4. This arm provides the final 5-seed definitive measurement.

### h-robustness: Maximal micro-optimization variant
**Change:** Lines 2075–2081: Replace the entire computation + return logic with:
```python
sig = pow(a, p >> 1, p)
return sig if sig <= 1 else -1
```

This combines ALL known micro-optimizations:
1. Three-arg pow (eliminates big intermediate — the dominant effect)
2. Bitshift exponent (`p >> 1` instead of `(p-1)//2` — saves one subtraction + one division → single bitshift)
3. Branchless return (`sig if sig <= 1 else -1` instead of if/elif/else — eliminates branch chain)

Correctness verified for all three return cases: sig=0 (a divisible by p), sig=1 (quadratic residue), sig=p−1 (non-residue, maps to −1). For odd primes, `p >> 1 == (p-1)//2` algebraically.

## Success Criteria

1. **h-main speedup > 2,500×** across all 5 seeds (conservative floor; prior runs average ~3,500×).
2. **h-robustness speedup within ±20% of h-main** — confirming additional micro-optimizations provide no measurable benefit above the fork overhead floor.
3. **38/38 covering tests pass** for both arms.
4. **h-robustness mean ≈ h-main mean** — confirming the optimization ceiling.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Use `PYTHONPATH=$PWD` for all runs.
- Use `/opt/miniconda3/envs/testbed/bin/python` (Python 3.6.13 — system Python 3.11 cannot import this sympy).
- Speedup = `0.0743 / measured_mean`.
- Apply patches from clean state — do NOT stack h-main and h-robustness patches.

## Prior Knowledge

- **RP-1 (high confidence):** Three-arg pow yields ~3,000–4,000× speedup for large exponents. Confirmed across 15 seeds in 4 iterations.
- **RP-2 (high confidence):** `a%p` pre-reduction is redundant. Confirmed in iter-2.
- **RP-3 (high confidence):** Jacobi algorithm provides no measurable improvement in the full workload due to ~16μs fork overhead. Confirmed in iter-3.
- **RP-4 (high confidence):** The speedup is mechanism-specific to the `_legendre` code path. Confirmed via control-negative in iter-4.
- **Microbenchmark evidence (this iter):** Per-call times: raw pow = 3.13μs, branched function = 3.16μs, branchless function = 3.22μs. The function overhead is <0.1μs — the fork overhead (~16μs) dominates the remaining ~17μs of measured time above the raw computation.
