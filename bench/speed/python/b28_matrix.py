# b28_matrix —— 矩阵乘法 300x300
import time
n = 300
sz = n * n
a = [0] * sz; b = [0] * sz; c = [0] * sz
seed = 7
for i in range(sz):
    seed = (seed * 1103515245 + 12345) % 2147483648
    a[i] = seed % 100
    seed = (seed * 1103515245 + 12345) % 2147483648
    b[i] = seed % 100
t0 = time.perf_counter_ns()
for r in range(n):
    for k in range(n):
        av = a[r * n + k]
        base = k * n
        for j in range(n):
            c[r * n + j] += av * b[base + j]
t1 = time.perf_counter_ns()
chk = 0
for i in range(sz):
    chk = (chk + c[i]) % 1000000007
print(chk); print("T"); print(t1 - t0)
