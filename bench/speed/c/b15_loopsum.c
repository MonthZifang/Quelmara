// b15_loopsum —— 最朴素循环累加 2 亿次
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 200000000;
    T0();
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += i;
    printf("%lld\n", (long long)s);
    T1();
    TPRINT();
    return 0;
}
