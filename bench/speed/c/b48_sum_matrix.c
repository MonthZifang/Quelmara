// b48_sum_matrix
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 500, sz = n * n;
    int64_t *a = malloc(sz * 8);
    for (int64_t i = 0; i < sz; i++) a[i] = i;
    T0();
    int64_t total = 0;
    for (int64_t r = 0; r < n; r++) {
        int64_t s = 0;
        for (int64_t c = 0; c < n; c++) s += a[r * n + c];
        total += s;
    }
    T1();
    printf("%lld\n", (long long)total);
    TPRINT();
    free(a);
    return 0;
}
