# b14_fibiter —— 迭代 fib 5000 万
import time
n = 50000000
t0 = time.perf_counter_ns()
a = 0; b = 1
for _ in range(n):
    t = a + b
    a = b
    b = t % 1000000007
t1 = time.perf_counter_ns()
print(a); print("T"); print(t1 - t0)
