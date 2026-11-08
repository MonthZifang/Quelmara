# b56_sieve_opt
import time
n = 2000000
flags = [1] * (n + 1)
flags[0] = flags[1] = 0
t0 = time.perf_counter_ns()
p = 2
while p * p <= n:
    if flags[p]:
        q = p * p
        while q <= n:
            flags[q] = 0
            q += p
    p += 1
cnt = 0
for k in range(2, n + 1):
    if flags[k]:
        cnt += 1
t1 = time.perf_counter_ns()
print(cnt)
print("T")
print(t1 - t0)
