// b54_merge_sort
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

static void merge(int64_t *a, int64_t lo, int64_t mid, int64_t hi, int64_t *tmp) {
    int64_t i = lo, j = mid, k = 0;
    while (i < mid && j < hi) tmp[k++] = a[i] <= a[j] ? a[i++] : a[j++];
    while (i < mid) tmp[k++] = a[i++];
    while (j < hi) tmp[k++] = a[j++];
    for (int64_t x = 0; x < k; x++) a[lo + x] = tmp[x];
}
static void msort(int64_t *a, int64_t lo, int64_t hi, int64_t *tmp) {
    if (hi - lo <= 1) return;
    int64_t mid = (lo + hi) / 2;
    msort(a, lo, mid, tmp); msort(a, mid, hi, tmp); merge(a, lo, mid, hi, tmp);
}
int main(void) {
    int64_t n = 100000;
    int64_t *a =(int64_t*)malloc(n * 8), *tmp =(int64_t*)malloc(n * 8);
    uint64_t seed = 12345;
    for (int64_t i = 0; i < n; i++) { seed=(seed*1103515245+12345)%2147483648ULL; a[i]=seed%1000000; }
    T0();
    msort(a, 0, n, tmp);
    T1();
    printf("%lld\n", (long long)a[0]);
    TPRINT();
    free(a); free(tmp);
    return 0;
}
