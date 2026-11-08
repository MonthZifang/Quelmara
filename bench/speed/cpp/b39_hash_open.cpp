// b39_hash_open
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t cap = 1048576;
    int64_t *keys =(int64_t*)calloc(cap, 8);
    int64_t *vals =(int64_t*)calloc(cap, 8);
    T0();
    for (int64_t j = 0; j < 500000; j++) {
        int64_t h = (j * 2654435761LL) % cap;
        keys[h] = j; vals[h] = j * 2;
    }
    int64_t found = 0;
    for (int64_t k = 0; k < 500000; k++) {
        int64_t h = (k * 2654435761LL) % cap;
        if (keys[h] == k) found++;
    }
    T1();
    printf("%lld\n", (long long)found);
    TPRINT();
    free(keys); free(vals);
    return 0;
}
