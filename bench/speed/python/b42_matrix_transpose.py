# b42_matrix_transpose
import time
n = 500
sz = n * n
a = [i for i in range(sz)]
b = [0] * sz
t0 = time.perf_counter_ns()
for r in range(n):
    for c in range(n):
        b[r * n + c] = a[c * n + r]
t1 = time.perf_counter_ns()
print(b[sz - 1])
print("T")
print(t1 - t0)
