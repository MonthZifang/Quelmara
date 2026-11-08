# b58_rec_sum
import sys
sys.setrecursionlimit(100000)
import time
def rec_sum(n):
    if n <= 0:
        return 0
    return n + rec_sum(n - 1)
acc = 0
t0 = time.perf_counter_ns()
for i in range(1, 101):
    acc += rec_sum(10000)
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
