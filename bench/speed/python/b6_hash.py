# b6_hash —— 哈希表：30 万插入 + 30 万查找（手写开放寻址，cap=2^20）
import time
cap = 1048576
mask = cap - 1
n = 300000
kt = [0] * cap
vt = [0] * cap
t0 = time.perf_counter_ns()
i = 1
while i <= n:
    k = i * 3 + 1
    h = (k * 2654435761) & mask
    while kt[h] != 0:
        h = (h + 1) & mask
    kt[h] = k
    vt[h] = k * 2
    i += 1
s = 0
i = 1
while i <= n:
    k = i * 3 + 1
    h = (k * 2654435761) & mask
    while kt[h] != k:
        h = (h + 1) & mask
    s += vt[h]
    i += 1
t1 = time.perf_counter_ns()
print(s)
print("T")
print(t1 - t0)
