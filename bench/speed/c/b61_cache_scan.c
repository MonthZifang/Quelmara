// b61_cache_scan
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 1000000;
    int64_t *a = malloc(n * 8);
    for (int64_t i = 0; i < n; i++) a[i] = i;
    T0();
    int64_t acc = 0;
    for (int64_t j = 0; j < 10; j++)
        for (int64_t k = 0; k < n; k++) acc += a[k];
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    free(a);
    return 0;
}
