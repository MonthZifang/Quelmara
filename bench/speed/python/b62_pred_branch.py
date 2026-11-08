# b62_pred_branch
import time
acc = 0
t0 = time.perf_counter_ns()
for i in range(5000000):
    if (i * 7 + 3) % 5 < 2:
        acc += 1
    else:
        acc -= 1
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
