# Problem Framing — iter-1

## Research Question

How can we reduce the runtime of `_check_hour_range(15)` (a scalar-input range validation call) in `astropy/coordinates/angles/formats.py` by avoiding unnecessary NumPy overhead for scalar arguments, while keeping the full covering test suite green?

The hot function is `_check_hour_range` at `astropy/coordinates/angles/formats.py:322`. It unconditionally uses `np.any(np.abs(hrs) == 24.0)` and `np.any(hrs < -24.0) or np.any(hrs > 24.0)` even for plain Python scalars (int/float), where built-in `abs()` and comparison operators are ~50-100x faster than NumPy equivalents.

## System Interface

- **Build command:** No build step needed — pure Python library.
- **Run workload:** `docker exec swegen_astropy_astropy-16295_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"`
- **Run tests:** `docker exec swegen_astropy_astropy-16295_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python -m pytest -q astropy/coordinates/tests/test_angles.py <other_test_files>"`
- **Code evidence:**
  - `astropy/coordinates/angles/formats.py:322` — `_check_hour_range` definition using `np.any(np.abs(...))` for all inputs.
  - `astropy/coordinates/angles/formats.py:332` — `_check_minute_range` (same pattern).
  - `astropy/coordinates/angles/formats.py:344` — `_check_second_range` (same pattern).
  - `astropy/coordinates/angles/core.py:170` — call site passing `angle[0]` (a Python scalar from tuple parsing).
- **Output format:** Workload prints `Mean: <float>` and `Std Dev: <float>` to stdout.

## Baseline Command

```bash
docker exec swegen_astropy_astropy-16295_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 0.000145` / `Std Dev: 1.1e-05` (second run; first run Mean: 0.000163)
- **Tests:** `test_angles.py` — 114 passed in 9.63s

## Experimental Conditions

### Condition: h-main (scalar fast-path)

**Change:** In `astropy/coordinates/angles/formats.py`, modify `_check_hour_range` (line 322) to add a scalar fast-path. When the input is not an `np.ndarray`, use plain Python `abs()` and comparison operators instead of `np.any`/`np.abs`. The array code path remains for `np.ndarray` inputs.

**Intent:** For scalar inputs (int, float, np.float64), bypass NumPy function call overhead entirely. The workload calls `_check_hour_range(15)` where 15 is a plain int — the isinstance check + Python builtins cost ~0.003s/100k calls vs ~1.4s/100k calls for the NumPy path.

**Measured speedup in isolation:** ~50x for scalar path; no regression for array path.

## Success Criteria

- `workload_mean_runtime` decreases significantly (directional: lower is better) compared to baseline ~0.000145-0.000163.
- All 13 covering test files pass with zero failures.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Optimize only library source under `/testbed`.
- All covering tests must remain green.

## Prior Knowledge

This is the first iteration. No active principles.
