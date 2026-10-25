// b1_int —— 整数运算热循环，20M 次
#include <stdio.h>
#include <stdint.h>
#include "bench.h"


int main(void) {
    T0();
    int64_t n = 20000000, acc = 0;
    for (int64_t i = 0; i < n; i++) acc += (i * 7) % 13;
    printf("%lld\n", (long long)acc);
    T1();
    TPRINT();
    return 0;
}
