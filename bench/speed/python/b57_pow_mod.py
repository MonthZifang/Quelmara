# b57_pow_mod
import time
def pow_mod(base, exp, mod):
    result = 1
    b = base % mod
    while exp > 0:
        if exp % 2 == 1:
            result = (result * b) % mod
        b = (b * b) % mod
        exp //= 2
    return result
acc = 0
t0 = time.perf_counter_ns()
for i in range(1, 1000001):
    acc = (acc + pow_mod(i, i, 1000003)) % 1000003
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
