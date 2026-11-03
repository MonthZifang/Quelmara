# b12_gcd —— 3000 万次辗转相除
import time
def gcd(a, b):
    while b:
        a, b = b, a % b
    return a
n = 30000000
t0 = time.perf_counter_ns()
s = 0
for i in range(1, n + 1):
    s += gcd(i, 1000000 - i)
t1 = time.perf_counter_ns()
print(s); print("T"); print(t1 - t0)
