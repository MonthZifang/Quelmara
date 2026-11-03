# b22_knapsack —— 0/1 背包 800x800
import time
n = 800; cap = 800
wt = [0] * n; vl = [0] * n
seed = 999
for i in range(n):
    seed = (seed * 1103515245 + 12345) % 2147483648
    wt[i] = seed % 50 + 1
    seed = (seed * 1103515245 + 12345) % 2147483648
    vl[i] = seed % 100 + 1
t0 = time.perf_counter_ns()
dp = [0] * (cap + 1)
for it in range(n):
    for c in range(cap, wt[it] - 1, -1):
        cand = dp[c - wt[it]] + vl[it]
        if cand > dp[c]: dp[c] = cand
t1 = time.perf_counter_ns()
print(dp[cap]); print("T"); print(t1 - t0)
