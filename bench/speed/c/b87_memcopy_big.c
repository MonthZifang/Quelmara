// b87_memcopy_big —— 内存：mem_copy 大块 100MB
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "bench.h"

int main(void) {
    size_t n = 12500000;
    int64_t *src = malloc(n * 8);
    int64_t *dst = malloc(n * 8);
    for (size_t i = 0; i < n; i++) src[i] = (int64_t)i * 7 + 1;
    T0();
    memcpy(dst, src, n * 8);
    T1();
    int64_t chk = dst[0] + dst[6250000] + dst[n - 1];
    printf("%lld\n", (long long)chk);
    TPRINT();
    return 0;
}
