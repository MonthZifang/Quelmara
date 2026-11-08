// b34_bitops
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t acc = 0;
    T0();
    for (int64_t i = 0; i < 20000000; i++)
        acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5));
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
