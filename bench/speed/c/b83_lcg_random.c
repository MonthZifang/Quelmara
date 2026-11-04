// b83_lcg_random
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    T0();
    uint64_t seed = 12345;
    int64_t acc = 0;
    for (int64_t i = 0; i < 10000000; i++) {
        seed = (seed * 1103515245 + 12345) % 2147483648ULL;
        acc += seed % 100;
    }
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
