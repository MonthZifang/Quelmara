// b76_io_line
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 1000000;
    int64_t *lines =(int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < n; i++) lines[i] = i * 7 + 3;
    T0();
    int64_t sum = 0;
    for (int64_t j = 0; j < n; j++) sum += lines[j] % 100;
    T1();
    printf("%lld\n", (long long)sum);
    TPRINT();
    free(lines);
    return 0;
}
