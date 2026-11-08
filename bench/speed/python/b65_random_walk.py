# b65_random_walk
import time
x = 0
y = 0
seed = 12345
t0 = time.perf_counter_ns()
for i in range(2000000):
    seed = (seed * 1103515245 + 12345) % 2147483648
    d = seed % 4
    if d == 0:
        x += 1
    elif d == 1:
        x -= 1
    elif d == 2:
        y += 1
    else:
        y -= 1
t1 = time.perf_counter_ns()
print(x * 1000000 + y)
print("T")
print(t1 - t0)
