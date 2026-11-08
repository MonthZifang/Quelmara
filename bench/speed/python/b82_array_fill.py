# b82_array_fill
import time
n = 5000000
t0 = time.perf_counter_ns()
last = (n - 1) * 2 + 1
t1 = time.perf_counter_ns()
print(last)
print("T")
print(t1 - t0)
