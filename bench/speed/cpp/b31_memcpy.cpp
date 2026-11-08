// b31_memcpy
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 12500000;
    int64_t *src = (int64_t*)malloc(n * 8);
    int64_t *dst = (int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < n; i++) src[i] = i;
    T0();
    for (int64_t j = 0; j < n; j++) dst[j] = src[j];
    T1();
    printf("%lld\n", (long long)dst[n-1]);
    TPRINT();
    free(src); free(dst);
    return 0;
}
