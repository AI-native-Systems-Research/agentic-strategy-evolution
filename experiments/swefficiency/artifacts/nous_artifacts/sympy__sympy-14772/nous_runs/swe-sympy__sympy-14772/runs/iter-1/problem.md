# Problem Framing — sympy__sympy-14772 iter-1

## Research Question

How can we reduce the runtime of the `_legendre(a, p)` function in `sympy/crypto/crypto.py` without changing observable behavior, while keeping the covering tests (`sympy/crypto/tests/test_crypto.py`) green?

The workload calls `_legendre(87389, 131071)` — computing the Legendre symbol via modular exponentiation. The implementation at `sympy/crypto/crypto.py:2075` uses two-argument `pow(a%p, (p-1)//2) % p`, which computes a huge intermediate integer before taking the modulus. Python's built-in three-argument `pow(base, exp, mod)` performs modular exponentiation natively in C, avoiding the enormous intermediate.

## System Interface

- **Build command:** None required — pure Python library; just set `PYTHONPATH=$PWD`.
- **Run workload:** `PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `/opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Code evidence:**
  - `sympy/crypto/crypto.py:2054` — `_legendre` function definition
  - `sympy/crypto/crypto.py:2075` — the hot line: `sig = pow(a%p, (p - 1)//2) % p`
- **Output format:** Workload prints `Mean: <seconds>` to stdout. Lower is faster. Speedup = 0.0743 / measured_mean.

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 0.06929` (10 repetitions)
- **Campaign reference baseline:** 0.0743s
- **Tests:** 38 passed in 0.89s (all green)

## Experimental Conditions

### h-main: Three-argument pow (modular exponentiation)

**Change:** In `sympy/crypto/crypto.py:2075`, replace `pow(a%p, (p - 1)//2) % p` with `pow(a % p, (p - 1) // 2, p)`.

**Rationale:** Python's three-argument `pow(base, exp, mod)` uses C-level modular exponentiation (square-and-multiply with mod at each step), avoiding the construction of a ~1.7-million-digit intermediate integer. The two-argument form computes `87389^65535` as a raw integer (≈65,535 × 17 ≈ 1.1 million bits) before a final mod — this dominates runtime.

**Validated result:** Mean dropped from 0.069s to 0.000016s (speedup ≈ 4,225x). All 38 tests pass.

## Success Criteria

- Speedup > 1.0 (any measurable improvement) — the observed speedup is ~4,000x, so this is unambiguous.
- All 38 tests in `sympy/crypto/tests/test_crypto.py` remain green.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Do NOT change observable behavior (same return values for all inputs).
- The `_legendre` function's mathematical semantics must be preserved: returns 1, -1, or 0 per the Legendre symbol definition.

## Prior Knowledge

This is iteration 1. No active principles exist.
