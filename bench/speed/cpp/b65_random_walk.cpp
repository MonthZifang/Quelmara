// b65_random_walk
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    T0();
    int64_t x = 0, y = 0;
    uint64_t seed = 12345;
    for (int64_t i = 0; i < 2000000; i++) {
        seed = (seed * 1103515245 + 12345) % 2147483648ULL;
        int64_t d = seed % 4;
        if (d == 0) x++; else if (d == 1) x--; else if (d == 2) y++; else y--;
    }
    T1();
    printf("%lld\n", (long long)(x * 1000000 + y));
    TPRINT();
    return 0;
}
