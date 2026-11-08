# b43_gcd_lcm
import time
def gcd(a, b):
    while b:
        t = b
        b = a % b
        a = t
    return a
acc = 0
t0 = time.perf_counter_ns()
for i in range(1, 1000001):
    acc += gcd(i, 1000000 - i + 1)
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
