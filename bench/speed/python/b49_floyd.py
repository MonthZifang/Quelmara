# b49_floyd
import time
n = 100
sz = n * n
dist = [999999] * sz
for k in range(n):
    dist[k * n + k] = 0
seed = 7
for e in range(300):
    seed = (seed * 1103515245 + 12345) % 2147483648
    u = seed % n
    seed = (seed * 1103515245 + 12345) % 2147483648
    v = seed % n
    seed = (seed * 1103515245 + 12345) % 2147483648
    w = seed % 100 + 1
    dist[u * n + v] = w
t0 = time.perf_counter_ns()
for a in range(n):
    for b in range(n):
        for c in range(n):
            d1 = dist[b * n + c]
            d2 = dist[b * n + a] + dist[a * n + c]
            if d2 < d1:
                dist[b * n + c] = d2
t1 = time.perf_counter_ns()
print(dist[1])
print("T")
print(t1 - t0)
