// b82_array_fill
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 5000000;
    int64_t *a = malloc(n * 8);
    T0();
    for (int64_t i = 0; i < n; i++) a[i] = i * 2 + 1;
    T1();
    printf("%lld\n", (long long)a[n-1]);
    TPRINT();
    free(a);
    return 0;
}
