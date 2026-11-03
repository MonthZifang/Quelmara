// b28_matrix —— 矩阵乘法 300×300（朴素三重循环）
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "bench.h"

int main(void) {
    int64_t n = 300;
    int64_t *a = (int64_t *)malloc(n*n*sizeof(int64_t));
    int64_t *b = (int64_t *)malloc(n*n*sizeof(int64_t));
    int64_t *c = (int64_t *)calloc(n*n, sizeof(int64_t));
    uint64_t seed = 7;
    for (int64_t i = 0; i < n*n; i++) {
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        a[i] = seed % 100;
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        b[i] = seed % 100;
    }
    T0();
    for (int64_t r = 0; r < n; r++)
        for (int64_t k = 0; k < n; k++) {
            int64_t av = a[r*n+k];
            for (int64_t j = 0; j < n; j++)
                c[r*n+j] += av * b[k*n+j];
        }
    T1();
    int64_t chk = 0;
    for (int64_t i = 0; i < n*n; i++) chk = (chk + c[i]) % 1000000007;
    printf("%lld\n", (long long)chk);
    TPRINT();
    free(a); free(b); free(c);
    return 0;
}
