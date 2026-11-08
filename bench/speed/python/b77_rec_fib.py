# b77_rec_fib
import time
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
t0 = time.perf_counter_ns()
r = fib(25)
t1 = time.perf_counter_ns()
print(r)
print("T")
print(t1 - t0)
