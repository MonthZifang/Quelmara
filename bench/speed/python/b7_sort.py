# b7_sort —— 排序：20 万伪随机 int 快排（手写）
import time
def qsort(a, lo, hi):
    if lo >= hi:
        return
    p = a[hi]
    i = lo
    j = lo
    while j < hi:
        if a[j] < p:
            a[i], a[j] = a[j], a[i]
            i += 1
        j += 1
    a[i], a[hi] = a[hi], a[i]
    qsort(a, lo, i - 1)
    qsort(a, i + 1, hi)

n = 200000
v = [0] * n
x = 12345
i = 0
while i < n:
    x = (x * 1103515245 + 12345) & 2147483647
    v[i] = x
    i += 1
t0 = time.perf_counter_ns()
qsort(v, 0, n - 1)
t1 = time.perf_counter_ns()
s = 0
i = 0
while i < n:
    s += v[i] % 1000
    i += 1
print(v[0])
print(v[n - 1])
print(s)
print("T")
print(t1 - t0)
