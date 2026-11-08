# b59_mat_vec
import time
n = 500
sz = n * n
mat = [0] * sz
vec = [0] * n
for i in range(sz):
    mat[i] = (i * 7 + 3) % 100
for j in range(n):
    vec[j] = (j * 13 + 1) % 100
total = 0
t0 = time.perf_counter_ns()
for r in range(n):
    s = 0
    for c in range(n):
        s += mat[r * n + c] * vec[c]
    total += s
t1 = time.perf_counter_ns()
print(total)
print("T")
print(t1 - t0)
