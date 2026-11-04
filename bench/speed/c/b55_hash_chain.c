// b55_hash_chain
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t cap = 262144;
    int64_t *buckets = calloc(cap, 8);
    T0();
    int64_t cnt = 0;
    for (int64_t j = 0; j < 200000; j++) {
        int64_t h = (j * 2654435761LL) % cap;
        buckets[h]++; cnt++;
    }
    T1();
    printf("%lld\n", (long long)cnt);
    TPRINT();
    free(buckets);
    return 0;
}
