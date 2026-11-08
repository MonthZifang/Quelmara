# b84_pair_swap
import time
n = 1000000
keys = [i for i in range(n)]
vals = [i * 2 for i in range(n)]
t0 = time.perf_counter_ns()
for j in range(n):
    k = keys[j]; v = vals[j]
    keys[j] = v; vals[j] = k
t1 = time.perf_counter_ns()
print(keys[0] + vals[0])
print("T")
print(t1 - t0)
