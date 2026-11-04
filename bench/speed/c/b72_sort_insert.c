// b72_sort_insert
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 10000;
    int64_t *a = malloc(n * 8);
    uint64_t seed = 777;
    for (int64_t i = 0; i < n; i++) { seed=(seed*1103515245+12345)%2147483648ULL; a[i]=seed%100000; }
    T0();
    for (int64_t x = 1; x < n; x++) {
        int64_t key = a[x], y = x - 1;
        while (y >= 0 && a[y] > key) { a[y+1] = a[y]; y--; }
        a[y+1] = key;
    }
    T1();
    printf("%lld\n", (long long)a[0]);
    TPRINT();
    free(a);
    return 0;
}
