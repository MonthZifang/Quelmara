// b16_leibniz —— 浮点：Leibniz 级数 π，2000 万项
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "bench.h"

int main(void) {
    int64_t n = 20000000;
    T0();
    double s = 0.0;
    for (int64_t i = 0; i < n; i++) {
        double d = (double)(2 * i + 1);
        if (i % 2 == 0) s += 1.0 / d; else s -= 1.0 / d;
    }
    double pi = s * 4.0;
    T1();
    printf("%.6f\n", pi);
    TPRINT();
    return 0;
}
