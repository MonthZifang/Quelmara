# b16_leibniz —— Leibniz pi 2000 万项
import time
n = 20000000
t0 = time.perf_counter_ns()
s = 0.0
for i in range(n):
    d = float(2 * i + 1)
    if i % 2 == 0: s += 1.0 / d
    else: s -= 1.0 / d
pi = s * 4.0
t1 = time.perf_counter_ns()
print("%.6f" % pi); print("T"); print(t1 - t0)
