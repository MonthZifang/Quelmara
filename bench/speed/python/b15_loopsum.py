# b15_loopsum —— 依赖链累加 2 亿次
import time
n = 200000000
t0 = time.perf_counter_ns()
s = 0
x = 1
for i in range(n):
    x = (x * 31 + i) | 1
    s += x & 1023
t1 = time.perf_counter_ns()
print(s); print("T"); print(t1 - t0)
