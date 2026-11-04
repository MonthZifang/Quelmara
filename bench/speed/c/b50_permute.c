// b50_permute
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t perm(int64_t *arr, int k, int n, int64_t acc) {
    if (k == n) {
        int64_t h = 0;
        for (int i = 0; i < n; i++) h = h * 31 + arr[i];
        return acc + (h % 1000003);
    }
    int64_t s = acc;
    for (int i = k; i < n; i++) {
        int64_t t = arr[k]; arr[k] = arr[i]; arr[i] = t;
        s = perm(arr, k + 1, n, s);
        t = arr[k]; arr[k] = arr[i]; arr[i] = t;
    }
    return s;
}
int main(void) {
    int64_t a[10];
    for (int i = 0; i < 10; i++) a[i] = i + 1;
    T0();
    int64_t r = perm(a, 0, 10, 0);
    T1();
    printf("%lld\n", (long long)r);
    TPRINT();
    return 0;
}
