# Problem Framing — Iteration 4

## Research Question

Can the confirmed three-argument `pow()` optimization in `_legendre()` deliver consistent ~3,500–4,500× speedup at full production scale (5 seeds), and is the speedup mechanism-specific — i.e., does it disappear when the same class of optimization is applied to a code path outside the workload?

The mechanism under study is implemented at `sympy/crypto/crypto.py:2075` (the `_legendre` function). A secondary optimization site at `sympy/crypto/crypto.py:2221` (`encipher_gm`) provides the control-negative target.

## System Interface

- **Build command:** None required — pure Python library, invoked via `PYTHONPATH=$PWD`.
- **Python executable:** `/opt/miniconda3/envs/testbed/bin/python` (Python 3.6.13). System Python 3.11 cannot import this sympy version (`ImportError: cannot import name 'Mapping' from 'collections'`).
- **Workload command:** `PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
  - Calls `_legendre(87389, 131071)` once per timing iteration, 10 repetitions via multiprocessing fork.
  - Prints `Mean:` and `Std Dev:` in seconds.
- **Test command:** `/opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
  - 38 tests total, must all pass.

### Code evidence

- `_legendre` function definition: `sympy/crypto/crypto.py:2054`
- Hot line (two-arg pow): `sympy/crypto/crypto.py:2075` — `sig = pow(a%p, (p - 1)//2) % p`
- `encipher_gm` two-arg pow: `sympy/crypto/crypto.py:2221` — `encode = lambda b: next(gen)**2*pow(a, b) % N`
- Call sites of `_legendre`: lines 2184, 2187 (in `gm_private_key`), line 2242 (in `decipher_gm`)
- All other `pow()` calls in crypto.py (lines 1268, 1288, 1821, 1874, 2008, 2048) already use three-arg form.

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 0.06918086059886264` / `Std Dev: 0.001124186419012558`
- **Key metric:** Mean ≈ 0.069s. Campaign reference baseline: 0.0743s.
- **Tests:** 38 passed in 0.75s (all green).

## Experimental Conditions

### h-main: Three-argument pow in `_legendre`

**Change:** At `crypto.py:2075`, replace `sig = pow(a%p, (p - 1)//2) % p` with `sig = pow(a, (p - 1) // 2, p)`.

**Rationale:** Eliminates construction of a ~1.1M-bit intermediate integer by using Python's C-level modular exponentiation. Removes redundant `a%p` pre-reduction per RP-2.

**Smoke-test result:** Mean 15.5μs (speedup ≈ 4,787×), 38/38 tests pass.

### h-control-negative: Three-argument pow in `encipher_gm` (NOT in workload path)

**Change:** At `crypto.py:2221`, replace `encode = lambda b: next(gen)**2*pow(a, b) % N` with `encode = lambda b: next(gen)**2*pow(a, b, N) % N`.

**Rationale:** Applies the same CLASS of optimization (two-arg pow + mod → three-arg pow) to a code path that is NOT called by the workload. The workload only calls `_legendre(87389, 131071)`. The `encipher_gm` function is not in the workload path. This validates mechanism specificity: the speedup should be zero because the optimized code path is never exercised during measurement.

**Smoke-test result:** Mean 0.069s (speedup ≈ 1.08×, within noise of baseline), 38/38 tests pass.

## Success Criteria

- **h-main:** Speedup ≥ 3,000× consistently across all 5 seeds (based on 14 prior seed measurements spanning iters 1–3 that showed 3,318–4,696×). All 38 tests pass.
- **h-control-negative:** Speedup ≈ 1.0× (within ±10% of baseline). All 38 tests pass.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Must use `/opt/miniconda3/envs/testbed/bin/python` (not system Python).
- `PYTHONPATH=$PWD` required for all invocations.
- Speedup formula: `0.0743 / measured_mean`.
- Campaign allows up to 5 iterations (this is iteration 4).

## Prior Knowledge

- **RP-1 (high confidence):** Three-arg `pow(base, exp, mod)` eliminates exponentially-large intermediates, yielding ~3,300–4,200× speedup. Confirmed across 10 independent seeds in iterations 1–3.
- **RP-2 (high confidence):** The `a%p` pre-reduction is redundant — Python's C-level pow handles unreduced inputs internally. Confirmed in iteration 2.
- **RP-3 (high confidence):** A Jacobi-symbol / quadratic-reciprocity algorithm yields no statistically significant improvement beyond three-arg pow due to ~16μs harness overhead dominating both algorithms' per-call times. Confirmed in iteration 3 (Welch's t=0.80, p≫0.05).
