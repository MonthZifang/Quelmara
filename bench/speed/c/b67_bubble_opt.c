// b67_bubble_opt
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 5000;
    int64_t *a = malloc(n * 8);
    uint64_t seed = 99;
    for (int64_t i = 0; i < n; i++) { seed=(seed*1103515245+12345)%2147483648ULL; a[i]=seed%100000; }
    T0();
    int swapped = 1;
    while (swapped) {
        swapped = 0;
        for (int64_t j = 0; j < n-1; j++)
            if (a[j] > a[j+1]) { int64_t t=a[j]; a[j]=a[j+1]; a[j+1]=t; swapped=1; }
    }
    T1();
    printf("%lld\n", (long long)a[0]);
    TPRINT();
    free(a);
    return 0;
}
