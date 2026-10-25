// b6_hash —— 手写开放寻址哈希表，10 万插入 + 10 万查找
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"


int main(void) {
    T0();
    int64_t cap = 1048576, mask = cap - 1, n = 300000;
    int64_t *kt = (int64_t *)calloc((size_t)cap, 8);
    int64_t *vt = (int64_t *)calloc((size_t)cap, 8);
    for (int64_t i = 1; i <= n; i++) {
        int64_t k = i * 3 + 1;
        int64_t h = (k * 2654435761LL) & mask;
        while (kt[h] != 0) h = (h + 1) & mask;
        kt[h] = k;
        vt[h] = k * 2;
    }
    int64_t s = 0;
    for (int64_t i = 1; i <= n; i++) {
        int64_t k = i * 3 + 1;
        int64_t h = (k * 2654435761LL) & mask;
        while (kt[h] != k) h = (h + 1) & mask;
        s += vt[h];
    }
    printf("%lld\n", (long long)s);
    free(kt); free(vt);
    T1();
    TPRINT();
    return 0;
}
