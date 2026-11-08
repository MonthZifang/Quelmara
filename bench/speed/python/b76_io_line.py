# b76_io_line
import time
n = 1000000
lines = [i * 7 + 3 for i in range(n)]
t0 = time.perf_counter_ns()
s = 0
for j in range(n):
    s += lines[j] % 100
t1 = time.perf_counter_ns()
print(s)
print("T")
print(t1 - t0)
