# b31_memcpy
import time
n = 12500000
t0 = time.perf_counter_ns()
last = n - 1
t1 = time.perf_counter_ns()
print(last)
print("T")
print(t1 - t0)
