# Handoff — sympy__sympy-14772 iter-3

## Goal

Apply the confirmed three-argument `pow()` optimization to `_legendre()` (h-main) and test a Jacobi/quadratic-reciprocity alternative algorithm (h-robustness). Run both across 5 seeds with all 38 covering tests passing. Measure speedup as `0.0743 / measured_mean`.

## Key Discoveries

- **Iter-1+2 confirmed RP-1:** Three-arg `pow` yields ~3,300–4,100x speedup consistently across 4 independent seeds (1 in iter-1, 3 in iter-2).
- **Iter-2 confirmed RP-2:** The `a%p` pre-reduction is redundant — removing it has no measurable impact.
- **Jacobi algorithm is ~1.7x faster per call** than three-arg `pow` in microbenchmarks (3.9μs vs 6.6μs amortized, 4.1μs vs 6.9μs single-call), but **not measurably faster in the workload** because ~16μs harness overhead dominates (workload probes: Jacobi 23.8μs vs pow3 22.6μs, within noise).
- **Correctness verified:** Jacobi algorithm matches three-arg `pow` across 131,930 test cases including all edge cases (negative `a`, `a=0`, `a` divisible by `p`, `a > p`).
- After the three-arg pow fix, remaining ~20μs per workload iteration is ~16μs harness overhead (fork + timeit) + ~4-7μs computation. Further speedup is harness-limited.

## System Interface

- **Build:** None needed — pure Python, just set `PYTHONPATH=$PWD`
- **Run baseline:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean: 0.0686s (campaign reference: 0.0743s). 38 tests pass.

## Code Map

- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition. The ONLY function under optimization.
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`. h-main changes this single line; h-robustness replaces lines 2075-2081.
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1). Replaced entirely in h-robustness.
- `sympy/crypto/crypto.py:2184,2187` — Call sites of `_legendre` in `gm_private_key`. Check here if tests fail.
- `sympy/crypto/crypto.py:2242` — Call site in `decipher_gm`: `res = lambda m, p: _legendre(m, p) > 0`.

## Code Targets

### h-main: Three-argument pow (without pre-reduction)
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a, (p - 1) // 2, p)`
- **Why this location:** This is the sole hot path. Removes redundant `a%p` per RP-2.

### h-robustness: Jacobi symbol via quadratic reciprocity
- **File:** `sympy/crypto/crypto.py`
- **Lines:** 2075-2081 (replace entire function body after docstring)
- **Change:** Replace Euler-criterion body with Jacobi algorithm:
  ```python
      a = a % p
      if a == 0:
          return 0
      result = 1
      n = p
      while a != 0:
          while a & 1 == 0:
              a >>= 1
              r = n & 7
              if r == 3 or r == 5:
                  result = -result
          a, n = n, a
          if a & 3 == 3 and n & 3 == 3:
              result = -result
          a = a % n
      if n == 1:
          return result
      return 0
  ```
- **Why this location:** Same function, different algorithm. Tests whether eliminating modular exponentiation entirely produces measurable improvement.

## What I Tried That Didn't Work

- **System Python 3.11** cannot import this sympy version — fails with `ImportError: cannot import name 'Mapping' from 'collections'`. Must use testbed conda env Python 3.6.
- **Running without PYTHONPATH=$PWD** — sympy imports fail without it.
- **Jacobi algorithm in full workload** — despite being ~1.7x faster per call in microbenchmarks, showed no measurable improvement in the full workload (23.8μs vs 22.6μs). Harness overhead (~16μs) dominates.
- **Iter-2 `a%p` ablation** — showed ~2.5% difference, within measurement noise. The pre-reduction is irrelevant.

## What I Excluded and Why

- **No further ablation** — already done in iter-2 (CONFIRMED RP-2).
- **`pow(a, b) % N` at line 2221** — in `encipher_gm`, not in the workload path. No impact.
- **All other pow() calls** in crypto.py (lines 1268, 1288, 1821, 1874, 2008, 2048) already use three-arg form.
- **Workload harness optimization** — harness is read-only; cannot be modified.

## Evolution of Thinking

Iter-1 discovered the core optimization (three-arg pow). Iter-2 confirmed it across 3 seeds and showed the `a%p` pre-reduction is irrelevant. For iter-3, I explored whether an entirely different algorithm (Jacobi/quadratic reciprocity) could outperform three-arg pow:

1. Implemented the binary Jacobi algorithm using bit operations (`&`, `>>`).
2. Verified correctness across 131,930 test cases — perfect match.
3. Microbenchmarked: Jacobi is ~1.7x faster per call (uses only Python-level integer ops vs one C-level pow call).
4. Full workload test: NO measurable improvement — harness overhead dominates both variants.
5. Conclusion: The three-arg pow is the optimal fix for this workload. The computation has been reduced to ~4-7μs; further improvement is blocked by the ~16μs harness overhead. The Jacobi algorithm confirms we've reached the noise floor.

## Current Status

- **Validated:** Three-arg pow optimization delivers ~3,300-4,100x speedup with all 38 tests green. Baseline command works. Both patch variants verified.
- **Uncertain:** Whether Jacobi will show any statistically distinguishable improvement across 5 seeds — probes suggest not, but 5 seeds provide more statistical power than 5 probe runs.
- **Suggested next:** The optimization space for `_legendre` in this workload is exhausted. If the campaign expands scope to other workload functions, look at line 2221 (`pow(a, b) % N` in `encipher_gm`). No further iterations needed for the current workload.

## Warnings & Constraints

- **MUST use testbed Python:** `/opt/miniconda3/envs/testbed/bin/python` (3.6.13). System Python 3.11 cannot import this sympy.
- **PYTHONPATH=$PWD is required** for all runs.
- **Do NOT edit /tmp/workload.py** — read-only per campaign rules.
- **Speedup formula:** `0.0743 / measured_mean` (campaign baseline is 0.0743s).
- **Patch application:** h-main modifies line 2075 only. h-robustness replaces lines 2075-2081. Apply from clean state — do NOT stack.
- **Seeds:** Use seeds 42, 43, 44, 45, 46 (or any 5 distinct values). The workload itself doesn't accept a seed flag — use the seed to label runs. Each run is an independent workload invocation measuring 10 repetitions.
