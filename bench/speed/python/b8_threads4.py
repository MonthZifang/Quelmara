# b8_threads4 —— 同样 4000 万次总量，拆成 4 个线程
# 注意：CPython 有 GIL，CPU 密集的线程**不会**并行，这个数就是 GIL 的成绩。
import threading
import time
def work(n):
    acc = 0
    i = 0
    while i < n:
        acc += (i * 7) % 13
        i += 1
    return acc
res = [0] * 4
def run(k):
    res[k] = work(40000000)
t0 = time.perf_counter_ns()
ts = [threading.Thread(target=run, args=(k,)) for k in range(4)]
for t in ts: t.start()
for t in ts: t.join()
t1 = time.perf_counter_ns()
print(sum(res))
print("T")
print(t1 - t0)
