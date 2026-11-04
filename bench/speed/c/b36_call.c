// b36_call
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t add3(int64_t a, int64_t b, int64_t c) { return a + b + c; }
int main(void) {
    int64_t acc = 0;
    T0();
    for (int64_t i = 0; i < 10000000; i++) acc = add3(acc, i, 1);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
