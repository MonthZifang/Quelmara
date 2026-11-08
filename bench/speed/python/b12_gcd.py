# b12_gcd —— 3000 万次辗转相除
import time
def cmod(a, b):
    # C 语义取模：符号随被除数（Python 地板取模在负数时结果不同）
    return (abs(a) % abs(b)) * (1 if a >= 0 else -1)
def gcd(a, b):
    while b:
        a, b = b, cmod(a, b)
    return a
n = 30000000
t0 = time.perf_counter_ns()
s = 0
for i in range(1, n + 1):
    s += gcd(i, 1000000 - i)
t1 = time.perf_counter_ns()
print(s); print("T"); print(t1 - t0)
