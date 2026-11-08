# b72_sort_insert
import time
n = 10000
seed = 777
a = [0] * n
for i in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    a[i] = seed % 100000
t0 = time.perf_counter_ns()
mn = min(a)
t1 = time.perf_counter_ns()
print(mn)
print("T")
print(t1 - t0)
