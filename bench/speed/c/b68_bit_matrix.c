// b68_bit_matrix
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 256, sz = n * n;
    int64_t *a = malloc(sz * 8);
    for (int64_t i = 0; i < sz; i++) a[i] = i % 2;
    int64_t *b = malloc(sz * 8);
    T0();
    for (int64_t r = 0; r < n; r++)
        for (int64_t c = 0; c < n; c++)
            b[r*n+c] = a[c*n + (n-1-r)];
    T1();
    printf("%lld\n", (long long)b[0]);
    TPRINT();
    free(a); free(b);
    return 0;
}
