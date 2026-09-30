# Problem Framing — iter-4: Pure Integer Utility Elimination

## Research Question

After three iterations of optimization achieving 66,584× harness speedup (iter-3), can we achieve a further measurable speedup by eliminating sympy's number-theory utility functions (`divisors`, `sqrt_mod`, `divisible`) from the hot path of `diop_DN`'s `|N|>1` branch and replacing them with pure-integer implementations?

Key source files:
- `sympy/solvers/diophantine.py:996` — `diop_DN` function entry
- `sympy/solvers/diophantine.py:1135-1184` — `|N|>1` branch (primary target)
- `sympy/solvers/diophantine.py:1294` — `PQa` generator (iter-2 integer arithmetic preserved)
- `sympy/solvers/diophantine.py:1469-1477` — `length` function (iter-2 integer version preserved)
- `sympy/ntheory/factor_.py:805` — `factorint` (called by `divisors`)
- `sympy/ntheory/residue_ntheory.py:215` — `sqrt_mod`

## System Interface

- **Build command:** N/A (pure Python library, use `PYTHONPATH=$PWD`)
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Code evidence:**
  - `diophantine.py:1139` — `div = divisors(N)` — calls sympy's `divisors` which dispatches through `factorint`
  - `diophantine.py:1142` — `divisible(N, d**2)` — calls `diophantine.py:743` (`not a % b`)
  - `diophantine.py:1148` — `sqrt_mod(D, abs(m), all_roots=True)` — calls `residue_ntheory.py:215`
  - `diophantine.py:1192` — `r**2` — uses Python's power operator instead of multiplication
  - `diophantine.py:1195-1196` — `diop_DN(D, -1)` called twice (check + retrieve) without caching

## Baseline Command

```
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

With the iter-3 patch applied (the current best optimization):
- Harness Mean: 0.823ms (three runs: 0.837, 0.844, 0.789ms)
- Campaign speedup: 57.3288 / 0.000823 ≈ 69,660×
- All 41 covering tests pass (1 XFAIL: test_fail_holzer)

Profile breakdown of iter-3 code (100 warm calls):
- `diop_DN` tottime: 0.022s (65%) — core inlined PQa loop
- `sqrt_mod`: 0.007s (21%) — sympy's CRT-based sqrt_mod via residue_ntheory
- `divisors`/`factorint`: 0.004s (12%) — sympy's factoring-based divisor enumeration
- `set.add`: 0.002s (6%) — period detection set

With the iter-4 optimization applied (iter-3 + pure integer utilities):
- Harness Mean: 0.310ms (five runs: 0.304, 0.309, 0.304, 0.328, 0.313ms)
- Campaign speedup: 57.3288 / 0.000310 ≈ 184,932×
- All 41 covering tests pass (1 XFAIL: test_fail_holzer)
- Function call count reduced from 387 to 249 per call (36% fewer)

## Experimental Conditions

### Baseline (iter-3 optimized)
The iter-3 patch with inlined PQa + period detection + integer arithmetic for PQa and length. Uses sympy's `divisors()`, `sqrt_mod()`, and `divisible()`.

### h-main Treatment
All iter-3 optimizations PLUS:
1. **Pure integer divisors:** Replace `divisors(N)` + `divisible(N, d²)` with inline trial division `while d*d <= absN: if absN % (d*d) == 0`. Eliminates calls to sympy's `factorint`.
2. **Pure integer sqrt_mod:** Replace `sqrt_mod(D, abs(m), all_roots=True)` with brute-force enumeration `for x in range(abs_m): if (x*x) % abs_m == D_mod` for small moduli (≤100,000). Falls back to sympy for large moduli.
3. **int() conversion at branch entry:** Convert D, N, sD to Python `int` at the top of the |N|>1 branch to avoid sympy `Integer` arithmetic overhead throughout.
4. **Replace `r**2` with `r*r` and `P_i**2` with `P_i*P_i`:** Avoids Python's power function dispatch.
5. **Cache `diop_DN(D, -1)` lazily:** Replace two separate calls (check-then-retrieve) with lazy evaluation and caching.
6. **Replace `abs()` calls with conditional arithmetic:** `abs_m = -m if m < 0 else m` and `absN = -_N if _N < 0 else _N` avoids function call overhead.

Code changes:
- `sympy/solvers/diophantine.py:1135-1208` — Replace entire |N|>1 branch
- `sympy/solvers/diophantine.py:1292-1306` — Integer arithmetic in PQa (iter-2, preserved)
- `sympy/solvers/diophantine.py:1469-1477` — Integer length() (iter-2, preserved)
- `sympy/core/basic.py:3` — Python 3.11 compat fix
- `sympy/plotting/plot.py:28` — Python 3.11 compat fix
- `sympy/matrices/matrices.py:389` — Python 3.11 compat fix

## Success Criteria

- Treatment Mean < baseline (iter-3) Mean, measured by workload harness
- All 41 covering tests pass (test_fail_holzer XFAIL expected)
- Results mathematically verified: all output tuples satisfy x²-Dy²=N
- Speedup = 57.3288 / treatment_mean

## Constraints

- Do NOT edit `/tmp/workload.py` or test files
- Changes must preserve correctness for ALL diop_DN inputs (verified by 41-test suite)
- The `sqrt_mod` brute-force must fall back to sympy for large moduli to maintain generality
- Python 3.11 compatibility fixes required for collections.abc

## Prior Knowledge

- **RP-1:** Loop-invariant hoisting of `length()` (iter-1, 59× speedup)
- **RP-2:** Integer arithmetic in PQa/length (iter-2, 49,519× speedup)
- **RP-3:** Inlined PQa + period detection (iter-3, 66,584× harness speedup, 334,595× direct)

All three prior principles are incorporated into the iter-4 treatment.

### Key Profiling Discovery

Profiling the iter-3 code reveals that sympy utility functions (`sqrt_mod`, `divisors`/`factorint`) still account for ~33% of per-call time (0.011s out of 0.034s for 100 calls). In the forked-process workload harness, first-call cold-start overhead for these sympy functions amplifies the benefit of pure-integer replacements:

| Component | Warm (us) | Pure-int (us) | Savings |
|-----------|-----------|---------------|---------|
| sympy divisors(20) | 5.0 | 0.7 | 86% |
| sympy sqrt_mod(D, 20) | 14.6 | 1.7 | 88% |
| sympy sqrt_mod(D, 5) | 3.0 | 0.9 | 70% |

Additionally, converting D, N, sD to Python `int` at the branch entry eliminates sympy `Integer` arithmetic overhead throughout the entire inner loop (234 iterations of multiplications and divisions), providing a further systematic speedup.
