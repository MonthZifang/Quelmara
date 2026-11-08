// b86_matrix_diag
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 1000, sz = n * n;
    int64_t *a =(int64_t*)malloc(sz * 8);
    for (int64_t i = 0; i < sz; i++) a[i] = (i * 7 + 3) % 100;
    T0();
    int64_t sum = 0;
    for (int64_t r = 0; r < n; r++) sum += a[r * n + r];
    T1();
    printf("%lld\n", (long long)sum);
    TPRINT();
    free(a);
    return 0;
}
