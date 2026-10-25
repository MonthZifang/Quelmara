# b2_float —— 浮点运算：调和级数前 500 万项
import time
n = 5000000
acc = 0.0
i = 1
t0 = time.perf_counter_ns()
while i <= n:
    acc += 1.0 / float(i)
    i += 1
t1 = time.perf_counter_ns()
print("%.6f" % acc)
print("T")
print(t1 - t0)
