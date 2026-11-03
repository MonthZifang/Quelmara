# b23_lcs —— 最长公共子序列 1500x1500 滚动数组
import time
n = 1500
prev = [0] * (n + 1)
cur = [0] * (n + 1)
t0 = time.perf_counter_ns()
for r in range(1, n + 1):
    for cc in range(1, n + 1):
        av = (r * 7 + 3) % 4
        bv = (cc * 11 + 5) % 4
        if av == bv:
            cur[cc] = prev[cc - 1] + 1
        else:
            cur[cc] = prev[cc] if prev[cc] > cur[cc - 1] else cur[cc - 1]
    for cc in range(n + 1):
        prev[cc] = cur[cc]
t1 = time.perf_counter_ns()
print(prev[n]); print("T"); print(t1 - t0)
