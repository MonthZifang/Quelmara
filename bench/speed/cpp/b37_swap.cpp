// b37_swap
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 10000;
    int64_t *a = (int64_t*)malloc(n * 8);
    uint64_t seed = 42;
    for (int64_t i = 0; i < n; i++) {
        seed = (seed * 1103515245 + 12345) % 2147483648ULL;
        a[i] = seed % 100000;
    }
    T0();
    for (int64_t round = 0; round < 100; round++)
        for (int64_t j = 0; j < n - 1; j++)
            if (a[j] > a[j+1]) { int64_t t = a[j]; a[j] = a[j+1]; a[j+1] = t; }
    T1();
    printf("%lld\n", (long long)a[0]);
    TPRINT();
    free(a);
    return 0;
}
