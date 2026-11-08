# b44_stack_sim
import time
st = [0] * 1000000
top = 0
t0 = time.perf_counter_ns()
for i in range(1000000):
    st[top] = i
    top += 1
    if i % 3 == 0 and top > 0:
        st[top - 1] += 1
t1 = time.perf_counter_ns()
print(st[top - 1])
print("T")
print(t1 - t0)
