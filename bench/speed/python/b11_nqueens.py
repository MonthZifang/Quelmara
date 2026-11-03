# b11_nqueens —— 8 皇后 x 2000 轮
import time
def solve(col, n, r):
    if r == n: return 1
    cnt = 0
    for c in range(n):
        ok = True
        for k in range(r):
            cc = col[k]
            if cc == c: ok = False
            d = cc - c
            if d == k - r or d == r - k: ok = False
        if ok:
            col[r] = c
            cnt += solve(col, n, r + 1)
    return cnt
n = 8
col = [0] * n
t0 = time.perf_counter_ns()
total = 0
for _ in range(2000):
    total += solve(col, n, 0)
t1 = time.perf_counter_ns()
print(total); print("T"); print(t1 - t0)
