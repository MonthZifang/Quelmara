# b18_insertion —— 插入排序 8 万
import time
n = 80000
a = [0] * n
seed = 12345
for i in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    a[i] = seed % 100000
t0 = time.perf_counter_ns()
for x in range(1, n):
    key = a[x]
    y = x - 1
    while y >= 0 and a[y] > key:
        a[y + 1] = a[y]
        y -= 1
    a[y + 1] = key
t1 = time.perf_counter_ns()
chk = 0
for i in range(n):
    chk = (chk + a[i] * (i + 1)) % 1000000007
print(chk); print("T"); print(t1 - t0)
