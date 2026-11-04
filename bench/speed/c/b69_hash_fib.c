// b69_hash_fib
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t fib_hash(int64_t key, int64_t cap) {
    return ((key * 2654435761LL) % cap + cap) % cap;
}
int main(void) {
    int64_t cap = 524288;
    int64_t *tab = calloc(cap, 8);
    T0();
    int64_t cnt = 0;
    for (int64_t j = 0; j < 500000; j++) {
        int64_t h = fib_hash(j, cap);
        tab[h]++; cnt++;
    }
    T1();
    printf("%lld\n", (long long)cnt);
    TPRINT();
    free(tab);
    return 0;
}
