# b46_strcat
import time
t0 = time.perf_counter_ns()
acc = 0
for i in range(100000):
    acc += len("hello world 12345")
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
