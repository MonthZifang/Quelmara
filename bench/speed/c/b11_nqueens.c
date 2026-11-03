// b11_nqueens —— N 皇后(8)：回溯 + 数组标记
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

static int64_t solve(int64_t *col, int64_t n, int64_t r) {
    if (r == n) return 1;
    int64_t cnt = 0;
    for (int64_t c = 0; c < n; c++) {
        int ok = 1;
        for (int64_t k = 0; k < r; k++) {
            int64_t cc = col[k];
            if (cc == c) ok = 0;
            int64_t d = cc - c;
            if (d == k - r || d == r - k) ok = 0;
        }
        if (ok) { col[r] = c; cnt += solve(col, n, r+1); }
    }
    return cnt;
}
int main(void) {
    int64_t n = 8;
    int64_t col[8] = {0};
    T0();
    int64_t total = 0;
    for (int64_t rep = 0; rep < 2000; rep++) total += solve(col, n, 0);
    printf("%lld\n", (long long)total);
    T1();
    TPRINT();
    return 0;
}
