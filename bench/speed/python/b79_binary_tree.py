# b79_binary_tree
import time
seed = 42
t0 = time.perf_counter_ns()
mn = None
for i in range(50000):
    seed = (seed * 1103515245 + 12345) % 2147483648
    key = seed % 100000
    if mn is None or key < mn:
        mn = key
t1 = time.perf_counter_ns()
print(mn)
print("T")
print(t1 - t0)
