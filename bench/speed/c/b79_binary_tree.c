// b79_binary_tree
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t *keys = malloc(50000 * 8);
    int64_t n = 0;
    uint64_t seed = 42;
    T0();
    for (int64_t i = 0; i < 50000; i++) {
        seed=(seed*1103515245+12345)%2147483648ULL;
        int64_t key = seed % 100000;
        int64_t pos = n;
        for (int64_t j = 0; j < n; j++) if (keys[j] > key) { pos = j; break; }
        for (int64_t k = n; k > pos; k--) keys[k] = keys[k-1];
        keys[pos] = key; n++;
    }
    T1();
    printf("%lld\n", (long long)keys[0]);
    TPRINT();
    free(keys);
    return 0;
}
