// b84_pair_swap
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 1000000;
    int64_t *keys =(int64_t*)malloc(n * 8), *vals =(int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < n; i++) { keys[i] = i; vals[i] = i * 2; }
    T0();
    for (int64_t j = 0; j < n; j++) {
        int64_t k = keys[j], v = vals[j];
        keys[j] = v; vals[j] = k;
    }
    T1();
    printf("%lld\n", (long long)(keys[0] + vals[0]));
    TPRINT();
    free(keys); free(vals);
    return 0;
}
