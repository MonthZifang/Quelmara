// b60_murmur
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

static int64_t murmur(int64_t h, int64_t k) {
    int64_t key = k;
    key *= -862048943LL;
    key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFFLL);
    key *= -862048943LL;
    h ^= key;
    h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFFLL);
    return h * 5 + 1;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 1000000; i++) acc = murmur(acc, i);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
