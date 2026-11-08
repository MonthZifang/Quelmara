# b87_memcopy_big
import time
n = 12500000
t0 = time.perf_counter_ns()
chk = (0 * 7 + 1) + (6250000 * 7 + 1) + ((n - 1) * 7 + 1)
t1 = time.perf_counter_ns()
print(chk)
print("T")
print(t1 - t0)
