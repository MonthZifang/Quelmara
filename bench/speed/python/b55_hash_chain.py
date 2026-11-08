# b55_hash_chain
import time
t0 = time.perf_counter_ns()
cnt = 0
for j in range(200000):
    cnt += 1
t1 = time.perf_counter_ns()
print(cnt)
print("T")
print(t1 - t0)
