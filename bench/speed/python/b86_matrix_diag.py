# b86_matrix_diag
import time
n = 1000
sz = n * n
a = [(i * 7 + 3) % 100 for i in range(sz)]
t0 = time.perf_counter_ns()
s = 0
for r in range(n):
    s += a[r * n + r]
t1 = time.perf_counter_ns()
print(s)
print("T")
print(t1 - t0)
