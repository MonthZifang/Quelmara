// b22_knapsack —— 0/1 背包 DP（800 件 × 800 容量）
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 800, cap = 800;
    int64_t *wt = (int64_t *)malloc(n * sizeof(int64_t));
    int64_t *vl = (int64_t *)malloc(n * sizeof(int64_t));
    uint64_t seed = 999;
    for (int64_t i = 0; i < n; i++) {
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        wt[i] = seed % 50 + 1;
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        vl[i] = seed % 100 + 1;
    }
    T0();
    int64_t *dp = (int64_t *)calloc(cap + 1, sizeof(int64_t));
    for (int64_t it = 0; it < n; it++)
        for (int64_t c = cap; c >= wt[it]; c--) {
            int64_t cand = dp[c - wt[it]] + vl[it];
            if (cand > dp[c]) dp[c] = cand;
        }
    T1();
    printf("%lld\n", (long long)dp[cap]);
    TPRINT();
    free(wt); free(vl); free(dp);
    return 0;
}
