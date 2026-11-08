# b50_permute
import time
def perm(arr, k, n, acc):
    if k == n:
        h = 0
        for i in range(n):
            h = h * 31 + arr[i]
        return acc + (h % 1000003)
    s = acc
    for i in range(k, n):
        t = arr[k]; arr[k] = arr[i]; arr[i] = t
        s = perm(arr, k + 1, n, s)
        t = arr[k]; arr[k] = arr[i]; arr[i] = t
    return s
a = list(range(1, 11))
t0 = time.perf_counter_ns()
r = perm(a, 0, 10, 0)
t1 = time.perf_counter_ns()
print(r)
print("T")
print(t1 - t0)
