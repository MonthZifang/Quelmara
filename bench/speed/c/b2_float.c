// b2_float —— 浮点运算：调和级数前 5M 项
#include <stdio.h>
#include <stdint.h>
#include "bench.h"


int main(void) {
    T0();
    int64_t n = 5000000;
    double acc = 0.0;
    for (int64_t i = 1; i <= n; i++) acc += 1.0 / (double)i;
    printf("%.6f\n", acc);
    T1();
    TPRINT();
    return 0;
}
