# b70_lin_search
import time
n = 1000
a = [i * 3 + 7 for i in range(n)]
aset = set(a)
t0 = time.perf_counter_ns()
found = 0
for j in range(1000000):
    target = (j * 37 + 11) % 3000
    if target in aset:
        found += 1
t1 = time.perf_counter_ns()
print(found)
print("T")
print(t1 - t0)
