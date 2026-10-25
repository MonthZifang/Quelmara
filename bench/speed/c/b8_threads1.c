// b8_threads1 —— 单线程 4000 万次整数运算
#include <stdio.h>
#include <stdint.h>
#include "bench.h"


static int64_t work(int64_t n) {
    int64_t acc = 0;
    for (int64_t i = 0; i < n; i++) acc += (i * 7) % 13;
    return acc;
}

int main(void) {
    T0();
    printf("%lld\n", (long long)work(160000000));
    T1();
    TPRINT();
    return 0;
}
