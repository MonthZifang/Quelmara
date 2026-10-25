# b5_string —— 字符串：50 万次 int→str→int
import time
n = 500000
acc = 0
i = 0
t0 = time.perf_counter_ns()
while i < n:
    s = str(i)
    acc += len(s)
    acc += int(s)
    i += 1
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
