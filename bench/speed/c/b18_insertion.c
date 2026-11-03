// b18_insertion —— 排序：插入排序 8 万元素
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
    for (int64_t x = 1; x < n; x++) {
        int64_t key = a[x];
        int64_t y = x - 1;
        while (y >= 0 && a[y] > key) { a[y+1] = a[y]; y--; }
        a[y+1] = key;
    }
    T1();
    int64_t chk = 0;
    for (int64_t i = 0; i < n; i++) chk = (chk + a[i] * (i + 1)) % 1000000007;
    printf("%lld\n", (long long)chk);
    TPRINT();
    free(a);
    return 0;
}
