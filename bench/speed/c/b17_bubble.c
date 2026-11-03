// b17_bubble —— 冒泡排序 8 万元素（最坏分支 + 交换开销）
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 80000;
    int64_t *a = (int64_t *)malloc(n * sizeof(int64_t));
    uint64_t seed = 12345;
    for (int64_t i = 0; i < n; i++) {
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        a[i] = seed % 100000;
    }
    T0();
    for (int64_t x = 0; x < n; x++)
        for (int64_t y = 0; y < n - 1 - x; y++)
            if (a[y] > a[y+1]) { int64_t t = a[y]; a[y] = a[y+1]; a[y+1] = t; }
    T1();
    int64_t chk = 0;
    for (int64_t i = 0; i < n; i++) chk = (chk + a[i] * (i + 1)) % 1000000007;
    printf("%lld\n", (long long)chk);
    TPRINT();
    free(a);
    return 0;
}
