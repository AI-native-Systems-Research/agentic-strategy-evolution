# Handoff — sympy__sympy-14772 iter-1

## Goal

Apply the three-argument `pow()` optimization to `_legendre()` in `sympy/crypto/crypto.py`, measure the speedup, and verify all 38 covering tests pass.

## Key Discoveries

- The workload calls `_legendre(87389, 131071)` which computes the Legendre symbol via `pow(a%p, (p-1)//2) % p` at `crypto.py:2075`.
- The two-argument `pow` creates a ~1.1 million-bit intermediate integer (87389^65535) before reducing mod 131071. This dominates runtime.
- Python's three-argument `pow(base, exp, mod)` performs modular exponentiation in C, keeping intermediates bounded by `mod` (~17 bits). This is an algorithmic complexity class change.
- Probe results: baseline mean 0.069s → optimized mean 0.000016s. Speedup ≈ 4,225x. All 38 tests green.
- The correct Python executable is `/opt/miniconda3/envs/testbed/bin/python` (Python 3.6.13). The system Python 3.11 cannot import this version of sympy due to `collections.Mapping` removal.

## System Interface

- **Build:** None needed — pure Python, just set `PYTHONPATH=$PWD`
- **Run baseline:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean: 0.06929s (campaign reference: 0.0743s)

## Code Map

- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition. The ONLY function under optimization.
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`. Change to three-arg pow here.
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1). Unchanged.
- `sympy/crypto/crypto.py:2184,2187` — Call sites of `_legendre` in `gm_private_key`. Check here if tests fail.
- `sympy/crypto/tests/test_crypto.py` — 38 tests covering all crypto functions.

## Code Targets

### h-main: Three-argument pow
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a % p, (p - 1) // 2, p)`
- **Why this location:** This is the sole hot path. The function is called once per workload iteration. The entire baseline runtime is spent computing the huge intermediate integer.

## What I Tried That Didn't Work

- **System Python 3.11** cannot import this sympy version — fails with `ImportError: cannot import name 'Mapping' from 'collections'`. Must use the testbed conda env Python 3.6.
- **Running without PYTHONPATH=$PWD** — sympy imports fail without it since the repo isn't installed.

## What I Excluded and Why

- **No negative control arm** — The effect is ~4,000x and the mechanism is a well-understood algorithmic complexity class change (exponential-size intermediate vs. bounded-size intermediate). A negative control (e.g., tiny p where both forms are fast) would confirm the obvious and waste compute at iter-1/tier-1.
- **No dose-response arm** — The knob is binary (two-arg vs three-arg pow); there's no continuous parameter to sweep.
- **Other call sites of pow in crypto.py** — Searched and found no other two-arg pow calls with large exponents in the hot path.

## Evolution of Thinking

Started by reading the workload — immediately saw the `_legendre` function is the only computation. Read the implementation and recognized the classic two-arg-pow-then-mod anti-pattern. Confirmed with a quick microbenchmark showing ~25,000x difference. Applied the fix, measured ~4,225x speedup on the full workload harness, and verified all tests pass. This is a textbook modular exponentiation optimization — no subtlety or risk.

## Current Status

- **Validated:** Patch applies cleanly, produces ~4,000x speedup, all 38 tests pass. Patch saved at `patches/h-main.patch`.
- **Uncertain:** Nothing — the mechanism and effect are fully characterized.
- **Suggested next:** If further optimization is desired, profile the remaining ~16μs to see if it's dominated by function call overhead, the `a % p` pre-reduction, or the three-arg pow itself. But the current speedup is already transformative.

## Warnings & Constraints

- **MUST use testbed Python:** `/opt/miniconda3/envs/testbed/bin/python` (3.6.13). System Python 3.11 cannot import this sympy version.
- **PYTHONPATH=$PWD is required** — the repo is not pip-installed.
- **Do NOT edit /tmp/workload.py** — the workload is read-only per campaign rules.
- **Speedup formula:** `0.0743 / measured_mean` (campaign baseline is 0.0743s, not the measured baseline).
