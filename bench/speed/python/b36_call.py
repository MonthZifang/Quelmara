# b36_call
import time
def add3(a, b, c):
    return a + b + c
acc = 0
t0 = time.perf_counter_ns()
for i in range(10000000):
    acc = add3(acc, i, 1)
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
