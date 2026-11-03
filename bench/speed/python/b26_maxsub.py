# b26_maxsub —— Kadane 2000 万
import time
n = 20000000
seed = 42
t0 = time.perf_counter_ns()
best = 0; cur = 0
for _ in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    v = seed % 201 - 100
    cur += v
    if cur < 0: cur = 0
    if cur > best: best = cur
t1 = time.perf_counter_ns()
print(best); print("T"); print(t1 - t0)
