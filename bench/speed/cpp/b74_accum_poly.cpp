// b74_accum_poly
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t n = 1; n <= 5000000; n++) {
        int64_t s = 0;
        for (int k = 0; k < 5; k++) s = s * n + k * 3 + 1;
        acc += s % 1000003;
    }
    T1();
    printf("%lld\n", (long long)(acc % 1000003));
    TPRINT();
    return 0;
}
