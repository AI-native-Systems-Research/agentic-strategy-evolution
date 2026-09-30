import timeit
import statistics
from sympy import npartitions

a = 10**6

def workload():
    _ = npartitions(a)

runtimes = timeit.repeat(workload, number=1, repeat=10)

print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
