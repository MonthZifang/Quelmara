# b73_graph_bfs
import time
n = 1000
adj = [[0] * n for _ in range(n)]
seed = 55
for e in range(5000):
    seed = (seed * 1103515245 + 12345) % 2147483648
    u = seed % n
    seed = (seed * 1103515245 + 12345) % 2147483648
    v = seed % n
    adj[u][v] = 1
visited = [0] * n
queue = [0] * n
front = 0
back = 0
queue[back] = 0
back += 1
visited[0] = 1
cnt = 0
t0 = time.perf_counter_ns()
while front < back:
    u = queue[front]
    front += 1
    cnt += 1
    for v in range(n):
        if adj[u][v] and not visited[v]:
            visited[v] = 1
            queue[back] = v
            back += 1
t1 = time.perf_counter_ns()
print(cnt)
print("T")
print(t1 - t0)
