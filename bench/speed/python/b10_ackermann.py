# b10_ackermann —— Ackermann(2,8)
import time, sys
sys.setrecursionlimit(100000)
def ack(m, n):
    if m == 0: return n + 1
    if n == 0: return ack(m - 1, 1)
    return ack(m - 1, ack(m, n - 1))
t0 = time.perf_counter_ns()
r = ack(2, 8)
t1 = time.perf_counter_ns()
print(r); print("T"); print(t1 - t0)
