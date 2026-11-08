# b61_cache_scan
import time
acc = 0
t0 = time.perf_counter_ns()
for j in range(10):
    for k in range(1000000):
        acc += k
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
