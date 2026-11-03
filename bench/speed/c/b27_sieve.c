// b27_sieve —— 埃氏筛 5000 万
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 50000000;
    T0();
    uint8_t *c = (uint8_t *)calloc(n + 1, 1);
    for (int64_t i = 0; i <= n; i++) c[i] = 1;
    c[0] = 0; c[1] = 0;
    for (int64_t p = 2; p * p <= n; p++)
        if (c[p])
            for (int64_t q = p * p; q <= n; q += p) c[q] = 0;
    int64_t cnt = 0;
    for (int64_t i = 0; i <= n; i++) cnt += c[i];
    printf("%lld\n", (long long)cnt);
    T1();
    TPRINT();
    free(c);
    return 0;
}
