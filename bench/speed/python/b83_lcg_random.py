# b83_lcg_random
import time
seed = 12345
acc = 0
t0 = time.perf_counter_ns()
for i in range(10000000):
    seed = (seed * 1103515245 + 12345) % 2147483648
    acc += seed % 100
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
