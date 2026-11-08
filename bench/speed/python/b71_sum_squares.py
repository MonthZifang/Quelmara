# b71_sum_squares
import time
acc = 0
t0 = time.perf_counter_ns()
for i in range(1, 1000001):
    acc += i * i
t1 = time.perf_counter_ns()
print(acc % 1000003)
print("T")
print(t1 - t0)
