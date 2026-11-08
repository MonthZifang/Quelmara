# b66_integrate
import time
M = 1000003
def f(x):
    return (x * x + 3 * x + 5) % M
acc = 0
t0 = time.perf_counter_ns()
for i in range(1000000):
    acc = (acc + f(i)) % M
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
