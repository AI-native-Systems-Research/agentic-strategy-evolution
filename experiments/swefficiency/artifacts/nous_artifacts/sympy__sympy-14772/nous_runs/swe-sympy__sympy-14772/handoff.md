# Handoff — sympy__sympy-14772 iter-5

## Goal

Run the final iteration: measure the three-arg `pow()` optimization (h-main) and the maximal micro-optimization variant (h-robustness: three-arg pow + bitshift + branchless return) across 5 seeds each, with all 38 covering tests passing. Confirm the performance ceiling — that stacking micro-optimizations produces no measurable improvement over three-arg pow alone.

## Key Discoveries

- **Three-arg pow yields ~3,000–4,000× speedup** — confirmed across 15+ seeds in iterations 1–4. Mean speedup across all prior runs: ~3,500×. The mechanism is eliminating a ~1.1M-bit intermediate integer.
- **`a%p` pre-reduction is redundant (RP-2)** — Python's C-level three-arg pow handles unreduced inputs internally. Confirmed in iter-2.
- **Jacobi algorithm provides no measurable improvement (RP-3)** — despite being ~1.7× faster per call in microbenchmarks (3.8μs vs 6.5μs), the ~16μs multiprocessing fork overhead makes both indistinguishable in the workload. Confirmed in iter-3.
- **Speedup is mechanism-specific to `_legendre` (RP-4)** — applying the same optimization to `encipher_gm` (line 2221, not in workload) shows no speedup (1.06×). Confirmed in iter-4.
- **Per-call floor (this iter's probes):** raw pow = 3.13μs, branched function = 3.16μs, branchless function = 3.22μs. Function overhead is <0.1μs. The ~16μs fork overhead dominates remaining measured time.
- **Branchless return is correct for all cases:** `sig if sig <= 1 else -1` works because `pow(a, (p-1)//2, p)` returns only 0, 1, or p−1. Verified for a ∈ {0, 1, 2, 5, 87389, 131070, 131071}.
- **Bitshift equivalence verified:** `p >> 1 == (p-1) // 2` for all odd primes (algebraically and numerically confirmed).

## System Interface

- **Build:** None needed — pure Python, just set `PYTHONPATH=$PWD`
- **Run workload:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean ≈ 0.0695s, 38 tests pass. Campaign reference: 0.0743s.

## Code Map

- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition. The ONLY function under optimization.
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`. Both h-main and h-robustness modify this.
- `sympy/crypto/crypto.py:2076-2081` — Return logic (if/elif/else chain). h-robustness replaces this with branchless expression.
- `sympy/crypto/crypto.py:2184,2187` — Call sites of `_legendre` in `gm_private_key`. Check here if tests fail.
- `sympy/crypto/crypto.py:2242` — Call site in `decipher_gm`.
- `sympy/crypto/tests/test_crypto.py:309` — `test_encipher_decipher_gm` exercises the full GM encryption pipeline.

## Code Targets

### h-main: Three-argument pow
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a, (p - 1) // 2, p)`
- **Why:** Eliminates ~1.1M-bit intermediate. Keep return logic (lines 2076-2081) unchanged.

### h-robustness: Maximal micro-optimization
- **File:** `sympy/crypto/crypto.py`
- **Lines:** 2075-2081 (entire computation + return block)
- **Change:** Replace all 7 lines with:
  ```python
      sig = pow(a, p >> 1, p)
      return sig if sig <= 1 else -1
  ```
- **Why:** Combines three-arg pow + bitshift exponent + branchless return. Tests whether any micro-optimization headroom remains.

## What I Tried That Didn't Work

- **System Python 3.11** — `ImportError: cannot import name 'Mapping' from 'collections'`. Must use testbed conda env Python 3.6.
- **Running without PYTHONPATH=$PWD** — sympy imports fail.
- **Jacobi algorithm in full workload (iter-3)** — Welch's t=0.80, no measurable improvement due to fork overhead.
- **`a%p` ablation (iter-2)** — ~2.5% difference, within measurement noise.
- **`sympy.ntheory.jacobi_symbol` delegation (iter-4)** — 6.4μs/call, same as three-arg pow due to validation overhead.
- **Combined micro-optimizations in microbenchmarks (iter-4)** — 6.6μs vs 6.6μs, identical.
- **Bitshift exponent in microbenchmarks (iter-4)** — 6.1μs vs 6.0μs, no measurable difference.
- **Control-negative: encipher_gm optimization (iter-4)** — 1.06× speedup (noise), confirming mechanism specificity.

## What I Excluded and Why

- **No further algorithmic alternatives** — Jacobi was the only plausible alternative; exhaustively tested in iter-3.
- **No `a%p` ablation** — already confirmed redundant in iter-2.
- **No control-negative** — already confirmed mechanism specificity in iter-4.
- **No workload modification** — read-only per campaign rules.
- **No Cython/C extensions** — not feasible in this environment.
- **No memoization** — workload clears cache in setup and calls `_legendre` once per timing iteration.

## Evolution of Thinking

Iterations 1–4 systematically explored the optimization space:
- Iter-1: Discovered three-arg pow (the single dominant optimization)
- Iter-2: Confirmed across seeds + showed `a%p` pre-reduction redundant
- Iter-3: Tested Jacobi algorithm (no improvement in workload due to fork overhead)
- Iter-4: Confirmed mechanism specificity via control-negative

For iter-5, the question shifted from "can we find a better optimization?" to "have we reached the performance ceiling?" The answer from microbenchmark probes is definitive: raw `pow(87389, 65535, 131071)` takes 3.13μs, and the full optimized function takes 3.16μs. The function overhead is 0.03μs. There is literally no room for improvement in the computation itself. The remaining measured workload time (~17μs above the raw computation) is entirely multiprocessing fork overhead.

The h-robustness arm formally tests this ceiling at full workload scale.

## Current Status

- **Validated:** Baseline command works (Mean ≈ 0.0695s). h-main smoke test works (Mean ≈ 20.6μs, ~3,607× speedup, 38/38 tests). h-robustness smoke test works (Mean ≈ 20.6μs, ~3,607× speedup, 38/38 tests). Both correctness-verified for all return cases.
- **Uncertain:** Nothing — all predictions grounded in extensive prior evidence + microbenchmark probes.
- **Suggested next:** The investigation is complete. The three-arg pow optimization is the single, definitive optimization for this workload, yielding ~3,500× speedup. No further improvement is possible without modifying the measurement harness or the workload.

## Warnings & Constraints

- **MUST use testbed Python:** `/opt/miniconda3/envs/testbed/bin/python` (3.6.13).
- **PYTHONPATH=$PWD is required** for all runs.
- **Do NOT edit /tmp/workload.py** — read-only per campaign rules.
- **Speedup formula:** `0.0743 / measured_mean`.
- **Apply patches from clean state** — do NOT stack h-main and h-robustness patches. Always `git checkout -- .` between arms.
- **Seeds:** Use runs labeled seed42 through seed46. The workload doesn't accept a seed parameter — each "seed" is simply an independent invocation of the workload.
- **h-robustness correctness:** `p >> 1 == (p-1)//2` for odd primes. `sig if sig <= 1 else -1` correct because pow returns only 0, 1, or p−1. All 38 tests pass.
