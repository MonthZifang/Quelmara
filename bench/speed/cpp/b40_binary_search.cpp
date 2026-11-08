// b40_binary_search
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

static int64_t bsearch_impl(int64_t *a, int64_t n, int64_t target) {
    int64_t lo = 0, hi = n - 1;
    while (lo <= hi) {
        int64_t mid = (lo + hi) / 2;
        if (a[mid] == target) return mid;
        if (a[mid] < target) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}
int main(void) {
    int64_t n = 1000000;
    int64_t *a =(int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < n; i++) a[i] = i * 2;
    T0();
    int64_t found = 0;
    for (int64_t j = 0; j < 1000000; j++)
        if (bsearch_impl(a, n, j * 2) >= 0) found++;
    T1();
    printf("%lld\n", (long long)found);
    TPRINT();
    free(a);
    return 0;
}
