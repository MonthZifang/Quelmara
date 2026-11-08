# b68_bit_matrix
import time
n = 256
sz = n * n
a = [i % 2 for i in range(sz)]
b = [0] * sz
t0 = time.perf_counter_ns()
for r in range(n):
    for c in range(n):
        b[r * n + c] = a[c * n + (n - 1 - r)]
t1 = time.perf_counter_ns()
print(b[0])
print("T")
print(t1 - t0)
