# b52_io_scan
import time
n = 1000000
buf = [i * 3 + 1 for i in range(n)]
t0 = time.perf_counter_ns()
s = 0
for j in range(n):
    s += buf[j]
t1 = time.perf_counter_ns()
print(s)
print("T")
print(t1 - t0)
