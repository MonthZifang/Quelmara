# b1_int —— 整数运算热循环：2000 万次 (i*7)%13
# 末行打印 "T" + 负载耗时（纳秒），进程创建成本不计入。
import time
n = 20000000
acc = 0
i = 0
t0 = time.perf_counter_ns()
while i < n:
    acc += (i * 7) % 13
    i += 1
t1 = time.perf_counter_ns()
print(acc)
print("T")
print(t1 - t0)
