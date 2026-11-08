# b74_accum_poly
import time
M = 1000003
acc = 0
t0 = time.perf_counter_ns()
for n in range(1, 5000001):
    s = 0
    for k in range(5):
        s = (s * n + k * 3 + 1) & 0xFFFFFFFFFFFFFFFF
    if s >= 0x8000000000000000:
        sv = s - 0x10000000000000000
    else:
        sv = s
    r = sv % M
    if sv < 0 and r != 0:
        r -= M
    acc += r
t1 = time.perf_counter_ns()
print(acc % M)
print("T")
print(t1 - t0)
