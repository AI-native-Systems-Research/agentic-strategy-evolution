# Problem Framing — iter-3: legendre-modpow-optimization

## Research Question

Can the confirmed three-argument `pow()` optimization in `_legendre()` deliver a consistent ~3,300–4,100x speedup at full experiment scope (5 seeds), and does replacing Euler's criterion with a Jacobi-symbol / quadratic-reciprocity algorithm yield any additional measurable improvement?

**Prior findings:**
- Iter-1 (CONFIRMED): Three-arg `pow` yields ~3,906x speedup (1 seed).
- Iter-2 (CONFIRMED): Effect replicates across 3 seeds at ~4,068x. The `a%p` pre-reduction is redundant (RP-2).
- Iter-3 escalates to 5 seeds for the primary optimization and adds a robustness arm testing an entirely different algorithm.

**Key source files:**
- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1)

## System Interface

- **Build:** None required — pure Python library, uses `PYTHONPATH=$PWD`
- **CLI flags:** No CLI. The workload is `PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Code evidence:**
  - `sympy/crypto/crypto.py:2075` — the two-arg pow call: `sig = pow(a%p, (p - 1)//2) % p`
  - `/tmp/workload.py:11-12` — workload calls `_legendre(87389, 131071)` with `a=87389, p=131071`
  - The workload uses `timeit` with `number=1`, `repeat=10`, multiprocessing fork
- **Output:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Test suite:** `python -m pytest -q sympy/crypto/tests/test_crypto.py` (38 tests)

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py
```

## Baseline Validation

Ran baseline command. Exit code 0. Output:
```
Mean: 0.06862385489657755
Std Dev: 0.0012146973888342658
```
Campaign reference baseline: 0.0743s. Measured baseline: 0.0686s. Speedup = 0.0743 / 0.0686 ≈ 1.08x (system-specific variance).

All 38 covering tests pass on the unmodified codebase.

## Experimental Conditions

### Arm selection rationale

Two arms are included:

1. **h-main** — Applies the confirmed three-arg `pow` optimization (RP-1) without the redundant `a%p` pre-reduction (RP-2). This is the simplest, cleanest fix delivering ~3,300–4,100x speedup. Iter-3 runs 5 seeds for stronger statistical confidence.

2. **h-robustness** — Replaces the entire Euler-criterion computation with a Jacobi-symbol algorithm based on quadratic reciprocity. This uses only integer arithmetic (shifts, comparisons, modular reductions) — no modular exponentiation at all. Microbenchmarks show the Jacobi per-call is ~1.7x faster than three-arg `pow` (3.9μs vs 6.6μs amortized), but the workload harness overhead (~16μs) dominates both, so the net workload improvement is predicted to be negligible. This arm tests mechanism robustness: does an entirely different algorithm change the outcome?

No h-ablation: already completed in iter-2, confirmed RP-2.
No h-control-negative: the ~3,900x effect is a complexity-class change; no diagnostic value in a control.
No h-dose-response: the knob is binary (algorithm choice), not continuous.

### h-main: Three-argument pow (without pre-reduction)

**Change at `crypto.py:2075`:**
- From: `sig = pow(a%p, (p - 1)//2) % p`
- To: `sig = pow(a, (p - 1) // 2, p)`

**Intent:** Replace two-argument pow (constructs ~1.1M-bit intermediate) with three-argument modular pow (intermediates bounded by `p` ~17 bits). Remove redundant `a%p` per RP-2.

### h-robustness: Jacobi symbol via quadratic reciprocity

**Change at `crypto.py:2075-2081`:**
Replace the entire Euler-criterion body with the binary Jacobi algorithm:
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

**Intent:** Eliminate modular exponentiation entirely. The Jacobi algorithm computes the Legendre symbol using only the law of quadratic reciprocity and properties of the Jacobi symbol — a GCD-like algorithm in O(log²p) using only shifts, comparisons, and modular reductions on small integers.

## Success Criteria

1. **h-main**: Speedup ≥ 3,000x (0.0743 / mean) consistently across all 5 seeds with 38/38 tests passing.
2. **h-robustness**: Speedup ≥ 3,000x with 38/38 tests passing. The directional prediction: similar to h-main (no statistically significant improvement due to harness-dominated measurement).

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Must use `/opt/miniconda3/envs/testbed/bin/python` (Python 3.6.13). System Python 3.11 cannot import this sympy version.
- `PYTHONPATH=$PWD` is required for all runs.
- Speedup formula: `0.0743 / measured_mean`.
- Patches modify the same region (lines 2075-2081). Apply from clean state; do NOT stack.

## Prior Knowledge

- **RP-1 (high confidence):** Three-arg pow yields multiple-orders-of-magnitude speedup. Confirmed in iter-1 (1 seed) and iter-2 (3 seeds). Iter-3 extends to 5 seeds.
- **RP-2 (high confidence):** The `a%p` pre-reduction is redundant. Confirmed in iter-2 ablation. Iter-3's h-main applies this directly.
- **Iter-2 handoff finding:** After the three-arg pow fix, the remaining ~19μs per workload iteration is dominated by harness overhead (~16μs). Further computation improvements face a noise floor.
