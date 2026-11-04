// b49_floyd
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 100, sz = n * n;
    int64_t *dist = malloc(sz * 8);
    for (int64_t i = 0; i < sz; i++) dist[i] = 999999;
    for (int64_t k = 0; k < n; k++) dist[k*n+k] = 0;
    uint64_t seed = 7;
    for (int64_t e = 0; e < 300; e++) {
        seed=(seed*1103515245+12345)%2147483648ULL; int64_t u=seed%n;
        seed=(seed*1103515245+12345)%2147483648ULL; int64_t v=seed%n;
        seed=(seed*1103515245+12345)%2147483648ULL; int64_t w=seed%100+1;
        dist[u*n+v]=w;
    }
    T0();
    for (int64_t a = 0; a < n; a++)
        for (int64_t b = 0; b < n; b++)
            for (int64_t c = 0; c < n; c++) {
                int64_t d1 = dist[b*n+c];
                int64_t d2 = dist[b*n+a] + dist[a*n+c];
                if (d2 < d1) dist[b*n+c] = d2;
            }
    T1();
    printf("%lld\n", (long long)dist[1]);
    TPRINT();
    free(dist);
    return 0;
}
