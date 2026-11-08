# b60_murmur
import time
MASK49 = 0x1FFFFFFFFFFFF
def i64(x):
    return x & 0xFFFFFFFFFFFFFFFF
def s64(x):
    x &= 0xFFFFFFFFFFFFFFFF
    return x - 0x10000000000000000 if x >= 0x8000000000000000 else x
def murmur(h, k):
    key = i64(k)
    key = i64(key * -862048943)
    sr = (s64(key) >> 51) & MASK49
    key = i64((key << 13) | sr)
    key = i64(key * -862048943)
    h = i64(h ^ key)
    sr = (s64(h) >> 51) & MASK49
    h = i64((h << 13) | sr)
    return i64(h * 5 + 1)
acc = 0
t0 = time.perf_counter_ns()
for i in range(1000000):
    acc = murmur(acc, i)
t1 = time.perf_counter_ns()
print(s64(acc))
print("T")
print(t1 - t0)
