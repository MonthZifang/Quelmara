// b7_sort —— 手写快排，20 万个伪随机 int
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"


static void qsort_i64(int64_t *a, int64_t lo, int64_t hi) {
    if (lo >= hi) return;
    int64_t p = a[hi], i = lo;
    for (int64_t j = lo; j < hi; j++) {
        if (a[j] < p) {
            int64_t t = a[i]; a[i] = a[j]; a[j] = t;
            i++;
        }
    }
    int64_t t2 = a[i]; a[i] = a[hi]; a[hi] = t2;
    qsort_i64(a, lo, i - 1);
    qsort_i64(a, i + 1, hi);
}

int main(void) {
    T0();
    int64_t n = 200000;
    int64_t *v = (int64_t *)malloc((size_t)n * 8);
    int64_t x = 12345;
    for (int64_t i = 0; i < n; i++) {
        x = (x * 1103515245LL + 12345) & 2147483647LL;
        v[i] = x;
    }
    qsort_i64(v, 0, n - 1);
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += v[i] % 1000;
    printf("%lld\n", (long long)v[0]);
    printf("%lld\n", (long long)v[n - 1]);
    printf("%lld\n", (long long)s);
    free(v);
    T1();
    TPRINT();
    return 0;
}
