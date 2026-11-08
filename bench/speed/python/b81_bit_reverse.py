# b81_bit_reverse
import time
def bitrev(x):
    return int(format(x, "032b")[::-1], 2)
acc = 0
t0 = time.perf_counter_ns()
for j in range(1000000):
    acc ^= bitrev(j)
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
