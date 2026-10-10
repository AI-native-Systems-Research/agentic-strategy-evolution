# Problem Framing — sympy__sympy-11675 iter-1

## Research Question

How can we reduce the runtime of the `diop_DN(15591784605, -20)` workload in SymPy's Diophantine solver without changing observable behavior, while keeping covering tests (`sympy/solvers/tests/test_diophantine.py`) green?

The key mechanism under study is a **loop-invariant `length()` call** inside the inner PQa iteration loop in `diop_DN()` at `sympy/solvers/diophantine.py:1181`. The `length(z, abs(m), D)` function computes the continued-fraction period length — an expensive operation involving symbolic square root evaluation (~0.335s per call). It is called on every iteration `j` of the inner loop despite its arguments `(z, abs(m), D)` being constant throughout that loop. For the workload's parameters, this results in ~231 redundant calls totaling ~120s of the ~42s-per-invocation runtime (5 invocations × ~42s = baseline mean ~57.3s).

## System Interface

- **Build command:** N/A (pure Python library; `PYTHONPATH=$PWD` suffices)
- **Python version note:** The repo targets Python 2.7/3.x; running on Python 3.11 requires compatibility fixes for `collections.Mapping` → `collections.abc.Mapping` (in `sympy/core/basic.py:3`) and `collections.Callable` → `collections.abc.Callable` (in `sympy/plotting/plot.py:28`, `sympy/matrices/matrices.py:389`). These are pre-existing compat issues unrelated to the optimization.
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
  - Prints `Mean:` (seconds, lower is better) and `Std Dev:`.
  - Runs `diop_DN(15591784605, -20)` via `timeit` with 5 repeats.
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Speedup formula:** `57.3288 / measured_mean`

### Code Evidence

- `diop_DN` definition: `sympy/solvers/diophantine.py:996`
- General-case branch (D>0, not perfect square, |N|!=1): `sympy/solvers/diophantine.py:1135`
- Inner PQa loop with `length()` call: `sympy/solvers/diophantine.py:1161-1182`
- `length()` function (delegates to `continued_fraction_periodic`): `sympy/solvers/diophantine.py:1435`
- `continued_fraction_periodic` (uses symbolic `sqrt`): `sympy/ntheory/continued_fraction.py:5`
- `PQa` generator (uses symbolic `floor` and `sqrt`): `sympy/solvers/diophantine.py:1249`
- Redundant `diop_DN(D, -1)` calls: `sympy/solvers/diophantine.py:1174-1175`

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 57.3288` (campaign-declared baseline)
- **Single-call timing (profiled):** ~42s for one `diop_DN(15591784605, -20)` call
- **Profiling evidence:** 167M function calls; `length()` called 231 times at ~0.52s each = ~120s cumulative; `continued_fraction_periodic` dominates via symbolic `sqrt` evaluation

## Experimental Conditions

### Condition: h-main (length-hoisting)

**Change:** In `sympy/solvers/diophantine.py`, hoist the `length(z, abs(m), D)` call from inside the inner `for i in pqa:` loop (line 1181) to just before the loop starts. Store the result in a local variable `l` and use `if j == l:` instead of `if j == length(z, abs(m), D):`.

This reduces `length()` calls from ~231 (once per inner-loop iteration across all `(z, m)` pairs) to just 3 (once per `(z, m)` pair). Since each `length()` call takes ~0.335s, this eliminates ~228 * 0.335s = ~76s of redundant computation per single `diop_DN` call.

**Validated speedup from probe:** Single `diop_DN` call dropped from 42s to 0.95s (44x). Full workload (5 repeats) dropped from 57.33s mean to 0.96s mean (~59.6x speedup).

## Success Criteria

- **Speedup:** `57.3288 / treatment_mean` should be substantially greater than 1.0 (probe observed ~59.6x).
- **Correctness:** All covering tests pass (`python -m pytest -q sympy/solvers/tests/test_diophantine.py` — 41 passed, 1 expected failure).
- **Identical results:** `sorted(diop_DN(15591784605, -20))` produces the same 3 solution tuples as baseline.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- A change that speeds up the workload but breaks covering tests has speedup nullified to 1.0.
- Python 3.11 compat fixes (`collections.Mapping` → `collections.abc.Mapping`, `collections.Callable` → `collections.abc.Callable`) are pre-existing issues required for import success but are not part of the optimization experiment.

## Prior Knowledge

This is iteration 1. No prior principles exist.
