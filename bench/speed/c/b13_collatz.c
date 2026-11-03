// b13_collatz —— Collatz 序列长度累加(1..30万)
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

static int64_t clen(int64_t n) {
    int64_t c = 0;
    while (n != 1) { n = (n % 2 == 0) ? n / 2 : 3 * n + 1; c++; }
    return c;
}
int main(void) {
    T0();
    int64_t best = 0, bn = 0;
    for (int64_t i = 1; i <= 300000; i++) {
        int64_t c = clen(i);
        if (c > best) { best = c; bn = i; }
    }
    printf("%lld\n", (long long)(best * 10000000 + bn));
    T1();
    TPRINT();
    return 0;
}
