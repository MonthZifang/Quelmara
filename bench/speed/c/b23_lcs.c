// b23_lcs —— DP：最长公共子序列 1500×1500
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 1500;
    int64_t *prev = (int64_t *)calloc(n + 1, sizeof(int64_t));
    int64_t *cur = (int64_t *)calloc(n + 1, sizeof(int64_t));
    T0();
    for (int64_t r = 1; r <= n; r++) {
        for (int64_t c = 1; c <= n; c++) {
            int64_t av = (r * 7 + 3) % 4;
            int64_t bv = (c * 11 + 5) % 4;
            if (av == bv) cur[c] = prev[c-1] + 1;
            else cur[c] = prev[c] > cur[c-1] ? prev[c] : cur[c-1];
        }
        for (int64_t c = 0; c <= n; c++) prev[c] = cur[c];
    }
    T1();
    printf("%lld\n", (long long)prev[n]);
    TPRINT();
    free(prev); free(cur);
    return 0;
}
