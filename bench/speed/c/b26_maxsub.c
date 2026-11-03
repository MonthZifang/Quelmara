// b26_maxsub —— 经典一维 DP：Kadane 最大子数组 2000 万
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

int main(void) {
    int64_t n = 20000000;
    uint64_t seed = 42;
    T0();
    int64_t best = 0, cur = 0;
    for (int64_t i = 0; i < n; i++) {
        seed = (seed * 1103515245ULL + 12345ULL) % 2147483648ULL;
        int64_t v = (int64_t)(seed % 201) - 100;
        cur += v;
        if (cur < 0) cur = 0;
        if (cur > best) best = cur;
    }
    T1();
    printf("%lld\n", (long long)best);
    TPRINT();
    return 0;
}
