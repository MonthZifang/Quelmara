# b3_recursion —— 递归：朴素 fib(30)
import time
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
t0 = time.perf_counter_ns()
r = fib(30)
t1 = time.perf_counter_ns()
print(r)
print("T")
print(t1 - t0)
