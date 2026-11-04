// b81_bit_reverse
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t bitrev(int64_t x) {
    int64_t v = x, r = 0;
    for (int i = 0; i < 32; i++) { r = (r << 1) | (v & 1); v >>= 1; }
    return r;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t j = 0; j < 1000000; j++) acc ^= bitrev(j);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
