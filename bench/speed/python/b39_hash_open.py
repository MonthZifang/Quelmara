# b39_hash_open
import time
cap = 1048576
keys = [0] * cap
vals = [0] * cap
t0 = time.perf_counter_ns()
for j in range(500000):
    h = (j * 2654435761) % cap
    keys[h] = j
    vals[h] = j * 2
found = 0
for k in range(500000):
    h = (k * 2654435761) % cap
    if keys[h] == k:
        found += 1
t1 = time.perf_counter_ns()
print(found)
print("T")
print(t1 - t0)
