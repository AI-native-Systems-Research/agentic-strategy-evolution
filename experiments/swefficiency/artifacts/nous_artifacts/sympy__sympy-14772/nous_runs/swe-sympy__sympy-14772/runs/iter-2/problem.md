# Problem Framing — iter-2: legendre-modpow-optimization

## Research Question

Can replacing the two-argument `pow(base, exp) % mod` with three-argument `pow(base, exp, mod)` in `_legendre()` reduce the workload runtime by multiple orders of magnitude while preserving all observable behavior?

This builds on iter-1's CONFIRMED finding (RP-1): the optimization yields ~3,900x speedup. Iter-2 runs the confirmed mechanism at full scope plus an ablation to test whether the `a%p` pre-reduction contributes measurable overhead.

**Key source files:**
- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1)
- `sympy/crypto/crypto.py:2184,2187,2242` — Call sites of `_legendre` in `gm_private_key` and `decipher_gm`

## System Interface

- **Build:** None required — pure Python library, uses `PYTHONPATH=$PWD`
- **CLI flags:** No CLI. The workload is `PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Code evidence:**
  - `sympy/crypto/crypto.py:2075` — the two-arg pow call: `sig = pow(a%p, (p - 1)//2) % p`
  - `/tmp/workload.py:11-12` — workload calls `_legendre(87389, 131071)`
  - The workload uses `timeit` with `number=1`, `repeat=10`, forked processes
- **Output:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Test suite:** `python -m pytest -q sympy/crypto/tests/test_crypto.py` (38 tests)

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py
```

## Baseline Validation

Ran baseline command. Exit code 0. Output:
```
Mean: 0.06858299160230671
Std Dev: 0.001495718655066475
```
Speedup baseline: 0.0743 / 0.0686 ≈ 1.08x (consistent with campaign reference of 0.0743s).

## Experimental Conditions

### Arm selection rationale

Two arms are included:

1. **h-main** — The confirmed three-arg pow optimization. This is the primary intervention, applying RP-1 directly.
2. **h-ablation** — Removes the `a%p` pre-reduction from the h-main fix. Tests whether this arithmetic step adds measurable overhead. Python's three-arg `pow(a, exp, mod)` handles `a >= mod` internally, making the explicit `a%p` redundant. Verified: `pow(a, (p-1)//2, p) == pow(a%p, (p-1)//2, p)` for all edge cases including negative `a` and `a=0`.

### h-main: Three-argument pow with pre-reduction

**Change at `crypto.py:2075`:**
- From: `sig = pow(a%p, (p - 1)//2) % p`
- To: `sig = pow(a % p, (p - 1) // 2, p)`

**Intent:** Replace two-argument pow (constructs ~1.1M-bit intermediate) with three-argument modular pow (intermediates bounded by `p` ~17 bits).

### h-ablation: Three-argument pow without pre-reduction

**Change at `crypto.py:2075`:**
- From: `sig = pow(a%p, (p - 1)//2) % p`
- To: `sig = pow(a, (p - 1) // 2, p)`

**Intent:** Same as h-main but additionally removes the `a%p` pre-reduction, testing whether it contributes overhead.

## Success Criteria

- **h-main:** Speedup > 1000x (0.0743 / mean < 7.43e-05s). All 38 covering tests pass.
- **h-ablation:** Speedup comparable to h-main (within measurement noise). All 38 tests pass.

## Constraints

- Must use `/opt/miniconda3/envs/testbed/bin/python` (Python 3.6.13). System Python 3.11 cannot import this sympy version.
- `PYTHONPATH=$PWD` is required.
- Do NOT edit `/tmp/workload.py` or test files.
- Speedup formula: `0.0743 / measured_mean`.

## Prior Knowledge

- **RP-1 (high confidence):** Replacing two-argument pow with three-argument pow eliminates exponentially-large intermediates, yielding ~3,900x speedup. Confirmed in iter-1 with 3 seeds × 10 reps. Treatment mean: ~19μs.
- Probe validated that `pow(a, exp, p)` (no pre-reduction) is functionally equivalent to `pow(a%p, exp, p)` for all relevant inputs including negative `a` and `a=0`.
- Microbenchmark: the `a%p` pre-reduction adds ~3% overhead (~0.1μs), well within noise for the full workload harness.
