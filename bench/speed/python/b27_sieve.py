# b27_sieve —— 埃氏筛 1000 万
import time
n = 10000000
t0 = time.perf_counter_ns()
c = bytearray([1]) * (n + 1)
c[0] = 0; c[1] = 0
p = 2
while p * p <= n:
    if c[p]:
        q = p * p
        while q <= n:
            c[q] = 0
            q += p
    p += 1
cnt = sum(c)
t1 = time.perf_counter_ns()
print(cnt); print("T"); print(t1 - t0)
