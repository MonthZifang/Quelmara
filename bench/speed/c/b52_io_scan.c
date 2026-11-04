// b52_io_scan
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 1000000;
    int64_t *buf = malloc(n * 8);
    for (int64_t i = 0; i < n; i++) buf[i] = i * 3 + 1;
    T0();
    int64_t sum = 0;
    for (int64_t j = 0; j < n; j++) sum += buf[j];
    T1();
    printf("%lld\n", (long long)sum);
    TPRINT();
    free(buf);
    return 0;
}
