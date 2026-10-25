# b4_array —— 数组：200 万元素写入 + 顺序 + 跨步遍历
import time
n = 2000000
v = [0] * n
t0 = time.perf_counter_ns()
i = 0
while i < n:
    v[i] = i * 3 + 1
    i += 1
s = 0
i = 0
while i < n:
    s += v[i]
    i += 1
t = 0
i = 0
while i < n:
    t += v[i]
    i += 7
t1 = time.perf_counter_ns()
print(s)
print(t)
print("T")
print(t1 - t0)
