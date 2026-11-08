# b48_sum_matrix
import time
n = 500
sz = n * n
a = [i for i in range(sz)]
total = 0
t0 = time.perf_counter_ns()
for r in range(n):
    s = 0
    for c in range(n):
        s += a[r * n + c]
    total += s
t1 = time.perf_counter_ns()
print(total)
print("T")
print(t1 - t0)
