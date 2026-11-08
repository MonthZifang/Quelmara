# b75_fib_matrix
import time
M = 1000003
a0 = 1; a1 = 1; a2 = 1; a3 = 0
n = 1000
t0 = time.perf_counter_ns()
while n > 0:
    if n % 2 == 1:
        t = (a0 * a1 + a1 * a3) % M
        u = (a0 * a2 + a1 * a3) % M
        v = (a2 * a1 + a3 * a3) % M
        w = (a2 * a1 + a3 * a3) % M
        a0 = t; a1 = u; a2 = v; a3 = w
    b0 = (a0 * a0 + a1 * a2) % M
    b1 = (a0 * a1 + a1 * a3) % M
    b2 = (a2 * a0 + a3 * a2) % M
    b3 = (a2 * a1 + a3 * a3) % M
    a0 = b0; a1 = b1; a2 = b2; a3 = b3
    n //= 2
t1 = time.perf_counter_ns()
print(a1)
print("T")
print(t1 - t0)
