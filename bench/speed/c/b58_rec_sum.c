// b58_rec_sum
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t rec_sum(int64_t n) {
    if (n <= 0) return 0;
    return n + rec_sum(n - 1);
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 1; i <= 100; i++) acc += rec_sum(10000);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
