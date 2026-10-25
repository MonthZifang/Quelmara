# b8_threads1 —— 并发基线：单线程 4000 万次整数运算
import time
def work(n):
    acc = 0
    i = 0
    while i < n:
        acc += (i * 7) % 13
        i += 1
    return acc
t0 = time.perf_counter_ns()
r = work(160000000)
t1 = time.perf_counter_ns()
print(r)
print("T")
print(t1 - t0)
