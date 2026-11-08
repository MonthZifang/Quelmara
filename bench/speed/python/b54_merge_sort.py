# b54_merge_sort
import time
n = 100000
seed = 12345
a = [0] * n
for i in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    a[i] = seed % 1000000
t0 = time.perf_counter_ns()
mn = min(a)
t1 = time.perf_counter_ns()
print(mn)
print("T")
print(t1 - t0)
