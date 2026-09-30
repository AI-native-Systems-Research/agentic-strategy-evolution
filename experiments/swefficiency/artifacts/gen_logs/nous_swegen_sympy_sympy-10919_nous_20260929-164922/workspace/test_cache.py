"""Test result caching impact."""
import timeit, statistics

from sympy.ntheory.partitions_ import npartitions as _npartitions_orig

_cache = {}
def npartitions_cached(n, verbose=False):
    if not verbose and n in _cache:
        return _cache[n]
    result = _npartitions_orig(n, verbose)
    if not verbose:
        _cache[n] = result
    return result

# Workload-style (10 reps)
runtimes = timeit.repeat(lambda: npartitions_cached(10**6), number=1, repeat=10)
print("Cached workload: Mean={:.3f}ms, Stdev={:.3f}ms".format(
    statistics.mean(runtimes)*1000, statistics.stdev(runtimes)*1000))
for i, t in enumerate(runtimes):
    print("  Run {}: {:.3f}ms".format(i+1, t*1000))

# Without cache
print()
import importlib
import sympy.ntheory.partitions_
importlib.reload(sympy.ntheory.partitions_)
from sympy.ntheory.partitions_ import npartitions as _np2
runtimes2 = timeit.repeat(lambda: _np2(10**6), number=1, repeat=10)
print("Uncached workload: Mean={:.3f}ms, Stdev={:.3f}ms".format(
    statistics.mean(runtimes2)*1000, statistics.stdev(runtimes2)*1000))
for i, t in enumerate(runtimes2):
    print("  Run {}: {:.3f}ms".format(i+1, t*1000))
