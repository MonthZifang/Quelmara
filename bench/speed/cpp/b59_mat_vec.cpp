// b59_mat_vec
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 500, sz = n * n;
    int64_t *mat =(int64_t*)malloc(sz * 8), *vec =(int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < sz; i++) mat[i] = (i * 7 + 3) % 100;
    for (int64_t j = 0; j < n; j++) vec[j] = (j * 13 + 1) % 100;
    T0();
    int64_t total = 0;
    for (int64_t r = 0; r < n; r++) {
        int64_t s = 0;
        for (int64_t c = 0; c < n; c++) s += mat[r*n+c] * vec[c];
        total += s;
    }
    T1();
    printf("%lld\n", (long long)total);
    TPRINT();
    free(mat); free(vec);
    return 0;
}
