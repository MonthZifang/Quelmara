// b32_io_write
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 1000000;
    int64_t *buf = (int64_t*)malloc(n * 8);
    T0();
    for (int64_t i = 0; i < n; i++) buf[i] = i * 2 + 1;
    T1();
    printf("%lld\n", (long long)buf[n-1]);
    TPRINT();
    free(buf);
    return 0;
}
