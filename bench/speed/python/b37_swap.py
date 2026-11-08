# b37_swap
import time
n = 10000
a = [0] * n
seed = 42
for i in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    a[i] = seed % 100000
t0 = time.perf_counter_ns()
for rnd in range(100):
    for j in range(n - 1):
        if a[j] > a[j + 1]:
            t = a[j]; a[j] = a[j + 1]; a[j + 1] = t
t1 = time.perf_counter_ns()
print(a[0])
print("T")
print(t1 - t0)
