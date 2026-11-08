# b38_prime
import time
def is_prime(n):
    if n < 2:
        return 0
    if n == 2:
        return 1
    if n % 2 == 0:
        return 0
    d = 3
    while d * d <= n:
        if n % d == 0:
            return 0
        d += 2
    return 1
cnt = 0
t0 = time.perf_counter_ns()
for i in range(100000):
    if is_prime(i):
        cnt += 1
t1 = time.perf_counter_ns()
print(cnt)
print("T")
print(t1 - t0)
