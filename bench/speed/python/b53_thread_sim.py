# b53_thread_sim
import time
def work(start, end):
    s = 0
    for i in range(start, end):
        s += i * 2 + 1
    return s
n = 10000000
t0 = time.perf_counter_ns()
a = work(0, n // 4); b = work(n // 4, n // 2)
c = work(n // 2, 3 * n // 4); d = work(3 * n // 4, n)
t1 = time.perf_counter_ns()
print(a + b + c + d)
print("T")
print(t1 - t0)
