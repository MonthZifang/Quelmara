// b47_bitcount
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int popcount(int64_t x) {
    int c = 0;
    while (x) { c += x & 1; x >>= 1; }
    return c;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 10000000; i++) acc += popcount(i);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
