# b35_branch
import time
acc = 0
t0 = time.perf_counter_ns()
for i in range(20000000):
    if (i & 3) == 0:
        acc += 1
    else:
        acc -= 1
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
