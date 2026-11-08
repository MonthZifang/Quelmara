# b40_binary_search
import time
n = 1000000
a = [0] * n
for i in range(n):
    a[i] = i * 2
def bs(target):
    lo = 0
    hi = n - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if a[mid] == target:
            return mid
        if a[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
found = 0
t0 = time.perf_counter_ns()
for j in range(1000000):
    if bs(j * 2) >= 0:
        found += 1
t1 = time.perf_counter_ns()
print(found)
print("T")
print(t1 - t0)
