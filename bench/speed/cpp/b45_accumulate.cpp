// b45_accumulate
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t n = 1; n <= 1000000; n++) {
        int64_t s = 0;
        for (int k = 0; k < 10; k++) s = s * n + k;
        acc += s % 1000003;
    }
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
