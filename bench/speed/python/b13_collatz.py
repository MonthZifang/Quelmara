# b13_collatz —— Collatz 1..30 万
import time
def clen(n0):
    n = n0
    c = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        c += 1
    return c
t0 = time.perf_counter_ns()
best = 0; bn = 0
for i in range(1, 300001):
    c = clen(i)
    if c > best:
        best = c; bn = i
t1 = time.perf_counter_ns()
print(best * 10000000 + bn); print("T"); print(t1 - t0)
