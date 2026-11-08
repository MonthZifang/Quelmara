# b85_count_ones
import time
acc = 0
t0 = time.perf_counter_ns()
for i in range(5000000):
    acc += bin(i).count("1")
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
