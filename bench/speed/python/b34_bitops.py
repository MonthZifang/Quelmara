# b34_bitops
import time
acc = 0
t0 = time.perf_counter_ns()
for i in range(20000000):
    acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5))
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
