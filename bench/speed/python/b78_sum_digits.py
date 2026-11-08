# b78_sum_digits
import time
def digit_sum(n):
    s = 0
    while n > 0:
        s += n % 10
        n //= 10
    return s
acc = 0
t0 = time.perf_counter_ns()
for i in range(1000000):
    acc += digit_sum(i)
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
