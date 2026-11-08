# b33_startup
import time
def init():
    s = 0
    for i in range(1000):
        s += i
    return s
t0 = time.perf_counter_ns()
a = init(); b = init(); c = init(); d = init()
t1 = time.perf_counter_ns()
print(a + b + c + d)
print("T")
print(t1 - t0)
